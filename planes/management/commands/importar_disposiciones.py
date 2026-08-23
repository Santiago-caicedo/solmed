"""
Carga en el PLAN DE TRABAJO las disposiciones que ya se hicieron pero nunca se
registraron en el sistema (el histórico que estaba en un Excel).

Por cada fila deja lo mismo que dejaría el plan si se hubiera asignado ese día:
el plan del día, la actividad «Disposición final» para el conductor y su
ayudante, con su placa y su orden, y el movimiento de carga del vehículo
fechado en el DÍA REAL de la disposición (no en el de la importación).

Lo que NO hace, a propósito: tocar el estado `cargado` de los camiones. Eso es
la foto de HOY y no se deduce del histórico; al final el comando lo reporta
para que se corrija a mano si hace falta.

El archivo es CSV (el servidor no lee .xlsx). Desde Excel: «Guardar como →
CSV UTF-8». Columnas esperadas, en cualquier orden:

    FECHA,CLIENTE,VEHÍCULO,ORDEN,CONDUCTOR,AYUDANTE
    02/08/2026,CREPES,OBC,#22204,WILLIAM,JULIO

  · FECHA      dd/mm/aaaa o aaaa-mm-dd
  · CLIENTE    solo para verificar contra el cliente de la orden (no se guarda)
  · VEHÍCULO   parte de la placa (OBC); debe encontrar una sola
  · ORDEN      número de la orden, con o sin #
  · CONDUCTOR  parte del nombre; debe encontrar uno solo entre los conductores
  · AYUDANTE   igual, entre los ayudantes. «SOLO» o vacío = el conductor fue solo

Vista previa por defecto; escribe solo con --confirmar:

    python manage.py importar_disposiciones disposiciones.csv
    python manage.py importar_disposiciones disposiciones.csv --confirmar
    python manage.py importar_disposiciones disposiciones.csv --confirmar --usuario ana

Y si se importó lo que no era, se revierte con lo mismo:

    python manage.py importar_disposiciones disposiciones.csv --deshacer
    python manage.py importar_disposiciones disposiciones.csv --deshacer --confirmar

Deshacer solo toca lo que ESTE comando creó: las asignaciones marcadas como
«Registro histórico» de esas órdenes, sus movimientos de carga, y los planes
del día que queden sin nada. Lo que se haya agregado a mano se respeta.
"""
import csv
import datetime
import unicodedata

from django.contrib.auth.models import Group, User
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from gestion.models import MovimientoCargaVehiculo, OrdenServicio, Vehiculo
from planes.models import Asignacion, PlanDia

# Marca con la que se reconoce lo que creó esta importación, para poder
# revertirla sin llevarse por delante lo que alguien registró a mano.
MARCA = 'Registro histórico'
SIN_AYUDANTE = {'', 'SOLO', 'SOLO.', 'NINGUNO', 'N/A', '-'}
FORMATOS_FECHA = ('%d/%m/%Y', '%Y-%m-%d', '%d-%m-%Y', '%d/%m/%y')


def _limpiar(texto):
    """Sin tildes, en mayúsculas y sin espacios de sobra: así se comparan los nombres."""
    texto = str(texto or '').strip().upper()
    return ''.join(c for c in unicodedata.normalize('NFD', texto)
                   if unicodedata.category(c) != 'Mn')


