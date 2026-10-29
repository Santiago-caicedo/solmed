"""
Plan de trabajo diario.

Réplica del formato físico de SOLMED: cada día se reparte a TODO el personal
(quién hace qué, con cuál placa) y se registran las novedades de recursos
humanos (incapacidades, licencias, permisos...). El plan de un día se compone
de tres fuentes:

  1. Los SERVICIOS ya programados (Recorrido de ese día): entran solos al
     tablero y al PDF, no se digitan de nuevo.
  2. Las ASIGNACIONES del plan (este módulo): tecnomecánica, lavada,
     mantenimientos, disposiciones, apoyos...
  3. Las NOVEDADES vigentes ese día (pueden abarcar un rango de fechas:
     unas vacaciones se registran una vez y aparecen todos sus días).

El PDF del día se genera al descargarlo (no se guarda): es un reporte interno
derivado de datos, igual que la encuesta de cierre.
"""
import datetime
import uuid

from django.conf import settings
from django.db import models
from django.utils import timezone

from gestion.models import (Dispositor, OrdenServicio, ProgramacionCuadrilla,
                            Proveedor, Vehiculo)


def horario(inicio, fin):
    """Las horas de una actividad o novedad como se leen en el plan."""
    if not inicio:
        return ''
    if fin:
        return f"{inicio:%H:%M}–{fin:%H:%M}"
    return f"{inicio:%H:%M}"


class TipoPersonalizado(models.Model):
    """
    Una actividad o una novedad que no está en el formato y que el
    administrador creó desde el popup del plan (oct-2026). Se elige en el
    mismo desplegable que las del formato; la asignación o la novedad la
    guarda con tipo 'PERSONALIZADA' y este enlace. Si ya se usó, no se borra:
    se oculta del desplegable y lo registrado conserva su nombre.
    """
    AMBITO_CHOICES = [('ACTIVIDAD', 'Actividad'), ('NOVEDAD', 'Novedad')]

    ambito = models.CharField(max_length=10, choices=AMBITO_CHOICES)
    nombre = models.CharField(max_length=100)
    # Solo para novedades: ¿sus horas son tiempo trabajado (como el trabajo en
    # bodega) o una ausencia (como un permiso)? Lo dice quien la crea.
    es_trabajo = models.BooleanField(default=False,
                                     verbose_name="Cuenta como tiempo trabajado")
    activo = models.BooleanField(default=True)
    creado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='tipos_plan_creados',
    )
    creado_en = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['nombre']
        verbose_name = "Actividad o novedad creada en el plan"
        verbose_name_plural = "Actividades y novedades creadas en el plan"

    def __str__(self):
        return self.nombre

    @property
    def valor(self):
        """Cómo viaja en el desplegable, al lado de los códigos del formato."""
        return f"P:{self.pk}"


def tipo_personalizado_de(valor, ambito):
    """El TipoPersonalizado activo que nombra un valor «P:<id>», o None."""
    valor = str(valor or '')
    if not valor.startswith('P:') or not valor[2:].isdigit():
        return None
    return TipoPersonalizado.objects.filter(
        pk=int(valor[2:]), ambito=ambito, activo=True).first()


class PlanDia(models.Model):
    """El plan de UN día. Se crea solo al registrar la primera asignación."""
    fecha = models.DateField(unique=True)
    notas = models.TextField(
        blank=True, verbose_name="Observaciones del día",
        help_text="Lo que el equipo deba tener presente (van al PDF).",
    )
    creado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True,
        related_name='planes_creados',
    )
    fecha_creacion = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-fecha']
        verbose_name = "Plan de trabajo (día)"
        verbose_name_plural = "Planes de trabajo (días)"

    def __str__(self):
        return f"Plan de trabajo del {self.fecha:%d/%m/%Y}"


