"""
Vistas del plan de trabajo diario.

Acceso: ÚNICAMENTE el superusuario y el rol Administradores (decisión del
usuario, ago-2026) — ni siquiera los asesores: el plan reparte a TODO el
personal y registra sus novedades de recursos humanos (incapacidades,
licencias, descargos...). Se reutilizan los mixins de gestión.
"""
import base64
import datetime
import os

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.models import User
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import get_template
from django.urls import reverse
from django.utils import timezone
from django.views import View
from django.views.generic import ListView
from weasyprint import HTML

from gestion.models import Dispositor, Manifiesto, Recorrido, Vehiculo
from gestion.views import AdministradorRequiredMixin, PaginadoMixin

from .forms import AsignacionForm, NovedadForm
from .models import Asignacion, Novedad, PlanDia

# El orden del formato físico: primero la operación, luego la oficina.
ORDEN_CARGOS = [
    'Conductores', 'Ayudantes', 'Planificadores', 'Asesores',
    'Talento Humano', 'Director Técnico', 'SISO', 'Soldador - Armador',
    'Auxiliares Administrativas', 'Administrativo', 'Administradores',
]


def _fecha_de(request):
    """La fecha pedida (?fecha=AAAA-MM-DD) o la de hoy."""
    crudo = request.GET.get('fecha') or request.POST.get('fecha') or ''
    try:
        return datetime.datetime.strptime(crudo, '%Y-%m-%d').date()
    except ValueError:
        return timezone.localdate()


def _personal_activo():
    """Todo el personal del plan: con rol, activo laboralmente, sin superadmins."""
    return (
        User.objects.filter(groups__isnull=False, is_superuser=False)
        .exclude(perfil__retirado=True)
        .prefetch_related('groups').distinct()
    )


def _cargo_de(persona):
    """El cargo con el que la persona sale en el plan (el más operativo)."""
    nombres = {g.name for g in persona.groups.all()}
    for cargo in ORDEN_CARGOS:
        if cargo in nombres:
            return cargo
    return next(iter(nombres), 'Sin cargo')


def _horario_de(recorrido, acta):
    """
    Las horas en que la cuadrilla participó en la orden. La fuente más real es
    el ACTA que llenó el conductor: la salida y la llegada a SolMed (la jornada
    completa) o, si no las anotó, el inicio y el final operativos. Sin tiempos
    en el acta, se muestra la hora PROGRAMADA por el asesor, marcada "prog."
    para distinguir el plan de lo ejecutado.
    """
    if acta is not None:
        inicio = acta.hora_salida_solmed or acta.tiempo_inicio_operativo
        fin = acta.hora_llegada_solmed or acta.tiempo_final_operativo
        if inicio and fin:
            return f"{inicio:%H:%M}–{fin:%H:%M}"
        if inicio:
            return f"desde {inicio:%H:%M}"
    programacion = getattr(recorrido.orden, 'programacion_origen', None)
    if programacion is not None:
        hora = programacion.hora_servicio or programacion.hora_ingreso_bodega
        if hora:
            return f"prog. {hora:%H:%M}"
    return ''


def _servicios_del_dia(fecha):
    """
    {persona_id: [servicio]} con los servicios de ese día: entran SOLOS al
    plan (el recorrido es la fuente, no se digitan de nuevo), cada uno con la
    orden, la placa y las horas en que la persona participó (_horario_de).
    """
    servicios = {}
    recorridos = (
        Recorrido.objects.filter(fecha_recorrido=fecha)
        .exclude(orden__estado_orden='CANCELADA')
        .select_related('vehiculo', 'orden', 'orden__cliente',
                        'orden__programacion_origen')
    )
    # El acta es OneToOne y puede no existir: se trae aparte en un solo query.
    actas = {a.recorrido_id: a for a in Manifiesto.objects.filter(
        recorrido__fecha_recorrido=fecha)}
    for r in recorridos:
        servicio = {'orden': r.orden_id, 'placa': r.vehiculo.placa,
                    'cliente': r.orden.cliente.nombre,
                    'horas': _horario_de(r, actas.get(r.pk))}
        for persona_id in (r.conductor_id, r.ayudante_id, r.ayudante2_id):
            if persona_id:
                servicios.setdefault(persona_id, []).append(servicio)
    return servicios


