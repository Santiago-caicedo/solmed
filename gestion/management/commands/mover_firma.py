"""
Mueve la firma del cliente del acta de una orden a la de otra: para cuando se
envió el enlace de la orden equivocada y el cliente firmó la que no era, pero
la firma es válida (mismo cliente, mismo servicio prestado).

    python manage.py mover_firma 22220 22217              # vista previa
    python manage.py mover_firma 22220 22217 --confirmar  # lo aplica

Qué hace al confirmar:
  - El acta de la orden DESTINO queda FIRMADA con la firma dibujada, el nombre
    de quien firmó y las 11 respuestas de satisfacción (la experiencia que el
    cliente calificó fue la de ese servicio).
  - El acta de la orden ORIGEN vuelve a PENDIENTE_FIRMA con TOKEN NUEVO: el
    enlace enviado por error queda muerto.
  - Lo diligenciado por los conductores en ambas actas no se toca.

Solo procede si LAS DOS ÓRDENES SON DEL MISMO CLIENTE (si no, la firma es de
la persona equivocada y no hay nada que mover: usa anular_firma). Se niega si
el destino ya está firmado o si el origen ya tiene encuesta de cierre.
"""
import uuid

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from gestion.models import EncuestaConductor, Manifiesto, OrdenServicio

CAMPOS_EVAL = [
    'eval_atencion', 'eval_amabilidad', 'eval_solucion_inquietudes',
    'eval_asesoria', 'eval_puntualidad', 'eval_calidad_servicio',
    'eval_oportunidad', 'eval_cumplimiento_condiciones',
    'eval_solucion_problemas', 'eval_volveria_contratar', 'eval_nos_recomendaria',
]