class Asignacion(models.Model):
    """
    Una fila del plan: UNA persona con UNA actividad del catálogo del formato.
    Los campos extra (placas, orden, proveedor) aplican según la
    actividad — CAMPOS_POR_TIPO dice cuáles pide cada una y la vista los
    valida y los muestra/oculta.
    """
    TIPO_CHOICES = [
        ('TECNOMECANICA', 'Tecnomecánica'),
        ('LAVADA', 'Lavada de vehículo'),
        ('MANT_EXTERNO', 'Mantenimiento externo'),
        ('MANT_INTERNO', 'Mantenimiento interno'),
        ('VISITA_TECNICA', 'Visita técnica'),
        ('COMPRA_REPUESTOS', 'Compra de repuestos'),
        ('MONTALLANTAS', 'Servicio de montallantas'),
        ('TRASTEO', 'Trasteo'),
        ('DISPOSICION_FINAL', 'Disposición final'),
        ('DISPOSICION_SOLMED', 'Disposición de Solmed SAS'),
        ('ACOMPANAMIENTO', 'Acompañamiento'),
        ('RECOGER_VEHICULO', 'Recoger vehículo'),
        ('DESTRUCCION_CANECAS', 'Destrucción, separación y alistamiento de canecas'),
        ('APOYO_SERVICIO', 'Apoyo a servicio'),
        ('APOYO_DISPOSICION', 'Apoyo a disposición'),
        ('OTRA', 'Otra actividad'),
        # Las que se crean en el popup: el nombre está en tipo_personalizado.
        ('PERSONALIZADA', 'Actividad creada en el plan'),
    ]

    # Qué campos pide cada actividad (el formato físico los trae por fila):
    #   vehiculos: 'uno' | 'varios' | 'cargados' | None — si lleva placa(s).
    #              'cargados' = SOLO camiones con residuo pendiente: asignar la
    #              actividad los DESCARGA (es la única vía para hacerlo) y la
    #              orden sale de la carga, no se digita.
    #   orden:     lleva el número de la orden de servicio (se digita).
    #   proveedor: lleva el proveedor externo (con opción de crearlo).
    #   dispositor:lleva el gestor donde se dispuso (opcional).
    #   detalle:   True = el detalle es OBLIGATORIO (acompañamiento / otra).
    CAMPOS_POR_TIPO = {
        'TECNOMECANICA':       {'vehiculos': 'uno'},
        'LAVADA':              {'vehiculos': 'uno'},
        'MANT_EXTERNO':        {'vehiculos': 'uno', 'proveedor': True},
        'MANT_INTERNO':        {'vehiculos': 'uno'},
        'VISITA_TECNICA':      {'vehiculos': 'uno'},
        'COMPRA_REPUESTOS':    {'vehiculos': 'varios'},
        'MONTALLANTAS':        {'vehiculos': 'varios'},
        'TRASTEO':             {},
        'DISPOSICION_FINAL':   {'ordenes': 'pendientes', 'dispositor': True},
        'DISPOSICION_SOLMED':  {},
        'ACOMPANAMIENTO':      {'detalle': True},
        'RECOGER_VEHICULO':    {'vehiculos': 'uno'},
        'DESTRUCCION_CANECAS': {},
        'APOYO_SERVICIO':      {'vehiculos': 'uno'},
        'APOYO_DISPOSICION':   {'vehiculos': 'uno'},
        'OTRA':                {'detalle': True},
        'PERSONALIZADA':       {},
    }

    plan = models.ForeignKey(PlanDia, on_delete=models.CASCADE,
                             related_name='asignaciones')
    persona = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
        related_name='asignaciones_plan',
    )
    tipo = models.CharField(max_length=25, choices=TIPO_CHOICES)
    tipo_personalizado = models.ForeignKey(
        TipoPersonalizado, on_delete=models.PROTECT, null=True, blank=True,
        related_name='asignaciones', verbose_name="Actividad creada en el plan",
    )
    vehiculos = models.ManyToManyField(
        Vehiculo, blank=True, related_name='asignaciones_plan',
        verbose_name="Placa(s)",
    )
    # La orden de la disposición final. PROTECT: renumerar órdenes las mueve
    # con sus hijos (gestion/renumeracion.py recorre related_objects).
    orden = models.ForeignKey(
        OrdenServicio, on_delete=models.PROTECT, null=True, blank=True,
        related_name='asignaciones_plan', verbose_name="Orden de servicio",
    )
    proveedor = models.ForeignKey(
        Proveedor, on_delete=models.PROTECT, null=True, blank=True,
        related_name='asignaciones_plan', verbose_name="Proveedor externo",
    )
    # A dónde se llevó el residuo (disposición final). Es el gestor autorizado,
    # no el proveedor de bienes y servicios: son catálogos distintos.
    dispositor = models.ForeignKey(
        Dispositor, on_delete=models.PROTECT, null=True, blank=True,
        related_name='asignaciones_plan', verbose_name="Gestor de disposición",
    )
    # Toda actividad lleva su hora de inicio y final (opcionales): son la base
    # de las horas trabajadas del centro de control del empleado.
    hora = models.TimeField(null=True, blank=True)
    hora_fin = models.TimeField(null=True, blank=True,
                                verbose_name="Hora de finalización")
    # Como en las novedades (oct-2026): solo con esta casilla las horas de la
    # actividad suman en las horas trabajadas del centro de control. Exige
    # las dos horas (ver AsignacionForm).
    suma_horas = models.BooleanField(
        default=False,
        verbose_name="Sumar estas horas al historial de horas trabajadas")
    detalle = models.CharField(max_length=255, blank=True, verbose_name="Descripción")
    registrado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True,
        related_name='asignaciones_registradas',
    )
    # Las DISPOSICIONES de orden que esta actividad registró (una por orden).
    # Con ellas se sabe qué órdenes dispuso este viaje y se puede deshacer si
    # la actividad se quita del plan.
    disposiciones = models.ManyToManyField(
        'gestion.DisposicionOrden', blank=True,
        related_name='asignaciones_plan', verbose_name="Disposiciones registradas",
    )
    # El viaje de disposición AGENDADO del que sale esta actividad (oct-2026):
    # una por persona del viaje. Mientras esté agendado no dispone nada.
    viaje = models.ForeignKey(
        'ViajeDisposicion', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='asignaciones')
    fecha_registro = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['id']
        verbose_name = "Asignación del plan"
        verbose_name_plural = "Asignaciones del plan"

    def __str__(self):
        return f"{self.get_tipo_display()} — {self.persona_nombre} ({self.plan.fecha:%d/%m/%Y})"

    def get_tipo_display(self):
        """El nombre de la actividad o novedad, también si se creó en el plan."""
        if self.tipo == 'PERSONALIZADA' and self.tipo_personalizado_id:
            return self.tipo_personalizado.nombre
        return dict(self._meta.get_field('tipo').flatchoices).get(self.tipo, self.tipo)

    @property
    def horario(self):
        """«08:00–10:30», «08:00» o vacío: la hora final es opcional."""
        return horario(self.hora, self.hora_fin)

    @property
    def persona_nombre(self):
        return self.persona.get_full_name() or self.persona.username

    @property
    def placas(self):
        """'WHB123, ABC987' para el tablero y el PDF."""
        return ', '.join(v.placa for v in self.vehiculos.all())

    @property
    def campos(self):
        return self.CAMPOS_POR_TIPO.get(self.tipo, {})

    @property
    def ordenes_dispuestas(self):
        """
        Los números de orden que esta disposición dejó dispuestas, para
        mostrarlos ("#22207, #22211"). Si no hay disposiciones enlazadas, cae
        a la orden suelta de la asignación (las demás actividades).
        """
        numeros = sorted({d.orden_id for d in self.disposiciones.all()})
        if numeros:
            return numeros
        # Un viaje agendado aún no dispone: se muestran las órdenes que lleva.
        if self.viaje_id:
            return sorted(o.pk for o in self.viaje.ordenes.all())
        return [self.orden_id] if self.orden_id else []

    @property
    def ordenes_texto(self):
        return ', '.join(f"#{n}" for n in self.ordenes_dispuestas)

    @property
    def dispone_ordenes(self):
        """¿Esta actividad es la que dispone el residuo de unas órdenes?"""
        return self.campos.get('ordenes') == 'pendientes'

    def aplicar_disposicion(self, personas, ordenes):
        """
        Deja DISPUESTAS las órdenes elegidas porque el plan asignó su
        disposición: es la vía normal para disponer (el residuo siempre sale
        del sistema con un responsable y una fecha). Cada orden recibe SU
        registro, enlazado a esta actividad para poder deshacerlo.
        """
        quien = f"dispuesto por {', '.join(personas)}"
        for orden in ordenes:
            nota = f"Plan del {self.plan.fecha:%d/%m/%Y}: {quien}"
            if self.detalle:
                nota += f" · {self.detalle}"
            registro = orden.registrar_disposicion(
                via='PLAN', fecha=self.plan.fecha, usuario=self.registrado_por,
                dispositor=self.dispositor, nota=nota)
            self.disposiciones.add(registro)

    def deshacer_disposicion(self):
        """
        Quitar la actividad deja SUS órdenes otra vez sin disponer: si la
        disposición no se hizo, el residuo sigue pendiente. El historial no se
        borra: cada registro queda marcado como deshecho con la razón.
        """
        nota = (f"Se quitó del plan del {self.plan.fecha:%d/%m/%Y} la "
                f"disposición asignada a {self.persona_nombre}")
        for registro in self.disposiciones.select_related('orden'):
            if not registro.deshecha:
                registro.orden.deshacer_disposicion(usuario=self.registrado_por, nota=nota)


