"""
GASTOS (nov-2026, pedido de Santiago).

Se registran a mano las facturas de compra, con los mismos campos del reporte
de facturas recibidas que lleva la oficina (Excel «FACTURAS AGOSTO SOLMED»):
tipo de documento, prefijo y folio, divisa, forma y medio de pago (códigos
DIAN), fechas de emisión y recepción, NIT y nombre del proveedor, total y
—la columna «COSTOS»— a qué se carga: un VEHÍCULO del sistema o una
CATEGORÍA propia que la oficina crea libremente (Administrativo, Junio…).

Con eso sale la UTILIDAD de cada vehículo: su ingreso (lo que valen sus
servicios prestados, ya con precio, repartido entre las placas de cada orden;
el mismo criterio del tablero de gerencia) menos sus gastos. Los gastos de
categorías NO se reparten entre vehículos (decisión de Santiago): van aparte
y se restan solo en la utilidad total de la empresa.

Acceso: administradores; a un asesor se le abre con la casilla «Gastos» de
«Gestionar accesos» (gestion/accesos.py). Los gastos no son de clientes, así
que la cartera no los recorta.
"""
import datetime
from collections import defaultdict
from decimal import Decimal, InvalidOperation

from django import forms
from django.contrib import messages
from django.db import IntegrityError
from django.db.models import Count, Min, Q, Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views import View

from .gerencia import PERIODOS, _sumar_meses, frase_periodo, nombre_periodo, periodo_anterior, periodo_de
from .models import CategoriaGasto, Gasto, LineaFactura, Vehiculo
from .views import AdministradorRequiredMixin, MESES_CORTOS, PaginadoMixin, rango_de_paginas


# ============================================================
#  El formulario
# ============================================================

def _numero(texto):
    """«1.234.567,89» o «1234567.89» → Decimal. None si no es un número."""
    t = str(texto or '').strip().replace('$', '').replace(' ', '')
    if not t:
        return None
    if ',' in t:
        t = t.replace('.', '').replace(',', '.')
    elif t.count('.') > 1 or (t.count('.') == 1 and len(t.split('.')[1]) == 3):
        t = t.replace('.', '')
    try:
        return Decimal(t)
    except InvalidOperation:
        return None


def _opciones_centro(gasto=None):
    """Los centros de costo para el desplegable: vehículos y categorías activas (y el que ya tiene)."""
    vehiculos = [(f'v{v.pk}', v.placa) for v in Vehiculo.objects.order_by('placa')]
    categorias = CategoriaGasto.objects.filter(activa=True)
    if gasto is not None and gasto.categoria_id:
        categorias = CategoriaGasto.objects.filter(Q(activa=True) | Q(pk=gasto.categoria_id))
    return [('', 'Elige a qué se carga'),
            ('Vehículos', vehiculos),
            ('Categorías', [(f'c{c.pk}', c.nombre) for c in categorias.order_by('nombre')])]


