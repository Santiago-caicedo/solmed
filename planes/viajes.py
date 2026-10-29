"""
Viajes de disposición AGENDADOS (oct-2026, pedido de Santiago).

El panel de Disposiciones registra un viaje ya hecho (dispone las órdenes al
instante) o AGENDA uno para un día que viene. Agendado:

  - Las órdenes quedan pendientes, marcadas como agendadas (no entran a otro
    viaje), y se crean las actividades «Disposición final» del plan de ese
    día, una por persona, enlazadas al viaje.
  - Al personal le llega el correo. El rol lo da su grupo (el mismo cargo con
    el que sale en el plan): el CONDUCTOR ve el viaje en su portal ese día y
    hace el preoperacional del vehículo; el AYUDANTE recibe sus novedades,
    las fotos que le piden y su enlace personal, como en la programación de
    una orden; los demás, el aviso de la actividad.
  - La oficina lo CONFIRMA cuando se hizo (con las horas reales, la casilla
    de sumar y los descuentos de cada uno: ahí se disponen las órdenes) o lo
    CANCELA (las actividades salen del plan y las órdenes siguen pendientes).
"""
from django.utils import timezone

from .models import AyudanteViaje, ViajeDisposicion

# El cargo (grupo) decide qué le toca a cada uno en el viaje.
CARGOS_CONDUCTOR = ('Conductores',)
CARGOS_AYUDANTE = ('Ayudantes', 'Conductor - Ayudante')


def rol_en_viaje(persona):
    """'conductor', 'ayudante' u 'otro', según el cargo con el que sale en el plan."""
    from .views import _cargo_de
    cargo = _cargo_de(persona)
    if cargo in CARGOS_CONDUCTOR:
        return 'conductor'
    if cargo in CARGOS_AYUDANTE:
        return 'ayudante'
    return 'otro'


def ids_ordenes_agendadas():
    """Las órdenes que ya van en un viaje agendado: no entran a otro."""
    return set(ViajeDisposicion.objects.filter(estado='AGENDADA')
               .values_list('ordenes', flat=True))


def leer_ayudantes(data, personas, vehiculo_viaje):
    """
    Las novedades, la observación y el vehículo de apoyo de cada AYUDANTE del
    popup (nov_<id>, obs_<id>, apoya_<id>). Solo códigos válidos; si marcó
    «Apoya disposición de:» sin elegir vehículo, es el del viaje.
    {persona.pk: {'novedades', 'observacion', 'apoya'}}
    """
    from gestion.models import Vehiculo
    validos = dict(AyudanteViaje.NOVEDAD_CHOICES)
    datos = {}
    for persona in personas:
        if rol_en_viaje(persona) != 'ayudante':
            continue
        codigos = [c for c in data.getlist(f'nov_{persona.pk}') if c in validos]
        apoya = None
        if AyudanteViaje.APOYA_DISPOSICION in codigos:
            crudo = data.get(f'apoya_{persona.pk}') or ''
            apoya = (Vehiculo.objects.filter(pk=crudo).first() if crudo.isdigit() else None) \
                or vehiculo_viaje
        datos[persona.pk] = {
            'novedades': ','.join(dict.fromkeys(codigos)),
            'observacion': (data.get(f'obs_{persona.pk}') or '').strip(),
            'apoya': apoya,
        }
    return datos


def agendar_viaje(form, plan, usuario, hora, ayudantes):
    """
    Crea el viaje agendado con las órdenes y el vehículo que validó el
    AsignacionForm, sus actividades en el plan (sin disponer nada) y la
    ficha de cada ayudante. Devuelve (viaje, asignaciones).
    """
    viaje = ViajeDisposicion.objects.create(
        fecha=plan.fecha, hora=hora, vehiculo=form.vehiculos[0],
        dispositor=form.cleaned_data.get('dispositor'),
        detalle=(form.cleaned_data.get('detalle') or '').strip(),
        creado_por=usuario)
    viaje.ordenes.set(form.ordenes)
    asignaciones = form.crear(plan, usuario, viaje=viaje)
    for persona in form.personas:
        datos = ayudantes.get(persona.pk)
        if datos is not None:
            AyudanteViaje.objects.create(
                viaje=viaje, persona=persona, novedades=datos['novedades'],
                observacion=datos['observacion'], apoya_vehiculo=datos['apoya'])
    return viaje, asignaciones


def confirmar_viaje(viaje, tiempos, usuario):
    """
    El viaje se hizo: cada actividad del plan queda con las horas reales, la
    casilla de sumar y los descuentos de esa persona, y las órdenes que
    siguen pendientes quedan DISPUESTAS (un registro por orden, compartido
    por todo el viaje, como al registrar uno ya hecho). Devuelve las órdenes
    que se dispusieron.
    """
    from .forms import guardar_descuentos
    asignaciones = list(viaje.asignaciones.select_related('persona', 'plan').order_by('id'))
    for a in asignaciones:
        t = tiempos.get(a.persona_id) or {}
        a.hora = t.get('hora')
        a.hora_fin = t.get('hora_fin')
        a.suma_horas = bool(t.get('suma_horas'))
        a.save(update_fields=['hora', 'hora_fin', 'suma_horas'])
        a.descuentos.all().delete()
        guardar_descuentos(t.get('descuentos'), asignacion=a)
    ordenes = list(viaje.ordenes.filter(estado_disposicion='PENDIENTE').order_by('numero_orden'))
    if asignaciones and ordenes:
        primera = asignaciones[0]
        primera.aplicar_disposicion([a.persona_nombre for a in asignaciones], ordenes)
        for a in asignaciones[1:]:
            a.disposiciones.set(primera.disposiciones.all())
    viaje.estado = 'REALIZADA'
    viaje.cerrado_por = usuario
    viaje.cerrado_en = timezone.now()
    viaje.save(update_fields=['estado', 'cerrado_por', 'cerrado_en'])
    return ordenes


def cancelar_viaje(viaje, usuario):
    """No se hizo: sus actividades salen del plan y las órdenes siguen pendientes."""
    viaje.asignaciones.all().delete()
    viaje.estado = 'CANCELADA'
    viaje.cerrado_por = usuario
    viaje.cerrado_en = timezone.now()
    viaje.save(update_fields=['estado', 'cerrado_por', 'cerrado_en'])


def quitar_persona(asignacion):
    """
    Se quitó del plan la actividad de alguien de un viaje agendado: deja de
    ir (su ficha de ayudante se va con ella). Si ya no queda nadie, el viaje
    se cancela. Lo llama EliminarAsignacionView antes de borrar la fila.
    """
    viaje = asignacion.viaje
    if viaje is None or not viaje.agendada:
        return
    viaje.ayudantes.filter(persona=asignacion.persona).delete()
    if not viaje.asignaciones.exclude(pk=asignacion.pk).exists():
        viaje.estado = 'CANCELADA'
        viaje.cerrado_en = timezone.now()
        viaje.save(update_fields=['estado', 'cerrado_en'])