class Novedad(models.Model):
    """
    Novedad de una persona en el plan de trabajo (sección 2 del formato).
    Vive por RANGO de fechas: unas vacaciones o una incapacidad se registran
    UNA vez y aparecen en el plan de cada día que cubran. Sin fecha final =
    solo el día de inicio (una cita médica, un permiso).
    """
    TIPO_CHOICES = [
        ('Ausencias y salud', (
            ('AUSENCIA', 'Ausencia'),
            ('CALAMIDAD', 'Calamidad doméstica'),
            ('EXAMEN_MEDICO', 'Examen médico (ingreso · periódico · anual)'),
            ('INCAPACIDAD_EPS', 'Incapacidad EPS'),
            ('INCAPACIDAD_ARL', 'Incapacidad ARL'),
        )),
        ('Licencias', (
            ('LIC_MATERNIDAD', 'Licencia de maternidad'),
            ('LIC_PATERNIDAD', 'Licencia de paternidad'),
            ('LIC_LUTO', 'Licencia por luto'),
            ('LIC_ADOPCION', 'Licencia por adopción'),
            ('LIC_REMUNERADA', 'Licencia remunerada'),
            ('LIC_NO_REMUNERADA', 'Licencia no remunerada'),
        )),
        ('Permisos', (
            ('PERMISO_ESPECIALISTA', 'Permiso: cita con especialista'),
            ('PERMISO_CITA_MEDICA', 'Permiso: cita médica / terapia'),
            ('PERMISO_PERSONAL', 'Permiso personal'),
            ('PERMISO_EXEQUIAL', 'Permiso exequial'),
            ('PERMISO_ESCOLAR', 'Permiso escolar'),
            ('PERMISO_VOTACION', 'Permiso para votar'),
            ('JURADO_VOTACION', 'Jurado de votación'),
            ('CITACION_JUDICIAL', 'Citación judicial'),
        )),
        ('Trabajo interno', (
            ('TRABAJO_BODEGA', 'Trabajo en bodega'),
            ('TRABAJO_OFICINA', 'Trabajo en oficina'),
        )),
        ('Situaciones laborales', (
            ('DESCANSO', 'Descanso'),
            ('COMPENSATORIO', 'Compensatorio'),
            ('VACACIONES', 'Vacaciones'),
            ('INGRESO_NUEVO', 'Ingreso de trabajador nuevo'),
            ('DESCARGOS', 'Citado a descargos'),
            ('RENUNCIA', 'Renuncia'),
            ('DESPIDO', 'Despido'),
        )),
        # Las que se crean en el popup: el nombre está en tipo_personalizado.
        ('Creadas en el plan', (
            ('PERSONALIZADA', 'Novedad creada en el plan'),
        )),
    ]
    # Las novedades que por su tipo SUELEN ser trabajo: en el popup dejan
    # marcada de entrada la casilla «Sumar estas horas…». Lo que manda es la
    # casilla (suma_horas), no el tipo (pedido de Santiago, oct-2026).
    TIPOS_TRABAJO = ('TRABAJO_BODEGA', 'TRABAJO_OFICINA')

    @property
    def es_trabajo(self):
        """¿Sus horas son tiempo trabajado? Lo dice la casilla al registrarla."""
        return self.suma_horas

    persona = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
        related_name='novedades_plan',
    )
    tipo = models.CharField(max_length=25, choices=TIPO_CHOICES)
    tipo_personalizado = models.ForeignKey(
        TipoPersonalizado, on_delete=models.PROTECT, null=True, blank=True,
        related_name='novedades', verbose_name="Novedad creada en el plan",
    )
    fecha_inicio = models.DateField(verbose_name="Fecha de inicio")
    fecha_fin = models.DateField(
        null=True, blank=True, verbose_name="Fecha final",
        help_text="Vacía = la novedad es solo del día de inicio.",
    )
    hora = models.TimeField(null=True, blank=True,
                            help_text="Para permisos de unas horas.")
    hora_fin = models.TimeField(null=True, blank=True,
                                verbose_name="Hora de finalización")
    # Solo las novedades con esta casilla suman en las horas trabajadas del
    # centro de control (base de la nómina): una calamidad con horas no es
    # trabajo; un día en bodega sí. Exige las dos horas (ver NovedadForm).
    suma_horas = models.BooleanField(
        default=False,
        verbose_name="Sumar estas horas al historial de horas trabajadas")
    detalle = models.CharField(max_length=255, blank=True, verbose_name="Detalle")
    registrado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True,
        related_name='novedades_registradas',
    )
    fecha_registro = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-fecha_inicio', '-id']
        verbose_name = "Novedad del plan de trabajo"
        verbose_name_plural = "Novedades del plan de trabajo"

    def __str__(self):
        return f"{self.get_tipo_display()} — {self.persona_nombre}"

    def get_tipo_display(self):
        """El nombre de la actividad o novedad, también si se creó en el plan."""
        if self.tipo == 'PERSONALIZADA' and self.tipo_personalizado_id:
            return self.tipo_personalizado.nombre
        return dict(self._meta.get_field('tipo').flatchoices).get(self.tipo, self.tipo)

    @property
    def horario(self):
        """«08:00–10:30», «08:00» o vacío: la hora final es opcional."""
        return horario(self.hora, self.hora_fin)

    @property
    def persona_nombre(self):
        return self.persona.get_full_name() or self.persona.username

    @classmethod
    def del_dia(cls, fecha):
        """Las novedades vigentes en esa fecha (rango o día único)."""
        return cls.objects.filter(
            models.Q(fecha_inicio=fecha, fecha_fin__isnull=True)
            | models.Q(fecha_inicio__lte=fecha, fecha_fin__gte=fecha)
        ).select_related('persona', 'tipo_personalizado')


