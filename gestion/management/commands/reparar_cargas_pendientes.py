"""
Repara el rastro de las cargas pendientes de disposición. Tres arreglos, en
este orden (cada uno depende del anterior):

1. REVIVE lo que una disposición ajena dio por dispuesto. Hasta ago-2026 un
   servicio que terminaba en el gestor saldaba TODA la mora del camión, no
   solo su propio residuo. Aquí se sueltan esas cargas: vuelven a estar
   pendientes. El trasiego NO se toca: ahí el camión sí se vacía entero
   porque su contenido pasa a otra placa.

2. RELACIONA con su orden las cargas que quedaron sin enlace. Son las
   creadas antes de que la migración 0062 añadiera la orden al movimiento:
   la nota dice de qué orden vienen, pero el campo quedó vacío y por eso el
   sistema las llama «carga manual».

3. QUITA los duplicados que salieron de eso: al no ver la carga original
   (sin enlace), `registrar_cargas_pendientes` creó una segunda para la
   misma orden. Se conserva la original —la que tiene la fecha real— y se
   borra la que creó ese comando, reconocible por su marca.

    python manage.py reparar_cargas_pendientes
    python manage.py reparar_cargas_pendientes --confirmar

Sin --confirmar solo muestra lo que haría.
"""
import re

from django.core.management.base import BaseCommand
from django.db import transaction

from gestion.models import MovimientoCargaVehiculo, OrdenServicio

# La nota automática dice "Orden #22207 del 05/08/2026: ...".
ORDEN_EN_NOTA = re.compile(r'#\s*(\d{3,})')
# Marca que deja registrar_cargas_pendientes en lo que él crea.
MARCA_REGISTRO = 'reporte solmed'
# El trasiego sí vacía el camión entero: sus descargas no se revisan.
SEÑAL_TRASIEGO = 'trasegó'


