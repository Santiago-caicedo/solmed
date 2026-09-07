"""
Recorre las órdenes ANTERIORES a la regla nueva de disposición (sep-2026) que
hoy cumplirían la condición de quedar SIN DISPONER pero no tienen carga — y
por eso nunca van a aparecer en el plan de trabajo.

La regla nueva: con «¿Se realizará disposición final?» = NO la orden queda
pendiente SIEMPRE, sin importar el destino. Pero con la regla vieja solo
«DEJAR CARRO CARGADO» dejaba carga: las de trasiego, tanques y «NO HAY
DISPOSICIÓN» pasaron sin dejar pendiente. Este comando las encuentra y les
crea su carga, para que entren al plan como las nuevas.

Candidatas: órdenes con programación marcada NO, sin NINGUNA carga registrada
(ni pendiente ni saldada), no canceladas y del consecutivo del sistema (las
históricas en papel se quedan quietas). Las de SÍ no entran: dispusieron en
gestor. Si la pregunta quedó en blanco (dato viejo), se listan aparte y NO se
tocan: nadie sabe qué pasó con ese residuo sin preguntarlo.

⚠️ OJO antes de confirmar: que la orden no tenga carga NO garantiza que su
residuo siga en el camión — pudo salir de verdad por tanques o trasiego. La
vista previa muestra el destino y lo que se registró al convertir; si alguna
NO debe quedar pendiente, se corre con los números de las que sí:

    python manage.py cargar_ordenes_viejas                    # vista previa
    python manage.py cargar_ordenes_viejas --confirmar        # todas
    python manage.py cargar_ordenes_viejas 22280 22283 --confirmar
    python manage.py cargar_ordenes_viejas --deshacer --confirmar

Deshacer quita SOLO las cargas que este comando creó y sigan pendientes.
"""
import datetime

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from gestion.models import MovimientoCargaVehiculo, OrdenServicio

# Marca en la nota, para reconocer y poder deshacer lo de este comando.
MARCA = 'regla nueva de disposición'