class DescuentoHoras(models.Model):
    """
    Tiempo que se le resta a UNA actividad o UNA novedad del plan al liquidar
    las horas trabajadas (oct-2026): un almuerzo, una pausa… Pueden ser
    varios por registro, cada uno con su motivo. Es la misma idea del
    descuento del servicio en «Corregir datos» (Recorrido.descuento_*), pero
    aquí viven aparte porque son varios. En una novedad de varios días el
    descuento es de CADA día, como sus horas.
    """
    asignacion = models.ForeignKey(
        Asignacion, on_delete=models.CASCADE, null=True, blank=True,
        related_name='descuentos')
    novedad = models.ForeignKey(
        Novedad, on_delete=models.CASCADE, null=True, blank=True,
        related_name='descuentos')
    minutos = models.PositiveSmallIntegerField()
    motivo = models.CharField(max_length=120)

    class Meta:
        ordering = ['id']
        verbose_name = "Descuento de horas del plan"
        verbose_name_plural = "Descuentos de horas del plan"
        constraints = [
            models.CheckConstraint(
                condition=(models.Q(asignacion__isnull=False, novedad__isnull=True)
                           | models.Q(asignacion__isnull=True, novedad__isnull=False)),
                name='descuento_de_una_actividad_o_una_novedad'),
        ]

    def __str__(self):
        return f"−{self.minutos} min · {self.motivo}"


