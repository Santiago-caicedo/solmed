"""
Lista las órdenes de preliquidaciones de D1 que quedaron con el precio en
cero y los seis datos de D1 llenos.

El valor de cada orden es SIEMPRE el precio que se escribe; el formato de
D1 solo cambia cómo se presenta (decisión de Santiago, oct-2026). Entre el
24-sep y el 05-oct-2026 el sistema no pedía precio en Ibagué y Sibaté, y lo
calculaba con los seis datos: las que se armaron así salen ahora en $0.
Al abrirlas con «Editar», el precio viene sugerido con lo que suman esos
datos: se revisa y se guarda.

Solo lee: no cambia nada.
"""
from django.core.management.base import BaseCommand

from gestion.formatos import _formato_del_cliente
from gestion.models import Factura


def pesos(valor):
    """$1.736.898, con punto de miles como en el PDF."""
    return f"${valor:,.0f}".replace(',', '.')


class Command(BaseCommand):
    help = "Lista las órdenes de D1 con el precio en $0 y sus datos de D1 llenos (solo lee)."

    def handle(self, *args, **opciones):
        facturas = (Factura.objects.select_related('cliente')
                    .prefetch_related('lineas__orden__programacion_origen__sede_cliente',
                                      'lineas__orden__programacion_origen__tercero',
                                      'lineas__conceptos')
                    .order_by('numero'))
        problemas = 0
        for factura in facturas:
            ficha = _formato_del_cliente(factura.cliente)
            if ficha is None or ficha['clave'] != 'd1':
                continue
            malas = [l for l in factura.lineas.all()
                     if l.lleva_global and not l.precio and l.suma_desglose]
            if not malas:
                continue
            problemas += 1
            self.stdout.write(f"{factura.codigo}  ({factura.fecha_emision:%d/%m/%Y})  "
                              f"total actual {pesos(factura.total)}")
            for l in malas:
                self.stdout.write(f"    orden #{l.orden.numero_orden:<7} {l.orden.sede_nombre or '—':<25} "
                                  f"precio en $0; sus datos de D1 suman {pesos(l.suma_desglose)}")
        if problemas:
            self.stdout.write(f"\n{problemas} preliquidación(es) por revisar: abrir «Editar», "
                              f"revisar el precio sugerido y guardar.")
        else:
            self.stdout.write("Ninguna orden de D1 con el precio en $0.")
