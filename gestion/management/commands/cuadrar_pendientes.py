"""
Deja las órdenes SIN DISPONER exactamente como la fotografía de la oficina.

La oficina pasó el 14-sep-2026 el listado DEFINITIVO de las órdenes que
siguen sin disponer (02/08 → 13/09; reemplaza al del 08-sep). Decisión de
Santiago: «esta es la última y la verdad absoluta de todo». El listado va
ESCRITO aquí abajo: así el comando es el documento de lo acordado y no
depende de un archivo que se mueva de sitio.

La foto es un RETRATO: solo juzga órdenes hasta la #22300 (la última que
retrata). Lo posterior es operación viva y no se toca — con la foto anterior
la primera vista previa iba a llevarse 12 órdenes reales de sep.

Contra lo que el sistema tiene hoy:
  · FALTAN  — están en la foto y no están sin disponer → quedan SIN DISPONER
    (si tenían una disposición vigente, se marca deshecha con la razón).
  · SOBRAN  — están sin disponer y la foto no las nombra (hasta la #22300)
    → quedan DISPUESTAS con vía «reporte de la oficina» y la fecha del listado.
    Ojo: eso no dice quién la dispuso; es lo que afirma la oficina.

Cliente y fecha de la foto NO se escriben: solo se contrastan y las
diferencias salen avisadas.

    python manage.py cuadrar_pendientes                  # vista previa
    python manage.py cuadrar_pendientes --confirmar
"""
import datetime
import unicodedata

from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import Min

from gestion.models import OrdenServicio

MARCA = 'foto de la oficina 14-sep'
FECHA_FOTO = datetime.date(2026, 9, 14)

# Hasta dónde alcanza la foto (la última orden que retrata).
TOPE = 22300

# La fotografía del 14-sep-2026, tal cual: número → (cliente, fecha, conductor,
# ayudante, placa). Esta foto no trae cuadrilla ni placa (quedan vacíos).
# Todo menos el número es para CONTRASTAR, no para escribir.
FOTO = {
    22204: ('CREPES Y WAFFLES S.A', '02/08/2026', '', '', ''),
    22207: ('D1 SAS', '05/08/2026', '', '', ''),
    22211: ('D1 SAS', '06/08/2026', '', '', ''),
    22212: ('LABORATORIOS SIEGFRIED SAS', '06/08/2026', '', '', ''),
    22213: ('CREPES Y WAFFLES S.A', '07/08/2026', '', '', ''),
    22215: ('CREPES Y WAFFLES S.A', '09/08/2026', '', '', ''),
    22218: ('D1 SAS', '11/08/2026', '', '', ''),
    22222: ('MECANICOS ASOCIADOS SAS', '12/08/2026', '', '', ''),
    22225: ('MECANICOS ASOCIADOS SAS', '13/08/2026', '', '', ''),
    22228: ('D1 SAS', '14/08/2026', '', '', ''),
    22229: ('CREPES Y WAFFLES S.A', '15/08/2026', '', '', ''),
    22230: ('INMEL INGENIERIA S.A.S', '15/08/2026', '', '', ''),
    22231: ('CREPES Y WAFFLES S.A', '16/08/2026', '', '', ''),
    22238: ('D1 SAS', '20/08/2026', '', '', ''),
    22239: ('CREPES Y WAFFLES S.A', '21/08/2026', '', '', ''),
    22240: ('D1 SAS', '21/08/2026', '', '', ''),
    22243: ('CREPES Y WAFFLES S.A', '23/08/2026', '', '', ''),
    22244: ('MECANICOS ASOCIADOS SAS', '23/08/2026', '', '', ''),
    22246: ('CREPES Y WAFFLES S.A', '25/08/2026', '', '', ''),
    22247: ('D1 SAS', '25/08/2026', '', '', ''),
    22248: ('LACTENOVO SAS', '25/08/2026', '', '', ''),
    22251: ('CREPES Y WAFFLES S.A', '27/08/2026', '', '', ''),
    22257: ('D1 SAS', '28/08/2026', '', '', ''),
    22258: ('MECANICOS ASOCIADOS SAS', '28/08/2026', '', '', ''),
    22259: ('MECANICOS ASOCIADOS SAS', '28/08/2026', '', '', ''),
    22260: ('CREPES Y WAFFLES S.A', '29/08/2026', '', '', ''),
    22261: ('CREPES Y WAFFLES S.A', '30/08/2026', '', '', ''),
    22265: ('D1 SAS', '02/09/2026', '', '', ''),
    22266: ('CREPES Y WAFFLES S.A', '03/09/2026', '', '', ''),
    22270: ('D1 SAS', '04/09/2026', '', '', ''),
    22271: ('COLORPLASTIC SOCIEDAD POR ACCIONES SIMPLIFICADA', '04/09/2026', '', '', ''),
    22273: ('CREPES Y WAFFLES S.A', '05/09/2026', '', '', ''),
    22274: ('CREPES Y WAFFLES S.A', '06/09/2026', '', '', ''),
    22278: ('D1 SAS', '08/09/2026', '', '', ''),
    22279: ('CREPES Y WAFFLES S.A', '09/09/2026', '', '', ''),
    22280: ('D1 SAS', '09/09/2026', '', '', ''),
    22281: ('D1 SAS', '09/09/2026', '', '', ''),
    22283: ('D1 SAS', '09/09/2026', '', '', ''),
    22284: ('D1 SAS', '09/09/2026', '', '', ''),
    22285: ('D1 SAS', '10/09/2026', '', '', ''),
    22289: ('D1 SAS', '10/09/2026', '', '', ''),
    22291: ('D1 SAS', '11/09/2026', '', '', ''),
    22294: ('MECANICOS ASOCIADOS SAS', '11/09/2026', '', '', ''),
    22296: ('MECANICOS ASOCIADOS SAS', '12/09/2026', '', '', ''),
    22297: ('MECANICOS ASOCIADOS SAS', '12/09/2026', '', '', ''),
    22298: ('CREPES Y WAFFLES S.A', '13/09/2026', '', '', ''),
    22299: ('CREPES Y WAFFLES S.A', '13/09/2026', '', '', ''),
    22300: ('CREPES Y WAFFLES S.A', '13/09/2026', '', '', ''),
}


