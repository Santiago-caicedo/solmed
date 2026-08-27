"""
Registra que unas órdenes quedaron SIN DISPONER: su residuo sigue en el camión.

Nació del reporte de SOLMED (ago-2026) con las órdenes cuyo carro quedó
cargado. Se le pasan los números de orden y el resto sale de la propia orden
(el camión y la fecha vienen de su recorrido): cada una queda como una CARGA
pendiente en su camión, y esas cargas se van acumulando y se saldan una por
una desde el plan de trabajo.

    python manage.py registrar_cargas_pendientes 22207 22211 22212
    python manage.py registrar_cargas_pendientes 22207 22211 --confirmar
    python manage.py registrar_cargas_pendientes --csv cargas_pendientes.csv
    python manage.py registrar_cargas_pendientes --deshacer --confirmar

Con --csv se pasa el listado de la empresa (columnas separadas por «;»:
Código, Cliente, Fecha, Descripción, Conductor, Acompañante, Vehículo). El
número de orden es lo único que se ESCRIBE; el resto de columnas se usa para
COMPARAR contra lo que el sistema ya sabe y avisar de las diferencias.

Además señala las cargas pendientes que NO vienen en la lista. Esas no se
tocan a propósito: darlas por dispuestas es afirmar que alguien las dispuso,
y eso se registra desde el plan de trabajo, con su responsable y su fecha.

Sin --confirmar solo muestra lo que haría. --deshacer quita lo que este
comando registró (reconoce sus cargas por la marca en la nota) siempre que
sigan pendientes: una carga ya saldada por una disposición real no se toca.
"""
import csv
import datetime
import io
import unicodedata

from django.core.management.base import BaseCommand
from django.db import transaction

from gestion.models import MovimientoCargaVehiculo, OrdenServicio

MARCA = 'Reporte SOLMED'


def _sin_tildes(texto):
    """Para comparar nombres escritos a mano: sin tildes, sin puntos, en mayúscula."""
    plano = unicodedata.normalize('NFKD', (texto or '').upper())
    plano = ''.join(c for c in plano if not unicodedata.combining(c))
    return ' '.join(plano.replace('.', ' ').split())


