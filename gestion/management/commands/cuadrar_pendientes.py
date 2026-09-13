"""
Deja las cargas pendientes EXACTAMENTE como la fotografía de la oficina.

La oficina pasó el 08-sep-2026 el listado de las órdenes que siguen SIN
DISPONER (02/08 → 09/09). Decisión de Santiago: «debemos dejar tal cual las
que aparecen en esa foto». Ese listado va ESCRITO aquí abajo (como los viajes
de `registrar_disposiciones`): así el comando es el documento de lo acordado y
no depende de un archivo que se mueva de sitio.

Lo que hace, contra lo que el sistema tiene hoy:
  · FALTAN  — están en la foto y no tienen carga pendiente → se la crea, en el
    camión de su recorrido y fechada el día del servicio.
  · SOBRAN  — tienen carga pendiente y la foto no las nombra → se les QUITA la
    carga. Ojo: quitar la carga NO dice que alguien la dispuso (eso se registra
    desde el plan de trabajo, con su responsable); dice que esa orden no tiene
    residuo esperando, que es justo lo que afirma la oficina.
  · DUPLICADAS — una orden que debe dos veces se recorta a la carga más vieja.
  · POSTERIORES — lo pendiente más nuevo que la foto (orden > TOPE) se lista
    pero NO se toca: es residuo vivo que entró después del corte.

Las columnas Conductor/Acompañante/Vehículo/Cliente/Fecha de la foto NO se
escriben: el sistema ya las tiene en la propia orden. Solo se CONTRASTAN y las
diferencias salen avisadas (fue el error del import de agosto).

Antes de borrar nada deja un respaldo CSV con cada movimiento que quita, para
poder reponerlo a mano si algo no cuadra.

    python manage.py cuadrar_pendientes                  # vista previa
    python manage.py cuadrar_pendientes --confirmar
    python manage.py cuadrar_pendientes --deshacer --confirmar   # solo lo que creó
"""
import csv
import datetime
import io
import unicodedata

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from gestion.models import MovimientoCargaVehiculo, OrdenServicio

# Marca de las cargas que ESTE comando crea (así --deshacer las reconoce).
MARCA = 'foto de la oficina 08-sep'

# Hasta dónde alcanza la foto. Es un RETRATO de un momento: la última orden
# que retrata es la #22279, y la operación siguió después. Todo lo que venga
# de ahí para arriba es residuo vivo —órdenes nuevas que la regla de
# disposición dejó pendientes— y este comando NO lo toca: quitarles la carga
# borraría la mora real de los últimos días. La vista previa del servidor
# (11-sep-2026) iba a llevarse 12 órdenes así.
TOPE = 22279