# ============================================================
#  VIAJES DE DISPOSICIÓN AGENDADOS (oct-2026, pedido de Santiago)
# ============================================================
class ViajeDisposicion(models.Model):
    """
    Un viaje de disposición AGENDADO desde el panel de Disposiciones para un
    día que todavía no llega (o para más tarde hoy). A diferencia de registrar
    uno ya hecho, agendarlo NO dispone las órdenes: quedan pendientes y
    marcadas como agendadas hasta que la oficina CONFIRMA que se hizo (con
    las horas reales y los descuentos de cada uno) o lo cancela.

    Al agendarlo se crean las actividades «Disposición final» del plan de
    ese día (una por persona, con `viaje`), así sale en el plan; al personal
    le llega el correo: el CONDUCTOR lo ve en su portal ese día y hace el
    preoperacional del vehículo; cada AYUDANTE, con sus novedades, sus
    fotos y su enlace personal, igual que en la programación de una orden.
    """
    ESTADO_CHOICES = [
        ('AGENDADA', 'Agendada'),
        ('REALIZADA', 'Realizada'),
        ('CANCELADA', 'Cancelada'),
    ]

    fecha = models.DateField(verbose_name="Día del viaje")
    hora = models.TimeField(null=True, blank=True, verbose_name="Hora programada")
    # Obligatorio al agendar: el preoperacional depende del tipo de vehículo.
    vehiculo = models.ForeignKey(
        Vehiculo, on_delete=models.PROTECT, related_name='viajes_disposicion',
        verbose_name="Vehículo del viaje")
    dispositor = models.ForeignKey(
        Dispositor, on_delete=models.PROTECT, null=True, blank=True,
        related_name='viajes_disposicion', verbose_name="Gestor de disposición")
    ordenes = models.ManyToManyField(
        OrdenServicio, related_name='viajes_disposicion', verbose_name="Órdenes")
    detalle = models.CharField(max_length=255, blank=True, verbose_name="Nota para el plan")
    estado = models.CharField(max_length=10, choices=ESTADO_CHOICES, default='AGENDADA')
    creado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True,
        related_name='viajes_disposicion_creados')
    creado_en = models.DateTimeField(auto_now_add=True)
    # Quién confirmó que se hizo o lo canceló, y cuándo.
    cerrado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True,
        related_name='viajes_disposicion_cerrados')
    cerrado_en = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['fecha', 'hora', 'id']
        verbose_name = "Viaje de disposición agendado"
        verbose_name_plural = "Viajes de disposición agendados"

    def __str__(self):
        return f"Disposición del {self.fecha:%d/%m/%Y} ({self.vehiculo.placa})"

    # El correo y el enlace del ayudante leen esto como si fuera la
    # programación de un servicio (gestion/correo_programacion.html).
    @property
    def observaciones_servicio(self):
        return self.detalle

    @property
    def agendada(self):
        return self.estado == 'AGENDADA'

    def personas(self):
        """Quiénes van, en el orden en que se asignaron."""
        return [a.persona for a in self.asignaciones.select_related('persona').order_by('id')]

    def conductores(self):
        """Las personas del viaje con rol de conductor: lo ven en su portal."""
        return [p for p in self.personas() if p.groups.filter(name='Conductores').exists()]

    def numeros_ordenes(self):
        return ', '.join(f"#{o.pk}" for o in self.ordenes.order_by('pk'))


