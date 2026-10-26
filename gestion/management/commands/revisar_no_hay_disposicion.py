"""
Revisa y arregla las órdenes con «NO HAY DISPOSICIÓN» que quedaron como
pendientes de disposición (oct-2026, pedido de Santiago).

Con «¿Se realizará disposición final? NO» + «¿Dónde queda el contenido? NO HAY
DISPOSICIÓN» el servicio no deja nada que disponer: la orden debe quedar «No
aplica» y no aparecer en Disposiciones. Entre sep y oct-2026 el sistema las
dejaba «Sin disponer». La migración 0097 ya las corrige al desplegar; este
comando sirve para ver el detalle antes y para confirmar después.

Lista tres grupos:
  · A ARREGLAR  — sin disponer y sin disposición registrada → pasan a «No aplica».
  · DISPUESTAS  — alguien les registró una disposición (seguramente para
    sacarlas de la lista). NO se tocan: se listan para que la oficina decida.
  · YA BIEN     — ya están en «No aplica» (solo se cuentan).

    python manage.py revisar_no_hay_disposicion             # solo muestra
    python manage.py revisar_no_hay_disposicion --aplicar   # arregla el primer grupo
"""
from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import Min

from gestion.models import Dispositor, OrdenServicio


class Command(BaseCommand):
    help = "Muestra (y con --aplicar arregla) las órdenes con «NO HAY DISPOSICIÓN» que quedaron pendientes."

    def add_arguments(self, parser):
        parser.add_argument('--aplicar', action='store_true',
                            help="Pasa a «No aplica» las que están sin disponer sin disposición registrada.")

    def handle(self, *args, **opciones):
        ordenes = (OrdenServicio.objects
                   .filter(programacion_origen__requiere_disposicion_final='NO',
                           programacion_origen__dispositor_final__nombre=Dispositor.SIN_DISPOSICION)
                   .select_related('cliente')
                   .prefetch_related('recorridos__vehiculo', 'disposiciones__registrado_por')
                   .annotate(servicio=Min('recorridos__fecha_recorrido'))
                   .order_by('numero_orden'))

        arreglar, dispuestas, bien = [], [], 0
        for orden in ordenes:
            vigentes = [d for d in orden.disposiciones.all() if not d.deshecha]
            if orden.estado_disposicion == 'PENDIENTE' and not vigentes:
                arreglar.append(orden)
            elif vigentes:
                dispuestas.append((orden, vigentes[-1]))
            else:
                bien += 1

        def linea(orden):
            placas = ', '.join(sorted({r.vehiculo.placa for r in orden.recorridos.all() if r.vehiculo_id})) or '—'
            fecha = orden.servicio.strftime('%d/%m/%Y') if orden.servicio else '—'
            return f"  #{orden.numero_orden:<6} {fecha:<11} {placas:<14} {orden.cliente.nombre[:45]}"

        total = len(arreglar) + len(dispuestas) + bien
        self.stdout.write(f"Órdenes con NO + «{Dispositor.SIN_DISPOSICION}»: {total}\n")

        self.stdout.write(self.style.WARNING(
            f"A ARREGLAR (sin disponer, deben quedar «No aplica»): {len(arreglar)}"))
        for orden in arreglar:
            self.stdout.write(linea(orden))

        self.stdout.write(self.style.NOTICE(
            f"\nDISPUESTAS con un registro de disposición (no se tocan, revisar a mano): {len(dispuestas)}"))
        for orden, registro in dispuestas:
            quien = (registro.registrado_por.get_full_name() or registro.registrado_por.username
                     if registro.registrado_por else '—')
            self.stdout.write(f"{linea(orden)}  · {registro.get_via_display()} {registro.fecha:%d/%m/%Y} por {quien}")

        self.stdout.write(f"\nYA BIEN («No aplica»): {bien}")

        if not arreglar:
            self.stdout.write(self.style.SUCCESS("\nNo hay nada que arreglar."))
            return
        if not opciones['aplicar']:
            self.stdout.write(self.style.WARNING(
                f"\nVista previa: no se cambió nada. Para arreglar las {len(arreglar)} órdenes, "
                "corre de nuevo con --aplicar."))
            return

        with transaction.atomic():
            n = (OrdenServicio.objects
                 .filter(pk__in=[o.pk for o in arreglar], estado_disposicion='PENDIENTE')
                 .update(estado_disposicion='NO_APLICA'))
        self.stdout.write(self.style.SUCCESS(
            f"\nListo: {n} orden(es) pasaron a «No aplica» y salieron de Disposiciones."))
