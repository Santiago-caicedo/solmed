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
from django.conf import settings
from django.db import models

from gestion.models import Dispositor, OrdenServicio, Proveedor, Vehiculo


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
    Los campos extra (placas, orden, proveedor, hora) aplican según la
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
    ]

    # Qué campos pide cada actividad (el formato físico los trae por fila):
    #   vehiculos: 'uno' | 'varios' | 'cargados' | None — si lleva placa(s).
    #              'cargados' = SOLO camiones con residuo pendiente: asignar la
    #              actividad los DESCARGA (es la única vía para hacerlo) y la
    #              orden sale de la carga, no se digita.
    #   orden:     lleva el número de la orden de servicio (se digita).
    #   proveedor: lleva el proveedor externo (con opción de crearlo).
    #   dispositor:lleva el gestor donde se dispuso (opcional).
    #   hora:      lleva hora (los apoyos).
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
        'DISPOSICION_FINAL':   {'vehiculos': 'cargados', 'dispositor': True},
        'DISPOSICION_SOLMED':  {},
        'ACOMPANAMIENTO':      {'detalle': True},
        'RECOGER_VEHICULO':    {'vehiculos': 'uno'},
        'DESTRUCCION_CANECAS': {},
        'APOYO_SERVICIO':      {'vehiculos': 'uno', 'hora': True},
        'APOYO_DISPOSICION':   {'vehiculos': 'uno', 'hora': True},
        'OTRA':                {'detalle': True},
    }

    plan = models.ForeignKey(PlanDia, on_delete=models.CASCADE,
                             related_name='asignaciones')
    persona = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
        related_name='asignaciones_plan',
    )
    tipo = models.CharField(max_length=25, choices=TIPO_CHOICES)
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
    hora = models.TimeField(null=True, blank=True)
    detalle = models.CharField(max_length=255, blank=True, verbose_name="Descripción")
    registrado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True,
        related_name='asignaciones_registradas',
    )
    fecha_registro = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['id']
        verbose_name = "Asignación del plan"
        verbose_name_plural = "Asignaciones del plan"

    def __str__(self):
        return f"{self.get_tipo_display()} — {self.persona_nombre} ({self.plan.fecha:%d/%m/%Y})"

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
    def descarga_vehiculos(self):
        """¿Esta actividad es la que dispone el residuo (y descarga el camión)?"""
        return self.campos.get('vehiculos') == 'cargados'

    def aplicar_descarga(self, vehiculo, personas):
        """
        Deja el camión vacío porque el plan asignó su disposición. Es la ÚNICA
        vía para descargar a mano (el botón del expediente se retiró): así el
        residuo siempre sale del sistema con un responsable y una fecha.
        El movimiento conserva la ORDEN que lo había cargado.
        """
        from gestion.models import MovimientoCargaVehiculo
        nota = (f"Plan del {self.plan.fecha:%d/%m/%Y}: dispuesto por "
                f"{', '.join(personas)}")
        if self.detalle:
            nota += f" · {self.detalle}"
        MovimientoCargaVehiculo.objects.create(
            vehiculo=vehiculo, accion='DESCARGA', nota=nota[:255],
            orden=self.orden, dispositor=self.dispositor,
            registrado_por=self.registrado_por,
        )
        vehiculo.cargado = False
        vehiculo.cargado_detalle = ''
        vehiculo.save(update_fields=['cargado', 'cargado_detalle'])

    def deshacer_descarga(self):
        """
        Quitar la asignación devuelve el camión a CARGADO: si la disposición no
        se hizo, el residuo sigue ahí. Se registra el movimiento para que el
        historial no mienta.
        """
        from gestion.models import MovimientoCargaVehiculo
        vehiculo = self.vehiculos.first()
        if vehiculo is None or vehiculo.cargado:
            return
        nota = (f"Se quitó del plan del {self.plan.fecha:%d/%m/%Y} la "
                f"disposición asignada a {self.persona_nombre}")
        MovimientoCargaVehiculo.objects.create(
            vehiculo=vehiculo, accion='CARGA', nota=nota[:255], orden=self.orden,
            registrado_por=self.registrado_por,
        )
        vehiculo.cargado = True
        vehiculo.cargado_detalle = (
            f"Orden #{self.orden_id}: sigue pendiente de disposición"
            if self.orden_id else "Pendiente de disposición")
        vehiculo.save(update_fields=['cargado', 'cargado_detalle'])


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
    ]

    persona = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
        related_name='novedades_plan',
    )
    tipo = models.CharField(max_length=25, choices=TIPO_CHOICES)
    fecha_inicio = models.DateField(verbose_name="Fecha de inicio")
    fecha_fin = models.DateField(
        null=True, blank=True, verbose_name="Fecha final",
        help_text="Vacía = la novedad es solo del día de inicio.",
    )
    hora = models.TimeField(null=True, blank=True,
                            help_text="Para permisos de unas horas.")
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

    @property
    def persona_nombre(self):
        return self.persona.get_full_name() or self.persona.username

    @classmethod
    def del_dia(cls, fecha):
        """Las novedades vigentes en esa fecha (rango o día único)."""
        return cls.objects.filter(
            models.Q(fecha_inicio=fecha, fecha_fin__isnull=True)
            | models.Q(fecha_inicio__lte=fecha, fecha_fin__gte=fecha)
        ).select_related('persona')