def _tablero(fecha):
    """
    El tablero de formación del día: los grupos de cargos, y por persona sus
    servicios, asignaciones y novedades. Es la misma fuente de la pantalla y
    del PDF, para que digan exactamente lo mismo.
    """
    servicios = _servicios_del_dia(fecha)
    plan = PlanDia.objects.filter(fecha=fecha).first()
    asignaciones = {}
    if plan:
        for a in (plan.asignaciones.select_related('persona', 'orden', 'proveedor')
                  .prefetch_related('vehiculos')):
            asignaciones.setdefault(a.persona_id, []).append(a)
    novedades = {}
    for n in Novedad.del_dia(fecha):
        novedades.setdefault(n.persona_id, []).append(n)

    por_cargo = {}
    for persona in _personal_activo():
        fila = {
            'persona': persona,
            'nombre': persona.get_full_name() or persona.username,
            'servicios': servicios.get(persona.pk, []),
            'asignaciones': asignaciones.get(persona.pk, []),
            'novedades': novedades.get(persona.pk, []),
        }
        fila['con_plan'] = bool(fila['servicios'] or fila['asignaciones']
                                or fila['novedades'])
        por_cargo.setdefault(_cargo_de(persona), []).append(fila)

    grupos = []
    conocidos = [c for c in ORDEN_CARGOS if c in por_cargo]
    extras = sorted(c for c in por_cargo if c not in ORDEN_CARGOS)
    for cargo in conocidos + extras:
        filas = sorted(por_cargo[cargo], key=lambda f: f['nombre'].lower())
        grupos.append({
            'cargo': cargo,
            'filas': filas,
            'total': len(filas),
            'con_plan': sum(1 for f in filas if f['con_plan']),
        })
    return plan, grupos


class PlanDiaView(AdministradorRequiredMixin, View):
    """El plan de UN día: tablero de formación + registro de actividades y novedades."""
    template_name = 'planes/plan_dia.html'

    def get(self, request):
        fecha = _fecha_de(request)
        plan, grupos = _tablero(fecha)
        total = sum(g['total'] for g in grupos)
        con_plan = sum(g['con_plan'] for g in grupos)
        # Metadatos de cada actividad para que el JS muestre solo sus campos.
        campos_tipo = {
            tipo: {
                'vehiculos': spec.get('vehiculos') or '',
                'orden': bool(spec.get('orden')),
                'proveedor': bool(spec.get('proveedor')),
                'hora': bool(spec.get('hora')),
                'detalle': bool(spec.get('detalle')),
            }
            for tipo, spec in Asignacion.CAMPOS_POR_TIPO.items()
        }
        hoy = timezone.localdate()
        return render(request, self.template_name, {
            'fecha': fecha,
            'hoy': hoy,
            'ayer': fecha - datetime.timedelta(days=1),
            'manana': fecha + datetime.timedelta(days=1),
            'plan': plan,
            'grupos': grupos,
            'total_personas': total,
            'con_plan': con_plan,
            'sin_plan': total - con_plan,
            'form_asignacion': AsignacionForm(),
            'form_novedad': NovedadForm(initial={'fecha_inicio': fecha}),
            'campos_tipo': campos_tipo,
            'tipos_actividad': Asignacion.TIPO_CHOICES,
            # TODAS las placas (también las que están en taller: la
            # tecnomecánica o el mantenimiento son justo para esas). Cada una
            # sabe si lleva residuo y qué orden la cargó: la actividad de
            # disposición solo ofrece esas, y es la única vía para descargar.
            'vehiculos': self._placas(),
            'gestores': Dispositor.objects.filter(activo=True, tipo='PROVEEDOR'),
        })

    @staticmethod
    def _placas():
        vehiculos = list(Vehiculo.objects.order_by('placa').prefetch_related(
            'movimientos_carga'))
        for v in vehiculos:
            movimiento = v.carga_actual
            v.orden_carga = movimiento.orden_id if movimiento is not None else None
            v.detalle_carga = (v.cargado_detalle or '') if v.cargado else ''
        return vehiculos

    def post(self, request):
        fecha = _fecha_de(request)
        volver = f"{reverse('planes:plan_dia')}?fecha={fecha.isoformat()}"

        if 'submit_asignacion' in request.POST:
            form = AsignacionForm(
                request.POST,
                personas_ids=request.POST.getlist('personas'),
                vehiculos_ids=request.POST.getlist('vehiculos'),
            )
            if form.is_valid():
                plan, _ = PlanDia.objects.get_or_create(
                    fecha=fecha, defaults={'creado_por': request.user})
                n = form.crear(plan, request.user)
                messages.success(
                    request,
                    f"Actividad asignada a {n} persona{'s' if n != 1 else ''}.")
            else:
                for lista in form.errors.values():
                    for error in lista:
                        messages.error(request, error)
            return redirect(volver)

        if 'submit_novedad' in request.POST:
            form = NovedadForm(request.POST)
            if form.is_valid():
                novedad = form.save(commit=False)
                novedad.registrado_por = request.user
                novedad.save()
                messages.success(
                    request,
                    f"Novedad registrada: {novedad.get_tipo_display().lower()} "
                    f"de {novedad.persona_nombre}.")
            else:
                for campo, lista in form.errors.items():
                    etiqueta = form.fields.get(campo)
                    nombre = etiqueta.label if etiqueta else ''
                    for error in lista:
                        messages.error(request, f"{nombre}: {error}" if nombre else error)
            return redirect(volver)

        if 'submit_notas' in request.POST:
            plan, _ = PlanDia.objects.get_or_create(
                fecha=fecha, defaults={'creado_por': request.user})
            plan.notas = request.POST.get('notas', '').strip()
            plan.save(update_fields=['notas'])
            messages.success(request, "Observaciones del día guardadas.")
            return redirect(volver)

        messages.error(request, "No se reconoció la acción enviada.")
        return redirect(volver)


