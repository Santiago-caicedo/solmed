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
    """
    Un monto como lo pega Excel → Decimal (None si no es un número). Acepta
    «$ 148.750», «120.039,44», «148750», «120039.44» y, si el Excel está en
    inglés, «$148,750.00»: manda el ÚLTIMO separador que aparezca.
    """
    t = str(texto or '').strip().replace('$', '').replace(' ', '').replace(' ', '')
    if not t:
        return None
    coma, punto = t.rfind(','), t.rfind('.')
    if coma >= 0 and punto >= 0:
        if coma > punto:                       # 1.234.567,89
            t = t.replace('.', '').replace(',', '.')
        else:                                  # 1,234,567.89
            t = t.replace(',', '')
    elif coma >= 0:                            # 1234,5  ·  1,234,567
        t = t.replace(',', '') if t.count(',') > 1 or len(t.split(',')[1]) == 3 else t.replace(',', '.')
    elif t.count('.') > 1 or (punto >= 0 and len(t.split('.')[1]) == 3):
        t = t.replace('.', '')                 # 148.750  ·  1.234.567
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


class GastoForm(forms.ModelForm):
    """
    Corregir UN gasto ya registrado (nov-2026: el registro es en lote, en la
    tabla; esto queda solo detrás de «Editar»). Mismos campos de la tabla:
    tipo, folio, prefijo, fecha, NIT, nombre, total, COSTOS (categoría),
    PLACA (vehículo) y DETALLE, más el archivo opcional.
    """
    total_texto = forms.CharField(label="Total", max_length=30)

    class Meta:
        model = Gasto
        fields = ['tipo_documento', 'folio', 'prefijo', 'fecha_emision', 'nit_emisor', 'nombre_emisor',
                  'categoria', 'vehiculo', 'nota', 'archivo']
        labels = {'categoria': 'Costos (categoría)', 'vehiculo': 'Placa', 'nota': 'Detalle'}
        widgets = {
            'tipo_documento': forms.Select(attrs={'class': 'form-select'}),
            'folio': forms.TextInput(attrs={'class': 'form-control', 'autocomplete': 'off'}),
            'prefijo': forms.TextInput(attrs={'class': 'form-control', 'autocomplete': 'off'}),
            'fecha_emision': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}, format='%Y-%m-%d'),
            'nit_emisor': forms.TextInput(attrs={'class': 'form-control', 'inputmode': 'numeric', 'autocomplete': 'off'}),
            'nombre_emisor': forms.TextInput(attrs={'class': 'form-control'}),
            'categoria': forms.Select(attrs={'class': 'form-select'}),
            'vehiculo': forms.Select(attrs={'class': 'form-select'}),
            'nota': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Ej: Llantas'}),
            'archivo': forms.FileInput(attrs={'class': 'form-control', 'accept': '.pdf,.xml,.zip,image/*'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        g = self.instance
        categorias = CategoriaGasto.objects.filter(Q(activa=True) | Q(pk=g.categoria_id or 0)).order_by('nombre')
        self.fields['categoria'].queryset = categorias
        self.fields['categoria'].empty_label = 'Sin categoría'
        self.fields['vehiculo'].queryset = Vehiculo.objects.order_by('placa')
        self.fields['vehiculo'].empty_label = 'Sin placa'
        self.fields['prefijo'].required = False
        self.fields['total_texto'].widget.attrs.update({'class': 'form-control gx-dinero', 'inputmode': 'decimal',
                                                         'autocomplete': 'off'})
        if g.pk:
            self.initial['total_texto'] = _texto_pesos(g.total)

    def clean_total_texto(self):
        valor = _numero(self.cleaned_data.get('total_texto'))
        if valor is None or valor <= 0:
            raise forms.ValidationError("Escribe el total del documento (mayor que cero). La nota crédito se resta sola.")
        return valor

    def clean_nit_emisor(self):
        return _nit(self.cleaned_data.get('nit_emisor')) or ''

    def clean(self):
        datos = super().clean()
        if not datos.get('categoria') and not datos.get('vehiculo'):
            self.add_error('categoria', "Escoge la categoría (COSTOS), la placa o las dos.")
        if datos.get('folio') and datos.get('nit_emisor') and datos.get('tipo_documento'):
            repetido = Gasto.objects.filter(tipo_documento=datos['tipo_documento'], nit_emisor=datos['nit_emisor'],
                                            prefijo=(datos.get('prefijo') or '').strip().upper(),
                                            folio=datos['folio'].strip()).exclude(pk=self.instance.pk)
            if repetido.exists():
                self.add_error('folio', "Ese documento de ese proveedor ya está registrado.")
        return datos

    def save(self, commit=True):
        gasto = super().save(commit=False)
        gasto.prefijo = (gasto.prefijo or '').strip().upper()
        gasto.folio = gasto.folio.strip()
        gasto.total = self.cleaned_data['total_texto']
        if commit:
            gasto.save()
        return gasto


# ============================================================
#  El registro EN LOTE (nov-2026, pedido de la clienta): una tabla con las
#  columnas de su Excel —Tipo de documento, Folio, Prefijo, Fecha Emisión,
#  NIT Emisor, Nombre Emisor, Total, COSTOS, PLACAS, DETALLE— donde se
#  pegan las filas copiadas del Excel. Cada celda se normaliza y se valida;
#  si algo no cuadra, no se guarda nada y la celda queda marcada.
# ============================================================

COLUMNAS_LOTE = [
    ('tipo', 'Tipo de documento'), ('folio', 'Folio'), ('prefijo', 'Prefijo'),
    ('fecha', 'Fecha emisión'), ('nit', 'NIT emisor'), ('nombre', 'Nombre emisor'),
    ('total', 'Total'), ('costos', 'Costos'), ('placa', 'Placas'), ('detalle', 'Detalle'),
]
FILAS_INICIALES = 12
# Nov-2026: el tope de filas SALE DE UNA CUENTA. Cada fila de la tabla manda
# un campo por columna (aunque esté vacía), y Django rechaza con 400 un
# formulario con más de DATA_UPLOAD_MAX_NUMBER_FIELDS campos. Se reservan
# unos para el csrf y las casillas de categorías nuevas. Con 6000 → 590.
RESERVA_CAMPOS = 100


def max_filas():
    from django.conf import settings
    tope = getattr(settings, 'DATA_UPLOAD_MAX_NUMBER_FIELDS', 1000) or 100000
    return max((tope - RESERVA_CAMPOS) // len(COLUMNAS_LOTE), 1)


MAX_FILAS = max_filas()


def _texto_pesos(valor):
    """1234567.5 → «1.234.567,5» (como lo escribe la oficina)."""
    entero, _, dec = f"{valor:.2f}".partition('.')
    entero = f"{int(entero):,}".replace(',', '.')
    dec = dec.rstrip('0')
    return f"{entero},{dec}" if dec else entero


def _nit(texto):
    """El NIT sin puntos, espacios ni dígito de verificación separado por guion se deja tal cual."""
    t = str(texto or '').strip().replace('.', '').replace(' ', '')
    if not t or t.upper() in ('#VALUE!', '#¡VALOR!', '#N/A', '#VALOR!'):
        return None
    if t.endswith('.0'):
        t = t[:-2]
    return t


def _tipo_documento(texto):
    t = str(texto or '').strip().lower()
    if not t or 'factura' in t:
        return 'FACTURA'
    if 'crédito' in t or 'credito' in t:
        return 'NOTA_CREDITO'
    if 'débito' in t or 'debito' in t:
        return 'NOTA_DEBITO'
    if 'soporte' in t:
        return 'SOPORTE'
    return None


def _fecha(texto):
    """«03-08-2026», «03/08/2026», «2026-08-03» o con hora → date. None si no se entiende."""
    t = str(texto or '').strip().split(' ')[0].split('T')[0]
    for formato in ('%d-%m-%Y', '%d/%m/%Y', '%Y-%m-%d', '%d-%m-%y', '%d/%m/%y'):
        try:
            return datetime.datetime.strptime(t, formato).date()
        except ValueError:
            continue
    return None


def _placa(texto):
    return str(texto or '').strip().upper().replace(' ', '').replace('-', '')


def revisar_lote(filas, crear_categorias=()):
    """
    Revisa las filas pegadas. Devuelve (resultado, categorias_nuevas):
    `resultado` es una lista con, por fila, los valores tal como se ven,
    los datos normalizados, los errores por columna y si se omite (ya estaba
    registrada). `categorias_nuevas`: los COSTOS que no existen (para
    ofrecer crearlos). Con `crear_categorias`, esos nombres se aceptan.
    """
    vehiculos = {v.placa.upper(): v for v in Vehiculo.objects.all()}
    categorias = {c.nombre.strip().lower(): c for c in CategoriaGasto.objects.all()}
    crear = {c.strip().lower() for c in crear_categorias if c.strip()}
    nuevas = {}
    vistos = {}
    resultado = []
    for i, fila in enumerate(filas):
        if not any(str(v or '').strip() for v in fila.values()):
            continue
        errores, datos = {}, {}
        datos['tipo_documento'] = _tipo_documento(fila.get('tipo'))
        if datos['tipo_documento'] is None:
            errores['tipo'] = "Tipo no reconocido: usa factura, nota crédito o nota débito."
        datos['folio'] = str(fila.get('folio') or '').strip()
        if datos['folio'].endswith('.0'):
            datos['folio'] = datos['folio'][:-2]
        if not datos['folio']:
            errores['folio'] = "Falta el folio."
        datos['prefijo'] = str(fila.get('prefijo') or '').strip().upper()
        datos['fecha_emision'] = _fecha(fila.get('fecha'))
        if datos['fecha_emision'] is None:
            errores['fecha'] = "Fecha no válida (usa día-mes-año)."
        datos['nit_emisor'] = _nit(fila.get('nit'))
        if not datos['nit_emisor']:
            errores['nit'] = "Falta el NIT (en el Excel puede venir como #VALUE!)."
        datos['nombre_emisor'] = str(fila.get('nombre') or '').strip()[:200]
        if not datos['nombre_emisor']:
            errores['nombre'] = "Falta el nombre del emisor."
        total = _numero(fila.get('total'))
        datos['total'] = total
        if total is None or total <= 0:
            errores['total'] = "Total no válido."
        # COSTOS: una categoría (existente, o nueva si se pidió crearla).
        costos = ' '.join(str(fila.get('costos') or '').split())
        datos['categoria'] = None
        datos['categoria_nueva'] = ''
        if costos:
            cat = categorias.get(costos.lower())
            if cat is not None:
                datos['categoria'] = cat
            elif costos.lower() in crear:
                datos['categoria_nueva'] = costos
            else:
                nuevas.setdefault(costos.lower(), costos)
                errores['costos'] = f"La categoría «{costos}» no existe: márcala para crearla."
        # PLACAS: un vehículo del sistema; si no existe o viene incompleta, se pide corregir.
        placa = _placa(fila.get('placa'))
        datos['vehiculo'] = None
        if placa:
            v = vehiculos.get(placa)
            if v is not None:
                datos['vehiculo'] = v
            else:
                parecidas = [p for p in vehiculos if p.startswith(placa) or placa.startswith(p)]
                errores['placa'] = (f"No existe {placa}." + (f" ¿Es {', '.join(sorted(parecidas))}?" if parecidas else ""))
        if not costos and not placa:
            errores['costos'] = "Escribe la categoría (COSTOS), la placa o las dos."
        datos['nota'] = str(fila.get('detalle') or '').strip()[:255]
        # Duplicados: en la misma tabla es error; ya registrado en el sistema se omite.
        omitir = False
        if datos['folio'] and datos['nit_emisor'] and datos['tipo_documento']:
            llave = (datos['tipo_documento'], datos['nit_emisor'], datos['prefijo'], datos['folio'])
            if llave in vistos:
                errores['folio'] = f"Repetido en la fila {vistos[llave] + 1}."
            else:
                vistos[llave] = i
                omitir = Gasto.objects.filter(tipo_documento=llave[0], nit_emisor=llave[1],
                                              prefijo=llave[2], folio=llave[3]).exists()
        resultado.append({'n': i + 1, 'valores': fila, 'datos': datos, 'errores': errores, 'omitir': omitir})
    return resultado, sorted(nuevas.values(), key=str.lower)


def _filas_del_post(request):
    """Las filas de la tabla tal como llegan: una lista por columna, alineadas."""
    columnas = {clave: request.POST.getlist(f'c_{clave}') for clave, _ in COLUMNAS_LOTE}
    n = max((len(v) for v in columnas.values()), default=0)
    return [{clave: (columnas[clave][i] if i < len(columnas[clave]) else '') for clave, _ in COLUMNAS_LOTE}
            for i in range(n)]


class GastosLoteView(AdministradorRequiredMixin, View):
    """
    «Registrar gastos»: la tabla en lote. Se pegan las filas del Excel, el
    sistema las revisa y, si todo cuadra, las guarda juntas (o ninguna).
    Las ya registradas (mismo tipo, NIT, prefijo y folio) se omiten.
    """
    acceso = 'gastos.editar'
    template_name = 'gestion/gastos_lote.html'

    def _render(self, request, filas, resultado=None, nuevas=(), crear=()):
        errores = {r['n'] - 1: r['errores'] for r in (resultado or [])}
        omitidas = {r['n'] - 1 for r in (resultado or []) if r['omitir']}
        while len(filas) < FILAS_INICIALES:
            filas.append({clave: '' for clave, _ in COLUMNAS_LOTE})
        tabla = [{'n': i + 1, 'celdas': [{'clave': c, 'valor': f.get(c, ''), 'error': errores.get(i, {}).get(c, '')}
                                          for c, _ in COLUMNAS_LOTE],
                  'con_error': bool(errores.get(i)), 'omitida': i in omitidas}
                 for i, f in enumerate(filas)]
        return render(request, self.template_name, {
            'columnas': COLUMNAS_LOTE, 'tabla': tabla, 'nuevas': nuevas, 'crear': set(crear),
            'max_filas': MAX_FILAS,
            'n_errores': sum(1 for r in (resultado or []) if r['errores']),
            'placas': list(Vehiculo.objects.order_by('placa').values_list('placa', flat=True)),
            'categorias': list(CategoriaGasto.objects.filter(activa=True).order_by('nombre').values_list('nombre', flat=True)),
            'pestana': 'registro',
        })

    def get(self, request):
        return self._render(request, [])

    def post(self, request):
        from django.db import transaction
        filas = _filas_del_post(request)
        crear = request.POST.getlist('crear_categoria')
        # La tabla no deja pasar del tope; si igual llegan más (otro navegador,
        # JS apagado), no se guarda NADA en vez de descartar filas en silencio.
        llenas = [f for f in filas if any((v or '').strip() for v in f.values())]
        if len(llenas) > MAX_FILAS:
            messages.error(request, f"Llegaron {len(llenas)} filas y caben {MAX_FILAS} por vez. "
                                    f"No se guardó nada: deja las primeras {MAX_FILAS}, guárdalas y pega el resto después.")
            return self._render(request, llenas[:MAX_FILAS])
        filas = filas[:MAX_FILAS] if len(filas) > MAX_FILAS else filas
        resultado, nuevas = revisar_lote(filas, crear)
        if not resultado:
            messages.error(request, "La tabla está vacía: pega las filas del Excel o escríbelas.")
            return self._render(request, filas)
        con_error = [r for r in resultado if r['errores']]
        if con_error:
            messages.error(request, f"{len(con_error)} fila{'s' if len(con_error) != 1 else ''} con algo por corregir "
                                    "(marcadas en rojo). No se guardó nada todavía.")
            return self._render(request, filas, resultado, nuevas, crear)
        por_guardar = [r for r in resultado if not r['omitir']]
        omitidas = len(resultado) - len(por_guardar)
        try:
            with transaction.atomic():
                creadas = {}
                for r in por_guardar:
                    d = r['datos']
                    if d['categoria_nueva'] and d['categoria'] is None:
                        clave = d['categoria_nueva'].lower()
                        if clave not in creadas:
                            creadas[clave] = (CategoriaGasto.objects.filter(nombre__iexact=d['categoria_nueva']).first()
                                              or CategoriaGasto.objects.create(nombre=d['categoria_nueva'].title()))
                        d['categoria'] = creadas[clave]
                    Gasto.objects.create(
                        tipo_documento=d['tipo_documento'], folio=d['folio'], prefijo=d['prefijo'],
                        fecha_emision=d['fecha_emision'], nit_emisor=d['nit_emisor'], nombre_emisor=d['nombre_emisor'],
                        total=d['total'], categoria=d['categoria'], vehiculo=d['vehiculo'], nota=d['nota'],
                        registrado_por=request.user)
        except IntegrityError:
            messages.error(request, "Alguien registró uno de estos documentos al mismo tiempo. No se guardó nada: "
                                    "vuelve a guardar y el sistema omitirá los que ya estén.")
            return self._render(request, filas)
        total = sum((r['datos']['total'] for r in por_guardar), Decimal('0'))
        texto = f"{len(por_guardar)} gasto{'s' if len(por_guardar) != 1 else ''} registrado{'s' if len(por_guardar) != 1 else ''} por ${_texto_pesos(total)}"
        if creadas:
            texto += f"; se crearon las categorías {', '.join(c.nombre for c in creadas.values())}"
        if omitidas:
            texto += f". {omitidas} ya estaba{'n' if omitidas != 1 else ''} registrado{'s' if omitidas != 1 else ''} y se omiti{'eron' if omitidas != 1 else 'ó'}"
        messages.success(request, texto + ".")
        return redirect('gestion:gastos')


class GastoFormView(AdministradorRequiredMixin, View):
    """Corregir un gasto ya registrado (el registro nuevo es en lote)."""
    acceso = 'gastos.editar'
    template_name = 'gestion/gasto_form.html'

    def get(self, request, pk):
        gasto = get_object_or_404(Gasto, pk=pk)
        return render(request, self.template_name, {'form': GastoForm(instance=gasto), 'gasto': gasto,
                                                    'pestana': 'registro'})

    def post(self, request, pk):
        gasto = get_object_or_404(Gasto, pk=pk)
        form = GastoForm(request.POST, request.FILES, instance=gasto)
        if not form.is_valid():
            return render(request, self.template_name, {'form': form, 'gasto': gasto, 'pestana': 'registro'})
        try:
            form.save()
        except IntegrityError:
            form.add_error('folio', "Ese documento de ese proveedor ya está registrado.")
            return render(request, self.template_name, {'form': form, 'gasto': gasto, 'pestana': 'registro'})
        messages.success(request, f"Gasto {gasto.documento} actualizado.")
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
