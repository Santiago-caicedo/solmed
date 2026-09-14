"""
Radiografía de las disposiciones, orden por orden. SOLO LEE.

    python manage.py diagnosticar_disposiciones            # todo
    python manage.py diagnosticar_disposiciones --dias 30  # dispuestas recientes
    python manage.py diagnosticar_disposiciones 22246 22251

Dice cuáles órdenes siguen sin disponer (y desde cuándo), cuáles se
dispusieron (cuándo, con quién, por cuál vía) y señala lo raro: una orden
DISPUESTA sin registro vigente, o SIN DISPONER con un registro vigente.
"""
import datetime

from django.core.management.base import BaseCommand
from django.db.models import Min
from django.utils import timezone

from gestion.models import DisposicionOrden, OrdenServicio


class Command(BaseCommand):
    help = "Muestra el estado de disposición de las órdenes (solo lee)."

    def add_arguments(self, parser):
        parser.add_argument('ordenes', nargs='*', type=int, metavar='ORDEN')
        parser.add_argument('--dias', type=int, default=None,
                            help='Solo las dispuestas en los últimos N días.')

    def handle(self, *args, **opciones):
        hoy = timezone.localdate()
        ordenes = (OrdenServicio.objects.exclude(estado_disposicion='NO_APLICA')
                   .select_related('cliente')
                   .annotate(servicio=Min('recorridos__fecha_recorrido'))
                   .order_by('numero_orden'))
        if opciones['ordenes']:
            ordenes = ordenes.filter(pk__in=opciones['ordenes'])

        pendientes = [o for o in ordenes if o.estado_disposicion == 'PENDIENTE']
        self.stdout.write(self.style.MIGRATE_HEADING(
            f"SIN DISPONER: {len(pendientes)} orden(es)"))
        for o in sorted(pendientes, key=lambda o: o.servicio or hoy):
            desde = o.servicio or timezone.localdate(o.fecha_creacion)
            self.stdout.write(f"  #{o.numero_orden}  {desde:%d/%m/%Y}  "
                              f"{(hoy - desde).days:>3} días  {o.cliente.nombre[:32]}")

        dispuestas = [o for o in ordenes if o.estado_disposicion == 'DISPUESTA']
        desde_dia = (hoy - datetime.timedelta(days=opciones['dias'])
                     if opciones['dias'] is not None else None)
        registros = {
            r.orden_id: r for r in
            DisposicionOrden.objects.filter(deshecha=False, orden__in=dispuestas)
            .select_related('dispositor', 'registrado_por')
            .prefetch_related('asignaciones_plan__persona').order_by('fecha', 'pk')
        }
        self.stdout.write(self.style.MIGRATE_HEADING(
            f"\nDISPUESTAS: {len(dispuestas)} orden(es)"
            + (f" (mostrando las de los últimos {opciones['dias']} días)" if desde_dia else '')))
        raras = []
        for o in dispuestas:
            r = registros.get(o.pk)
            if r is None:
                raras.append(f"#{o.numero_orden} está DISPUESTA pero no tiene registro vigente")
                continue
            if desde_dia and r.fecha < desde_dia:
                continue
            quien = ', '.join(r.personas) or (
                (r.registrado_por.get_full_name() or r.registrado_por.username)
                if r.registrado_por_id else '—')
            self.stdout.write(
                f"  #{o.numero_orden}  {r.fecha:%d/%m/%Y}  {r.get_via_display():<22} "
                f"{quien[:28]:<28} {r.dispositor.nombre if r.dispositor_id else '—'}")

        vigentes_de_pendientes = (DisposicionOrden.objects
                                  .filter(deshecha=False, orden__in=pendientes)
                                  .values_list('orden_id', flat=True))
        for numero in sorted(set(vigentes_de_pendientes)):
            raras.append(f"#{numero} está SIN DISPONER pero tiene un registro vigente")

        self.stdout.write(self.style.MIGRATE_HEADING("\nRevisar:"))
        if not raras:
            self.stdout.write(self.style.SUCCESS("  ✓ Todo cuadra."))
        for aviso in raras:
            self.stdout.write(self.style.WARNING(f"  ⚠ {aviso}"))