class FichaPersonaPlanView(AdministradorRequiredMixin, View):
    """
    La hoja del día de UNA persona, para el popup del tablero: quién es, si su
    documentación está al día, y todo lo que tiene ese día (servicios con sus
    horas, actividades del plan y novedades).

    Se sirve como fragmento y bajo demanda —una petición por persona al abrir
    el popup— en vez de incrustar una ficha oculta por cada fila del tablero.
    """
    template_name = 'planes/ficha_persona.html'

    def get(self, request, pk):
        from gestion.models import DocumentoPersonal
        from gestion.views import _cobertura_vigente

        persona = get_object_or_404(User, pk=pk)
        fecha = _fecha_de(request)
        documentos = list(persona.documentos_personales.all())
        roles = set(persona.groups.values_list('name', flat=True))

        return render(request, self.template_name, {
            'persona': persona,
            'perfil': getattr(persona, 'perfil', None),
            'fecha': fecha,
            'hoy': timezone.localdate(),
            'cargo': _cargo_de(persona),
            'papeles': self._papeles(documentos, roles, _cobertura_vigente),
            'servicios': _servicios_del_dia(fecha).get(persona.pk, []),
            'asignaciones': (
                Asignacion.objects
                .filter(plan__fecha=fecha, persona=persona)
                .select_related('orden', 'proveedor', 'dispositor', 'registrado_por')
                .prefetch_related('vehiculos')),
            'novedades': [n for n in Novedad.del_dia(fecha) if n.persona_id == persona.pk],
        })

    @staticmethod
    def _papeles(documentos, roles, cobertura_vigente):
        """
        Los papeles que le importan a ESE cargo, con su estado. Es la misma
        pregunta que el expediente le hace al camión —¿puede salir?— aplicada
        a la persona: cobertura siempre, licencia si conduce, cursos si es
        ayudante (opcionales, solo se muestran si los tiene).
        """
        from gestion.models import DocumentoPersonal

        def estado(documento):
            if documento is None:
                return {'nivel': 'falta', 'texto': 'sin cargar'}
            if documento.vencido:
                return {'nivel': 'alto',
                        'texto': f"venció el {documento.fecha_vencimiento:%d/%m/%Y}"}
            if documento.por_vencer:
                dias = documento.dias_restantes
                return {'nivel': 'aviso',
                        'texto': f"vence en {dias} día{'s' if dias != 1 else ''}"}
            if documento.fecha_vencimiento:
                return {'nivel': 'ok',
                        'texto': f"vigente hasta {documento.fecha_vencimiento:%d/%m/%Y}"}
            return {'nivel': 'ok', 'texto': 'cargado'}

        def ultimo(tipo):
            candidatos = [d for d in documentos if d.tipo == tipo]
            return max(candidatos, key=lambda d: d.fecha_vencimiento or datetime.date.min,
                       default=None)

        cobertura = cobertura_vigente(documentos) or ultimo('SEGURIDAD_SOCIAL') or ultimo('ARL')
        papeles = [{
            'nombre': (cobertura.get_tipo_display() if cobertura
                       else 'Seguridad social o ARL'),
            **estado(cobertura),
        }]
        if 'Conductores' in roles:
            papeles.append({'nombre': 'Licencia de conducción', **estado(ultimo('LICENCIA'))})
        if 'Ayudantes' in roles:
            for tipo in ('CURSO_ALTURAS', 'CURSO_CONFINADOS'):
                curso = ultimo(tipo)
                if curso is not None:      # los cursos son opcionales
                    papeles.append({'nombre': dict(DocumentoPersonal.TIPO_CHOICES)[tipo],
                                    **estado(curso)})
        return papeles


