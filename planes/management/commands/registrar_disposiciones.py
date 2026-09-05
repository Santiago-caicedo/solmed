"""
Deja cada orden del reporte de la oficina (SANTI.xlsx, jul-31→sep-03 de 2026)
en el estado que el reporte dice, revisando ORDEN POR ORDEN — no por día:
Nancy ya registró en vivo casi todos los viajes en el plan de trabajo (se
descubrió con diagnosticar_cargas el 05-sep-2026) y nada de lo suyo se toca
ni se duplica.

Qué hace con cada orden del reporte, según lo decidido con Santiago:

  · Dispuesta en un VIAJE y aún pendiente → se salda. Si el plan de ese día
    ya tiene el viaje (el de Nancy, aunque lo haya anotado con otras órdenes
    u otra gente), la descarga se le AÑADE a ese viaje; si no existe, se crea
    con las dos personas del reporte. La descarga siempre se registra en el
    camión que llevaba la carga y fechada el día real del viaje.
  · Dispuesta en un GESTOR según el reporte pero pendiente en el sistema
    (22206, 22266) → se salda con su descarga al gestor, sin viaje.
  · Ya saldada → no se toca. Sin carga registrada → no hay nada que saldar
    (salió por otra vía: gestor al convertir, trasiego al tanque auxiliar).
  · Con carga saldada Y otra pendiente a la vez → es un duplicado: se avisa
    para correr reparar_cargas_pendientes y no se toca.

Lo que este comando NO hace, a propósito:
  · 22251, 22254 y 22265 deben quedar PENDIENTES (decisión de Santiago:
    manda el Excel sobre lo que Nancy registró al convertir): se crean con
    `registrar_cargas_pendientes 22251 22254 22265 --confirmar`.
  · El duplicado de 22239 lo quita `reparar_cargas_pendientes`.
  · La placa de 22240 (WNN675 en el sistema, WNO623 en el reporte) sigue
    abierta con la oficina.

La lectura del Excel quedó cerrada pregunta por pregunta (guiones = órdenes
sueltas, bloque bueno del 28/08, «322238»=22238, «#22248#22250»=22248 y
22250, «MUEVE SALDO #22181» solo nota, JEFFERSON=JEFERSON).

Vista previa por defecto; escribe con --confirmar; --deshacer revierte SOLO
lo de este comando (sus descargas y sus viajes, nunca los de Nancy). Al
final siempre imprime el contraste contra lo que el reporte espera.

    python manage.py registrar_disposiciones
    python manage.py registrar_disposiciones --confirmar --usuario santiago
    python manage.py registrar_disposiciones --deshacer --confirmar
"""
import datetime
import unicodedata

from django.contrib.auth.models import User
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from gestion.models import Dispositor, MovimientoCargaVehiculo, OrdenServicio, Vehiculo
from planes.models import Asignacion, PlanDia

# Marca con la que se reconoce lo que creó este comando, para poder
# revertirlo sin llevarse por delante lo registrado a mano.
MARCA = 'Registro histórico (reporte de disposiciones)'

