"""
Radiografía de las cargas pendientes de disposición: qué debe cada camión,
de dónde salió cada pendiente y qué lo descargó.

Responde las preguntas que aparecen cuando el sistema y el listado de la
empresa no coinciden:

  · ¿Qué órdenes sin disponer tiene hoy cada camión?
  · ¿Hay cargas SIN ORDEN («carga manual»)? ¿De dónde vienen?
  · ¿Hay pendientes DUPLICADOS de una misma orden?
  · ¿Qué descargó a un camión hace poco, quién lo registró y cuántas
    órdenes saldó de una sola vez?

    python manage.py diagnosticar_cargas
    python manage.py diagnosticar_cargas --dias 15
    python manage.py diagnosticar_cargas --placa WNO623

Solo LEE: no escribe nada en la base.
"""
import re

from django.core.management.base import BaseCommand
from django.utils import timezone

from gestion.models import MovimientoCargaVehiculo, OrdenServicio, Vehiculo

# Las notas automáticas empiezan por "Orden #22207 del ...": de ahí se saca a
# qué orden pertenecía una carga vieja que quedó sin el enlace (las creadas
# antes de que la migración 0062 añadiera la orden al movimiento).
ORDEN_EN_NOTA = re.compile(r'#\s*(\d{3,})')


class Command(BaseCommand):
    help = ("Muestra las cargas pendientes de disposición por camión, su "
            "origen, los duplicados y las descargas recientes.")

    def add_arguments(self, parser):
        parser.add_argument('--dias', type=int, default=7, metavar='N',
                            help='Cuántos días atrás mirar las descargas (7).')
        parser.add_argument('--placa', default=None,
                            help='Mirar un solo camión.')

    # ---------- utilidades ----------

    def _titulo(self, texto):
        self.stdout.write(self.style.MIGRATE_HEADING(f"\n{texto}"))

    def _nota(self, texto=''):
        self.stdout.write(f"    {texto}" if texto else "")

    @staticmethod
    def _orden_de_la_nota(nota):
        """El número de orden que menciona la nota, si menciona alguno."""
        hallazgo = ORDEN_EN_NOTA.search(nota or '')
        return int(hallazgo.group(1)) if hallazgo else None

    def _pendientes(self, placa=None):
        qs = (MovimientoCargaVehiculo.objects
              .filter(accion='CARGA', descarga__isnull=True)
              .select_related('vehiculo', 'orden__cliente')
              .order_by('vehiculo__placa', 'fecha'))
        return qs.filter(vehiculo__placa__iexact=placa) if placa else qs

    # ---------- los bloques ----------

    def _por_camion(self, pendientes):
        self._titulo("1. Qué debe cada camión")
        porcamion = {}
        for c in pendientes:
            porcamion.setdefault(c.vehiculo.placa, []).append(c)
        if not porcamion:
            return self._nota("Ningún camión tiene residuo pendiente.")
        for placa, cargas in sorted(porcamion.items()):
            etiquetas = [f"#{c.orden_id}" if c.orden_id else 'manual' for c in cargas]
            self.stdout.write(
                f"  {placa:<9}{len(cargas):>2} sin disponer → {', '.join(etiquetas)}")
        self._nota()
        self._nota(f"Total: {len(pendientes)} carga(s) en {len(porcamion)} camión(es).")

    def _sin_orden(self, pendientes):
        huerfanas = [c for c in pendientes if not c.orden_id]
        self._titulo(f"2. Cargas sin orden — «carga manual» ({len(huerfanas)})")
        if not huerfanas:
            return self._nota("No hay: todas las cargas saben de qué orden vienen.")
        for c in huerfanas:
            numero = self._orden_de_la_nota(c.nota)
            self.stdout.write(f"  {c.vehiculo.placa:<9}{c.fecha:%d/%m/%Y}  {c.nota[:80]}")
            if numero is None:
                self._nota("  · la nota no menciona ninguna orden: se marcó a mano")
                continue
            existe = OrdenServicio.objects.filter(pk=numero).exists()
            if not existe:
                self._nota(f"  · la nota habla de la orden #{numero}, que no existe")
                continue
            repetida = MovimientoCargaVehiculo.objects.filter(
                accion='CARGA', descarga__isnull=True, orden_id=numero).exists()
            if repetida:
                self.stdout.write(self.style.WARNING(
                    f"      ⚠ DUPLICADO: la orden #{numero} ya tiene otra carga "
                    f"pendiente enlazada"))
            else:
                self._nota(f"  · viene de la orden #{numero}, pero perdió el enlace")

    def _duplicados(self, pendientes):
        conteo = {}
        for c in pendientes:
            if c.orden_id:
                conteo.setdefault(c.orden_id, []).append(c)
        repetidas = {n: cs for n, cs in conteo.items() if len(cs) > 1}
        self._titulo(f"3. Órdenes con más de una carga pendiente ({len(repetidas)})")
        if not repetidas:
            return self._nota("Ninguna: cada orden pendiente aparece una sola vez.")
        for numero, cargas in sorted(repetidas.items()):
            self.stdout.write(self.style.WARNING(
                f"  ⚠ #{numero}: {len(cargas)} cargas"))
            for c in cargas:
                self._nota(f"  · {c.vehiculo.placa} {c.fecha:%d/%m/%Y} {c.nota[:70]}")

    def _descargas(self, dias, placa):
        desde = timezone.localdate() - timezone.timedelta(days=dias)
        qs = (MovimientoCargaVehiculo.objects
              .filter(accion='DESCARGA', fecha__date__gte=desde)
              .select_related('vehiculo', 'dispositor', 'registrado_por')
              .prefetch_related('cargas_saldadas')
              .order_by('fecha'))
        if placa:
            qs = qs.filter(vehiculo__placa__iexact=placa)
        descargas = list(qs)
        self._titulo(f"4. Descargas de los últimos {dias} días ({len(descargas)})")
        if not descargas:
            return self._nota("Ninguna en ese periodo.")
        for d in descargas:
            quien = (d.registrado_por.get_full_name() or d.registrado_por.username
                     if d.registrado_por_id else 'el sistema')
            saldadas = list(d.cargas_saldadas.all())
            numeros = sorted({c.orden_id for c in saldadas if c.orden_id})
            self.stdout.write(
                f"  {d.vehiculo.placa:<9}{d.fecha:%d/%m/%Y %H:%M}  "
                f"saldó {len(saldadas)} carga(s)"
                + (f": {', '.join(f'#{n}' for n in numeros)}" if numeros else ''))
            self._nota(f"  · {d.nota[:88]}")
            self._nota(f"  · la registró {quien}"
                       + (f", gestor {d.dispositor.nombre}" if d.dispositor_id else ''))
            if len(saldadas) > 1:
                self.stdout.write(self.style.WARNING(
                    "      ⚠ una sola descarga saldó varias órdenes: pasa cuando "
                    "el camión\n        vacía completo (el servicio terminó en el "
                    "gestor)"))

    def handle(self, *args, **opciones):
        placa = (opciones['placa'] or '').strip() or None
        if placa and not Vehiculo.objects.filter(placa__iexact=placa).exists():
            self.stderr.write(f"No existe el vehículo «{placa}».")
            return

        self.stdout.write(self.style.MIGRATE_HEADING(
            "\nDIAGNÓSTICO DE CARGAS PENDIENTES"
            + (f" — {placa.upper()}" if placa else "")))
        pendientes = list(self._pendientes(placa))
        self._por_camion(pendientes)
        self._sin_orden(pendientes)
        self._duplicados(pendientes)
        self._descargas(opciones['dias'], placa)
        self.stdout.write("")