class EliminarAsignacionView(AdministradorRequiredMixin, View):
    """
    Quita una fila del plan (se asignó mal). Si era la disposición de un
    camión y no queda nadie más encargado de ella, el camión vuelve a estar
    CARGADO: si la disposición no se hizo, el residuo sigue ahí.
    """
    def post(self, request, pk):
        asignacion = get_object_or_404(Asignacion, pk=pk)
        fecha = asignacion.plan.fecha
        vehiculo = asignacion.vehiculos.first()
        descargaba = asignacion.descarga_vehiculos and vehiculo is not None
        # ¿Queda alguien más con esa misma disposición en el plan del día?
        acompanantes = (
            Asignacion.objects.filter(plan=asignacion.plan, tipo=asignacion.tipo,
                                      vehiculos=vehiculo)
            .exclude(pk=asignacion.pk).exists()
            if descargaba else False
        )
        if descargaba and not acompanantes:
            asignacion.deshacer_descarga()
            messages.warning(
                request,
                f"El camión {vehiculo.placa} vuelve a quedar CARGADO: se quitó "
                f"del plan la disposición que tenía asignada."
            )
        asignacion.delete()
        messages.success(request, "Asignación quitada del plan.")
        return redirect(f"{reverse('planes:plan_dia')}?fecha={fecha.isoformat()}")


class EliminarNovedadView(AdministradorRequiredMixin, View):
    """Borra una novedad registrada por error. Solo POST."""
    def post(self, request, pk):
        novedad = get_object_or_404(Novedad, pk=pk)
        fecha = _fecha_de(request)
        novedad.delete()
        messages.success(request, "Novedad eliminada del registro.")
        return redirect(f"{reverse('planes:plan_dia')}?fecha={fecha.isoformat()}")


class HistorialPlanesView(AdministradorRequiredMixin, PaginadoMixin, ListView):
    """
    El registro: un renglón por día con actividad. Entran tanto los días
    PLANEADOS (PlanDia) como los que solo tuvieron SERVICIOS: esos también
    hacen parte del histórico del plan, porque los recorridos entran solos
    al tablero y al PDF de su fecha.
    """
    template_name = 'planes/historial.html'
    context_object_name = 'planes'

    def get_queryset(self):
        from django.db.models import Count
        planes = {p.fecha: p for p in PlanDia.objects.annotate(
            n_asignaciones=Count('asignaciones'))}
        servicios = {
            f['fecha_recorrido']: f['n'] for f in
            Recorrido.objects.exclude(orden__estado_orden='CANCELADA')
            .values('fecha_recorrido').annotate(n=Count('id'))
        }
        filas = []
        for fecha in sorted(set(planes) | set(servicios), reverse=True):
            plan = planes.get(fecha)
            filas.append({
                'fecha': fecha,
                'plan': plan,
                'n_asignaciones': plan.n_asignaciones if plan else 0,
                'n_servicios': servicios.get(fecha, 0),
            })
        return filas


