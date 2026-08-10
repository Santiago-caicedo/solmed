"""
Cambia el número (consecutivo) de una orden de servicio ya creada, arrastrando
todo lo que cuelga de ella (recorridos, pagos, documentos y su programación).

Pensado para órdenes históricas: el sistema numera hacia adelante desde 22207,
así que un servicio viejo (22201, 22202, ...) se crea normal por la app y luego
se le pone aquí su número real.

    python manage.py renumerar_orden 22215 22201              # vista previa
    python manage.py renumerar_orden 22215 22201 --confirmar  # lo aplica

El número es la clave primaria: el cambio se hace copiando la orden con el
número nuevo, moviendo los hijos y borrando la fila vieja, todo en una
transacción (si algo falla, no queda a medias).
"""
from django.core.management.base import BaseCommand, CommandError

from gestion.models import OrdenServicio
from gestion.renumeracion import hijos_de, mover_orden


class Command(BaseCommand):
    help = ("Cambia el número de una orden de servicio (y mueve recorridos, "
            "pagos, documentos y programación al número nuevo).")

    def add_arguments(self, parser):
        parser.add_argument('actual', type=int, help='Número que tiene hoy la orden.')
        parser.add_argument('nuevo', type=int, help='Número que debe quedar.')
        parser.add_argument(
            '--confirmar', action='store_true',
            help='Sin esta opción solo se muestra qué se movería.',
        )

    def handle(self, *args, **opciones):
        actual, nuevo = opciones['actual'], opciones['nuevo']
        if actual == nuevo:
            raise CommandError("El número actual y el nuevo son el mismo.")
        if nuevo <= 0:
            raise CommandError("El número nuevo debe ser positivo.")

        try:
            orden = OrdenServicio.objects.get(pk=actual)
        except OrdenServicio.DoesNotExist:
            raise CommandError(f"No existe la orden #{actual}.")
        if OrdenServicio.objects.filter(pk=nuevo).exists():
            raise CommandError(f"Ya hay una orden con el número #{nuevo}.")

        self.stdout.write(
            f"\nOrden #{actual} — {orden.cliente.nombre} "
            f"(creada el {orden.fecha_creacion:%d/%m/%Y}) pasaría a ser #{nuevo}.")
        self.stdout.write("Se moverían con ella:")
        for etiqueta, cuantos in hijos_de(actual):
            self.stdout.write(f"  {etiqueta}: {cuantos}")

        if not opciones['confirmar']:
            self.stdout.write(self.style.WARNING(
                "\nVista previa: no se cambió nada. Para aplicarlo:\n"
                f"  python manage.py renumerar_orden {actual} {nuevo} --confirmar"))
            return

        mover_orden(actual, nuevo)

        self.stdout.write(self.style.SUCCESS(
            f"\nListo: la orden #{actual} ahora es la #{nuevo}."))