class AyudanteViaje(models.Model):
    """
    Un AYUDANTE de un viaje agendado (oct-2026): las mismas novedades que se
    le marcan en la programación de una orden (ProgramacionCuadrilla), su
    observación, el vehículo del que apoya la disposición y su enlace
    personal (token, sin usuario) para ver el viaje y subir las fotos que le
    pidan sus novedades.
    """
    NOVEDAD_CHOICES = ProgramacionCuadrilla.NOVEDAD_CHOICES
    NOVEDADES_CON_FOTO = ProgramacionCuadrilla.NOVEDADES_CON_FOTO
    APOYA_DISPOSICION = ProgramacionCuadrilla.APOYA_DISPOSICION
    DIAS_VIGENCIA_ACCESO = ProgramacionCuadrilla.DIAS_VIGENCIA_ACCESO

    viaje = models.ForeignKey(ViajeDisposicion, on_delete=models.CASCADE,
                              related_name='ayudantes')
    persona = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
                                related_name='viajes_como_ayudante')
    # Selección múltiple, como en la cuadrilla: códigos separados por coma.
    novedades = models.CharField(max_length=200, blank=True, default='')
    observacion = models.TextField(blank=True, verbose_name="Observaciones para el ayudante")
    apoya_vehiculo = models.ForeignKey(
        Vehiculo, on_delete=models.PROTECT, null=True, blank=True,
        related_name='viajes_apoyo_ayudante', verbose_name="Apoya disposición del vehículo")
    token = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)

    class Meta:
        ordering = ['id']
        verbose_name = "Ayudante de un viaje de disposición"
        verbose_name_plural = "Ayudantes de viajes de disposición"
        constraints = [
            models.UniqueConstraint(fields=['viaje', 'persona'], name='ayudante_una_vez_por_viaje'),
        ]

    def __str__(self):
        return f"{self.persona_nombre} — {self.viaje}"

    @property
    def persona_nombre(self):
        return self.persona.get_full_name() or self.persona.username

    def codigos(self):
        return [c for c in (self.novedades or '').split(',') if c]

    def novedades_display(self):
        etiquetas = dict(self.NOVEDAD_CHOICES)
        textos = []
        for c in self.codigos():
            texto = etiquetas.get(c, c)
            if c == self.APOYA_DISPOSICION and self.apoya_vehiculo_id:
                texto = f"{texto} {self.apoya_vehiculo.placa}"
            textos.append(texto)
        return textos

    def fotos_pedidas(self):
        """Novedades que le exigen foto: [{'codigo', 'etiqueta'}]."""
        etiquetas = dict(self.NOVEDAD_CHOICES)
        return [{'codigo': c, 'etiqueta': etiquetas.get(c, c)}
                for c in self.codigos() if c in self.NOVEDADES_CON_FOTO]

    @property
    def fecha_limite_acceso(self):
        return self.viaje.fecha + datetime.timedelta(days=self.DIAS_VIGENCIA_ACCESO)

    @property
    def acceso_vigente(self):
        return (self.viaje.estado != 'CANCELADA'
                and timezone.localdate() <= self.fecha_limite_acceso)


class FotoAyudanteViaje(models.Model):
    """Foto que sube el ayudante de un viaje como evidencia de una novedad."""
    ayudante = models.ForeignKey(AyudanteViaje, on_delete=models.CASCADE, related_name='fotos')
    novedad = models.CharField(max_length=30)
    archivo = models.ImageField(upload_to='fotos_ayudantes/')
    fecha_subida = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['fecha_subida']
        verbose_name = "Foto del ayudante (viaje de disposición)"
        verbose_name_plural = "Fotos de los ayudantes (viajes de disposición)"

    def get_novedad_display_label(self):
        return dict(AyudanteViaje.NOVEDAD_CHOICES).get(self.novedad, self.novedad)

    @property
    def persona_nombre(self):
        return self.ayudante.persona_nombre
