"""
Anula la firma del cliente en el acta de una orden: para cuando se envió el
enlace de firma de la ORDEN EQUIVOCADA y el cliente firmó la que no era.

    python manage.py anular_firma 22220              # vista previa
    python manage.py anular_firma 22220 --confirmar  # lo aplica

Qué hace al confirmar:
  - El acta vuelve a PENDIENTE_FIRMA.
  - Se borran la firma dibujada, el nombre de quien firmó y las 11 respuestas
    de satisfacción (eran del servicio equivocado).
  - Se genera un TOKEN NUEVO: el enlace que se envió por error queda muerto.
    El QR y el enlace de la orden salen con el token nuevo automáticamente.
  - Lo que el conductor haya diligenciado (tiempos, kilómetros, novedades)
    NO se toca.

No se puede anular si el recorrido ya tiene encuesta de cierre (quedaría un
servicio completado sin firma); en ese caso hay que decidir primero qué hacer
con la encuesta desde el admin.
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
    help = ("Anula la firma del cliente en el acta de una orden firmada por "
            "error (vista previa por defecto; ejecuta con --confirmar).")

    def add_arguments(self, parser):
        parser.add_argument('orden', type=int, help='Número de la orden.')
        parser.add_argument(
            '--confirmar', action='store_true',
            help='Ejecuta de verdad (sin esto, solo muestra qué pasaría).',
        )

    def handle(self, *args, **opciones):
        numero = opciones['orden']
        try:
            orden = OrdenServicio.objects.select_related('cliente').get(pk=numero)
        except OrdenServicio.DoesNotExist:
            raise CommandError(f"No existe la orden #{numero}.")

        firmadas = list(Manifiesto.objects.filter(
            recorrido__orden=orden, estado_firma='FIRMADO'
        ).select_related('recorrido'))
        if not firmadas:
            raise CommandError(
                f"La orden #{numero} no tiene ningún acta firmada: no hay nada que anular.")
        if len(firmadas) > 1:
            raise CommandError(
                f"La orden #{numero} tiene {len(firmadas)} actas firmadas; "
                f"esto está pensado para el caso normal de una sola. Revisa en el admin.")
        manifiesto = firmadas[0]
        recorrido = manifiesto.recorrido

        if EncuestaConductor.objects.filter(recorrido=recorrido).exists():
            raise CommandError(
                "Ese recorrido ya tiene la encuesta de cierre diligenciada "
                "(el servicio figura completado). Anular la firma lo dejaría "
                "inconsistente: decide primero qué hacer con la encuesta desde "
                "el admin de Django.")

        evals = sum(1 for c in CAMPOS_EVAL if getattr(manifiesto, c) is not None)
        self.stdout.write(self.style.MIGRATE_HEADING(
            f"\nActa firmada de la orden #{numero} — {orden.cliente.nombre}"))
        self.stdout.write(
            f"  Servicio: {recorrido.fecha_recorrido:%d/%m/%Y}"
            f"{' · placa ' + recorrido.vehiculo.placa if recorrido.vehiculo else ''}")
        self.stdout.write(
            f"  Firmó: {manifiesto.nombre_responsable_cliente or '—'} · "
            f"respuestas de satisfacción: {evals} de {len(CAMPOS_EVAL)}")
        self.stdout.write(
            "\nAl anular: el acta vuelve a PENDIENTE_FIRMA, se borran la firma, "
            "el nombre y las respuestas, y el enlace enviado queda muerto "
            "(token nuevo). Los datos del conductor no se tocan.")

        if not opciones['confirmar']:
            self.stdout.write(self.style.WARNING(
                "\nVISTA PREVIA: no se cambió nada. Para ejecutarlo de verdad:\n"
                f"  python manage.py anular_firma {numero} --confirmar"))
            return

        archivo_firma = (manifiesto.firma_cliente.storage, manifiesto.firma_cliente.name) \
            if manifiesto.firma_cliente else None
        with transaction.atomic():
            manifiesto.estado_firma = 'PENDIENTE_FIRMA'
            manifiesto.firma_cliente = None
            manifiesto.nombre_responsable_cliente = ''
            for campo in CAMPOS_EVAL:
                setattr(manifiesto, campo, None)
            manifiesto.token_publico = uuid.uuid4()
            manifiesto.save(update_fields=[
                'estado_firma', 'firma_cliente', 'nombre_responsable_cliente',
                'token_publico', *CAMPOS_EVAL])

        # La imagen de la firma equivocada se elimina del storage DESPUÉS de
        # confirmar (si falla, solo queda un archivo huérfano sin referencia).
        if archivo_firma:
            try:
                archivo_firma[0].delete(archivo_firma[1])
                self.stdout.write("  Imagen de la firma eliminada del storage.")
            except Exception:
                self.stdout.write(self.style.WARNING(
                    "  La imagen de la firma no se pudo eliminar del storage "
                    "(quedó huérfana, sin referencia)."))

        self.stdout.write(self.style.SUCCESS(
            f"\nListo: el acta de la orden #{numero} volvió a PENDIENTE_FIRMA "
            f"con enlace nuevo. Envíale al cliente el QR/enlace desde la orden "
            f"(el viejo ya no sirve)."))
