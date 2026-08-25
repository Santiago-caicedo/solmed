"""
Registra que unas órdenes quedaron SIN DISPONER: su residuo sigue en el camión.

Nació del reporte de SOLMED (ago-2026) con las órdenes cuyo carro quedó
cargado. Se le pasan los números de orden y el resto sale de la propia orden
(el camión y la fecha vienen de su recorrido): cada una queda como una CARGA
pendiente en su camión, y esas cargas se van acumulando y se saldan una por
una desde el plan de trabajo.

    python manage.py registrar_cargas_pendientes 22207 22211 22212
    python manage.py registrar_cargas_pendientes 22207 22211 --confirmar
    python manage.py registrar_cargas_pendientes --deshacer --confirmar

Sin --confirmar solo muestra lo que haría. --deshacer quita lo que este
comando registró (reconoce sus cargas por la marca en la nota) siempre que
sigan pendientes: una carga ya saldada por una disposición real no se toca.
"""
from django.core.management.base import BaseCommand
from django.db import transaction

from gestion.models import MovimientoCargaVehiculo, OrdenServicio

MARCA = 'Reporte SOLMED'


class Command(BaseCommand):
    help = ("Registra órdenes cuyo residuo quedó en el camión sin disponer "
            "(cargas pendientes que se saldan desde el plan de trabajo).")

    def add_arguments(self, parser):
        parser.add_argument('ordenes', nargs='*', type=int, metavar='ORDEN',
                            help='Números de orden que quedaron sin disponer.')
        parser.add_argument('--confirmar', action='store_true',
                            help='Sin esto solo se muestra la vista previa.')
        parser.add_argument('--deshacer', action='store_true',
                            help='Quita las cargas que este comando registró '
                                 'y siguen pendientes.')

    def handle(self, *args, **opciones):
        if opciones['deshacer']:
            return self._deshacer(opciones['confirmar'])
        if not opciones['ordenes']:
            self.stderr.write("Pasa los números de orden (o --deshacer).")
            return
        self._registrar(opciones['ordenes'], opciones['confirmar'])

    # ---------- registrar ----------

    def _revisar(self, numero):
        """(orden, vehiculo, aviso, error) de un número de orden."""
        orden = OrdenServicio.objects.filter(pk=numero).first()
        if orden is None:
            return None, None, None, "no existe en el sistema"
        recorrido = orden.recorridos.select_related('vehiculo').first()
        if recorrido is None:
            return orden, None, None, "no tiene recorrido (¿de cuál camión?)"
        if MovimientoCargaVehiculo.objects.filter(
                orden=orden, accion='CARGA', descarga__isnull=True).exists():
            return orden, recorrido.vehiculo, None, "ya está pendiente de disponer"
        aviso = None
        if MovimientoCargaVehiculo.objects.filter(
                orden=orden, accion='DESCARGA').exists():
            aviso = ("el sistema la tenía como dispuesta; el reporte de la "
                     "empresa manda y vuelve a quedar pendiente")
        return orden, recorrido.vehiculo, aviso, None

    def _registrar(self, numeros, confirmar):
        listas, errores = [], []
        for numero in dict.fromkeys(numeros):     # sin repetidos, en orden
            orden, vehiculo, aviso, error = self._revisar(numero)
            if error:
                errores.append((numero, error))
            else:
                listas.append((orden, vehiculo, aviso))

        self.stdout.write(self.style.MIGRATE_HEADING(
            f"\n{'REGISTRO' if confirmar else 'VISTA PREVIA (no se guarda nada)'}"
            f" — {len(listas)} orden(es) por marcar sin disponer"))
        for orden, vehiculo, aviso in listas:
            recorrido = orden.recorridos.first()
            self.stdout.write(
                f"  ✓ #{orden.pk}  {vehiculo.placa:<8}"
                f"{recorrido.fecha_recorrido:%d/%m/%Y}  "
                f"{orden.cliente.nombre[:35]}")
            if aviso:
                self.stdout.write(self.style.WARNING(f"      ⚠ {aviso}"))
        for numero, error in errores:
            self.stdout.write(self.style.ERROR(f"  ✗ #{numero}: {error}"))

        if not confirmar:
            self.stdout.write("\nRevisa y vuelve a correr con --confirmar.")
            return
        if not listas:
            self.stdout.write("Nada por registrar.")
            return

        with transaction.atomic():
            camiones = {}
            for orden, vehiculo, aviso in listas:
                recorrido = orden.recorridos.first()
                movimiento = MovimientoCargaVehiculo.objects.create(
                    vehiculo=vehiculo, accion='CARGA', orden=orden,
                    nota=(f"Orden #{orden.pk} del "
                          f"{recorrido.fecha_recorrido:%d/%m/%Y}: quedó "
                          f"cargado (sin disposición) · {MARCA.lower()}")[:255],
                )
                # La fecha real es la del recorrido, no la de hoy (auto_now_add
                # no deja fijarla al crear).
                MovimientoCargaVehiculo.objects.filter(pk=movimiento.pk).update(
                    fecha=recorrido.fecha_recorrido)
                camiones[vehiculo.pk] = vehiculo
            for vehiculo in camiones.values():
                vehiculo.sincronizar_carga()

        self.stdout.write(self.style.SUCCESS(
            f"\nListo: {len(listas)} carga(s) pendiente(s) registradas en "
            f"{len(camiones)} camión(es). Se saldan desde el plan de trabajo."))

    # ---------- deshacer ----------

    def _deshacer(self, confirmar):
        cargas = (MovimientoCargaVehiculo.objects
                  .filter(accion='CARGA', nota__icontains=MARCA.lower(),
                          descarga__isnull=True)
                  .select_related('vehiculo', 'orden'))
        saldadas = MovimientoCargaVehiculo.objects.filter(
            accion='CARGA', nota__icontains=MARCA.lower(),
            descarga__isnull=False).count()

        self.stdout.write(self.style.MIGRATE_HEADING(
            f"\n{'REVERSA' if confirmar else 'VISTA PREVIA (no se borra nada)'}"
            f" — {cargas.count()} carga(s) de este comando por quitar"))
        for c in cargas:
            self.stdout.write(f"  · {c.vehiculo.placa}  "
                              f"{'#' + str(c.orden_id) if c.orden_id else 'sin orden'}")
        if saldadas:
            self.stdout.write(self.style.WARNING(
                f"  ⚠ {saldadas} ya fueron saldadas por una disposición real: "
                f"esas no se tocan."))
        if not confirmar:
            self.stdout.write("\nRevisa y vuelve a correr con --confirmar.")
            return

        with transaction.atomic():
            camiones = {c.vehiculo.pk: c.vehiculo for c in cargas}
            borradas = cargas.delete()[0]
            for vehiculo in camiones.values():
                vehiculo.sincronizar_carga()
        self.stdout.write(self.style.SUCCESS(f"\nListo: {borradas} quitada(s)."))