class Command(BaseCommand):
    help = ("Registra en el plan de trabajo las disposiciones históricas de un CSV "
            "(vista previa por defecto; escribe con --confirmar).")

    def add_arguments(self, parser):
        parser.add_argument('archivo', help='Ruta del CSV con las disposiciones.')
        parser.add_argument('--confirmar', action='store_true',
                            help='Escribe de verdad (sin esto solo muestra qué haría).')
        parser.add_argument('--usuario', default=None,
                            help='Usuario al que se le atribuye el registro (username).')
        parser.add_argument('--omitir-errores', action='store_true',
                            help='Importa las filas que sí resolvieron y salta las demás.')
        parser.add_argument('--deshacer', action='store_true',
                            help='Revierte lo que esta importación creó para ese archivo.')

    # ---------- resolución de cada columna ----------

    def _fecha(self, crudo):
        crudo = str(crudo or '').strip()
        for formato in FORMATOS_FECHA:
            try:
                return datetime.datetime.strptime(crudo, formato).date()
            except ValueError:
                continue
        raise ValueError(f"fecha «{crudo}» no reconocida (usa dd/mm/aaaa)")

    def _orden(self, crudo):
        numero = str(crudo or '').replace('#', '').strip()
        if not numero.isdigit():
            raise ValueError(f"orden «{crudo}» no es un número")
        orden = OrdenServicio.objects.filter(pk=int(numero)).first()
        if orden is None:
            raise ValueError(f"la orden #{numero} no existe en el sistema")
        return orden

    def _vehiculo(self, crudo):
        fragmento = _limpiar(crudo).replace(' ', '')
        if not fragmento:
            raise ValueError("falta la placa")
        candidatos = [v for v in self._placas
                      if fragmento in _limpiar(v.placa).replace(' ', '')]
        if not candidatos:
            raise ValueError(f"ninguna placa contiene «{crudo}»")
        if len(candidatos) > 1:
            placas = ', '.join(v.placa for v in candidatos)
            raise ValueError(f"«{crudo}» coincide con varias placas: {placas}")
        return candidatos[0]

    # Cómo se nombra cada rol en los mensajes (en singular).
    SINGULAR = {'Conductores': 'conductor', 'Ayudantes': 'ayudante'}

    def _persona(self, crudo, rol):
        """
        Encuentra a la persona por un fragmento de su nombre, DENTRO de su rol.
        Si no aparece, el error dice por qué: casi siempre está con otro rol,
        retirada, o escrita distinto — y con eso se corrige el archivo sin
        tener que ir a buscar a la base.
        """
        singular = self.SINGULAR.get(rol, rol.lower())
        fragmento = _limpiar(crudo)
        if not fragmento:
            raise ValueError(f"falta el {singular}")

        def coincide(personas):
            return [u for u in personas
                    if fragmento in _limpiar(f"{u.first_name} {u.last_name}")]

        candidatos = coincide(self._personal[rol])
        if len(candidatos) == 1:
            return candidatos[0]
        if len(candidatos) > 1:
            nombres = ', '.join(u.get_full_name() or u.username for u in candidatos)
            raise ValueError(
                f"«{crudo}» coincide con varios {rol.lower()}: {nombres}. "
                f"Escribe el nombre completo en el archivo.")

        # No está entre los de ese rol. Se busca en TODA la gente: en el
        # histórico pasa —un ayudante que ese día llevó el camión, alguien que
        # ya se retiró— así que se acepta, pero AVISANDO, para que quien
        # importa lo vea en la vista previa antes de confirmar.
        otros = coincide(self._todos)
        if len(otros) == 1:
            persona = otros[0]
            roles = ', '.join(persona.groups.values_list('name', flat=True)) or 'sin rol'
            retirado = ', retirado' if getattr(
                getattr(persona, 'perfil', None), 'retirado', False) else ''
            self._avisos_fila.append(
                f"«{crudo}» va como {singular}, pero está registrado como "
                f"{roles}{retirado}: se asignó a "
                f"{persona.get_full_name() or persona.username}")
            return persona
        if len(otros) > 1:
            nombres = ', '.join(u.get_full_name() or u.username for u in otros)
            raise ValueError(
                f"«{crudo}» no está entre los {rol.lower()} y coincide con "
                f"varias personas: {nombres}. Escribe el nombre completo.")

        disponibles = ', '.join(sorted(
            (u.first_name or u.username).split(' ')[0] for u in self._personal[rol]))
        raise ValueError(
            f"«{crudo}» no está registrado como {singular}. "
            f"Hay estos: {disponibles or 'ninguno'}")

    def _leer(self, ruta):
        try:
            with open(ruta, encoding='utf-8-sig', newline='') as f:
                filas = list(csv.DictReader(f))
        except FileNotFoundError:
            raise CommandError(f"No existe el archivo «{ruta}».")
        if not filas:
            raise CommandError("El archivo no tiene filas.")
        columnas = {_limpiar(c) for c in filas[0]}
        faltan = {'FECHA', 'VEHICULO', 'ORDEN', 'CONDUCTOR'} - columnas
        if faltan:
            raise CommandError(
                f"Al CSV le faltan columnas: {', '.join(sorted(faltan))}. "
                f"Trae: {', '.join(sorted(columnas))}.")
        return filas

    @staticmethod
    def _campo(fila, nombre):
        for clave, valor in fila.items():
            if _limpiar(clave) == nombre:
                return valor
        return ''

    # ---------- el comando ----------

    def handle(self, *args, **opciones):
        filas = self._leer(opciones['archivo'])

        # Se cargan una vez: las listas son cortas y así no se consulta por fila.
        self._placas = list(Vehiculo.objects.all())
        self._personal = {}
        for rol in ('Conductores', 'Ayudantes'):
            grupo = Group.objects.filter(name=rol).first()
            self._personal[rol] = list(
                grupo.user_set.exclude(perfil__retirado=True) if grupo else [])
        # Todo el personal (incluidos retirados y otros roles): solo se usa
        # para explicar por qué un nombre no resolvió.
        self._todos = list(User.objects.exclude(is_superuser=True)
                           .select_related('perfil').prefetch_related('groups'))

        autor = None
        if opciones['usuario']:
            autor = User.objects.filter(username=opciones['usuario']).first()
            if autor is None:
                raise CommandError(f"No existe el usuario «{opciones['usuario']}».")

        listas, errores, avisos = [], [], []
        for numero, fila in enumerate(filas, start=2):   # 1 es la cabecera
            self._avisos_fila = []
            try:
                datos = {
                    'fecha': self._fecha(self._campo(fila, 'FECHA')),
                    'orden': self._orden(self._campo(fila, 'ORDEN')),
                    'vehiculo': self._vehiculo(self._campo(fila, 'VEHICULO')),
                    'conductor': self._persona(self._campo(fila, 'CONDUCTOR'), 'Conductores'),
                }
                ayudante_crudo = self._campo(fila, 'AYUDANTE')
                datos['ayudante'] = (
                    None if _limpiar(ayudante_crudo) in SIN_AYUDANTE
                    else self._persona(ayudante_crudo, 'Ayudantes'))
            except ValueError as e:
                errores.append(f"fila {numero}: {e}")
                continue

            avisos.extend(f"fila {numero}: {a}" for a in self._avisos_fila)

            # El cliente no se guarda: sirve para cazar una orden mal escrita.
            cliente = _limpiar(self._campo(fila, 'CLIENTE'))
            if cliente and cliente not in _limpiar(datos['orden'].cliente.nombre):
                avisos.append(
                    f"fila {numero}: el CSV dice «{cliente}» pero la orden "
                    f"#{datos['orden'].pk} es de «{datos['orden'].cliente.nombre}»")

            datos['fila'] = numero
            listas.append(datos)

        if opciones['deshacer']:
            return self._deshacer(listas, errores, opciones['confirmar'])

        self._informar(listas, errores, avisos)

        if errores and not opciones['omitir_errores']:
            raise CommandError(
                f"{len(errores)} fila(s) sin resolver: no se escribió nada. "
                f"Corrige el archivo, o repite con --omitir-errores para "
                f"importar solo las que sí resolvieron.")
        if not listas:
            self.stdout.write(self.style.WARNING("No hay nada que importar."))
            return
        if not opciones['confirmar']:
            self.stdout.write(self.style.WARNING(
                "\nVista previa: no se escribió nada. Repite con --confirmar."))
            return

        creadas, repetidas = self._importar(listas, autor)
        self.stdout.write(self.style.SUCCESS(
            f"\nListo: {creadas} disposición(es) registrada(s) en el plan."
            + (f" {repetidas} ya estaban y se dejaron como estaban." if repetidas else "")))
        self._estado_actual(listas)

    # ---------- deshacer ----------

    def _deshacer(self, listas, errores, confirmar):
        """
        Quita lo que esta importación dejó: las asignaciones que llevan su
        marca, los movimientos de carga que creó y los planes del día que
        queden vacíos. Nada más: lo que alguien haya registrado a mano en esos
        días se queda donde está.
        """
        from gestion.models import MovimientoCargaVehiculo

        ordenes = {d['orden'].pk for d in listas}
        fechas = {d['fecha'] for d in listas}
        if errores:
            self.stdout.write(self.style.WARNING(
                f"{len(errores)} fila(s) del archivo no se pudieron leer; se "
                f"revierte lo que corresponde a las demás."))
        if not ordenes:
            raise CommandError("Ninguna fila del archivo resolvió: no hay qué deshacer.")

        asignaciones = Asignacion.objects.filter(
            tipo='DISPOSICION_FINAL', detalle=MARCA,
            orden_id__in=ordenes, plan__fecha__in=fechas
        ).select_related('persona', 'orden', 'plan')
        movimientos = MovimientoCargaVehiculo.objects.filter(
            accion='DESCARGA', orden_id__in=ordenes,
            nota__icontains=MARCA.lower()
        ).select_related('vehiculo', 'orden')

        self.stdout.write(self.style.MIGRATE_HEADING("\nSe va a quitar del plan:"))
        for a in asignaciones:
            self.stdout.write(
                f"  {a.plan.fecha:%d/%m/%Y}  Orden #{a.orden_id:<6} "
                f"{a.persona_nombre}")
        self.stdout.write(
            f"  → {asignaciones.count()} asignación(es) y "
            f"{movimientos.count()} movimiento(s) de carga")

        if not asignaciones.exists() and not movimientos.exists():
            self.stdout.write(self.style.WARNING(
                "No hay nada de esta importación en la base."))
            return
        if not confirmar:
            self.stdout.write(self.style.WARNING(
                "\nVista previa: no se borró nada. Repite con --confirmar."))
            return

        with transaction.atomic():
            quitadas = asignaciones.count()
            borrados = movimientos.count()
            asignaciones.delete()
            movimientos.delete()
            # Los planes del día que quedaron sin nada (ni asignaciones ni
            # observaciones) los creó esta importación: se van con ella.
            vacios = [p for p in PlanDia.objects.filter(fecha__in=fechas)
                      if not p.asignaciones.exists() and not p.notas.strip()]
            for plan in vacios:
                plan.delete()

        self.stdout.write(self.style.SUCCESS(
            f"\nListo: se quitaron {quitadas} asignación(es), {borrados} "
            f"movimiento(s) y {len(vacios)} plan(es) de día que quedaron vacíos."))

    # ---------- salida ----------

    def _informar(self, listas, errores, avisos):
        self.stdout.write(self.style.MIGRATE_HEADING(
            f"\nDisposiciones a registrar en el plan ({len(listas)}):"))
        for d in listas:
            ayudante = (d['ayudante'].get_full_name() or d['ayudante'].username
                        if d['ayudante'] else '— va solo —')
            self.stdout.write(
                f"  {d['fecha']:%d/%m/%Y}  Orden #{d['orden'].pk:<6} "
                f"{d['vehiculo'].placa:<8} "
                f"{d['conductor'].get_full_name() or d['conductor'].username:<18} "
                f"{ayudante}")
        for aviso in avisos:
            self.stdout.write(self.style.WARNING(f"  OJO  {aviso}"))
        for error in errores:
            self.stdout.write(self.style.ERROR(f"  ✗    {error}"))

    def _estado_actual(self, listas):
        """
        El histórico no decide la foto de hoy: si un camión sigue marcado como
        cargado, hay que resolverlo desde el plan (es la única vía).
        """
        placas = {d['vehiculo'].pk: d['vehiculo'] for d in listas}
        cargados = [v for v in Vehiculo.objects.filter(pk__in=placas) if v.cargado]
        if not cargados:
            return
        self.stdout.write(self.style.WARNING(
            "\nOJO: el estado de carga de HOY no se tocó. Siguen marcados como cargados:"))
        for v in cargados:
            self.stdout.write(f"  · {v.placa} — {v.cargado_detalle or 'sin detalle'}")
        self.stdout.write(
            "  Si esas disposiciones ya se hicieron, asígnalas en el plan de trabajo.")

    # ---------- escritura ----------

    @transaction.atomic
    def _importar(self, listas, autor):
        creadas = repetidas = 0
        for d in listas:
            plan, _ = PlanDia.objects.get_or_create(
                fecha=d['fecha'], defaults={'creado_por': autor})

            personas = [d['conductor']] + ([d['ayudante']] if d['ayudante'] else [])
            nuevas = []
            for persona in personas:
                # Idempotente: correr el comando dos veces no duplica el plan.
                ya_esta = Asignacion.objects.filter(
                    plan=plan, persona=persona, tipo='DISPOSICION_FINAL',
                    orden=d['orden']).exists()
                if ya_esta:
                    repetidas += 1
                    continue
                asignacion = Asignacion.objects.create(
                    plan=plan, persona=persona, tipo='DISPOSICION_FINAL',
                    orden=d['orden'], registrado_por=autor,
                    detalle=MARCA)
                asignacion.vehiculos.set([d['vehiculo']])
                nuevas.append(asignacion)
                creadas += 1

            if nuevas:
                self._movimiento(d, personas, autor)
        return creadas, repetidas

    def _movimiento(self, d, personas, autor):
        """
        El movimiento de carga del camión, fechado el día en que de verdad se
        dispuso. `fecha` es auto_now_add, así que se corrige con un UPDATE
        (mismo truco que `mover_orden` con fecha_creacion).
        """
        nombres = ', '.join(p.get_full_name() or p.username for p in personas)
        movimiento = MovimientoCargaVehiculo.objects.create(
            vehiculo=d['vehiculo'], accion='DESCARGA', orden=d['orden'],
            registrado_por=autor,
            nota=(f"Plan del {d['fecha']:%d/%m/%Y}: dispuesto por {nombres} "
                  f"· {MARCA.lower()}")[:255],
        )
        momento = timezone.make_aware(
            datetime.datetime.combine(d['fecha'], datetime.time(12, 0)),
            timezone.get_current_timezone())
        MovimientoCargaVehiculo.objects.filter(pk=movimiento.pk).update(fecha=momento)