class Command(BaseCommand):
    help = ("Mueve la firma del cliente del acta de una orden a la de otra "
            "del MISMO cliente (vista previa por defecto; --confirmar aplica).")

    def add_arguments(self, parser):
        parser.add_argument('origen', type=int,
                            help='Orden firmada por error (la firma sale de aquí).')
        parser.add_argument('destino', type=int,
                            help='Orden que debía firmarse (la firma llega aquí).')
        parser.add_argument(
            '--confirmar', action='store_true',
            help='Ejecuta de verdad (sin esto, solo muestra qué pasaría).',
        )

    def _orden(self, numero):
        try:
            return OrdenServicio.objects.select_related('cliente').get(pk=numero)
        except OrdenServicio.DoesNotExist:
            raise CommandError(f"No existe la orden #{numero}.")

    def handle(self, *args, **opciones):
        if opciones['origen'] == opciones['destino']:
            raise CommandError("El origen y el destino son la misma orden.")
        origen = self._orden(opciones['origen'])
        destino = self._orden(opciones['destino'])

        # La validación que no se negocia: mismo cliente. Si no, la firma es
        # de la persona equivocada y lo correcto es anular_firma.
        if origen.cliente_id != destino.cliente_id:
            raise CommandError(
                f"Las órdenes son de CLIENTES DISTINTOS (#{origen.pk}: "
                f"{origen.cliente.nombre} / #{destino.pk}: {destino.cliente.nombre}). "
                f"La firma no se puede mover: usa anular_firma y pide la firma correcta.")

        firmadas = list(Manifiesto.objects.filter(
            recorrido__orden=origen, estado_firma='FIRMADO'
        ).select_related('recorrido'))
        if not firmadas:
            raise CommandError(
                f"La orden #{origen.pk} no tiene ningún acta firmada.")
        if len(firmadas) > 1:
            raise CommandError(
                f"La orden #{origen.pk} tiene {len(firmadas)} actas firmadas; "
                f"esto está pensado para el caso normal de una sola.")
        acta_origen = firmadas[0]

        if EncuestaConductor.objects.filter(recorrido=acta_origen.recorrido).exists():
            raise CommandError(
                f"El recorrido de la orden #{origen.pk} ya tiene la encuesta de "
                f"cierre (figura completado). Quitarle la firma lo dejaría "
                f"inconsistente: revisa primero la encuesta en el admin.")

        recorridos_destino = list(destino.recorridos.select_related('vehiculo'))
        if len(recorridos_destino) != 1:
            raise CommandError(
                f"La orden #{destino.pk} tiene {len(recorridos_destino)} "
                f"recorridos; esto está pensado para el caso normal de uno.")
        recorrido_destino = recorridos_destino[0]
        acta_destino = Manifiesto.objects.filter(recorrido=recorrido_destino).first()
        if acta_destino is not None and acta_destino.estado_firma == 'FIRMADO':
            raise CommandError(
                f"El acta de la orden #{destino.pk} YA está firmada: no se "
                f"puede firmar encima.")

        evals = sum(1 for c in CAMPOS_EVAL if getattr(acta_origen, c) is not None)
        self.stdout.write(self.style.MIGRATE_HEADING(
            f"\nCliente: {origen.cliente.nombre}"))
        rec_o = acta_origen.recorrido
        self.stdout.write(
            f"  ORIGEN  #{origen.pk} — servicio {rec_o.fecha_recorrido:%d/%m/%Y}"
            f"{' · placa ' + rec_o.vehiculo.placa if rec_o.vehiculo else ''} · "
            f"firmó: {acta_origen.nombre_responsable_cliente or '—'} · "
            f"respuestas: {evals} de {len(CAMPOS_EVAL)}")
        self.stdout.write(
            f"  DESTINO #{destino.pk} — servicio {recorrido_destino.fecha_recorrido:%d/%m/%Y}"
            f"{' · placa ' + recorrido_destino.vehiculo.placa if recorrido_destino.vehiculo else ''}"
            f"{' · acta sin crear (se crea)' if acta_destino is None else ''}")
        self.stdout.write(
            "\nAl mover: el destino queda FIRMADO con esa firma, nombre y "
            "respuestas; el origen vuelve a PENDIENTE_FIRMA con enlace nuevo "
            "(el enviado por error muere). Lo del conductor no se toca.")

        if not opciones['confirmar']:
            self.stdout.write(self.style.WARNING(
                "\nVISTA PREVIA: no se cambió nada. Para ejecutarlo de verdad:\n"
                f"  python manage.py mover_firma {origen.pk} {destino.pk} --confirmar"))
            return

        with transaction.atomic():
            if acta_destino is None:
                acta_destino = Manifiesto.objects.create(recorrido=recorrido_destino)

            # La firma llega al destino (el archivo es el mismo: solo cambia
            # de acta; no se copia ni se vuelve a subir).
            acta_destino.firma_cliente = acta_origen.firma_cliente.name
            acta_destino.nombre_responsable_cliente = acta_origen.nombre_responsable_cliente
            for campo in CAMPOS_EVAL:
                setattr(acta_destino, campo, getattr(acta_origen, campo))
            acta_destino.estado_firma = 'FIRMADO'
            acta_destino.save(update_fields=[
                'estado_firma', 'firma_cliente', 'nombre_responsable_cliente',
                *CAMPOS_EVAL])

            # El origen queda limpio, pendiente y con el enlace viejo muerto.
            acta_origen.estado_firma = 'PENDIENTE_FIRMA'
            acta_origen.firma_cliente = None
            acta_origen.nombre_responsable_cliente = ''
            for campo in CAMPOS_EVAL:
                setattr(acta_origen, campo, None)
            acta_origen.token_publico = uuid.uuid4()
            acta_origen.save(update_fields=[
                'estado_firma', 'firma_cliente', 'nombre_responsable_cliente',
                'token_publico', *CAMPOS_EVAL])

        self.stdout.write(self.style.SUCCESS(
            f"\nListo: la orden #{destino.pk} quedó FIRMADA y la #{origen.pk} "
            f"volvió a pendiente con enlace nuevo. El PDF del acta del destino "
            f"sale con la firma en la próxima descarga."))