class Command(BaseCommand):
    help = ("Revive las cargas que una disposición ajena dio por dispuestas, "
            "relaciona las que perdieron su orden y quita los duplicados.")

    def add_arguments(self, parser):
        parser.add_argument('--confirmar', action='store_true',
                            help='Sin esto solo se muestra la vista previa.')

    # ---------- utilidades ----------

    def _titulo(self, texto):
        self.stdout.write(self.style.MIGRATE_HEADING(f"\n{texto}"))

    def _nota(self, texto=''):
        self.stdout.write(f"    {texto}" if texto else "")

    @staticmethod
    def _orden_de_la_nota(nota):
        hallazgo = ORDEN_EN_NOTA.search(nota or '')
        return int(hallazgo.group(1)) if hallazgo else None

    # ---------- 1. revivir lo saldado por una disposición ajena ----------

    def _por_revivir(self):
        """
        Cargas saldadas por una DESCARGA de OTRA orden que no fue un trasiego:
        ese servicio dispuso su residuo, no el que el camión debía de antes.
        """
        candidatas = (MovimientoCargaVehiculo.objects
                      .filter(accion='CARGA', descarga__isnull=False)
                      .exclude(descarga__nota__icontains=SEÑAL_TRASIEGO)
                      .select_related('vehiculo', 'descarga')
                      .order_by('vehiculo__placa', 'fecha'))
        return [c for c in candidatas if c.orden_id != c.descarga.orden_id]

    # ---------- 2. relacionar las que perdieron su orden ----------

    def _por_relacionar(self):
        """[(carga, orden)] de las pendientes sin enlace cuya nota sí lo dice."""
        huerfanas = (MovimientoCargaVehiculo.objects
                     .filter(accion='CARGA', descarga__isnull=True,
                             orden__isnull=True)
                     .select_related('vehiculo').order_by('fecha'))
        parejas = []
        for carga in huerfanas:
            numero = self._orden_de_la_nota(carga.nota)
            if numero and OrdenServicio.objects.filter(pk=numero).exists():
                parejas.append((carga, numero))
        return parejas

    # ---------- 3. duplicados ----------

    def _duplicados(self, extra=None):
        """
        [(orden, conservada, [por borrar])] de las órdenes que quedan con más
        de una carga pendiente. `extra` son los enlaces que el paso 2 hará y
        que todavía no están guardados, para verlos en la vista previa.
        """
        pendientes = list(MovimientoCargaVehiculo.objects
                          .filter(accion='CARGA', descarga__isnull=True)
                          .select_related('vehiculo').order_by('fecha', 'pk'))
        futuros = dict(extra or [])
        pororden = {}
        for c in pendientes:
            numero = futuros.get(c.pk, c.orden_id)
            if numero:
                pororden.setdefault(numero, []).append(c)

        grupos = []
        for numero, cargas in sorted(pororden.items()):
            if len(cargas) < 2:
                continue
            # Se conserva la más antigua (la original, con su fecha real) y se
            # borran las que creó registrar_cargas_pendientes.
            conservada, resto = cargas[0], cargas[1:]
            borrables = [c for c in resto
                         if MARCA_REGISTRO in (c.nota or '').lower()]
            grupos.append((numero, conservada, borrables, resto))
        return grupos

    # ---------- ejecución ----------

    def handle(self, *args, **opciones):
        confirmar = opciones['confirmar']
        self.stdout.write(self.style.MIGRATE_HEADING(
            "\nREPARACIÓN DE CARGAS PENDIENTES"
            + ("" if confirmar else " — VISTA PREVIA (no se guarda nada)")))

        revivir = self._por_revivir()
        relacionar = self._por_relacionar()
        grupos = self._duplicados([(c.pk, n) for c, n in relacionar])

        # --- 1 ---
        self._titulo(f"1. Vuelven a quedar PENDIENTES ({len(revivir)})")
        if not revivir:
            self._nota("Ninguna: no hay cargas saldadas por una disposición ajena.")
        for c in revivir:
            quien = f"#{c.orden_id}" if c.orden_id else 'sin orden'
            self.stdout.write(
                f"  ↺ {c.vehiculo.placa:<9}{quien:<9}la dio por dispuesta la "
                f"descarga de #{c.descarga.orden_id}")

        # --- 2 ---
        self._titulo(f"2. Recuperan su orden ({len(relacionar)})")
        if not relacionar:
            self._nota("Ninguna: todas las cargas pendientes saben de dónde vienen.")
        for carga, numero in relacionar:
            self.stdout.write(
                f"  → {carga.vehiculo.placa:<9}{carga.fecha:%d/%m/%Y}  "
                f"queda enlazada a la orden #{numero}")

        # --- 3 ---
        total_borrar = sum(len(b) for _n, _c, b, _r in grupos)
        self._titulo(f"3. Duplicados por quitar ({total_borrar})")
        if not grupos:
            self._nota("Ninguno: cada orden pendiente aparece una sola vez.")
        for numero, conservada, borrables, resto in grupos:
            self.stdout.write(f"  #{numero}:")
            self._nota(f"  ✓ se conserva {conservada.fecha:%d/%m/%Y} · "
                       f"{conservada.nota[:60]}")
            for c in borrables:
                self._nota(f"  ✗ se borra    {c.fecha:%d/%m/%Y} · {c.nota[:60]}")
            sin_marca = [c for c in resto if c not in borrables]
            for c in sin_marca:
                self.stdout.write(self.style.WARNING(
                    f"      ⚠ queda otra sin la marca del registro, no se toca: "
                    f"{c.fecha:%d/%m/%Y} · {c.nota[:50]}"))

        if not confirmar:
            self._titulo("Revisa y vuelve a correr con --confirmar.")
            return
        if not (revivir or relacionar or total_borrar):
            self._titulo("Nada por reparar.")
            return

        with transaction.atomic():
            camiones = {}
            for c in revivir:
                c.descarga = None
                c.save(update_fields=['descarga'])
                camiones[c.vehiculo_id] = c.vehiculo
            for carga, numero in relacionar:
                carga.orden_id = numero
                carga.save(update_fields=['orden'])
                camiones[carga.vehiculo_id] = carga.vehiculo
            for _numero, _conservada, borrables, _resto in grupos:
                for c in borrables:
                    camiones[c.vehiculo_id] = c.vehiculo
                    c.delete()
            for vehiculo in camiones.values():
                vehiculo.sincronizar_carga()

        self._titulo("Listo")
        self._nota(f"{len(revivir)} revivida(s), {len(relacionar)} "
                   f"relacionada(s), {total_borrar} duplicado(s) quitado(s) "
                   f"en {len(camiones)} camión(es).")
        self._nota("Revisa cómo quedó con: python manage.py diagnosticar_cargas")