def _sin_tildes(texto):
    """Para comparar nombres escritos a mano: sin tildes, sin puntos, en mayúscula."""
    plano = unicodedata.normalize('NFKD', (texto or '').upper())
    plano = ''.join(c for c in plano if not unicodedata.combining(c))
    return ' '.join(plano.replace('.', ' ').split())


class Command(BaseCommand):
    help = ("Deja las órdenes sin disponer exactamente como el listado de la "
            "oficina del 14-sep-2026 (vista previa; escribe con --confirmar).")

    def add_arguments(self, parser):
        parser.add_argument('--confirmar', action='store_true',
                            help='Sin esto solo se muestra la vista previa.')

    def handle(self, *args, **opciones):
        pendientes = set(OrdenServicio.objects
                         .filter(estado_disposicion='PENDIENTE')
                         .values_list('pk', flat=True))
        faltan = sorted(set(FOTO) - pendientes)
        sobran = sorted(n for n in pendientes - set(FOTO) if n <= TOPE)
        posteriores = sorted(n for n in pendientes - set(FOTO) if n > TOPE)
        cuadran = sorted(set(FOTO) & pendientes)

        self.stdout.write(self.style.MIGRATE_HEADING(
            f"La foto pide {len(FOTO)} órdenes sin disponer; el sistema tiene "
            f"{len(pendientes)}."))
        self.stdout.write(f"  ✓ {len(cuadran)} ya cuadran.")

        ordenes = {o.pk: o for o in OrdenServicio.objects
                   .filter(pk__in=faltan + sobran + posteriores + cuadran)
                   .select_related('cliente')
                   .annotate(servicio=Min('recorridos__fecha_recorrido'))}

        a_pendiente, a_dispuesta = [], []
        if faltan:
            self.stdout.write(self.style.MIGRATE_HEADING(
                f"\nFALTAN: {len(faltan)} órdenes de la foto que no están sin disponer"))
            for numero in faltan:
                orden = ordenes.get(numero)
                if orden is None:
                    self.stdout.write(self.style.ERROR(f"  ✗ #{numero} no existe en el sistema."))
                    continue
                vigente = orden.disposicion_vigente
                detalle = (f"dispuesta el {vigente.fecha:%d/%m/%Y} ({vigente.get_via_display()})"
                           if vigente else orden.get_estado_disposicion_display().lower())
                self.stdout.write(f"  + #{numero}  {orden.cliente.nombre[:32]:<32}  hoy: {detalle}")
                a_pendiente.append(orden)
        if sobran:
            self.stdout.write(self.style.MIGRATE_HEADING(
                f"\nSOBRAN: {len(sobran)} órdenes sin disponer que la foto no nombra"))
            for numero in sobran:
                orden = ordenes[numero]
                self.stdout.write(f"  − #{numero}  {orden.cliente.nombre[:32]}")
                a_dispuesta.append(orden)
            self.stdout.write(
                "    Quedan DISPUESTAS por «reporte de la oficina»: la foto dice que\n"
                "    no tienen residuo esperando. No dice quién las dispuso.")
        if posteriores:
            self.stdout.write(self.style.MIGRATE_HEADING(
                f"\nPOSTERIORES A LA FOTO: {len(posteriores)} órdenes sin disponer "
                f"después de la #{TOPE} — NO se tocan"))
            for numero in posteriores:
                self.stdout.write(f"  · #{numero}  {ordenes[numero].cliente.nombre[:32]}")

        self._contrastar(ordenes, cuadran + [o.pk for o in a_pendiente])

        if not (a_pendiente or a_dispuesta):
            self.stdout.write(self.style.SUCCESS(
                "\nNo hay nada que cuadrar: el sistema ya está como la foto."))
            return
        if not opciones['confirmar']:
            self.stdout.write(self.style.WARNING(
                "\nVista previa: no se escribió nada. Repite con --confirmar."))
            return

        with transaction.atomic():
            for orden in a_pendiente:
                orden.deshacer_disposicion(nota=f"Sigue sin disponer según la {MARCA}")
            for orden in a_dispuesta:
                orden.registrar_disposicion(
                    via='REPORTE', fecha=FECHA_FOTO,
                    nota=f"No aparece sin disponer en la {MARCA}")
        self.stdout.write(self.style.SUCCESS(
            f"\nListo: {len(a_pendiente)} vuelven a sin disponer, "
            f"{len(a_dispuesta)} quedan dispuestas."))
        self._contraste_final()

    def _contrastar(self, ordenes, numeros):
        """Lo que la foto dice distinto de lo que el sistema tiene (solo avisa)."""
        avisos = []
        for numero in sorted(numeros):
            orden = ordenes.get(numero)
            if orden is None:
                continue
            cliente_foto, fecha_foto, _, _, placa_foto = FOTO[numero]
            if _sin_tildes(cliente_foto) != _sin_tildes(orden.cliente.nombre):
                avisos.append(f"  #{numero}: la foto dice cliente «{cliente_foto}» "
                              f"y el sistema «{orden.cliente.nombre}»")
            placas = {r.vehiculo.placa.upper() for r in orden.recorridos.all() if r.vehiculo_id}
            if placa_foto and placas and placa_foto.upper() not in placas:
                avisos.append(f"  #{numero}: la foto dice placa «{placa_foto}» "
                              f"y el sistema «{', '.join(sorted(placas))}»")
            try:
                fecha = datetime.datetime.strptime(fecha_foto, '%d/%m/%Y').date()
            except ValueError:
                fecha = None
            if fecha and orden.servicio and fecha != orden.servicio:
                avisos.append(f"  #{numero}: la foto dice {fecha_foto} y el servicio es "
                              f"{orden.servicio:%d/%m/%Y}")
        if avisos:
            self.stdout.write(self.style.MIGRATE_HEADING(
                f"\nDiferencias con la foto ({len(avisos)}) — NO se escriben, solo se avisan:"))
            for aviso in avisos:
                self.stdout.write(self.style.WARNING(aviso))

    def _contraste_final(self):
        pendientes = set(OrdenServicio.objects
                         .filter(estado_disposicion='PENDIENTE')
                         .values_list('pk', flat=True))
        hasta_la_foto = {n for n in pendientes if n <= TOPE}
        self.stdout.write(self.style.MIGRATE_HEADING("\nContraste con la foto:"))
        if hasta_la_foto == set(FOTO):
            self.stdout.write(self.style.SUCCESS(
                f"  ✓ Hasta la #{TOPE}: las {len(FOTO)} órdenes de la foto, y "
                f"solo esas, quedaron sin disponer."))
            posteriores = len(pendientes) - len(hasta_la_foto)
            if posteriores:
                self.stdout.write(f"    (y {posteriores} pendiente(s) posterior(es) a la foto, intactas)")
            return
        for numero in sorted(set(FOTO) - pendientes):
            self.stdout.write(self.style.WARNING(f"  ⚠ La #{numero} debería quedar sin disponer y no lo está."))
        for numero in sorted(hasta_la_foto - set(FOTO)):
            self.stdout.write(self.style.WARNING(f"  ⚠ La #{numero} quedó sin disponer y la foto no la nombra."))