class GastoForm(forms.ModelForm):
    centro = forms.ChoiceField(label="A qué se carga")
    total_texto = forms.CharField(label="Total", max_length=30)

    class Meta:
        model = Gasto
        fields = ['tipo_documento', 'prefijo', 'folio', 'divisa', 'forma_pago', 'medio_pago',
                  'fecha_emision', 'fecha_recepcion', 'nit_emisor', 'nombre_emisor', 'nota', 'archivo']
        widgets = {
            'tipo_documento': forms.Select(attrs={'class': 'form-select'}),
            'prefijo': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Ej: FVE', 'autocomplete': 'off'}),
            'folio': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Ej: 604503', 'autocomplete': 'off'}),
            'divisa': forms.TextInput(attrs={'class': 'form-control', 'maxlength': 3}),
            'forma_pago': forms.Select(attrs={'class': 'form-select'}),
            'medio_pago': forms.Select(attrs={'class': 'form-select'}),
            'fecha_emision': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}, format='%Y-%m-%d'),
            'fecha_recepcion': forms.DateTimeInput(attrs={'class': 'form-control', 'type': 'datetime-local'},
                                                   format='%Y-%m-%dT%H:%M'),
            'nit_emisor': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Ej: 800066365',
                                                 'list': 'proveedores', 'autocomplete': 'off', 'inputmode': 'numeric'}),
            'nombre_emisor': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Ej: Inversiones Rengifo Rojas SAS'}),
            'nota': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Ej: Cambio de llantas traseras'}),
            'archivo': forms.FileInput(attrs={'class': 'form-control', 'accept': '.pdf,.xml,.zip,image/*'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        g = self.instance
        self.fields['centro'].choices = _opciones_centro(g if g.pk else None)
        self.fields['centro'].widget.attrs['class'] = 'form-select'
        self.fields['total_texto'].widget.attrs.update({'class': 'form-control gx-dinero', 'inputmode': 'decimal',
                                                         'placeholder': '$0', 'autocomplete': 'off'})
        self.fields['fecha_recepcion'].input_formats = ['%Y-%m-%dT%H:%M', '%Y-%m-%d %H:%M', '%Y-%m-%d']
        self.fields['prefijo'].required = False
        if g.pk:
            self.initial['centro'] = f'v{g.vehiculo_id}' if g.vehiculo_id else (f'c{g.categoria_id}' if g.categoria_id else '')
            self.initial['total_texto'] = f"{g.total:,.2f}".replace(',', 'X').replace('.', ',').replace('X', '.').rstrip('0').rstrip(',')
        else:
            self.initial.setdefault('fecha_emision', timezone.localdate())

    def clean_total_texto(self):
        valor = _numero(self.cleaned_data.get('total_texto'))
        if valor is None or valor <= 0:
            raise forms.ValidationError("Escribe el total del documento (mayor que cero). La nota crédito se resta sola.")
        return valor

    def clean_nit_emisor(self):
        return (self.cleaned_data.get('nit_emisor') or '').strip().replace(' ', '')

    def clean_divisa(self):
        return (self.cleaned_data.get('divisa') or 'COP').strip().upper() or 'COP'

    def clean(self):
        datos = super().clean()
        centro = datos.get('centro') or ''
        self._vehiculo = self._categoria = None
        if centro.startswith('v') and centro[1:].isdigit():
            self._vehiculo = Vehiculo.objects.filter(pk=int(centro[1:])).first()
        elif centro.startswith('c') and centro[1:].isdigit():
            self._categoria = CategoriaGasto.objects.filter(pk=int(centro[1:])).first()
        if self._vehiculo is None and self._categoria is None:
            self.add_error('centro', "Elige el vehículo o la categoría a la que se carga el gasto.")
        # El mismo documento del mismo proveedor no se registra dos veces.
        if datos.get('folio') and datos.get('nit_emisor') and datos.get('tipo_documento'):
            repetido = Gasto.objects.filter(tipo_documento=datos['tipo_documento'], nit_emisor=datos['nit_emisor'],
                                            prefijo=(datos.get('prefijo') or '').strip(), folio=datos['folio'].strip())
            if self.instance.pk:
                repetido = repetido.exclude(pk=self.instance.pk)
            if repetido.exists():
                self.add_error('folio', "Ese documento de ese proveedor ya está registrado.")
        return datos

    def save(self, commit=True):
        gasto = super().save(commit=False)
        gasto.prefijo = (gasto.prefijo or '').strip().upper()
        gasto.folio = gasto.folio.strip()
        gasto.total = self.cleaned_data['total_texto']
        gasto.vehiculo, gasto.categoria = self._vehiculo, self._categoria
        if commit:
            gasto.save()
        return gasto


# ============================================================
#  Cálculos
# ============================================================

def _filtrar(qs, request):
    """Los filtros de la lista: centro de costo y búsqueda (proveedor, NIT, documento)."""
    centro = (request.GET.get('centro') or '').strip()
    q = (request.GET.get('q') or '').strip()
    if centro == 'vehiculos':
        qs = qs.filter(vehiculo__isnull=False)
    elif centro == 'categorias':
        qs = qs.filter(categoria__isnull=False)
    elif centro.startswith('v') and centro[1:].isdigit():
        qs = qs.filter(vehiculo_id=int(centro[1:]))
    elif centro.startswith('c') and centro[1:].isdigit():
        qs = qs.filter(categoria_id=int(centro[1:]))
    else:
        centro = ''
    if q:
        qs = qs.filter(Q(nombre_emisor__icontains=q) | Q(nit_emisor__icontains=q)
                       | Q(folio__icontains=q) | Q(prefijo__icontains=q) | Q(nota__icontains=q))
    return qs, centro, q


def _suma(qs):
    """Suma con signo: las notas crédito restan."""
    total = Decimal('0')
    for tipo, t in qs.values_list('tipo_documento', 'total'):
        total += -t if tipo == 'NOTA_CREDITO' else t
    return total


def _ingreso_por_vehiculo(desde, hasta):
    """
    Lo que valen los servicios prestados en las fechas, ya con precio, por
    vehículo: el valor de cada orden se reparte entre sus placas (el mismo
    criterio del tablero de gerencia).
    """
    lineas = (LineaFactura.objects
              .annotate(servicio=Min('orden__recorridos__fecha_recorrido'))
              .filter(servicio__range=(desde, hasta))
              .exclude(orden__estado_orden='CANCELADA')
              .prefetch_related('conceptos', 'orden__recorridos'))
    valor = defaultdict(Decimal)
    total = Decimal('0')
    for l in lineas:
        sub = l.subtotal
        total += sub
        ids = sorted({r.vehiculo_id for r in l.orden.recorridos.all() if r.vehiculo_id})
        if not ids:
            valor[None] += sub
            continue
        for vid in ids:
            valor[vid] += sub / len(ids)
    return valor, total


def _margen(ingreso, gasto):
    """
    El margen sobre el ingreso, en %. Solo cuando los gastos no superan el
    ingreso: si lo superan, un «−7.800 %» no le dice nada a gerencia; la
    plantilla lo dice en palabras.
    """
    if not ingreso or gasto > ingreso:
        return None
    return float((ingreso - gasto) / ingreso * 100)


def utilidad(desde, hasta):
    """La utilidad del periodo: por vehículo, las categorías aparte y el total de la empresa."""
    ingreso_v, ingreso_total = _ingreso_por_vehiculo(desde, hasta)
    gastos = Gasto.objects.filter(fecha_emision__range=(desde, hasta))
    gasto_v = defaultdict(Decimal)
    gasto_c = defaultdict(Decimal)
    n_c = defaultdict(int)
    for tipo, total, vid, cid in gastos.values_list('tipo_documento', 'total', 'vehiculo_id', 'categoria_id'):
        valor = -total if tipo == 'NOTA_CREDITO' else total
        if vid:
            gasto_v[vid] += valor
        else:
            gasto_c[cid] += valor
            n_c[cid] += 1
    vehiculos = []
    for v in Vehiculo.objects.order_by('placa'):
        ing, gas = ingreso_v.get(v.pk, Decimal('0')), gasto_v.get(v.pk, Decimal('0'))
        if not ing and not gas:
            continue
        vehiculos.append({'id': v.pk, 'placa': v.placa, 'detalle': f"{v.marca} {v.modelo}".strip(),
                          'ingreso': float(ing), 'gasto': float(gas), 'utilidad': float(ing - gas),
                          'margen': _margen(ing, gas)})
    vehiculos.sort(key=lambda x: -x['utilidad'])
    nombres = dict(CategoriaGasto.objects.values_list('pk', 'nombre'))
    categorias = sorted(({'id': cid, 'nombre': nombres.get(cid, 'Sin asignar'), 'gasto': float(v), 'n': n_c[cid]}
                         for cid, v in gasto_c.items()), key=lambda x: -x['gasto'])
    gasto_vehiculos = sum(gasto_v.values(), Decimal('0'))
    gasto_categorias = sum(gasto_c.values(), Decimal('0'))
    gasto_total = gasto_vehiculos + gasto_categorias
    sin_vehiculo = ingreso_v.get(None, Decimal('0'))
    return {
        'vehiculos': vehiculos,
        'categorias': categorias,
        'ingreso': float(ingreso_total),
        'ingreso_sin_vehiculo': float(sin_vehiculo),
        'gasto': float(gasto_total),
        'gasto_vehiculos': float(gasto_vehiculos),
        'gasto_categorias': float(gasto_categorias),
        'utilidad_vehiculos': float(sum((Decimal(str(v['utilidad'])) for v in vehiculos), Decimal('0'))),
        'utilidad': float(ingreso_total - gasto_total),
        'margen': _margen(ingreso_total, gasto_total),
    }


def _por_mes(hasta):
    """Ingreso, gasto y utilidad de los 12 meses que terminan en `hasta`."""
    meses = []
    inicio = _sumar_meses(hasta.replace(day=1), -11)
    cursor = inicio
    while cursor <= hasta:
        import calendar
        fin = min(cursor.replace(day=calendar.monthrange(cursor.year, cursor.month)[1]), hasta)
        _, ingreso = _ingreso_por_vehiculo(cursor, fin)
        gasto = _suma(Gasto.objects.filter(fecha_emision__range=(cursor, fin)))
        meses.append({'etiqueta': f"{MESES_CORTOS[cursor.month - 1]} {str(cursor.year)[2:]}",
                      'mes': nombre_periodo(cursor, fin).capitalize(),
                      'ingreso': float(ingreso), 'gasto': float(gasto), 'utilidad': float(ingreso - gasto)})
        cursor = _sumar_meses(cursor, 1)
    return meses


def _periodo_contexto(request):
    clave, desde, hasta = periodo_de(request)
    a_desde, a_hasta = periodo_anterior(desde, hasta, clave)
    return {'periodo': clave, 'periodos': PERIODOS, 'desde': desde, 'hasta': hasta,
            'frase_periodo': frase_periodo(clave, desde, hasta),
            'nombre_periodo': nombre_periodo(desde, hasta),
            'nombre_anterior': nombre_periodo(a_desde, a_hasta),
            'a_desde': a_desde, 'a_hasta': a_hasta}


def _delta(actual, anterior):
    actual, anterior = float(actual or 0), float(anterior or 0)
    return round((actual - anterior) / anterior * 100, 1) if anterior else None


# ============================================================
#  Las vistas
# ============================================================

class GastosView(AdministradorRequiredMixin, PaginadoMixin, View):
    """El registro de gastos del periodo, con sus filtros y totales."""
    acceso = 'gastos.ver'
    template_name = 'gestion/gastos_lista.html'

    def get(self, request):
        from django.core.paginator import Paginator
        ctx = _periodo_contexto(request)
        base = Gasto.objects.filter(fecha_emision__range=(ctx['desde'], ctx['hasta']))
        qs, centro, q = _filtrar(base.select_related('vehiculo', 'categoria'), request)
        total = _suma(qs)
        anterior = _suma(_filtrar(Gasto.objects.filter(fecha_emision__range=(ctx['a_desde'], ctx['a_hasta'])), request)[0])
        pagina = Paginator(qs.order_by('-fecha_emision', '-pk'), 30).get_page(request.GET.get('page'))
        # El resumen de arriba: siempre sobre el periodo, sin el filtro de centro.
        resumen = {
            'total': total, 'delta': _delta(total, anterior), 'n': qs.count(),
            'vehiculos': _suma(base.filter(vehiculo__isnull=False)),
            'categorias': _suma(base.filter(categoria__isnull=False)),
        }
        mayor = (base.values('nombre_emisor').annotate(t=Sum('total'), n=Count('pk')).order_by('-t').first())
        ctx.update({
            'gastos': pagina.object_list, 'page_obj': pagina, 'pagina_rango': rango_de_paginas(pagina, 2),
            'resumen': resumen, 'mayor_proveedor': mayor, 'centro': centro, 'q': q,
            'centros': _opciones_centro(), 'filtrado': bool(centro or q),
            'pestana': 'registro',
        })
        return render(request, self.template_name, ctx)


class GastoFormView(AdministradorRequiredMixin, View):
    """Registrar o corregir un gasto. Se queda en el formulario para registrar el siguiente si se pide."""
    acceso = 'gastos.editar'
    template_name = 'gestion/gasto_form.html'

    def _gasto(self, pk):
        return get_object_or_404(Gasto, pk=pk) if pk else None

    def _render(self, request, form, gasto):
        # Para el autocompletado: cada NIT ya usado con su nombre (no se vuelve a teclear).
        proveedores = (Gasto.objects.values('nit_emisor', 'nombre_emisor').annotate(n=Count('pk'))
                       .order_by('-n')[:300])
        return render(request, self.template_name, {
            'form': form, 'gasto': gasto, 'proveedores': list(proveedores),
            'hay_categorias': CategoriaGasto.objects.filter(activa=True).exists(), 'pestana': 'registro',
        })

    def get(self, request, pk=None):
        gasto = self._gasto(pk)
        return self._render(request, GastoForm(instance=gasto), gasto)

    def post(self, request, pk=None):
        gasto = self._gasto(pk)
        form = GastoForm(request.POST, request.FILES, instance=gasto)
        if not form.is_valid():
            return self._render(request, form, gasto)
        nuevo = form.save(commit=False)
        if nuevo.registrado_por_id is None:
            nuevo.registrado_por = request.user
        try:
            nuevo.save()
        except IntegrityError:
            # Dos envíos a la vez del mismo documento: el segundo no lo duplica.
            form.add_error('folio', "Ese documento de ese proveedor ya está registrado.")
            return self._render(request, form, gasto)
        messages.success(request, f"Gasto {nuevo.documento} de {nuevo.nombre_emisor} por ${nuevo.total:,.0f} "
                                  f"cargado a {nuevo.centro}.".replace(',', '.'))
        if 'otro' in request.POST and gasto is None:
            return redirect('gestion:crear_gasto')
        return redirect('gestion:gastos')


class EliminarGastoView(AdministradorRequiredMixin, View):
    acceso = 'gastos.eliminar'

    def post(self, request, pk):
        gasto = Gasto.objects.filter(pk=pk).first()
        if gasto is None:
            messages.info(request, "Ese gasto ya se había eliminado.")
            return redirect('gestion:gastos')
        documento = gasto.documento
        if gasto.archivo:
            gasto.archivo.delete(save=False)
        gasto.delete()
        messages.success(request, f"Gasto {documento} eliminado.")
        return redirect('gestion:gastos')


class CategoriasGastoView(AdministradorRequiredMixin, View):
    """Las categorías propias: crear, renombrar y archivar (no se borran: sus gastos se conservan)."""
    acceso = 'gastos.ver'
    acceso_escribir = 'gastos.editar'
    template_name = 'gestion/gastos_categorias.html'

    def get(self, request):
        from django.db.models import Case, F, When
        # El total con signo: la nota crédito resta, como en el resto del módulo.
        neto = Case(When(gastos__tipo_documento='NOTA_CREDITO', then=-F('gastos__total')), default=F('gastos__total'))
        categorias = (CategoriaGasto.objects.annotate(n=Count('gastos'), t=Sum(neto))
                      .order_by('-activa', 'nombre'))
        return render(request, self.template_name, {'categorias': categorias, 'pestana': 'categorias'})

    def post(self, request):
        volver = redirect('gestion:categorias_gasto')
        nombre = ' '.join((request.POST.get('nombre') or '').split())[:80]
        descripcion = (request.POST.get('descripcion') or '').strip()[:255]
        if 'crear' in request.POST:
            if not nombre:
                messages.error(request, "Escribe el nombre de la categoría.")
                return volver
            if CategoriaGasto.objects.filter(nombre__iexact=nombre).exists():
                messages.error(request, f"Ya existe una categoría «{nombre}».")
                return volver
            CategoriaGasto.objects.create(nombre=nombre, descripcion=descripcion)
            messages.success(request, f"Categoría «{nombre}» creada.")
            return volver
        categoria = CategoriaGasto.objects.filter(pk=request.POST.get('categoria') or 0).first()
        if categoria is None:
            messages.error(request, "Esa categoría ya no existe.")
            return volver
        if 'guardar' in request.POST:
            if not nombre:
                messages.error(request, "El nombre no puede quedar vacío.")
                return volver
            if CategoriaGasto.objects.filter(nombre__iexact=nombre).exclude(pk=categoria.pk).exists():
                messages.error(request, f"Ya existe otra categoría «{nombre}».")
                return volver
            categoria.nombre, categoria.descripcion = nombre, descripcion
            categoria.save(update_fields=['nombre', 'descripcion'])
            messages.success(request, f"Categoría «{nombre}» guardada.")
        elif 'archivar' in request.POST:
            categoria.activa = not categoria.activa
            categoria.save(update_fields=['activa'])
            messages.success(request, f"Categoría «{categoria.nombre}» "
                                      f"{'activada de nuevo' if categoria.activa else 'archivada: ya no se ofrece al registrar'}.")
        return volver


class UtilidadView(AdministradorRequiredMixin, View):
    """La utilidad del periodo: por vehículo (ingreso − gastos), las categorías aparte y el total."""
    acceso = 'gastos.ver'
    template_name = 'gestion/gastos_utilidad.html'

    def get(self, request):
        ctx = _periodo_contexto(request)
        u = utilidad(ctx['desde'], ctx['hasta'])
        ua = utilidad(ctx['a_desde'], ctx['a_hasta'])
        u['utilidad_delta'] = _delta(u['utilidad'], ua['utilidad']) if ua['utilidad'] > 0 else None
        u['gasto_delta'] = _delta(u['gasto'], ua['gasto'])
        meses = _por_mes(ctx['hasta'])
        ctx.update({'u': u, 'meses': meses, 'pestana': 'utilidad',
                    # La escala de las barras: el mayor valor de cada tabla.
                    'u_max': max([max(v['ingreso'], v['gasto']) for v in u['vehiculos']] + [0]),
                    'meses_max': max([max(m['ingreso'], m['gasto']) for m in meses] + [0])})
        return render(request, self.template_name, ctx)
