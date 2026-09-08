"""
Borra TODAS las disposiciones registradas en el plan de trabajo y deja como
PENDIENTES las órdenes del reporte de la oficina (SANTI.xlsx) que no
dispusieron en gestor desde la programación — decisión de Santiago del
08-sep-2026: la oficina va a re-registrar las disposiciones ella misma desde
el plan, con sus fechas y su gente reales.

Qué hace:
  1. Borra todas las actividades «Disposición final» del plan (las cargadas a
     mano y las de los comandos, de cualquier fecha) y sus descargas: cada
     carga que habían saldado vuelve a quedar pendiente sola (el enlace es
     SET_NULL). También borra las salidas a gestor que dejó
     registrar_disposiciones «según el reporte» (22206 y 22266: vuelven a
     pendientes, decisión explícita). Las disposiciones hechas DESDE LA
     PROGRAMACIÓN (SÍ → gestor al convertir) no se tocan.
  2. Si al revivir una orden quedan varias cargas pendientes de ella (los
     dobles registros del 23-24/08 y 03-04/09), conserva la más vieja y
     quita las demás: una orden debe una sola vez.
  3. A las órdenes del reporte que deben quedar pendientes y nunca tuvieron
     carga (22217, 22250, 22255, 22258, 22259, 22263) se la crea, en el
     camión de su servicio y fechada ese día.
  4. Imprime el contraste final contra la lista objetivo.

⚠️ IRREVERSIBLE: los viajes que Nancy registró a mano en el plan se borran y
ningún comando los recrea (los 12 del reporte sí podrían volver con
registrar_disposiciones). Por eso la vista previa lista todo lo que se va.

    python manage.py reiniciar_disposiciones               # vista previa
    python manage.py reiniciar_disposiciones --confirmar
"""
import datetime

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from gestion.models import MovimientoCargaVehiculo, OrdenServicio
from planes.models import Asignacion, PlanDia

from .registrar_disposiciones import MARCA as MARCA_REPORTE

# Marca de las cargas que ESTE comando crea (las que nunca existieron).
MARCA = 'reinicio de disposiciones'

# Las órdenes del reporte que deben quedar SIN DISPONER (las filas
# SIN DISPOSICION + las que salieron en viajes + 22206/22255/22266 por
# decisión explícita del 08-sep; las ENERGY/APS/VEOLIA de la programación
# se quedan dispuestas).
PENDIENTES_OBJETIVO = {
    22204, 22206, 22207, 22211, 22212, 22213, 22214, 22215, 22217, 22218,
    22222, 22225, 22228, 22229, 22230, 22231, 22238, 22239, 22240, 22243,
    22244, 22246, 22247, 22248, 22250, 22251, 22254, 22255, 22257, 22258,
    22259, 22260, 22261, 22263, 22265, 22266,
}