# La fotografía del 08-sep-2026, tal cual: número → (cliente, fecha, conductor,
# ayudante, placa). Todo menos el número es para CONTRASTAR, no para escribir.
FOTO = {
    22204: ('CREPES Y WAFFLES S.A', '02/08/2026', 'WILLIAM', 'JULIO', 'OBC727'),
    22207: ('D1 SAS', '05/08/2026', 'JAVIER', 'DAVID', 'WNO623'),
    22211: ('D1 SAS', '06/08/2026', 'OSCAR', 'SOLO', 'WNO623'),
    22212: ('LABORATORIOS SIEGFRIED SAS', '06/08/2026', 'ALONSO', 'DAVID', 'WGY347'),
    22213: ('CREPES Y WAFFLES S.A', '07/08/2026', 'WILLIAM', 'JULIO', 'WGY347'),
    22215: ('CREPES Y WAFFLES S.A', '09/08/2026', 'WILLIAM', 'JEFFERSON', 'WGY347'),
    22218: ('D1 SAS', '11/08/2026', 'JAVIER', 'JEFFERSON', 'WNO623'),
    22222: ('MECANICOS ASOCIADOS SAS', '12/08/2026', 'ALONSO', 'OSCAR', 'WGY347'),
    22225: ('MECANICOS ASOCIADOS SAS', '13/08/2026', 'JAVIER', 'JULIO', 'OBB178'),
    22228: ('D1 SAS', '14/08/2026', 'OSCAR', 'SOLO', 'WNO623'),
    22229: ('CREPES Y WAFFLES S.A', '15/08/2026', 'JAVIER', 'JEFFERSON', 'OBB178'),
    22230: ('INMEL INGENIERIA S.A.S', '15/08/2026', 'WILLIAM', 'OSCAR', 'WGY347'),
    22231: ('CREPES Y WAFFLES S.A', '16/08/2026', 'ALONSO', 'OSCAR', 'WGY347'),
    22238: ('D1 SAS', '20/08/2026', 'JAVIER', 'JULIO', 'WNO623'),
    22239: ('CREPES Y WAFFLES S.A', '21/08/2026', 'WILLIAM', 'JULIO', 'WGY347'),
    22240: ('D1 SAS', '21/08/2026', 'JAVIER', 'SOLO', 'WNO623'),
    22243: ('CREPES Y WAFFLES S.A', '23/08/2026', 'WILLIAM', 'JEFFERSON', 'WGY347'),
    22244: ('MECANICOS ASOCIADOS SAS', '23/08/2026', 'ALONSO', 'OSCAR', 'WGY347'),
    22246: ('CREPES Y WAFFLES S.A', '25/08/2026', 'WILLIAM', 'JEFFERSON', 'WGY347'),
    22247: ('D1 SAS', '25/08/2026', 'OSCAR', 'SOLO', 'WNO623'),
    22248: ('LACTENOVO SAS', '25/08/2026', 'WILLIAM', 'JULIO', 'WGY347'),
    22251: ('CREPES Y WAFFLES S.A', '27/08/2026', 'JAVIER', 'JEFFERSON', 'OBB178'),
    22257: ('D1 SAS', '28/08/2026', 'ALONSO', 'JUAN', 'WNO623'),
    22258: ('MECANICOS ASOCIADOS SAS', '28/08/2026', 'ALONSO', 'JULIO', 'WGY347'),
    22259: ('MECANICOS ASOCIADOS SAS', '28/08/2026', 'ALONSO', 'JULIO', 'WGY347'),
    22260: ('CREPES Y WAFFLES S.A', '29/08/2026', 'JAVIER', 'OSCAR', 'OBB178'),
    22261: ('CREPES Y WAFFLES S.A', '30/08/2026', 'WILLIAM', 'JULIO', 'WGY347'),
    22265: ('D1 SAS', '02/09/2026', 'WILLIAM', 'JULIO', 'WNO623'),
    22266: ('CREPES Y WAFFLES S.A', '03/09/2026', 'WILLIAM', 'JEFFERSON', 'WGY347'),
    22270: ('D1 SAS', '04/09/2026', 'OSCAR', 'ANDRES', 'WNO623'),
    22271: ('COLORPLASTIC SOCIEDAD POR ACCIONES SIMPLIFICADA', '04/09/2026',
            'JAVIER', 'JEFFERSON', 'OBB178'),
    22273: ('CREPES Y WAFFLES S.A', '05/09/2026', 'WILLIAM', 'JEFFERSON', 'WGY347'),
    22274: ('CREPES Y WAFFLES S.A', '06/09/2026', 'ALONSO', 'JEFFERSON', 'WGY347'),
    22278: ('D1 SAS', '08/09/2026', 'ALONSO', 'JULIO', 'WNO623'),
    22279: ('CREPES Y WAFFLES S.A', '09/09/2026', 'JAVIER', 'JULIO', 'OBB178'),
}


def _sin_tildes(texto):
    """Para comparar nombres escritos a mano: sin tildes, sin puntos, en mayúscula."""
    plano = unicodedata.normalize('NFKD', (texto or '').upper())
    plano = ''.join(c for c in plano if not unicodedata.combining(c))
    return ' '.join(plano.replace('.', ' ').split())


