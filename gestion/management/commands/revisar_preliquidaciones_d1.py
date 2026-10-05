"""
Revisa las preliquidaciones de los clientes con formato propio (D1) en busca
de órdenes cuyo valor está guardado en el lugar que su formato NO lee, y que
por eso salen en $0 en el PDF, el Excel y el total.

Nació en oct-2026: una preliquidación de D1 que mezclaba Ibagué/Sibaté con
otra sede guardaba lo escrito en el desglose, pero salía con el formato de
siempre, que lee el precio (en cero). Ahora la preliquidación entera decide
(ver Factura.formato) y esto encuentra las que quedaron así de antes:

- MEZCLADA: formato de siempre, precio en 0 y desglose lleno. Al abrirla con
  «Editar», el precio viene sugerido con el total del desglose: se revisa y
  se guarda.
- SOLO D1: formato de D1, desglose vacío y precio lleno (se registraron antes
  de que existiera el desglose, 24-sep-2026). Hay que llenar el desglose.

Solo lee: no cambia nada.
"""
from django.core.management.base import BaseCommand

from gestion.formatos import _formato_del_cliente
from gestion.models import Factura


def pesos(valor):
    """$1.736.898, con punto de miles como en el PDF."""
    return f"${valor:,.0f}".replace(',', '.')


class Command(BaseCommand):
    help = "Lista las preliquidaciones de D1 con órdenes que salen en $0 por el formato (solo lee)."

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
            lineas = list(factura.lineas.all())
            formato = factura.formato([l.orden.sede_nombre for l in lineas])
            malas = []
            for l in lineas:
                if not l.lleva_global:
                    continue
                if formato == 'd1' and not l.total_general and l.precio:
                    malas.append((l, 'SOLO D1', f"precio {pesos(l.precio)} guardado, desglose vacío"))
                elif formato != 'd1' and not l.precio and l.total_general:
                    malas.append((l, 'MEZCLADA', f"desglose {pesos(l.total_general)} guardado, precio en 0"))
            if not malas:
                continue
            problemas += 1
            self.stdout.write(f"{factura.codigo}  ({factura.fecha_emision:%d/%m/%Y})  "
                              f"total actual {pesos(factura.total)}")
            for l, tipo, detalle in malas:
                self.stdout.write(f"    orden #{l.orden.numero_orden:<7} {l.orden.sede_nombre or '—':<25} "
                                  f"{tipo:<9} {detalle}")
        if problemas:
            self.stdout.write(f"\n{problemas} preliquidación(es) por revisar. MEZCLADA: abrir «Editar», "
                              f"revisar el precio sugerido y guardar. SOLO D1: llenar el desglose.")
        else:
            self.stdout.write("Ninguna preliquidación de D1 con valores en el lugar equivocado.")