class Command(BaseCommand):
    help = ("Registra órdenes cuyo residuo quedó en el camión sin disponer "
            "(cargas pendientes que se saldan desde el plan de trabajo).")

    def add_arguments(self, parser):
        parser.add_argument('ordenes', nargs='*', type=int, metavar='ORDEN',
                            help='Números de orden que quedaron sin disponer.')
        parser.add_argument('--csv', default=None, metavar='ARCHIVO',
                            help='Listado de la empresa (separado por «;»). '
                                 'Compara sus columnas contra el sistema.')
        parser.add_argument('--confirmar', action='store_true',
                            help='Sin esto solo se muestra la vista previa.')
        parser.add_argument('--deshacer', action='store_true',
                            help='Quita las cargas que este comando registró '
                                 'y siguen pendientes.')

    def handle(self, *args, **opciones):
        if opciones['deshacer']:
            return self._deshacer(opciones['confirmar'])
        esperado = {}
        if opciones['csv']:
            esperado = self._leer_csv(opciones['csv'])
            if esperado is None:
                return
        numeros = list(esperado) or opciones['ordenes']
        if not numeros:
            self.stderr.write("Pasa los números de orden, --csv o --deshacer.")
            return
        self._registrar(numeros, opciones['confirmar'], esperado)
        self._sobrantes(set(numeros))

    # ---------- el listado de la empresa ----------

    def _leer_csv(self, ruta):
        """{numero: fila} del CSV, o None si no se pudo leer."""
        try:
            with io.open(ruta, encoding='utf-8-sig') as fh:
                filas = list(csv.DictReader(fh, delimiter=';'))
        except OSError as e:
            self.stderr.write(f"No se pudo leer «{ruta}»: {e}")
            return None
        if not filas or 'Código' not in filas[0]:
            self.stderr.write(
                "El archivo no trae la columna «Código». Se esperan columnas "
                "separadas por «;»: Código;Cliente;Fecha;Descripción;"
                "Conductor;Acompañante;Vehículo")
            return None

        esperado, malos = {}, []
        for fila in filas:
            crudo = (fila.get('Código') or '').strip().lstrip('#').strip()
            if crudo.isdigit():
                esperado[int(crudo)] = fila
            elif crudo:
                malos.append(crudo)
        for crudo in malos:
            self.stdout.write(self.style.ERROR(
                f"  ✗ «{crudo}» no es un número de orden: se omite."))
        return esperado

    def _diferencias(self, orden, fila):
        """Lo que el listado dice distinto de lo que el sistema tiene."""
        if not fila:
            return []
        avisos = []
        recorrido = orden.recorridos.select_related('vehiculo').first()

        cliente_csv = _sin_tildes(fila.get('Cliente'))
        if cliente_csv and cliente_csv != _sin_tildes(orden.cliente.nombre):
            avisos.append(f"el listado dice cliente «{fila['Cliente'].strip()}» "
                          f"y el sistema tiene «{orden.cliente.nombre}»")

        placa_csv = (fila.get('Vehículo') or '').strip().upper()
        placa_sistema = (recorrido.vehiculo.placa.upper()
                         if recorrido and recorrido.vehiculo_id else '')
        if placa_csv and placa_sistema and placa_csv != placa_sistema:
            avisos.append(f"el listado dice placa {placa_csv} y el sistema "
                          f"tiene {placa_sistema} (manda el sistema)")

        crudo_fecha = (fila.get('Fecha') or '').strip()
        if crudo_fecha and recorrido:
            try:
                fecha_csv = datetime.datetime.strptime(crudo_fecha, '%d/%m/%Y').date()
            except ValueError:
                avisos.append(f"la fecha «{crudo_fecha}» no se entiende")
            else:
                if fecha_csv != recorrido.fecha_recorrido:
                    avisos.append(
                        f"el listado dice {fecha_csv:%d/%m/%Y} y el servicio "
                        f"quedó el {recorrido.fecha_recorrido:%d/%m/%Y}")

        if recorrido and not recorrido.conductor_id and (fila.get('Conductor') or '').strip():
            avisos.append(f"la orden no tiene conductor registrado; el listado "
                          f"dice {fila['Conductor'].strip()} (se pone editando la orden)")
        return avisos

    # ---------- registrar ----------

    def _revisar(self, numero):
        """(orden, vehiculo, aviso, error) de un número de orden."""
        orden = OrdenServicio.objects.filter(pk=numero).first()
        if orden is None:
            return None, None, None, "no existe en el sistema"
        recorrido = orden.recorridos.select_related('vehiculo').first()
        if recorrido is None:
            return orden, None, None, "no tiene recorrido (¿de cuál camión?)"
        if MovimientoCargaVehiculo.objects.filter(
                orden=orden, accion='CARGA', descarga__isnull=True).exists():
            return orden, recorrido.vehiculo, None, "ya está pendiente de disponer"
        aviso = None
        if MovimientoCargaVehiculo.objects.filter(
                orden=orden, accion='DESCARGA').exists():
            aviso = ("el sistema la tenía como dispuesta; el reporte de la "
                     "empresa manda y vuelve a quedar pendiente")
        return orden, recorrido.vehiculo, aviso, None

    def _registrar(self, numeros, confirmar, esperado=None):
        esperado = esperado or {}
        listas, errores, ya_estaban = [], [], []
        for numero in dict.fromkeys(numeros):     # sin repetidos, en orden
            orden, vehiculo, aviso, error = self._revisar(numero)
            if error == "ya está pendiente de disponer":
                ya_estaban.append((orden, vehiculo))
                continue
            if error:
                errores.append((numero, error))
            else:
                listas.append((orden, vehiculo, aviso))

        self.stdout.write(self.style.MIGRATE_HEADING(
            f"\n{'REGISTRO' if confirmar else 'VISTA PREVIA (no se guarda nada)'}"
            f" — {len(listas)} orden(es) por marcar sin disponer"))
        for orden, vehiculo, aviso in listas:
            recorrido = orden.recorridos.first()
            self.stdout.write(
                f"  ✓ #{orden.pk}  {vehiculo.placa:<8}"
                f"{recorrido.fecha_recorrido:%d/%m/%Y}  "
                f"{orden.cliente.nombre[:35]}")
            if aviso:
                self.stdout.write(self.style.WARNING(f"      ⚠ {aviso}"))
            for diferencia in self._diferencias(orden, esperado.get(orden.pk)):
                self.stdout.write(self.style.WARNING(f"      ⚠ {diferencia}"))

        if ya_estaban:
            self.stdout.write(self.style.MIGRATE_HEADING(
                f"\nYa estaban pendientes ({len(ya_estaban)}), no se tocan"))
            for orden, vehiculo in ya_estaban:
                placa = vehiculo.placa if vehiculo else '—'
                self.stdout.write(f"  · #{orden.pk}  {placa}")
                for diferencia in self._diferencias(orden, esperado.get(orden.pk)):
                    self.stdout.write(self.style.WARNING(f"      ⚠ {diferencia}"))
        for numero, error in errores:
            self.stdout.write(self.style.ERROR(f"  ✗ #{numero}: {error}"))

        if not confirmar:
            self.stdout.write("\nRevisa y vuelve a correr con --confirmar.")
            return
        if not listas:
            self.stdout.write("Nada por registrar.")
            return

        with transaction.atomic():
            camiones = {}
            for orden, vehiculo, aviso in listas:
                recorrido = orden.recorridos.first()
                movimiento = MovimientoCargaVehiculo.objects.create(
                    vehiculo=vehiculo, accion='CARGA', orden=orden,
                    nota=(f"Orden #{orden.pk} del "
                          f"{recorrido.fecha_recorrido:%d/%m/%Y}: quedó "
                          f"cargado (sin disposición) · {MARCA.lower()}")[:255],
                )
                # La fecha real es la del recorrido, no la de hoy (auto_now_add
                # no deja fijarla al crear).
                MovimientoCargaVehiculo.objects.filter(pk=movimiento.pk).update(
                    fecha=recorrido.fecha_recorrido)
                camiones[vehiculo.pk] = vehiculo
            for vehiculo in camiones.values():
                vehiculo.sincronizar_carga()

        self.stdout.write(self.style.SUCCESS(
            f"\nListo: {len(listas)} carga(s) pendiente(s) registradas en "
            f"{len(camiones)} camión(es). Se saldan desde el plan de trabajo."))

    # ---------- lo que sobra ----------

    def _sobrantes(self, esperados):
        """
        Cargas pendientes que la lista NO menciona. No se tocan: darlas por
        dispuestas es afirmar que alguien las dispuso, y eso se registra desde
        el plan de trabajo con su responsable. Aquí solo se señalan.
        """
        sobran = (MovimientoCargaVehiculo.objects
                  .filter(accion='CARGA', descarga__isnull=True)
                  .exclude(orden_id__in=esperados)
                  .select_related('vehiculo', 'orden__cliente')
                  .order_by('vehiculo__placa', 'fecha'))
        if not sobran:
            return
        self.stdout.write(self.style.MIGRATE_HEADING(
            f"\nPendientes que NO vienen en la lista ({sobran.count()})"))
        for c in sobran:
            quien = (f"#{c.orden_id} {c.orden.cliente.nombre[:28]}" if c.orden_id
                     else 'sin orden (carga manual)')
            self.stdout.write(f"  ? {c.vehiculo.placa:<8}{c.fecha:%d/%m/%Y}  {quien}")
        self.stdout.write(
            "    Si ya se dispusieron, regístralo desde el PLAN DE TRABAJO "
            "para que quede\n    con su responsable y su fecha. Este comando "
            "no las descarga a propósito.")

    # ---------- deshacer ----------

    def _deshacer(self, confirmar):
        cargas = (MovimientoCargaVehiculo.objects
                  .filter(accion='CARGA', nota__icontains=MARCA.lower(),
                          descarga__isnull=True)
                  .select_related('vehiculo', 'orden'))
        saldadas = MovimientoCargaVehiculo.objects.filter(
            accion='CARGA', nota__icontains=MARCA.lower(),
            descarga__isnull=False).count()

        self.stdout.write(self.style.MIGRATE_HEADING(
            f"\n{'REVERSA' if confirmar else 'VISTA PREVIA (no se borra nada)'}"
            f" — {cargas.count()} carga(s) de este comando por quitar"))
        for c in cargas:
            self.stdout.write(f"  · {c.vehiculo.placa}  "
                              f"{'#' + str(c.orden_id) if c.orden_id else 'sin orden'}")
        if saldadas:
            self.stdout.write(self.style.WARNING(
                f"  ⚠ {saldadas} ya fueron saldadas por una disposición real: "
                f"esas no se tocan."))
        if not confirmar:
            self.stdout.write("\nRevisa y vuelve a correr con --confirmar.")
            return

        with transaction.atomic():
            camiones = {c.vehiculo.pk: c.vehiculo for c in cargas}
            borradas = cargas.delete()[0]
            for vehiculo in camiones.values():
                vehiculo.sincronizar_carga()
        self.stdout.write(self.style.SUCCESS(f"\nListo: {borradas} quitada(s)."))
