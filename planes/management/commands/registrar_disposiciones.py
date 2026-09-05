"""
Registra en el PLAN DE TRABAJO los viajes de disposición del reporte de la
oficina (SANTI.xlsx, jul-31 a sep-03 de 2026), tal como se acordaron con
Santiago el 05-sep-2026. Los viajes van ESCRITOS en este comando — no se
re-interpreta el Excel — porque la lectura del archivo se resolvió pregunta
por pregunta:

  · Los guiones de la columna H separan órdenes sueltas (no son rangos):
    lo confirman los colores del propio archivo.
  · Del bloque repetido del 28/08 vale el SEGUNDO (la #22255 quedó pendiente
    y se dispuso el 31/08; la #22257 fue con JUAN).
  · «322238» es la #22238 y «#22248#22250» son la 22248 y la 22250.
  · «MUEVE SALDO #22181» es solo una nota: queda en la observación del viaje
    del 10/08 y no escribe nada.
  · La #22254 sigue SIN disponer («si no aparece disposición es porque aún
    no se ha hecho»); la #22251 sigue pendiente (el residuo va en el tanque
    auxiliar del camión); la #22264 y la #22266 sí dispusieron en ENERGY.
  · Un viaje puede saldar órdenes cargadas por OTRA placa: se salda tal
    cual y cada descarga se registra en el camión que llevaba esa carga.
  · Cada viaje queda asignado a las DOS personas; el gestor queda vacío.

Por cada viaje deja lo mismo que dejaría el plan de trabajo en vivo: el plan
del día, una actividad «Disposición final» por persona, y una DESCARGA por
orden saldada —fechada el día real del viaje— que enlaza su carga pendiente.

Vista previa por defecto; escribe solo con --confirmar:

    python manage.py registrar_disposiciones
    python manage.py registrar_disposiciones --confirmar
    python manage.py registrar_disposiciones --confirmar --usuario santiago

Se revierte con --deshacer (también con vista previa): borra las descargas
que este comando creó —sus cargas vuelven a quedar pendientes solas, el
enlace es SET_NULL—, quita las asignaciones con su marca y los planes del
día que queden vacíos. Lo registrado a mano no se toca.

Al final SIEMPRE imprime el contraste contra el reporte: qué órdenes deben
quedar sin disponer según el Excel y qué dice el sistema.
"""
import datetime
import unicodedata

from django.contrib.auth.models import User
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from gestion.models import MovimientoCargaVehiculo, OrdenServicio, Vehiculo
from planes.models import Asignacion, PlanDia

# Marca con la que se reconoce lo que creó este comando, para poder
# revertirlo sin llevarse por delante lo registrado a mano.
MARCA = 'Registro histórico (reporte de disposiciones)'

# Los 12 viajes del reporte: fecha, placa del viaje, las dos personas,
# las órdenes que saldó y la nota que traía la celda (si alguna).
VIAJES = [
    (datetime.date(2026, 8, 3),  'OBC727', ('WILLIAM', 'DAVID'),     (22204,), ''),
    (datetime.date(2026, 8, 8),  'WGY347', ('WILLIAM', 'JEFFERSON'), (22213, 22214, 22212), ''),
    (datetime.date(2026, 8, 10), 'WNO623', ('OSCAR', 'JEFFERSON'),   (22207, 22211), 'MUEVE SALDO #22181'),
    (datetime.date(2026, 8, 11), 'WGY347', ('ALONSO', 'JULIO'),      (22217, 22215), ''),
    (datetime.date(2026, 8, 18), 'WGY347', ('WILLIAM', 'JEFFERSON'), (22229, 22231), ''),
    (datetime.date(2026, 8, 24), 'WGY347', ('WILLIAM', 'JULIO'),     (22243, 22239), ''),
    (datetime.date(2026, 8, 24), 'WNO623', ('OSCAR', 'JEFFERSON'),   (22218, 22228, 22238), ''),
    (datetime.date(2026, 8, 26), 'WGY347', ('WILLIAM', 'OSCAR'),     (22248, 22250), ''),
    (datetime.date(2026, 8, 27), 'OBB178', ('JAVIER', 'JEFFERSON'),  (22222, 22225, 22230, 22244), ''),
    (datetime.date(2026, 8, 29), 'WGY347', ('WILLIAM', 'JEFFERSON'), (22259, 22258), ''),
    (datetime.date(2026, 8, 31), 'WGY347', ('WILLIAM', 'JEFFERSON'), (22261, 22255), ''),
    (datetime.date(2026, 9, 1),  'WGY347', ('WILLIAM', 'JULIO'),     (22263, 22260, 22246), ''),
]

