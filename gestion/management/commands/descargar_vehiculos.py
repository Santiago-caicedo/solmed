"""
Descarga los vehículos marcados como CARGADOS **sin dejar registro** en el
historial de movimientos: es la limpieza para cuando el estado quedó sucio por
pruebas (el botón del expediente, en cambio, siempre registra — esa es la
trazabilidad real del residuo).

Por defecto solo MUESTRA lo que haría; para ejecutar de verdad hay que pasar
--confirmar.

    python manage.py descargar_vehiculos                        # vista previa
    python manage.py descargar_vehiculos --confirmar
    python manage.py descargar_vehiculos --confirmar --borrar-historial
    python manage.py descargar_vehiculos --confirmar --placa CV0001 --placa CV0002

--borrar-historial elimina además TODOS los movimientos de carga/descarga
registrados (los de las pruebas). --placa limita la limpieza a esas placas
(repetible); sin él, aplica a toda la flota.
"""
from django.core.management.base import BaseCommand
from django.db import transaction

from gestion.models import MovimientoCargaVehiculo, Vehiculo


class Command(BaseCommand):
    help = ("Descarga los vehículos cargados SIN dejar registro (limpieza de "
            "pruebas; vista previa por defecto, ejecuta con --confirmar).")

    def add_arguments(self, parser):
        parser.add_argument(
            '--confirmar', action='store_true',
            help='Ejecuta la limpieza de verdad (sin esto, solo muestra el resumen).',
        )
        parser.add_argument(
            '--borrar-historial', action='store_true',
            help='Elimina también los movimientos de carga/descarga registrados.',
        )
        parser.add_argument(
            '--placa', action='append', default=[],
            help='Limita la limpieza a esta placa (se puede repetir).',
        )

    def handle(self, *args, **opciones):
        vehiculos = Vehiculo.objects.all()
        movimientos = MovimientoCargaVehiculo.objects.all()
        if opciones['placa']:
            placas = [p.strip().upper() for p in opciones['placa']]
            vehiculos = vehiculos.filter(placa__in=placas)
            movimientos = movimientos.filter(vehiculo__placa__in=placas)
            no_existen = set(placas) - set(vehiculos.values_list('placa', flat=True))
            if no_existen:
                self.stdout.write(self.style.WARNING(
                    f"Placas que no existen: {', '.join(sorted(no_existen))}"))

        cargados = vehiculos.filter(cargado=True).order_by('placa')

        # --- Resumen ---
        self.stdout.write(self.style.MIGRATE_HEADING("Vehículos cargados:"))
        if cargados:
            for v in cargados:
                self.stdout.write(f"  - {v.placa}: {v.cargado_detalle or '(sin detalle)'}")
        else:
            self.stdout.write("  (ninguno)")
        if opciones['borrar_historial']:
            self.stdout.write(self.style.MIGRATE_HEADING(
                f"Movimientos de carga/descarga a borrar: {movimientos.count()}"))

        if not opciones['confirmar']:
            self.stdout.write(self.style.WARNING(
                "\nVista previa: no se cambió nada. Ejecuta con --confirmar "
                "para descargar de verdad."))
            return

        # --- Limpieza (update directo: no pasa por save() ni deja registro) ---
        with transaction.atomic():
            descargados = cargados.update(cargado=False, cargado_detalle='')
            borrados = 0
            if opciones['borrar_historial']:
                borrados, _detalle = movimientos.delete()
        self.stdout.write(self.style.SUCCESS(
            f"Listo: {descargados} vehículo(s) descargado(s) sin dejar registro."
            + (f" Historial borrado: {borrados} movimiento(s)."
               if opciones['borrar_historial'] else "")
        ))