class HistorialNovedadesView(AdministradorRequiredMixin, PaginadoMixin, ListView):
    """
    El registro completo de novedades, filtrable por trabajador, tipo de
    novedad y FECHA. El filtro de fechas trabaja por CRUCE, no por igualdad:
    una novedad que va del 14 al 25 aparece si se consulta el 20, o del 18 al
    21 — que es como se pregunta de verdad ("¿quién estaba incapacitado esa
    semana?"). Sin fecha final, la novedad vale solo su día de inicio.
    """
    model = Novedad
    template_name = 'planes/novedades.html'
    context_object_name = 'novedades'

    @staticmethod
    def _fecha(crudo):
        try:
            return datetime.datetime.strptime(crudo, '%Y-%m-%d').date()
        except (TypeError, ValueError):
            return None

    def get_queryset(self):
        from django.db.models import Q
        from django.db.models.functions import Coalesce

        qs = (Novedad.objects.select_related('persona', 'registrado_por')
              # El último día que cubre la novedad: su fecha final o, si no
              # tiene, la de inicio (las de un solo día).
              .annotate(fin_efectivo=Coalesce('fecha_fin', 'fecha_inicio')))
        q = self.request.GET.get('q', '').strip()
        tipo = self.request.GET.get('tipo', '')
        desde = self._fecha(self.request.GET.get('desde'))
        hasta = self._fecha(self.request.GET.get('hasta'))

        if q:
            qs = qs.filter(Q(persona__first_name__icontains=q)
                           | Q(persona__last_name__icontains=q)
                           | Q(persona__username__icontains=q)
                           | Q(persona__perfil__numero_documento__icontains=q))
        if tipo:
            qs = qs.filter(tipo=tipo)
        if desde:
            qs = qs.filter(fin_efectivo__gte=desde)
        if hasta:
            qs = qs.filter(fecha_inicio__lte=hasta)
        return qs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        filtros = {campo: self.request.GET.get(campo, '')
                   for campo in ('q', 'tipo', 'desde', 'hasta')}
        context.update({
            'filtros': filtros,
            # Nombres viejos, por si alguna plantilla los usa.
            'q': filtros['q'],
            'tipo_sel': filtros['tipo'],
            'tipos': Novedad.TIPO_CHOICES,
            'hay_filtros': any(filtros.values()),
            'hoy': timezone.localdate(),
        })
        return context


def _pdf_plan(fecha, request):
    """
    El plan del día en PDF, generado al momento (no se guarda: es un reporte
    interno derivado de datos, con la misma fuente que la pantalla).
    """
    plan, grupos = _tablero(fecha)
    template = get_template('planes/plan_pdf.html')

    logo_path = os.path.join(settings.BASE_DIR, 'static', 'images', 'logo-solmed.png')
    with open(logo_path, 'rb') as archivo:
        logo_b64 = 'data:image/png;base64,' + base64.b64encode(archivo.read()).decode()

    # Filas de la sección 1 (una por servicio/actividad; el orden del formato).
    filas = []
    sin_plan = []
    novedades_dia = []
    for grupo in grupos:
        for fila in grupo['filas']:
            base = {'cargo': grupo['cargo'], 'nombre': fila['nombre']}
            for servicio in fila['servicios']:
                # En el plan impreso, el servicio se nombra por la ORDEN y el
                # CLIENTE que se va a atender: "Servicio programado" no decía
                # nada que el equipo pudiera usar.
                filas.append({**base,
                              'actividad': f"Orden #{servicio['orden']}",
                              'cliente': servicio['cliente'],
                              'es_servicio': True,
                              'placa': servicio['placa'],
                              'detalle': servicio['horas']})
            for a in fila['asignaciones']:
                detalle = ' · '.join(filter(None, [
                    f"Orden #{a.orden_id}" if a.orden_id else '',
                    a.proveedor.razon_social if a.proveedor_id else '',
                    a.hora.strftime('%H:%M') if a.hora else '',
                    a.detalle,
                ]))
                filas.append({**base, 'actividad': a.get_tipo_display(),
                              'placa': a.placas, 'detalle': detalle})
            for n in fila['novedades']:
                novedades_dia.append(n)
            if not fila['con_plan']:
                sin_plan.append(f"{fila['nombre']} ({grupo['cargo']})")

    html = template.render({
        'fecha': fecha, 'plan': plan, 'filas': filas,
        'novedades': novedades_dia, 'sin_plan': sin_plan,
        'logo_b64': logo_b64, 'generado': timezone.localtime(),
    })
    return HTML(string=html, base_url=request.build_absolute_uri()).write_pdf()


class PlanPDFView(AdministradorRequiredMixin, View):
    """Descarga el PDF del plan de un día."""
    def get(self, request, fecha):
        try:
            dia = datetime.datetime.strptime(fecha, '%Y-%m-%d').date()
        except ValueError:
            raise Http404("Fecha inválida.")
        respuesta = HttpResponse(_pdf_plan(dia, request),
                                 content_type='application/pdf')
        respuesta['Content-Disposition'] = (
            f'attachment; filename="plan_trabajo_{dia.isoformat()}.pdf"')
        return respuesta