# Lo que, según el reporte, debe quedar SIN disponer después de registrar
# los viajes (las filas «SIN DISPOSICION» que ningún viaje saldó, más la
# #22254, que no dice nada porque aún no se ha hecho).
PENDIENTES_ESPERADAS = {22240, 22247, 22251, 22254, 22257, 22265}


def _limpiar(texto):
    """Sin tildes, en mayúsculas y sin espacios de sobra, para comparar nombres."""
    texto = str(texto or '').strip().upper()
    return ''.join(c for c in unicodedata.normalize('NFD', texto)
                   if unicodedata.category(c) != 'Mn')


class Command(BaseCommand):
    help = ("Registra en el plan de trabajo los viajes de disposición del "
            "reporte de la oficina (vista previa por defecto; escribe con "
            "--confirmar; se revierte con --deshacer).")

    def add_arguments(self, parser):
        parser.add_argument('--confirmar', action='store_true',
                            help='Escribe de verdad (sin esto solo muestra qué haría).')
        parser.add_argument('--usuario', default=None,
                            help='Usuario al que se le atribuye el registro (username).')
        parser.add_argument('--deshacer', action='store_true',
                            help='Revierte lo que este comando creó.')

    # ---------- resolución ----------

    def _persona(self, nombre):
        """
        La persona por un fragmento de su nombre, entre TODO el personal con
        rol (retirados incluidos: el histórico puede nombrarlos). Ambigüedad o
        ausencia son error: aquí no se adivina.
        """
        fragmento = _limpiar(nombre)
        candidatos = [u for u in self._personal
                      if fragmento in _limpiar(f"{u.first_name} {u.last_name}")]
        if len(candidatos) == 1:
            persona = candidatos[0]
            if getattr(getattr(persona, 'perfil', None), 'retirado', False):
                self._avisos.append(
                    f"«{nombre}» está retirado: se asigna igual "
                    f"({persona.get_full_name() or persona.username})")
            return persona
        if not candidatos:
            raise ValueError(f"«{nombre}» no coincide con nadie del personal")
        nombres = ', '.join(u.get_full_name() or u.username for u in candidatos)
        raise ValueError(f"«{nombre}» coincide con varias personas: {nombres}")

    def _carga_de(self, numero):
        """
        La CARGA pendiente de esa orden, viva en el camión que la lleve.
        Devuelve (carga, aviso): sin carga pendiente no es error del comando,
        pero se avisa para que se vea ANTES de confirmar.
        """
        if not OrdenServicio.objects.filter(pk=numero).exists():
            return None, f"la orden #{numero} no existe en el sistema"
        pendiente = (MovimientoCargaVehiculo.objects
                     .filter(accion='CARGA', descarga__isnull=True, orden_id=numero)
                     .select_related('vehiculo').order_by('fecha').first())
        if pendiente is not None:
            return pendiente, None
        saldada = (MovimientoCargaVehiculo.objects
                   .filter(accion='CARGA', descarga__isnull=False, orden_id=numero)
                   .select_related('descarga').order_by('fecha').last())
        if saldada is not None:
            return None, (f"la orden #{numero} ya estaba saldada "
                          f"(descarga del {timezone.localtime(saldada.descarga.fecha):%d/%m/%Y}): "
                          f"no se toca")
        return None, (f"la orden #{numero} no tiene carga registrada: el viaje "
                      f"queda en el plan pero no salda nada (regístrala antes "
                      f"con registrar_cargas_pendientes si debe saldarse)")

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

        # Resolver todo ANTES de escribir nada.
        self._avisos = []
        errores, viajes = [], []
        for fecha, placa, nombres, numeros, nota in VIAJES:
            try:
                vehiculo = Vehiculo.objects.filter(placa__iexact=placa).first()
                if vehiculo is None:
                    raise ValueError(f"no existe la placa {placa}")
                personas = [self._persona(n) for n in nombres]
            except ValueError as e:
                errores.append(f"viaje del {fecha:%d/%m/%Y} ({placa}): {e}")
                continue
            cargas, avisos_viaje = [], []
            for numero in numeros:
                carga, aviso = self._carga_de(numero)
                if carga is not None:
                    cargas.append(carga)
                if aviso:
                    avisos_viaje.append(aviso)
            viajes.append({'fecha': fecha, 'vehiculo': vehiculo,
                           'personas': personas, 'numeros': numeros,
                           'cargas': cargas, 'nota': nota,
                           'avisos': avisos_viaje})

        # Vista previa.
        self.stdout.write(self.style.MIGRATE_HEADING(
            f"Viajes de disposición del reporte ({len(VIAJES)}):"))
        for v in viajes:
            quienes = ' + '.join(p.get_full_name() or p.username for p in v['personas'])
            saldadas = ', '.join(
                f"#{c.orden_id} ({c.vehiculo.placa})" for c in v['cargas']) or '—'
            self.stdout.write(
                f"\n  {v['fecha']:%d/%m/%Y}  {v['vehiculo'].placa}  {quienes}"
                + (f"  · nota: {v['nota']}" if v['nota'] else ''))
            self.stdout.write(f"      salda: {saldadas}")
            for aviso in v['avisos']:
                self.stdout.write(self.style.WARNING(f"      ⚠ {aviso}"))
        for aviso in self._avisos:
            self.stdout.write(self.style.WARNING(f"\n⚠ {aviso}"))
        if errores:
            for e in errores:
                self.stdout.write(self.style.ERROR(f"✗ {e}"))
            raise CommandError(
                f"{len(errores)} viaje(s) sin resolver: no se escribió nada.")

        if not opciones['confirmar']:
            self._contraste(por_saldar={c.orden_id for v in viajes
                                        for c in v['cargas']})
            self.stdout.write(self.style.WARNING(
                "\nVista previa: no se escribió nada. Repite con --confirmar."))
            return

        creados, repetidos, descargas = self._escribir(viajes, autor)
        self.stdout.write(self.style.SUCCESS(
            f"\nListo: {creados} viaje(s) registrados en el plan, "
            f"{descargas} orden(es) saldada(s)."
            + (f" {repetidos} ya estaban y se dejaron como estaban." if repetidos else "")))
        self._contraste()

    def _escribir(self, viajes, autor):
        creados = repetidos = descargas = 0
        with transaction.atomic():
            for v in viajes:
                plan, _ = PlanDia.objects.get_or_create(fecha=v['fecha'])
                # Idempotencia: si este comando ya dejó el viaje, no se repite.
                if plan.asignaciones.filter(
                        tipo='DISPOSICION_FINAL', detalle__startswith=MARCA,
                        persona__in=v['personas'],
                        vehiculos=v['vehiculo']).exists():
                    repetidos += 1
                    continue
                detalle = MARCA + (f" · {v['nota']}" if v['nota'] else '')
                # Una sola orden entre las cargas halladas → queda en la
                # asignación; varias o ninguna → la traza por orden vive en
                # las descargas enlazadas (igual que el plan en vivo).
                ordenes = {c.orden_id for c in v['cargas'] if c.orden_id}
                asignaciones = []
                for persona in v['personas']:
                    asignacion = Asignacion.objects.create(
                        plan=plan, persona=persona, tipo='DISPOSICION_FINAL',
                        detalle=detalle, registrado_por=autor,
                        orden_id=(next(iter(ordenes)) if len(ordenes) == 1 else None),
                    )
                    asignacion.vehiculos.add(v['vehiculo'])
                    asignaciones.append(asignacion)
                creados += 1

                # Cada carga se salda EN SU PROPIO camión (los viajes del
                # reporte saldan órdenes que cargaron otras placas).
                nombres = [a.persona_nombre for a in asignaciones]
                por_camion = {}
                for carga in v['cargas']:
                    por_camion.setdefault(carga.vehiculo, []).append(carga)
                for camion, cargas in por_camion.items():
                    asignaciones[0].aplicar_descarga(camion, nombres, cargas)
                    descargas += len(cargas)
                # La pareja comparte la disposición (como en el plan en vivo).
                asignaciones[1].descargas.set(asignaciones[0].descargas.all())
                # Las descargas quedan fechadas el día REAL del viaje.
                cuando = timezone.make_aware(
                    datetime.datetime.combine(v['fecha'], datetime.time(12, 0)))
                MovimientoCargaVehiculo.objects.filter(
                    pk__in=asignaciones[0].descargas.values_list('pk', flat=True)
                ).update(fecha=cuando)
        return creados, repetidos, descargas

    # ---------- deshacer ----------

    def _deshacer(self, confirmar):
        asignaciones = (Asignacion.objects
                        .filter(tipo='DISPOSICION_FINAL',
                                detalle__startswith=MARCA,
                                plan__fecha__in=[v[0] for v in VIAJES])
                        .select_related('persona', 'plan')
                        .prefetch_related('descargas__vehiculo'))
        movimientos = {m.pk: m for a in asignaciones for m in a.descargas.all()}
        if not asignaciones.exists():
            self.stdout.write(self.style.WARNING(
                "No hay nada de este comando en la base."))
            return

        self.stdout.write(self.style.MIGRATE_HEADING("Se va a quitar del plan:"))
        for a in asignaciones:
            self.stdout.write(f"  {a.plan.fecha:%d/%m/%Y}  {a.persona_nombre}")
        self.stdout.write(
            f"  → {asignaciones.count()} asignación(es) y "
            f"{len(movimientos)} descarga(s); al borrarlas, sus cargas "
            f"vuelven a quedar pendientes solas (el enlace se suelta).")
        if not confirmar:
            self.stdout.write(self.style.WARNING(
                "\nVista previa: no se borró nada. Repite con --confirmar."))
            return

        with transaction.atomic():
            camiones = {m.vehiculo for m in movimientos.values()}
            planes = {a.plan for a in asignaciones}
            asignaciones.delete()
            MovimientoCargaVehiculo.objects.filter(pk__in=movimientos).delete()
            for camion in camiones:
                camion.sincronizar_carga()
            for plan in planes:
                if not plan.asignaciones.exists() and not plan.notas:
                    plan.delete()
        self.stdout.write(self.style.SUCCESS("Revertido."))
        self._contraste()

    # ---------- contraste contra el reporte ----------

    def _contraste(self, por_saldar=frozenset()):
        """
        Qué dice el sistema frente a lo que el reporte espera: las órdenes de
        PENDIENTES_ESPERADAS deben estar sin disponer, y ninguna otra del
        rango del reporte (22201–22268) debería estarlo. Solo lee. En la vista
        previa, `por_saldar` son las que los viajes van a saldar: se informan
        aparte en lugar de reclamarlas.
        """
        pendientes = {
            m.orden_id: m for m in
            MovimientoCargaVehiculo.objects
            .filter(accion='CARGA', descarga__isnull=True, orden__isnull=False)
            .select_related('vehiculo')}
        sin_orden = (MovimientoCargaVehiculo.objects
                     .filter(accion='CARGA', descarga__isnull=True,
                             orden__isnull=True).count())

        self.stdout.write(self.style.MIGRATE_HEADING(
            "\nContraste contra el reporte:"))
        bien = PENDIENTES_ESPERADAS & set(pendientes)
        if bien:
            detalle = ', '.join(
                f"#{n} ({pendientes[n].vehiculo.placa})" for n in sorted(bien))
            self.stdout.write(f"  ✓ Sin disponer, como dice el reporte: {detalle}")
        for n in sorted(PENDIENTES_ESPERADAS - set(pendientes)):
            self.stdout.write(self.style.WARNING(
                f"  ⚠ La #{n} debería estar SIN disponer y el sistema no tiene "
                f"su carga pendiente (regístrala con registrar_cargas_pendientes)."))
        if por_saldar:
            saldables = sorted(set(pendientes) & set(por_saldar))
            self.stdout.write(
                f"  · {len(saldables)} orden(es) pendientes se saldarán al "
                f"confirmar: " + ', '.join(f"#{n}" for n in saldables))
        sobran = {n for n in pendientes
                  if 22201 <= n <= 22268 and n not in PENDIENTES_ESPERADAS
                  and n not in por_saldar}
        for n in sorted(sobran):
            self.stdout.write(self.style.WARNING(
                f"  ⚠ La #{n} ({pendientes[n].vehiculo.placa}) está pendiente en "
                f"el sistema, pero según el reporte ya se dispuso (o dispuso en "
                f"gestor)."))
        fuera = {n for n in pendientes if n < 22201 or n > 22268}
        if fuera:
            self.stdout.write(
                "  · Fuera del rango del reporte siguen pendientes: "
                + ', '.join(f"#{n}" for n in sorted(fuera)))
        if sin_orden:
            self.stdout.write(
                f"  · Y hay {sin_orden} carga(s) manuales sin orden enlazada "
                f"(diagnosticar_cargas las detalla).")