class Command(BaseCommand):
    help = ("Borra las disposiciones del plan y deja pendientes las órdenes "
            "del reporte que no fueron a gestor desde la programación "
            "(vista previa por defecto; escribe con --confirmar; SIN reversa).")

    def add_arguments(self, parser):
        parser.add_argument('--confirmar', action='store_true',
                            help='Sin esto solo se muestra la vista previa.')

    def handle(self, *args, **opciones):
        asignaciones = list(
            Asignacion.objects.filter(tipo='DISPOSICION_FINAL')
            .select_related('persona', 'plan')
            .prefetch_related('descargas'))
        descargas = {m.pk: m for a in asignaciones for m in a.descargas.all()}
        # Las salidas a gestor del reporte (sin viaje): también se van.
        del_reporte = list(MovimientoCargaVehiculo.objects.filter(
            accion='DESCARGA', nota__contains=MARCA_REPORTE)
            .exclude(pk__in=descargas))
        faltantes = self._sin_carga()

        self.stdout.write(self.style.MIGRATE_HEADING(
            f"Se van a borrar del plan {len(asignaciones)} asignación(es) de "
            f"disposición y {len(descargas) + len(del_reporte)} descarga(s):"))
        for a in asignaciones:
            ordenes = ', '.join(f"#{d.orden_id}" for d in a.descargas.all()
                                if d.orden_id) or 'sin órdenes saldadas'
            self.stdout.write(
                f"  {a.plan.fecha:%d/%m/%Y}  {a.persona_nombre}  → {ordenes}")
        for m in del_reporte:
            self.stdout.write(f"  (sin viaje)  #{m.orden_id}: {m.nota[:60]}")
        self.stdout.write(self.style.WARNING(
            "  ⚠ Esto NO tiene reversa: lo registrado a mano en el plan se "
            "pierde y la oficina deberá re-registrarlo."))

        if faltantes:
            self.stdout.write(self.style.MIGRATE_HEADING(
                f"\nY se les crea la carga pendiente a {len(faltantes)} "
                f"órdenes del reporte que nunca la tuvieron:"))
            for orden in faltantes:
                self.stdout.write(f"  #{orden.numero_orden}")

        if not opciones['confirmar']:
            self.stdout.write(self.style.WARNING(
                "\nVista previa: no se escribió nada. Repite con --confirmar."))
            return

        with transaction.atomic():
            camiones = {m.vehiculo for m in descargas.values()}
            camiones |= {m.vehiculo for m in del_reporte}
            planes = {a.plan for a in asignaciones}
            for a in asignaciones:
                a.delete()
            MovimientoCargaVehiculo.objects.filter(
                pk__in=list(descargas) + [m.pk for m in del_reporte]).delete()

            # Una orden debe UNA sola vez: los dobles registros revividos
            # se recortan a la carga más vieja.
            quitadas = 0
            vivas = (MovimientoCargaVehiculo.objects
                     .filter(accion='CARGA', descarga__isnull=True,
                             orden__isnull=False).order_by('fecha'))
            vistas = set()
            for carga in vivas:
                if carga.orden_id in vistas:
                    camiones.add(carga.vehiculo)
                    carga.delete()
                    quitadas += 1
                else:
                    vistas.add(carga.orden_id)

            creadas = 0
            for orden in self._sin_carga():
                recorrido = orden.recorridos.first()
                if recorrido is None:
                    continue
                programacion = getattr(orden, 'programacion_origen', None)
                fecha = (programacion.fecha if programacion
                         else recorrido.fecha_recorrido)
                movimiento = MovimientoCargaVehiculo.objects.create(
                    vehiculo=recorrido.vehiculo, accion='CARGA',
                    orden=orden,
                    nota=(f"Orden #{orden.numero_orden} del {fecha:%d/%m/%Y}: "
                          f"quedó sin disponer · {MARCA}")[:255])
                MovimientoCargaVehiculo.objects.filter(pk=movimiento.pk).update(
                    fecha=timezone.make_aware(datetime.datetime.combine(
                        fecha, datetime.time(12, 0))))
                camiones.add(recorrido.vehiculo)
                creadas += 1

            for camion in camiones:
                camion.sincronizar_carga()
            for plan in planes:
                if not plan.asignaciones.exists() and not plan.notas:
                    plan.delete()

        self.stdout.write(self.style.SUCCESS(
            f"\nListo: {len(asignaciones)} asignación(es) borradas, "
            f"{len(descargas) + len(del_reporte)} descarga(s) borradas, "
            f"{quitadas} duplicado(s) recortados, {creadas} carga(s) creadas."))
        self._contraste()

    def _sin_carga(self):
        """Las del objetivo que no tienen NINGUNA carga (habrá que crearla)."""
        return list(
            OrdenServicio.objects
            .filter(pk__in=PENDIENTES_OBJETIVO)
            .exclude(movimientos_carga__accion='CARGA')
            .order_by('numero_orden').distinct())

    def _contraste(self):
        pendientes = set(
            MovimientoCargaVehiculo.objects
            .filter(accion='CARGA', descarga__isnull=True, orden__isnull=False)
            .values_list('orden_id', flat=True))
        self.stdout.write(self.style.MIGRATE_HEADING(
            "\nContraste contra el objetivo:"))
        bien = PENDIENTES_OBJETIVO & pendientes
        self.stdout.write(f"  ✓ {len(bien)} de {len(PENDIENTES_OBJETIVO)} "
                          f"órdenes del reporte quedaron sin disponer.")
        for n in sorted(PENDIENTES_OBJETIVO - pendientes):
            self.stdout.write(self.style.WARNING(
                f"  ⚠ La #{n} debería quedar pendiente y no lo está "
                f"(¿no existe o no tiene recorrido?)."))
        extras = sorted(pendientes - PENDIENTES_OBJETIVO)
        if extras:
            self.stdout.write(
                "  · También quedan pendientes (posteriores al reporte o "
                "revividas de viajes recientes): "
                + ', '.join(f"#{n}" for n in extras))