# Las órdenes que el reporte da por dispuestas EN UN VIAJE: número, fecha del
# viaje, placa con la que salió el viaje y las dos personas que lo hicieron.
DISPUESTAS_EN_VIAJE = [
    (22204, datetime.date(2026, 8, 3),  'OBC727', ('WILLIAM', 'DAVID')),
    (22213, datetime.date(2026, 8, 8),  'WGY347', ('WILLIAM', 'JEFFERSON')),
    (22214, datetime.date(2026, 8, 8),  'WGY347', ('WILLIAM', 'JEFFERSON')),
    (22212, datetime.date(2026, 8, 8),  'WGY347', ('WILLIAM', 'JEFFERSON')),
    (22207, datetime.date(2026, 8, 10), 'WNO623', ('OSCAR', 'JEFFERSON')),
    (22211, datetime.date(2026, 8, 10), 'WNO623', ('OSCAR', 'JEFFERSON')),
    (22217, datetime.date(2026, 8, 11), 'WGY347', ('ALONSO', 'JULIO')),
    (22215, datetime.date(2026, 8, 11), 'WGY347', ('ALONSO', 'JULIO')),
    (22229, datetime.date(2026, 8, 18), 'WGY347', ('WILLIAM', 'JEFFERSON')),
    (22231, datetime.date(2026, 8, 18), 'WGY347', ('WILLIAM', 'JEFFERSON')),
    (22243, datetime.date(2026, 8, 24), 'WGY347', ('WILLIAM', 'JULIO')),
    (22239, datetime.date(2026, 8, 24), 'WGY347', ('WILLIAM', 'JULIO')),
    (22218, datetime.date(2026, 8, 24), 'WNO623', ('OSCAR', 'JEFFERSON')),
    (22228, datetime.date(2026, 8, 24), 'WNO623', ('OSCAR', 'JEFFERSON')),
    (22238, datetime.date(2026, 8, 24), 'WNO623', ('OSCAR', 'JEFFERSON')),
    (22248, datetime.date(2026, 8, 26), 'WGY347', ('WILLIAM', 'OSCAR')),
    (22250, datetime.date(2026, 8, 26), 'WGY347', ('WILLIAM', 'OSCAR')),
    (22222, datetime.date(2026, 8, 27), 'OBB178', ('JAVIER', 'JEFFERSON')),
    (22225, datetime.date(2026, 8, 27), 'OBB178', ('JAVIER', 'JEFFERSON')),
    (22230, datetime.date(2026, 8, 27), 'OBB178', ('JAVIER', 'JEFFERSON')),
    (22244, datetime.date(2026, 8, 27), 'OBB178', ('JAVIER', 'JEFFERSON')),
    (22259, datetime.date(2026, 8, 29), 'WGY347', ('WILLIAM', 'JEFFERSON')),
    (22258, datetime.date(2026, 8, 29), 'WGY347', ('WILLIAM', 'JEFFERSON')),
    (22261, datetime.date(2026, 8, 31), 'WGY347', ('WILLIAM', 'JEFFERSON')),
    (22255, datetime.date(2026, 8, 31), 'WGY347', ('WILLIAM', 'JEFFERSON')),
    (22263, datetime.date(2026, 9, 1),  'WGY347', ('WILLIAM', 'JULIO')),
    (22260, datetime.date(2026, 9, 1),  'WGY347', ('WILLIAM', 'JULIO')),
    (22246, datetime.date(2026, 9, 1),  'WGY347', ('WILLIAM', 'JULIO')),
]

# Pendientes en el sistema que según el reporte dispusieron directo en un
# gestor (sin viaje): se saldan con su descarga al gestor, fechada ese día.
DISPUESTAS_EN_GESTOR = {
    22206: (datetime.date(2026, 8, 4), 'ENERGY'),
    22266: (datetime.date(2026, 9, 3), 'ENERGY'),
}

# Lo que debe quedar SIN disponer al final (22251/22254/22265 entran aquí
# después de crearlas con registrar_cargas_pendientes).
PENDIENTES_ESPERADAS = {22240, 22251, 22254, 22265}

# El reporte escribe algunos nombres distinto a como están en el sistema.
ALIAS = {
    'JEFFERSON': 'JEFERSON',
}


def _limpiar(texto):
    """Sin tildes, en mayúsculas y sin espacios de sobra, para comparar nombres."""
    texto = str(texto or '').strip().upper()
    return ''.join(c for c in unicodedata.normalize('NFD', texto)
                   if unicodedata.category(c) != 'Mn')


