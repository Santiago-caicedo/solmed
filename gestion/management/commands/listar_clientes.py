"""
Lista los clientes con su id, para poder señalar uno sin ambigüedad.

Nació porque dos clientes puntuales pidieron un formato propio de
preliquidación (sep-2026): hacía falta una forma de decir «es este» sin
depender del nombre, que se repite entre sedes del mismo NIT.
"""
from django.core.management.base import BaseCommand
from django.db.models import Count, Q

from gestion.models import Cliente


class Command(BaseCommand):
    help = "Lista los clientes con su id (para señalar uno sin ambigüedad)."

    def add_arguments(self, parser):
        parser.add_argument('buscar', nargs='?', default='',
                            help="Filtra por nombre, sigla o NIT (opcional)")
        parser.add_argument('--con-ordenes', action='store_true',
                            help="Solo los que tienen al menos una orden")

    def handle(self, *args, **opciones):
        qs = (Cliente.objects
              .annotate(n_ordenes=Count('ordenes', distinct=True),
                        n_facturas=Count('facturas', distinct=True),
                        n_sedes=Count('sedes', distinct=True))
              .order_by('nombre'))
        buscar = (opciones['buscar'] or '').strip()
        if buscar:
            qs = qs.filter(Q(nombre__icontains=buscar) | Q(sigla__icontains=buscar)
                           | Q(identificacion__icontains=buscar))
        if opciones['con_ordenes']:
            qs = qs.filter(n_ordenes__gt=0)

        clientes = list(qs)
        if not clientes:
            self.stdout.write("Ningún cliente con ese criterio.")
            return

        # Ancho de cada columna según el contenido, para que quede alineado.
        ancho_nombre = max(len(c.nombre) for c in clientes)
        ancho_nit = max(len(c.identificacion or '') for c in clientes)
        cabecera = (f"{'ID':>5}  {'NOMBRE'.ljust(ancho_nombre)}  {'NIT'.ljust(ancho_nit)}  "
                    f"{'SEDES':>5} {'ÓRDENES':>7} {'PRELIQ':>6}")
        self.stdout.write(cabecera)
        self.stdout.write('-' * len(cabecera))
        for c in clientes:
            self.stdout.write(
                f"{c.pk:>5}  {c.nombre.ljust(ancho_nombre)}  "
                f"{(c.identificacion or '').ljust(ancho_nit)}  "
                f"{c.n_sedes:>5} {c.n_ordenes:>7} {c.n_facturas:>6}")
        self.stdout.write('-' * len(cabecera))
        self.stdout.write(f"{len(clientes)} cliente(s).")