class Command(BaseCommand):
    help = ("Deja las cargas pendientes exactamente como el listado de la "
            "oficina del 08-sep-2026 (vista previa; escribe con --confirmar).")

    def add_arguments(self, parser):
        parser.add_argument('--confirmar', action='store_true',
                            help='Sin esto solo se muestra la vista previa.')
        parser.add_argument('--deshacer', action='store_true',
                            help='Quita las cargas que este comando creó y '
                                 'siguen pendientes. No repone las que quitó.')
        parser.add_argument('--respaldo', default='respaldo_cuadrar.csv',
                            metavar='ARCHIVO',
                            help='Dónde guardar lo que se quita (CSV).')

    def handle(self, *args, **opciones):
        if opciones['deshacer']:
            return self._deshacer(opciones['confirmar'])

        pendientes = self._pendientes()
        con_orden = {c.orden_id: c for c in pendientes if c.orden_id}
        # Una orden puede deber dos veces (dobles registros): la más vieja manda.
        duplicadas = self._duplicadas(pendientes)
        sueltas = [c for c in pendientes if not c.orden_id]

        faltan = sorted(set(FOTO) - set(con_orden))
        # Solo se juzga lo que la foto alcanza a retratar.
        sobran = sorted(n for n in set(con_orden) - set(FOTO) if n <= TOPE)
        posteriores = sorted(n for n in set(con_orden) - set(FOTO) if n > TOPE)
        cuadran = sorted(set(FOTO) & set(con_orden))

        self.stdout.write(self.style.MIGRATE_HEADING(
            f"La foto pide {len(FOTO)} órdenes sin disponer; el sistema tiene "
            f"{len(con_orden)}."))
        self.stdout.write(f"  ✓ {len(cuadran)} ya cuadran.")

        creables = self._informar_faltantes(faltan)
        quitables = self._informar_sobrantes(sobran, con_orden)
        self._informar_posteriores(posteriores, con_orden)
        self._informar_duplicadas(duplicadas)
        self._informar_sueltas(sueltas)
        self._contrastar(cuadran + [n for n, _ in creables])

        if not (creables or quitables or duplicadas):
            self.stdout.write(self.style.SUCCESS(
                "\nNo hay nada que cuadrar: el sistema ya está como la foto."))
            return

        if not opciones['confirmar']:
            self.stdout.write(self.style.WARNING(
                "\nVista previa: no se escribió nada. Repite con --confirmar."))
            return

        self._aplicar(creables, quitables, duplicadas, opciones['respaldo'])

    # ---------- lo que hay hoy ----------

    def _pendientes(self):
        return list(MovimientoCargaVehiculo.objects
                    .filter(accion='CARGA', descarga__isnull=True)
                    .select_related('vehiculo', 'orden__cliente')
                    .order_by('fecha'))

    def _duplicadas(self, pendientes):
        """Las cargas de más de una orden que ya debe (se conserva la vieja)."""
        vistas, sobrantes = set(), []
        for carga in pendientes:            # vienen ordenadas por fecha
            if not carga.orden_id:
                continue
            if carga.orden_id in vistas and carga.orden_id <= TOPE:
                sobrantes.append(carga)
            else:
                vistas.add(carga.orden_id)
        return sobrantes

    # ---------- lo que falta ----------

    def _informar_faltantes(self, faltan):
        """[(numero, recorrido)] de las que se les puede crear la carga."""
        if not faltan:
            return []
        self.stdout.write(self.style.MIGRATE_HEADING(
            f"\nFALTAN: {len(faltan)} órdenes de la foto sin carga pendiente"))
        creables = []
        for numero in faltan:
            orden = OrdenServicio.objects.filter(pk=numero).first()
            if orden is None:
                self.stdout.write(self.style.ERROR(
                    f"  ✗ #{numero} no existe en el sistema."))
                continue
            recorrido = orden.recorridos.select_related('vehiculo').first()
            if recorrido is None or recorrido.vehiculo is None:
                self.stdout.write(self.style.ERROR(
                    f"  ✗ #{numero} no tiene recorrido con vehículo: "
                    f"no se sabe en qué camión quedó el residuo."))
                continue
            if orden.movimientos_carga.filter(accion='CARGA').exists():
                self.stdout.write(self.style.WARNING(
                    f"  ⚠ #{numero} ya tuvo una carga y quedó saldada. Se le "
                    f"crea una nueva: la foto dice que sigue sin disponer."))
            self.stdout.write(
                f"  + #{numero}  {recorrido.vehiculo.placa:<8}"
                f"{recorrido.fecha_recorrido:%d/%m/%Y}  "
                f"{orden.cliente.nombre[:32]}")
            creables.append((numero, recorrido))
        return creables

    # ---------- lo que sobra ----------

    def _informar_sobrantes(self, sobran, con_orden):
        if not sobran:
            return []
        self.stdout.write(self.style.MIGRATE_HEADING(
            f"\nSOBRAN: {len(sobran)} órdenes pendientes que la foto no nombra"))
        quitables = []
        for numero in sobran:
            carga = con_orden[numero]
            cliente = carga.orden.cliente.nombre[:28] if carga.orden else '—'
            self.stdout.write(
                f"  − #{numero}  {carga.vehiculo.placa:<8}"
                f"{carga.fecha:%d/%m/%Y}  {cliente}")
            self.stdout.write(f"      nota: {carga.nota[:90]}")
            quitables.append(carga)
        self.stdout.write(
            "    Se les quita la carga: la oficina dice que no tienen residuo\n"
            "    esperando. Quitarla NO registra una disposición — si alguien\n"
            "    las dispuso, eso va en el PLAN DE TRABAJO con su responsable.")
        return quitables

    def _informar_posteriores(self, posteriores, con_orden):
        """
        Órdenes pendientes MÁS NUEVAS que la foto: operación viva. Se listan
        para que se vean, pero no se tocan — la foto no las retrata, así que
        no dice nada sobre ellas.
        """
        if not posteriores:
            return
        self.stdout.write(self.style.MIGRATE_HEADING(
            f"\nPOSTERIORES A LA FOTO: {len(posteriores)} órdenes pendientes "
            f"después de la #{TOPE} — NO se tocan"))
        for numero in posteriores:
            carga = con_orden[numero]
            cliente = carga.orden.cliente.nombre[:28] if carga.orden else '—'
            self.stdout.write(
                f"  · #{numero}  {carga.vehiculo.placa:<8}"
                f"{carga.fecha:%d/%m/%Y}  {cliente}")
        self.stdout.write(
            "    Es residuo vivo: entró después del corte de la foto. Se\n"
            "    dispone desde el plan de trabajo, como cualquier pendiente.")

    def _informar_duplicadas(self, duplicadas):
        if not duplicadas:
            return
        self.stdout.write(self.style.MIGRATE_HEADING(
            f"\nDUPLICADAS: {len(duplicadas)} carga(s) de órdenes que ya deben"))
        for carga in duplicadas:
            self.stdout.write(
                f"  − #{carga.orden_id}  {carga.vehiculo.placa:<8}"
                f"{carga.fecha:%d/%m/%Y}  (se conserva la más vieja)")

    def _informar_sueltas(self, sueltas):
        """Cargas manuales sin orden: no se pueden cotejar con la foto."""
        if not sueltas:
            return
        self.stdout.write(self.style.MIGRATE_HEADING(
            f"\nSIN ORDEN: {len(sueltas)} carga(s) manual(es) — no se tocan"))
        for carga in sueltas:
            self.stdout.write(
                f"  ? {carga.vehiculo.placa:<8}{carga.fecha:%d/%m/%Y}  "
                f"{carga.nota[:70]}")

    # ---------- contraste de las columnas ----------

    def _contrastar(self, numeros):
        """Lo que la foto dice distinto de lo que el sistema tiene."""
        avisos = []
        for numero in sorted(numeros):
            cliente_foto, fecha_foto, _, _, placa_foto = FOTO[numero]
            orden = (OrdenServicio.objects
                     .filter(pk=numero).select_related('cliente').first())
            if orden is None:
                continue
            if _sin_tildes(cliente_foto) != _sin_tildes(orden.cliente.nombre):
                avisos.append(f"  #{numero}: la foto dice cliente "
                              f"«{cliente_foto}» y el sistema «{orden.cliente.nombre}»")
            recorrido = orden.recorridos.select_related('vehiculo').first()
            if recorrido is None:
                continue
            placa = (recorrido.vehiculo.placa if recorrido.vehiculo else '')
            if placa_foto and placa and placa_foto != placa.upper():
                avisos.append(f"  #{numero}: la foto dice placa «{placa_foto}» "
                              f"y el sistema «{placa}»")
            fecha = self._fecha(fecha_foto)
            if fecha and fecha != recorrido.fecha_recorrido:
                avisos.append(
                    f"  #{numero}: la foto dice {fecha_foto} y el recorrido es "
                    f"{recorrido.fecha_recorrido:%d/%m/%Y}")
        if avisos:
            self.stdout.write(self.style.MIGRATE_HEADING(
                f"\nDiferencias con la foto ({len(avisos)}) — NO se escriben, "
                f"solo se avisan:"))
            for aviso in avisos:
                self.stdout.write(self.style.WARNING(aviso))

    def _fecha(self, texto):
        try:
            return datetime.datetime.strptime(texto, '%d/%m/%Y').date()
        except (TypeError, ValueError):
            return None

    # ---------- escribir ----------

    def _aplicar(self, creables, quitables, duplicadas, ruta_respaldo):
        fuera = quitables + duplicadas
        if fuera:
            self._respaldar(fuera, ruta_respaldo)

        with transaction.atomic():
            camiones = {c.vehiculo for c in fuera}
            MovimientoCargaVehiculo.objects.filter(
                pk__in=[c.pk for c in fuera]).delete()

            for numero, recorrido in creables:
                fecha = recorrido.fecha_recorrido
                movimiento = MovimientoCargaVehiculo.objects.create(
                    vehiculo=recorrido.vehiculo, accion='CARGA',
                    orden_id=numero,
                    nota=(f"Orden #{numero} del {fecha:%d/%m/%Y}: quedó sin "
                          f"disponer · {MARCA}")[:255])
                # `fecha` es auto_now_add: se corrige con UPDATE al día real.
                MovimientoCargaVehiculo.objects.filter(pk=movimiento.pk).update(
                    fecha=timezone.make_aware(datetime.datetime.combine(
                        fecha, datetime.time(12, 0))))
                camiones.add(recorrido.vehiculo)

            for camion in camiones:
                camion.sincronizar_carga()

        self.stdout.write(self.style.SUCCESS(
            f"\nListo: {len(creables)} carga(s) creadas, {len(quitables)} "
            f"quitada(s) y {len(duplicadas)} duplicada(s) recortada(s)."))
        self._contraste_final()

    def _respaldar(self, movimientos, ruta):
        try:
            with io.open(ruta, 'w', encoding='utf-8-sig', newline='') as fh:
                escritor = csv.writer(fh, delimiter=';')
                escritor.writerow(['id', 'placa', 'accion', 'orden', 'fecha',
                                   'nota'])
                for m in movimientos:
                    escritor.writerow([m.pk, m.vehiculo.placa, m.accion,
                                       m.orden_id or '',
                                       m.fecha.strftime('%Y-%m-%d %H:%M'),
                                       m.nota])
        except OSError as e:
            self.stderr.write(f"No se pudo escribir el respaldo «{ruta}»: {e}")
            return
        self.stdout.write(f"Respaldo de lo que se quita: {ruta}")

    def _contraste_final(self):
        pendientes = set(MovimientoCargaVehiculo.objects
                         .filter(accion='CARGA', descarga__isnull=True,
                                 orden__isnull=False)
                         .values_list('orden_id', flat=True))
        self.stdout.write(self.style.MIGRATE_HEADING("\nContraste con la foto:"))
        hasta_la_foto = {n for n in pendientes if n <= TOPE}
        if hasta_la_foto == set(FOTO):
            self.stdout.write(self.style.SUCCESS(
                f"  ✓ Hasta la #{TOPE}: las {len(FOTO)} órdenes de la foto, y "
                f"solo esas, quedaron sin disponer."))
            posteriores = len(pendientes) - len(hasta_la_foto)
            if posteriores:
                self.stdout.write(
                    f"    (y {posteriores} pendiente(s) posterior(es) a la "
                    f"foto, intactas)")
            return
        for numero in sorted(set(FOTO) - pendientes):
            self.stdout.write(self.style.WARNING(
                f"  ⚠ La #{numero} debería quedar pendiente y no lo está."))
        for numero in sorted(hasta_la_foto - set(FOTO)):
            self.stdout.write(self.style.WARNING(
                f"  ⚠ La #{numero} quedó pendiente y la foto no la nombra."))

    # ---------- deshacer ----------

    def _deshacer(self, confirmar):
        creadas = list(MovimientoCargaVehiculo.objects
                       .filter(accion='CARGA', descarga__isnull=True,
                               nota__contains=MARCA)
                       .select_related('vehiculo'))
        if not creadas:
            self.stdout.write("Este comando no tiene cargas pendientes que quitar.")
            return
        self.stdout.write(self.style.MIGRATE_HEADING(
            f"Se van a quitar {len(creadas)} carga(s) que creó este comando:"))
        for carga in creadas:
            self.stdout.write(
                f"  − #{carga.orden_id}  {carga.vehiculo.placa:<8}"
                f"{carga.fecha:%d/%m/%Y}")
        self.stdout.write(self.style.WARNING(
            "  ⚠ Esto NO repone las cargas que el comando QUITÓ: esas están "
            "en el CSV de respaldo."))
        if not confirmar:
            self.stdout.write(self.style.WARNING(
                "\nVista previa: no se escribió nada. Repite con --confirmar."))
            return
        with transaction.atomic():
            camiones = {c.vehiculo for c in creadas}
            MovimientoCargaVehiculo.objects.filter(
                pk__in=[c.pk for c in creadas]).delete()
            for camion in camiones:
                camion.sincronizar_carga()
        self.stdout.write(self.style.SUCCESS(
            f"\nListo: {len(creadas)} carga(s) quitada(s)."))