class Command(BaseCommand):
    help = ("Deja cada orden del reporte de disposiciones en el estado que el "
            "reporte dice, orden por orden (vista previa por defecto; escribe "
            "con --confirmar; se revierte con --deshacer).")

    def add_arguments(self, parser):
        parser.add_argument('--confirmar', action='store_true',
                            help='Escribe de verdad (sin esto solo muestra qué haría).')
        parser.add_argument('--usuario', default=None,
                            help='Usuario al que se le atribuye el registro (username).')
        parser.add_argument('--deshacer', action='store_true',
                            help='Revierte lo que este comando creó.')

    # ---------- resolución ----------

    def _persona(self, nombre):
        fragmento = ALIAS.get(_limpiar(nombre), _limpiar(nombre))
        candidatos = [u for u in self._personal
                      if fragmento in _limpiar(f"{u.first_name} {u.last_name}")]
        if len(candidatos) == 1:
            return candidatos[0]
        if not candidatos:
            raise ValueError(f"«{nombre}» no coincide con nadie del personal")
        nombres = ', '.join(u.get_full_name() or u.username for u in candidatos)
        raise ValueError(f"«{nombre}» coincide con varias personas: {nombres}")

    def _estado_de(self, numero):
        """('sin_orden'|'sin_carga'|'saldada'|'pendiente'|'duplicada', carga)."""
        if not OrdenServicio.objects.filter(pk=numero).exists():
            return 'sin_orden', None
        cargas = list(MovimientoCargaVehiculo.objects
                      .filter(accion='CARGA', orden_id=numero)
                      .select_related('vehiculo').order_by('fecha'))
        pendientes = [c for c in cargas if c.descarga_id is None]
        if not cargas:
            return 'sin_carga', None
        if not pendientes:
            return 'saldada', None
        if len(cargas) > len(pendientes) or len(pendientes) > 1:
            return 'duplicada', pendientes[0]
        return 'pendiente', pendientes[0]

    def _viaje_existente(self, fecha):
        """
        Las asignaciones «Disposición final» que YA tenga el plan de ese día
        (las de Nancy). Se exige que formen UN solo viaje (todas comparten las
        mismas descargas); con dos viajes distintos ese día no se adivina.
        """
        asignaciones = list(
            Asignacion.objects.filter(plan__fecha=fecha, tipo='DISPOSICION_FINAL')
            .prefetch_related('descargas'))
        grupos = {frozenset(d.pk for d in a.descargas.all()) for a in asignaciones}
        if len(grupos) > 1:
            return None   # ambiguo: mejor crear el viaje propio y que se vea
        return asignaciones or None

    # ---------- el comando ----------

    def handle(self, *args, **opciones):
        self._personal = list(
            User.objects.filter(groups__isnull=False, is_superuser=False)
            .select_related('perfil').distinct())
        autor = None
        if opciones['usuario']:
            autor = User.objects.filter(username=opciones['usuario']).first()
            if autor is None:
                raise CommandError(f"No existe el usuario «{opciones['usuario']}».")

        if opciones['deshacer']:
            return self._deshacer(opciones['confirmar'])

        errores, tareas, al_dia, avisos = [], [], 0, []

        # 1. Las dispuestas en viaje.
        for numero, fecha, placa, nombres in DISPUESTAS_EN_VIAJE:
            estado, carga = self._estado_de(numero)
            if estado == 'saldada':
                al_dia += 1
                continue
            if estado == 'sin_orden':
                avisos.append(f"#{numero}: la orden no existe en el sistema")
                continue
            if estado == 'sin_carga':
                avisos.append(f"#{numero}: sin carga registrada — ya salió por "
                              f"otra vía (gestor o trasiego); nada que saldar")
                continue
            if estado == 'duplicada':
                avisos.append(f"#{numero}: tiene carga saldada Y pendiente a la "
                              f"vez (duplicado): quítalo con reparar_cargas_pendientes")
                continue
            try:
                vehiculo = Vehiculo.objects.filter(placa__iexact=placa).first()
                if vehiculo is None:
                    raise ValueError(f"no existe la placa {placa}")
                personas = [self._persona(n) for n in nombres]
            except ValueError as e:
                errores.append(f"#{numero} (viaje del {fecha:%d/%m/%Y}): {e}")
                continue
            existentes = self._viaje_existente(fecha)
            tareas.append({'que': 'viaje', 'numero': numero, 'carga': carga,
                           'fecha': fecha, 'vehiculo': vehiculo,
                           'personas': personas, 'existentes': existentes})

        # 2. Las dispuestas directo en gestor.
        for numero, (fecha, gestor) in DISPUESTAS_EN_GESTOR.items():
            estado, carga = self._estado_de(numero)
            if estado != 'pendiente':
                if estado == 'duplicada':
                    avisos.append(f"#{numero}: duplicada — reparar_cargas_pendientes")
                else:
                    al_dia += 1
                continue
            dispositores = list(Dispositor.objects.filter(
                nombre__icontains=gestor, tipo='PROVEEDOR', activo=True))
            if len(dispositores) != 1:
                errores.append(f"#{numero}: el gestor «{gestor}» resolvió "
                               f"{len(dispositores)} dispositores")
                continue
            tareas.append({'que': 'gestor', 'numero': numero, 'carga': carga,
                           'fecha': fecha, 'dispositor': dispositores[0]})

        # Vista previa.
        self.stdout.write(self.style.MIGRATE_HEADING(
            f"Revisión orden por orden del reporte "
            f"({len(DISPUESTAS_EN_VIAJE) + len(DISPUESTAS_EN_GESTOR)} órdenes):"))
        self.stdout.write(f"  ✓ {al_dia} ya están como dice el reporte.")
        for t in tareas:
            if t['que'] == 'viaje':
                quienes = ' + '.join(p.get_full_name() or p.username
                                     for p in t['personas'])
                destino = ("se AÑADE al viaje ya registrado ese día"
                           if t['existentes'] else
                           f"se crea el viaje ({quienes})")
                self.stdout.write(
                    f"  → #{t['numero']} ({t['carga'].vehiculo.placa}): se salda "
                    f"con el viaje del {t['fecha']:%d/%m/%Y} — {destino}")
            else:
                self.stdout.write(
                    f"  → #{t['numero']} ({t['carga'].vehiculo.placa}): se salda "
                    f"al gestor {t['dispositor'].nombre} ({t['fecha']:%d/%m/%Y}), sin viaje")
        for a in avisos:
            self.stdout.write(self.style.WARNING(f"  ⚠ {a}"))
        if errores:
            for e in errores:
                self.stdout.write(self.style.ERROR(f"  ✗ {e}"))
            raise CommandError(f"{len(errores)} orden(es) sin resolver: no se escribió nada.")
        if not tareas:
            self.stdout.write("  Nada por hacer.")
            self._contraste()
            return
        if not opciones['confirmar']:
            self._contraste(por_saldar={t['numero'] for t in tareas})
            self.stdout.write(self.style.WARNING(
                "\nVista previa: no se escribió nada. Repite con --confirmar."))
            return

        saldadas, viajes_creados = self._escribir(tareas, autor)
        self.stdout.write(self.style.SUCCESS(
            f"\nListo: {saldadas} orden(es) saldada(s), "
            f"{viajes_creados} viaje(s) creado(s) en el plan."))
        self._contraste()

    # ---------- escribir ----------

    def _saldar(self, carga, fecha, nota, dispositor=None, autor=None):
        """La DESCARGA de una carga, en SU camión y fechada el día real."""
        movimiento = MovimientoCargaVehiculo.objects.create(
            vehiculo=carga.vehiculo, accion='DESCARGA', nota=nota[:255],
            orden=carga.orden, dispositor=dispositor, registrado_por=autor)
        carga.descarga = movimiento
        carga.save(update_fields=['descarga'])
        MovimientoCargaVehiculo.objects.filter(pk=movimiento.pk).update(
            fecha=timezone.make_aware(
                datetime.datetime.combine(fecha, datetime.time(12, 0))))
        carga.vehiculo.sincronizar_carga()
        return movimiento

    def _escribir(self, tareas, autor):
        saldadas = viajes_creados = 0
        with transaction.atomic():
            for t in tareas:
                if t['que'] == 'gestor':
                    nota = (f"Se dispuso con {t['dispositor'].nombre} según el "
                            f"reporte de la oficina · {MARCA}")
                    self._saldar(t['carga'], t['fecha'], nota,
                                 dispositor=t['dispositor'], autor=autor)
                    saldadas += 1
                    continue

                asignaciones = t['existentes']
                if asignaciones is None:
                    plan, _ = PlanDia.objects.get_or_create(fecha=t['fecha'])
                    # Puede que ESTE comando ya haya creado el viaje en una
                    # corrida anterior para otra orden del mismo día.
                    asignaciones = list(plan.asignaciones.filter(
                        tipo='DISPOSICION_FINAL', detalle__startswith=MARCA))
                    if not asignaciones:
                        for persona in t['personas']:
                            asignacion = Asignacion.objects.create(
                                plan=plan, persona=persona,
                                tipo='DISPOSICION_FINAL', detalle=MARCA,
                                registrado_por=autor)
                            asignacion.vehiculos.add(t['vehiculo'])
                            asignaciones.append(asignacion)
                        viajes_creados += 1
                quienes = ', '.join(a.persona_nombre for a in asignaciones)
                nota = (f"Plan del {t['fecha']:%d/%m/%Y}: orden "
                        f"#{t['numero']} dispuesto por {quienes} · {MARCA}")
                movimiento = self._saldar(t['carga'], t['fecha'], nota, autor=autor)
                for asignacion in asignaciones:
                    asignacion.descargas.add(movimiento)
                saldadas += 1
        return saldadas, viajes_creados

    # ---------- deshacer ----------

    def _deshacer(self, confirmar):
        movimientos = list(
            MovimientoCargaVehiculo.objects
            .filter(accion='DESCARGA', nota__contains=MARCA)
            .select_related('vehiculo'))
        asignaciones = list(
            Asignacion.objects.filter(tipo='DISPOSICION_FINAL',
                                      detalle__startswith=MARCA)
            .select_related('persona', 'plan'))
        if not movimientos and not asignaciones:
            self.stdout.write(self.style.WARNING(
                "No hay nada de este comando en la base."))
            return
        self.stdout.write(self.style.MIGRATE_HEADING("Se va a quitar:"))
        for m in movimientos:
            self.stdout.write(f"  descarga de #{m.orden_id} ({m.vehiculo.placa}) "
                              f"— su carga vuelve a quedar pendiente")
        for a in asignaciones:
            self.stdout.write(f"  viaje del {a.plan.fecha:%d/%m/%Y} · {a.persona_nombre}")
        if not confirmar:
            self.stdout.write(self.style.WARNING(
                "\nVista previa: no se borró nada. Repite con --confirmar."))
            return
        with transaction.atomic():
            camiones = {m.vehiculo for m in movimientos}
            planes = {a.plan for a in asignaciones}
            for a in asignaciones:
                a.delete()
            MovimientoCargaVehiculo.objects.filter(
                pk__in=[m.pk for m in movimientos]).delete()
            for camion in camiones:
                camion.sincronizar_carga()
            for plan in planes:
                if not plan.asignaciones.exists() and not plan.notas:
                    plan.delete()
        self.stdout.write(self.style.SUCCESS("Revertido."))
        self._contraste()

    # ---------- contraste ----------

    def _contraste(self, por_saldar=frozenset()):
        pendientes = {
            m.orden_id: m for m in
            MovimientoCargaVehiculo.objects
            .filter(accion='CARGA', descarga__isnull=True, orden__isnull=False)
            .select_related('vehiculo')}
        self.stdout.write(self.style.MIGRATE_HEADING("\nContraste contra el reporte:"))
        bien = PENDIENTES_ESPERADAS & set(pendientes)
        if bien:
            detalle = ', '.join(
                f"#{n} ({pendientes[n].vehiculo.placa})" for n in sorted(bien))
            self.stdout.write(f"  ✓ Sin disponer, como se espera: {detalle}")
        for n in sorted(PENDIENTES_ESPERADAS - set(pendientes) - por_saldar):
            self.stdout.write(self.style.WARNING(
                f"  ⚠ La #{n} debería quedar SIN disponer y no tiene carga "
                f"pendiente: créala con registrar_cargas_pendientes {n} --confirmar"))
        if por_saldar:
            saldables = sorted(set(pendientes) & set(por_saldar))
            if saldables:
                self.stdout.write(
                    f"  · {len(saldables)} orden(es) se saldarán al confirmar: "
                    + ', '.join(f"#{n}" for n in saldables))
        sobran = {n for n in pendientes
                  if 22201 <= n <= 22268 and n not in PENDIENTES_ESPERADAS
                  and n not in por_saldar}
        for n in sorted(sobran):
            self.stdout.write(self.style.WARNING(
                f"  ⚠ La #{n} ({pendientes[n].vehiculo.placa}) sigue pendiente y "
                f"el reporte no la deja así (¿duplicado? ¿carga posterior?)."))
        fuera = {n for n in pendientes if n < 22201 or n > 22268}
        if fuera:
            self.stdout.write(
                "  · Fuera del rango del reporte siguen pendientes: "
                + ', '.join(f"#{n}" for n in sorted(fuera))
                + " (órdenes nuevas o casos abiertos, no las toca este comando)")
