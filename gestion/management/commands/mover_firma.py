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
  - Si el conductor ya respondió la ENCUESTA DE CIERRE en el origen (se
    desbloqueó con la firma equivocada), también se traslada al destino:
    el recorrido destino queda COMPLETADO y el origen vuelve a PROGRAMADO,
    con los estados de ambas órdenes recalculados. Exige que el conductor
    sea el mismo en las dos (la encuesta es su autorreporte PESV).
  - Lo diligenciado por los conductores en ambas actas no se toca.

Solo procede si LAS DOS ÓRDENES SON DEL MISMO CLIENTE (si no, la firma es de
la persona equivocada y no hay nada que mover: usa anular_firma). Se niega si
el destino ya está firmado o ya tiene su propia encuesta de cierre.
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
        parser.add_argument(
            '--clientes-distintos', action='store_true',
            help='Permite mover la firma entre órdenes de clientes distintos '
                 '(cuando el enlace equivocado le llegó a la persona correcta: '
                 'quien firmó es el cliente de la orden DESTINO).',
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

        # Por defecto se exige el mismo cliente. Con --clientes-distintos se
        # permite el caso "el enlace equivocado le llegó a la persona correcta":
        # quien firmó es el cliente del DESTINO confirmando su propio servicio.
        if origen.cliente_id != destino.cliente_id and not opciones['clientes_distintos']:
            raise CommandError(
                f"Las órdenes son de CLIENTES DISTINTOS (#{origen.pk}: "
                f"{origen.cliente.nombre} / #{destino.pk}: {destino.cliente.nombre}). "
                f"Si quien firmó fue el cliente del destino (le llegó el enlace "
                f"equivocado), repite con --clientes-distintos. Si firmó otra "
                f"persona, usa anular_firma y pide la firma correcta.")

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

        encuesta = EncuestaConductor.objects.filter(
            recorrido=acta_origen.recorrido).first()

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

        mover_encuesta = False
        if encuesta is not None:
            if EncuestaConductor.objects.filter(recorrido=recorrido_destino).exists():
                raise CommandError(
                    f"La orden #{destino.pk} ya tiene su propia encuesta de "
                    f"cierre: revisa en el admin cuál de las dos vale.")
            # La encuesta es el AUTORREPORTE PESV del conductor: solo puede
            # viajar si el conductor es el mismo. Si no, la del origen se
            # ELIMINA: describe un servicio que no se ha prestado y no se
            # puede atribuir a otra persona.
            mover_encuesta = (
                acta_origen.recorrido.conductor_id is not None
                and acta_origen.recorrido.conductor_id == recorrido_destino.conductor_id)

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
        if origen.cliente_id != destino.cliente_id:
            self.stdout.write(self.style.WARNING(
                f"  ⚠ CLIENTES DISTINTOS: la firma pasa de una orden de "
                f"{origen.cliente.nombre} a una de {destino.cliente.nombre}. "
                f"Se asume que quien firmó fue el cliente del destino."))
        if encuesta is not None and mover_encuesta:
            self.stdout.write(
                "  La ENCUESTA DE CIERRE del conductor también se traslada: "
                "el recorrido destino queda COMPLETADO y el origen vuelve a "
                "PROGRAMADO (estados de las órdenes recalculados).")
        elif encuesta is not None:
            self.stdout.write(self.style.WARNING(
                "  ⚠ La encuesta de cierre del origen se ELIMINARÁ: los "
                "conductores no coinciden y ese autorreporte corresponde a un "
                "servicio que no se ha prestado. El recorrido origen vuelve a "
                "PROGRAMADO; el conductor del destino responde la suya normal."))
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

            if encuesta is not None:
                if mover_encuesta:
                    # La encuesta pasa al recorrido destino; su save() lo marca
                    # COMPLETADO y recalcula el estado de esa orden.
                    encuesta.recorrido = recorrido_destino
                    encuesta.save()
                else:
                    # Conductores distintos: la encuesta del origen no se puede
                    # reatribuir y era de un servicio no prestado. Se elimina.
                    encuesta.delete()
                # El recorrido origen vuelve a PROGRAMADO (su servicio sigue
                # pendiente) y su orden se recalcula al guardar.
                rec_origen = acta_origen.recorrido
                rec_origen.estado = 'PROGRAMADO'
                rec_origen.save()

        if encuesta is not None and mover_encuesta:
            extra = " La encuesta de cierre quedó en el destino."
        elif encuesta is not None:
            extra = (" La encuesta de cierre del origen se eliminó (conductores "
                     "distintos); el conductor del destino responde la suya.")
        else:
            extra = ""
        self.stdout.write(self.style.SUCCESS(
            f"\nListo: la orden #{destino.pk} quedó FIRMADA y la #{origen.pk} "
            f"volvió a pendiente con enlace nuevo. El PDF del acta del destino "
            f"sale con la firma en la próxima descarga.{extra}"))