class Command(BaseCommand):
    help = ("Crea la carga pendiente de las órdenes viejas marcadas NO que la "
            "regla vieja dejó sin pendiente (vista previa por defecto; escribe "
            "con --confirmar; se revierte con --deshacer).")

    def add_arguments(self, parser):
        parser.add_argument('ordenes', nargs='*', type=int, metavar='ORDEN',
                            help='Solo estas órdenes (sin números: todas las halladas).')
        parser.add_argument('--confirmar', action='store_true',
                            help='Sin esto solo se muestra la vista previa.')
        parser.add_argument('--deshacer', action='store_true',
                            help='Quita las cargas que este comando creó y sigan pendientes.')

    def handle(self, *args, **opciones):
        if opciones['deshacer']:
            return self._deshacer(opciones['ordenes'], opciones['confirmar'])

        base = (OrdenServicio.objects
                .filter(numero_orden__gte=OrdenServicio.NUMERO_INICIAL,
                        programacion_origen__requiere_disposicion_final='NO')
                .exclude(estado_orden='CANCELADA')
                .exclude(movimientos_carga__accion='CARGA')
                .select_related('cliente', 'programacion_origen__dispositor_final')
                .prefetch_related('recorridos__vehiculo')
                .order_by('numero_orden')
                .distinct())
        if opciones['ordenes']:
            base = base.filter(numero_orden__in=opciones['ordenes'])
        candidatas = list(base)

        # Las de pregunta en blanco: solo se avisan, nadie sabe qué pasó ahí.
        en_blanco = list(
            OrdenServicio.objects
            .filter(numero_orden__gte=OrdenServicio.NUMERO_INICIAL,
                    programacion_origen__requiere_disposicion_final='')
            .exclude(estado_orden='CANCELADA')
            .exclude(movimientos_carga__accion='CARGA')
            .values_list('numero_orden', flat=True).distinct())

        self.stdout.write(self.style.MIGRATE_HEADING(
            f"Órdenes viejas con NO y sin carga registrada ({len(candidatas)}):"))
        for orden in candidatas:
            programacion = orden.programacion_origen
            destino = (programacion.dispositor_final.nombre
                       if programacion.dispositor_final_id else 'sin destino')
            placas = ', '.join(r.vehiculo.placa for r in orden.recorridos.all()) or '—'
            fecha = programacion.fecha.strftime('%d/%m/%Y')
            self.stdout.write(
                f"  #{orden.numero_orden}  {fecha}  {placas:<10} "
                f"{orden.cliente.nombre[:30]:<30}  destino: {destino}")
            # Lo que la regla vieja registró al convertir (tanques/trasiego):
            # señal de que el residuo pudo salir de verdad.
            vieja = orden.movimientos_carga.filter(accion='DESCARGA').first()
            if vieja is not None:
                self.stdout.write(self.style.WARNING(
                    f"      ⚠ al convertir se registró: "
                    f"«{vieja.nota[:80]}» — confirma si de verdad debe quedar pendiente"))

        if en_blanco:
            self.stdout.write(self.style.WARNING(
                f"\n  Con la pregunta SIN responder (no se tocan; complétalas con "
                f"«Editar» en cada orden): " + ', '.join(f"#{n}" for n in en_blanco)))

        if not candidatas:
            self.stdout.write("  Ninguna: todo lo marcado NO ya tiene su carga.")
            return
        if not opciones['confirmar']:
            self.stdout.write(self.style.WARNING(
                "\nVista previa: no se escribió nada. Repite con --confirmar "
                "(o con los números de las que sí deban quedar pendientes)."))
            return

        creadas = 0
        with transaction.atomic():
            for orden in candidatas:
                programacion = orden.programacion_origen
                destino = (programacion.dispositor_final.nombre
                           if programacion.dispositor_final_id else '')
                camiones = [r.vehiculo for r in orden.recorridos.all()]
                for camion in camiones:
                    nota = (f"Orden #{orden.numero_orden} del "
                            f"{programacion.fecha:%d/%m/%Y}: quedó sin disponer"
                            + (f" · destino previsto: {destino}" if destino else "")
                            + f" · {MARCA}")
                    movimiento = MovimientoCargaVehiculo.objects.create(
                        vehiculo=camion, accion='CARGA', nota=nota[:255],
                        orden=orden)
                    # Fechada el día del servicio, no el de hoy.
                    MovimientoCargaVehiculo.objects.filter(pk=movimiento.pk).update(
                        fecha=timezone.make_aware(datetime.datetime.combine(
                            programacion.fecha, datetime.time(12, 0))))
                    camion.sincronizar_carga()
                    creadas += 1
        self.stdout.write(self.style.SUCCESS(
            f"\nListo: {creadas} carga(s) pendientes creadas — ya aparecen en "
            f"el plan de trabajo para asignarles su disposición."))

    def _deshacer(self, numeros, confirmar):
        cargas = (MovimientoCargaVehiculo.objects
                  .filter(accion='CARGA', descarga__isnull=True,
                          nota__contains=MARCA)
                  .select_related('vehiculo', 'orden'))
        if numeros:
            cargas = cargas.filter(orden_id__in=numeros)
        cargas = list(cargas)
        self.stdout.write(self.style.MIGRATE_HEADING("Se va a quitar:"))
        for c in cargas:
            self.stdout.write(f"  #{c.orden_id} ({c.vehiculo.placa})")
        if not cargas:
            self.stdout.write(self.style.WARNING(
                "No hay cargas de este comando que sigan pendientes."))
            return
        if not confirmar:
            self.stdout.write(self.style.WARNING(
                "\nVista previa: no se borró nada. Repite con --confirmar."))
            return
        with transaction.atomic():
            camiones = {c.vehiculo for c in cargas}
            MovimientoCargaVehiculo.objects.filter(
                pk__in=[c.pk for c in cargas]).delete()
            for camion in camiones:
                camion.sincronizar_carga()
        self.stdout.write(self.style.SUCCESS(f"Quitadas {len(cargas)} carga(s)."))
