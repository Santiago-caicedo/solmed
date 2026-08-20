# gestion/models.py
import datetime
import uuid
from django.db import models, transaction
from django.conf import settings # Para relacionar con el usuario/asesor
from django.db.models import Sum
from django.utils import timezone


class Cliente(models.Model):
    # --- Campos existentes ---
    nombre = models.CharField(max_length=200, help_text="Razón Social de la empresa cliente")
    sigla = models.CharField(max_length=100, blank=True, verbose_name="Sigla")
    identificacion = models.CharField(max_length=50, help_text="NIT o Cédula (puede repetirse entre sedes del mismo cliente, ej. D1 Ibagué y D1 Manizales)")
    direccion = models.CharField(max_length=255, blank=True)
    
    # --- Nuevos campos ---
    ciudad = models.CharField(max_length=100, blank=True)
    telefono_fijo = models.CharField(max_length=20, blank=True, verbose_name="Teléfono Fijo")
    telefono_celular = models.CharField(max_length=20, blank=True, verbose_name="Teléfono Celular")
    persona_contacto = models.CharField(max_length=200, blank=True, verbose_name="Persona de Contacto")
    cargo_contacto = models.CharField(max_length=200, blank=True, verbose_name="Cargo del Contacto")
    
    # --- Campos existentes re-contextualizados ---
    email = models.EmailField(blank=True, help_text="Correo electrónico del contacto")
    telefono = models.CharField(max_length=20, blank=True, help_text="Teléfono del contacto")

    # --- Contacto Comercial ---
    comercial_nombre = models.CharField(max_length=200, blank=True, verbose_name="Comercial - Nombre")
    comercial_telefono = models.CharField(max_length=20, blank=True, verbose_name="Comercial - Teléfono")
    comercial_cargo = models.CharField(max_length=200, blank=True, verbose_name="Comercial - Cargo")
    comercial_correo = models.EmailField(blank=True, verbose_name="Comercial - Correo")

    # --- Contacto Contabilidad y Facturación Electrónica ---
    contab_nombre = models.CharField(max_length=200, blank=True, verbose_name="Contabilidad - Nombre")
    contab_telefono = models.CharField(max_length=20, blank=True, verbose_name="Contabilidad - Teléfono")
    contab_cargo = models.CharField(max_length=200, blank=True, verbose_name="Contabilidad - Cargo")
    contab_correo = models.EmailField(blank=True, verbose_name="Contabilidad - Correo")
    contab_correo_facturacion = models.EmailField(blank=True, verbose_name="Correo de Facturación Electrónica")
    contab_domicilio_fiscal = models.CharField(max_length=255, blank=True, verbose_name="Domicilio Fiscal")

    # --- Contacto Ambiental ---
    ambiental_nombre = models.CharField(max_length=200, blank=True, verbose_name="Ambiental - Nombre")
    ambiental_telefono = models.CharField(max_length=20, blank=True, verbose_name="Ambiental - Teléfono")
    ambiental_cargo = models.CharField(max_length=200, blank=True, verbose_name="Ambiental - Cargo")
    ambiental_correo = models.EmailField(blank=True, verbose_name="Ambiental - Correo")

    # --- Contacto SST ---
    sst_nombre = models.CharField(max_length=200, blank=True, verbose_name="SST - Nombre")
    sst_telefono = models.CharField(max_length=20, blank=True, verbose_name="SST - Teléfono")
    sst_cargo = models.CharField(max_length=200, blank=True, verbose_name="SST - Cargo")
    sst_correo = models.EmailField(blank=True, verbose_name="SST - Correo")

    # --- Documentos a adjuntar (archivos fijos) ---
    doc_rut = models.FileField(upload_to='clientes_documentos/', blank=True, null=True, verbose_name="RUT actualizado")
    doc_camara_comercio = models.FileField(upload_to='clientes_documentos/', blank=True, null=True, verbose_name="Cámara de Comercio")
    doc_cedula_rep_legal = models.FileField(upload_to='clientes_documentos/', blank=True, null=True, verbose_name="Cédula del Representante Legal")

    def __str__(self):
        return self.nombre


class DocumentoAmbientalCliente(models.Model):
    """
    Documentos ambientales del cliente (carga múltiple): Documento Ambiental,
    Caracterización, Análisis Químico, Declaración de Residuo, Soporte de
    Conocimiento del Residuo, etc. Se pueden adjuntar varios por cliente.
    """
    cliente = models.ForeignKey(Cliente, on_delete=models.CASCADE, related_name='documentos_ambientales')
    archivo = models.FileField(upload_to='clientes_documentos/ambientales/')
    descripcion = models.CharField(max_length=255, blank=True)
    fecha_subida = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-fecha_subida']

    def __str__(self):
        return self.archivo.name.split('/')[-1]


class DocumentoCorreoCliente(models.Model):
    """
    Documentos del cliente que se adjuntan AUTOMÁTICAMENTE al correo que se envía
    al generar cada orden de ese cliente (junto con la seguridad social del
    personal). Carga múltiple, igual que los documentos ambientales.
    """
    cliente = models.ForeignKey(Cliente, on_delete=models.CASCADE, related_name='documentos_correo')
    archivo = models.FileField(upload_to='clientes_documentos/correo/')
    descripcion = models.CharField(max_length=255, blank=True)
    fecha_subida = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-fecha_subida']
        verbose_name = "Documento del cliente para el correo"
        verbose_name_plural = "Documentos del cliente para el correo"

    def __str__(self):
        return self.descripcion or self.archivo.name.split('/')[-1]


class DocumentoInterno(models.Model):
    """
    Documentación INTERNA de SOLMED (la propia empresa), a la mano para las áreas:
    RUT, cámara de comercio, cédulas de representantes, estados financieros,
    certificaciones bancarias, RIT, certificados de Contraloría y Procuraduría,
    más la documentación ADICIONAL con nombre libre (tipo OTRO).

    De cada documento hay UNO solo vigente: cargar otro del mismo tipo lo
    REEMPLAZA (no se acumulan). La certificación bancaria reemplaza por
    cuenta/banco (`entidad`) y la adicional por su nombre (`descripcion`).
    Algunos llevan fecha (RUT, cámara).
    """
    TIPO_CHOICES = [
        ('RUT', 'RUT completo'),
        ('RUT_PRIMERA_PAGINA', 'RUT primera página'),
        ('CAMARA_COMERCIO', 'Cámara de Comercio'),
        ('CEDULA_REP_LEGAL', 'Cédula del representante legal'),
        ('CEDULA_REP_SUPLENTE', 'Cédula del representante legal suplente'),
        ('ESTADOS_FINANCIEROS', 'Estados financieros'),
        ('CERTIFICACION_BANCARIA', 'Certificación bancaria'),
        ('RIT', 'RIT'),
        ('CERT_CONTRALORIA', 'Certificado de la Contraloría'),
        ('CERT_PROCURADURIA', 'Certificado de la Procuraduría'),
        ('OTRO', 'Documentación adicional'),
    ]
    # Tipos que llevan fecha del documento (para que las áreas la conozcan).
    TIPOS_CON_FECHA = ('RUT', 'RUT_PRIMERA_PAGINA', 'CAMARA_COMERCIO')
    # Tipo que admite varios (una certificación por cuenta/banco).
    TIPO_MULTIPLE = 'CERTIFICACION_BANCARIA'
    # Documentación adicional: nombre libre en `descripcion`; una por nombre.
    TIPO_ADICIONAL = 'OTRO'
    # Cuentas/bancos sugeridos para la certificación bancaria.
    ENTIDADES_BANCARIAS = [
        'Bancolombia', 'Occidente', 'Nequi Gustavo', 'Cuenta de ahorros Bancolombia',
    ]

    tipo = models.CharField(max_length=30, choices=TIPO_CHOICES)
    archivo = models.FileField(upload_to='solmed_documentos/')
    fecha = models.DateField(null=True, blank=True, verbose_name="Fecha del documento")
    entidad = models.CharField(
        max_length=150, blank=True,
        help_text="Para certificación bancaria: banco / cuenta."
    )
    descripcion = models.CharField(max_length=255, blank=True)
    fecha_subida = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['tipo', '-fecha_subida']
        verbose_name = "Documento interno de SOLMED"
        verbose_name_plural = "Documentos internos de SOLMED"

    def __str__(self):
        if self.tipo == self.TIPO_ADICIONAL and self.descripcion:
            return self.descripcion
        return f"{self.get_tipo_display()}{' - ' + self.entidad if self.entidad else ''}"

    @property
    def nombre_visible(self):
        """Cómo se nombra en las listas y en los correos."""
        return str(self)


class Sede(models.Model):
    """
    Sede (sucursal / punto) de un cliente. Un cliente puede tener varias
    (ej. D1 Centro, D1 Norte). Al programar un servicio, si el cliente tiene
    sedes se elige a cuál corresponde, y su dirección se arrastra a la orden.
    """
    cliente = models.ForeignKey(Cliente, on_delete=models.CASCADE, related_name='sedes')
    nombre = models.CharField(max_length=150, help_text="Ej: Sede Centro, Bodega Norte…")
    direccion = models.CharField(max_length=255, blank=True)
    ciudad = models.CharField(max_length=100, blank=True)
    telefono = models.CharField(max_length=30, blank=True)
    persona_contacto = models.CharField(max_length=200, blank=True, verbose_name="Persona de contacto")
    activa = models.BooleanField(
        default=True,
        help_text="Desmárcala para ocultarla de los desplegables sin borrar el histórico."
    )

    class Meta:
        ordering = ['nombre']
        verbose_name = "Sede"
        verbose_name_plural = "Sedes"

    def __str__(self):
        return f"{self.nombre} ({self.cliente.nombre})"


class Tercero(models.Model):
    """
    Tercero de un cliente: algunos clientes no manejan sedes sino terceros,
    puntos donde se recoge el servicio (con su propio nombre, dirección y
    contacto). Se registran desde la ficha del cliente, igual que las sedes,
    y al programar un servicio se puede elegir el tercero para arrastrar su
    dirección y contacto a la orden.
    """
    cliente = models.ForeignKey(Cliente, on_delete=models.CASCADE, related_name='terceros')
    nombre = models.CharField(max_length=200, help_text="Nombre o razón social del tercero")
    direccion = models.CharField(max_length=255, blank=True)
    ciudad = models.CharField(max_length=100, blank=True)
    telefono = models.CharField(max_length=30, blank=True)
    persona_contacto = models.CharField(max_length=200, blank=True, verbose_name="Persona de contacto")
    activo = models.BooleanField(
        default=True,
        help_text="Desmárcalo para ocultarlo de los desplegables sin borrar el histórico."
    )

    class Meta:
        ordering = ['nombre']
        verbose_name = "Tercero"
        verbose_name_plural = "Terceros"

    def __str__(self):
        return f"{self.nombre} ({self.cliente.nombre})"


class Vehiculo(models.Model):
    ESTADO_CHOICES = [
        ('OPERATIVO', 'Operativo'),
        ('MANTENIMIENTO', 'En mantenimiento'),
        ('STAND_BY', 'Stand by (reparación mayor)'),
    ]

    # Días de antelación con los que se empieza a avisar de un documento por vencer.
    DIAS_ALERTA_VENCIMIENTO = 20

    placa = models.CharField(max_length=10, unique=True, help_text="Placa del vehículo")
    marca = models.CharField(max_length=50)
    modelo = models.CharField(max_length=50)
    capacidad = models.CharField(max_length=100, help_text="Ej: '3 toneladas', '20 m³'")
    estado = models.CharField(max_length=20, choices=ESTADO_CHOICES, default='OPERATIVO')

    # --- Carga pendiente de disposición ---
    # True cuando el camión quedó con contenido sin disposición final (se marcó
    # "dejar carro cargado" o fue destino de un trasiego a placa). Se limpia
    # cuando participa en una orden con disposición final real (proveedor).
    cargado = models.BooleanField(default=False, verbose_name="Cargado (pendiente de disposición)")
    cargado_detalle = models.CharField(
        max_length=255, blank=True,
        help_text="De dónde viene la carga pendiente (orden y fecha)."
    )

    # --- Documentos legales ---
    # Tarjeta de propiedad: solo se adjunta el PDF (no tiene vencimiento ni alerta).
    archivo_tarjeta = models.FileField(
        upload_to='vehiculos_documentos/', blank=True, null=True,
        verbose_name="PDF Tarjeta de Propiedad"
    )
    # SOAT: fecha de vencimiento (con alerta) + PDF adjunto.
    fecha_vencimiento_soat = models.DateField(
        null=True, blank=True, verbose_name="Vencimiento SOAT"
    )
    archivo_soat = models.FileField(
        upload_to='vehiculos_documentos/', blank=True, null=True,
        verbose_name="PDF SOAT"
    )
    # Tecnomecánica: fecha de vencimiento (con alerta) + PDF adjunto.
    fecha_vencimiento_tecnomecanica = models.DateField(
        null=True, blank=True, verbose_name="Vencimiento Tecnomecánica"
    )
    archivo_tecnomecanica = models.FileField(
        upload_to='vehiculos_documentos/', blank=True, null=True,
        verbose_name="PDF Tecnomecánica"
    )

    def __str__(self):
        return f"{self.marca} {self.modelo} ({self.placa})"

    @property
    def carga_actual(self):
        """
        El movimiento de CARGA que dejó el camión en este estado, o None si
        está vacío. De ahí sale la orden que lo cargó y desde cuándo espera
        disposición (lo que el plan de trabajo le muestra al asesor).
        """
        if not self.cargado:
            return None
        return self.movimientos_carga.filter(accion='CARGA').first()

    @property
    def orden_que_cargo(self):
        """La orden que dejó cargado el camión (None si fue carga manual)."""
        movimiento = self.carga_actual
        return movimiento.orden if movimiento is not None else None

    def documentos_por_vencer(self, dias=None):
        """
        Devuelve los documentos vencidos o próximos a vencer (dentro de `dias`,
        por defecto DIAS_ALERTA_VENCIMIENTO). Se recalcula en cada llamada usando
        la fecha de hoy, por lo que el conteo de días se actualiza solo cada día.
        """
        if dias is None:
            dias = self.DIAS_ALERTA_VENCIMIENTO
        hoy = timezone.localdate()
        documentos = [
            ("SOAT", self.fecha_vencimiento_soat),
            ("Tecnomecánica", self.fecha_vencimiento_tecnomecanica),
        ]
        alertas = []
        for nombre, fecha in documentos:
            if not fecha:
                continue
            dias_restantes = (fecha - hoy).days
            if dias_restantes <= dias:
                alertas.append({
                    'documento': nombre,
                    'fecha': fecha,
                    'dias_restantes': dias_restantes,
                    'dias_abs': abs(dias_restantes),
                    'vencido': dias_restantes < 0,
                })
        return alertas

    @property
    def tiene_alerta_documentos(self):
        return bool(self.documentos_por_vencer())


class FiltroAceite(models.Model):
    """
    Registro de FILTROS y ACEITES del vehículo. Cada cambio se anota con su
    fecha, la cantidad (galones/litros de aceite aplicados o unidades de filtro
    instaladas), el kilometraje y la referencia. El "último cambio" de cada tipo
    es el registro más reciente; los anteriores quedan como historial de
    mantenimiento del vehículo.
    """
    TIPO_CHOICES = [
        ('ACEITE_MOTOR', 'Aceite de motor'),
        ('ACEITE_CAJA', 'Aceite de caja'),
        ('ACEITE_CORONA', 'Aceite de corona / diferencial'),
        ('ACEITE_HIDRAULICO', 'Aceite hidráulico'),
        ('FILTRO_ACEITE', 'Filtro de aceite'),
        ('FILTRO_AIRE', 'Filtro de aire'),
        ('FILTRO_COMBUSTIBLE', 'Filtro de combustible'),
        ('FILTRO_SEPARADOR', 'Filtro separador de agua'),
        ('OTRO', 'Otro (indicar en la referencia)'),
    ]
    UNIDAD_CHOICES = [
        ('UNIDADES', 'unidad(es)'),
        ('GALONES', 'galón(es)'),
        ('LITROS', 'litro(s)'),
        ('CUARTOS', 'cuarto(s)'),
    ]
    # Tipos que son aceite (para preseleccionar la unidad en el formulario).
    TIPOS_ACEITE = ('ACEITE_MOTOR', 'ACEITE_CAJA', 'ACEITE_CORONA', 'ACEITE_HIDRAULICO')

    vehiculo = models.ForeignKey(Vehiculo, on_delete=models.CASCADE, related_name='filtros_aceites')
    tipo = models.CharField(max_length=30, choices=TIPO_CHOICES)
    fecha_cambio = models.DateField(verbose_name="Fecha del cambio")
    cantidad = models.DecimalField(
        max_digits=8, decimal_places=2,
        verbose_name="Cantidad",
        help_text="Galones/litros de aceite aplicados o número de filtros instalados."
    )
    unidad = models.CharField(max_length=10, choices=UNIDAD_CHOICES, default='UNIDADES')
    kilometraje = models.PositiveIntegerField(
        null=True, blank=True, verbose_name="Kilometraje en el cambio (opcional)"
    )
    referencia = models.CharField(
        max_length=150, blank=True, verbose_name="Referencia / marca",
        help_text="Ej: Mobil Delvac 15W-40, filtro FL-820S…"
    )
    observaciones = models.CharField(max_length=255, blank=True)
    fecha_registro = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-fecha_cambio', '-id']
        verbose_name = "Cambio de filtro / aceite"
        verbose_name_plural = "Filtros y aceites del vehículo"

    def __str__(self):
        return f"{self.get_tipo_display()} - {self.vehiculo.placa} ({self.fecha_cambio:%d/%m/%Y})"

    @property
    def es_aceite(self):
        return self.tipo in self.TIPOS_ACEITE

    @property
    def dias_desde_cambio(self):
        return (timezone.localdate() - self.fecha_cambio).days


class OrdenServicio(models.Model):
    # --- NUEVOS ESTADOS AUTOMÁTICOS PARA LA ORDEN ---
    ESTADO_ORDEN_CHOICES = [
        ('PROGRAMADA', 'Programada'),
        ('EN_EJECUCION', 'En Ejecución'),
        ('FINALIZADA', 'Finalizada'),
        ('CANCELADA', 'Cancelada'),
    ]
    
    # Los estados de pago no cambian
    ESTADO_PAGO_CHOICES = [
        ('PENDIENTE', 'Pendiente'),
        ('PAGADO', 'Pagado'),
        ('ABONADO', 'Abonado'),
    ]

    # --- Conciliación de "Transporte - Cantidad" ---
    # Ese campo de las instrucciones del servicio por lo general NO se llena al
    # crear la programación: el asesor lo concilia DESPUÉS de prestar el
    # servicio, durante el mes calendario. Si la orden se genera con el campo
    # vacío queda PENDIENTE (con alerta y estadística) hasta que el asesor la
    # concilie desde el expediente de la orden. NO_APLICA = órdenes creadas a
    # mano (sin programación, no tienen instrucciones del servicio).
    CONCILIACION_CHOICES = [
        ('NO_APLICA', 'No aplica'),
        ('PENDIENTE', 'Pendiente de conciliación'),
        ('CONCILIADA', 'Conciliada'),
    ]

    SI_NO_CHOICES = [('SI', 'Sí'), ('NO', 'No')]
    BASCULA_CHOICES = [
        ('PESAN', 'Sí'),
        ('NO_PESAN', 'No'),
        ('PESO_CLIENTE', 'Báscula del cliente'),
    ]

    # --- Relaciones Principales ---
    cliente = models.ForeignKey(Cliente, on_delete=models.PROTECT, related_name='ordenes')
    asesor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='ordenes_creadas')

    # --- CAMPOS ELIMINADOS ---
    # El vehículo y la fecha ahora pertenecen a los "Recorridos" individuales.
    # vehiculo_asignado = models.ManyToManyField(...) -> ELIMINADO
    # fecha_servicio = models.DateField(...) -> ELIMINADO

    

    # El consecutivo de las órdenes arranca en este número (pedido del usuario:
    # empatar con el consecutivo que la empresa ya llevaba). Las órdenes nuevas
    # toman max(última + 1, este valor); ver save().
    NUMERO_INICIAL = 22207

    # --- Detalles Generales de la Orden ---
    numero_orden = models.AutoField(primary_key=True)
    fecha_creacion = models.DateTimeField(auto_now_add=True)
    direccion_servicio = models.CharField(max_length=255, help_text="Dirección principal del servicio o contrato")
    descripcion = models.TextField(help_text="Descripción general del acuerdo o contrato")
    valor_servicio = models.DecimalField(max_digits=10, decimal_places=2, default=0.00, help_text="Costo total del acuerdo")

    # --- Datos operativos (antes en la programación) ---
    bascula = models.CharField(max_length=20, choices=BASCULA_CHOICES, blank=True, verbose_name="Báscula")
    bascula_adjunto = models.FileField(upload_to='ordenes_documentos/', null=True, blank=True, verbose_name="Adjunto báscula")
    registro_fotografico = models.CharField(max_length=2, choices=SI_NO_CHOICES, blank=True, verbose_name="Registro fotográfico")
    registro_fotografico_adjunto = models.FileField(upload_to='ordenes_documentos/', null=True, blank=True, verbose_name="Adjunto registro fotográfico")

    # --- Campos de Seguimiento ---
    estado_orden = models.CharField(max_length=20, choices=ESTADO_ORDEN_CHOICES, default='PROGRAMADA')
    estado_pago = models.CharField(max_length=20, choices=ESTADO_PAGO_CHOICES, default='PENDIENTE')
    estado_conciliacion = models.CharField(
        max_length=20, choices=CONCILIACION_CHOICES, default='NO_APLICA',
        verbose_name="Conciliación (Transporte - Cantidad)"
    )
    fecha_conciliacion = models.DateTimeField(null=True, blank=True, verbose_name="Fecha de conciliación")

    def save(self, *args, **kwargs):
        # Numeración explícita: la siguiente orden es max(última + 1,
        # NUMERO_INICIAL). Así el consecutivo arranca en 22207 sin depender de
        # la secuencia de la base de datos (funciona igual en Postgres y en
        # sqlite, y también si se crean órdenes desde el admin).
        if self.numero_orden is None:
            from django.db.models import Max
            ultimo = OrdenServicio.objects.aggregate(m=Max('numero_orden'))['m'] or 0
            self.numero_orden = max(ultimo + 1, self.NUMERO_INICIAL)
        super().save(*args, **kwargs)

    def __str__(self):
        return f"Orden #{self.numero_orden} - {self.cliente.nombre}"

    @property
    def pendiente_conciliacion(self):
        return self.estado_conciliacion == 'PENDIENTE'

    def conciliar_transporte(self, cantidad):
        """
        Registra la conciliación de "Transporte - Cantidad" (la hace el asesor
        durante el mes, después de prestado el servicio): guarda la cantidad en
        la programación de origen y marca la orden como CONCILIADA.

        DECISIÓN PROVISIONAL (pendiente de confirmar en la empresa): si el acta
        ya fue diligenciada o firmada, el valor TAMBIÉN se actualiza en ella
        (el PDF firmado ya generado no se regenera). Si el acta aún no se ha
        cerrado, el valor llega solo al copiarse las instrucciones al cerrarla.
        """
        cantidad = (cantidad or '').strip()
        programacion = getattr(self, 'programacion_origen', None)
        if programacion is not None:
            programacion.transporte_cantidad = cantidad
            programacion.save(update_fields=['transporte_cantidad'])
        for recorrido in self.recorridos.all():
            try:
                manifiesto = recorrido.manifiesto
            except Manifiesto.DoesNotExist:
                continue
            manifiesto.transporte_cantidad = cantidad
            manifiesto.save(update_fields=['transporte_cantidad'])
        self.estado_conciliacion = 'CONCILIADA'
        self.fecha_conciliacion = timezone.now()
        self.save(update_fields=['estado_conciliacion', 'fecha_conciliacion'])

    @property
    def requiere_bascula(self):
        """
        Se planeó pesar (en báscula propia o del cliente), así que hay que
        adjuntar el soporte. Con 'No' o sin definir, el adjunto no aplica.
        """
        return self.bascula in ('PESAN', 'PESO_CLIENTE')

    @property
    def requiere_registro_fotografico(self):
        return self.registro_fotografico == 'SI'

    


class DocumentoOrden(models.Model):
    orden = models.ForeignKey(OrdenServicio, on_delete=models.CASCADE, related_name='documentos')
    archivo = models.FileField(upload_to='ordenes_documentos/')
    descripcion = models.CharField(max_length=255, blank=True)
    fecha_subida = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        # Devuelve solo el nombre del archivo, no la ruta completa
        return self.archivo.name.split('/')[-1]





def _recalcular_estado_orden(orden):
    """
    Ajusta el estado de la orden según sus recorridos: FINALIZADA si todos están
    completados, EN_EJECUCION si hay alguno, PROGRAMADA si no queda ninguno.
    Se usa al guardar y al eliminar un recorrido. No toca órdenes CANCELADAS.
    """
    if orden is None or orden.estado_orden == 'CANCELADA':
        return
    recorridos = orden.recorridos.all()
    total = recorridos.count()
    completados = recorridos.filter(estado='COMPLETADO').count()
    if total == 0:
        orden.estado_orden = 'PROGRAMADA'
    elif completados == total:
        orden.estado_orden = 'FINALIZADA'
    else:
        orden.estado_orden = 'EN_EJECUCION'
    orden.save(update_fields=['estado_orden'])


class Recorrido(models.Model):
    ESTADO_CHOICES = [
        ('PROGRAMADO', 'Programado'),
        ('EN_CURSO', 'En Curso'),
        ('COMPLETADO', 'Completado'),
    ]
    # Cada recorrido pertenece a una orden de servicio
    orden = models.ForeignKey(OrdenServicio, on_delete=models.CASCADE, related_name='recorridos')
    vehiculo = models.ForeignKey(Vehiculo, on_delete=models.PROTECT, related_name='recorridos')

    conductor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='recorridos',
        null=True, blank=True
    )

    # Ayudante del conductor (rol 'Ayudantes'). Opcional.
    ayudante = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='recorridos_como_ayudante',
        null=True, blank=True
    )
    # Segundo ayudante (opcional).
    ayudante2 = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='recorridos_como_ayudante2',
        null=True, blank=True
    )

    fecha_recorrido = models.DateField()
    estado = models.CharField(max_length=20, choices=ESTADO_CHOICES, default='PROGRAMADO')
    descripcion = models.CharField(max_length=255, blank=True, help_text="Descripción específica de este recorrido si es necesaria")

    def __str__(self):
        return f"Recorrido del {self.fecha_recorrido} para Orden #{self.orden.numero_orden}"

    @property
    def responsable_empresa(self):
        """
        Nombre del RESPONSABLE SOLMED del acta: es el conductor asignado. El
        conductor no lo escribe; se copia al manifiesto al cerrarlo.
        """
        if self.conductor is None:
            return ''
        return self.conductor.get_full_name() or self.conductor.username

    @property
    def auxiliares(self):
        """
        Nombres de los AUXILIARES del acta: son los ayudantes que asignó el
        asesor en la programación. El conductor no los escribe ni los edita;
        se copian al manifiesto al cerrarlo. Devuelve (auxiliar1, auxiliar2).
        """
        def nombre(persona):
            if persona is None:
                return ''
            return persona.get_full_name() or persona.username
        return nombre(self.ayudante), nombre(self.ayudante2)

    @property
    def va_sin_ayudante(self):
        """
        El servicio se programó a propósito SIN ayudante (el asesor lo marcó
        en la cuadrilla). Distinto de que falte asignarlo: por eso se muestra.
        """
        if self.ayudante_id or self.ayudante2_id:
            return False
        programacion = getattr(self.orden, 'programacion_origen', None)
        if programacion is None:
            return False
        cuadrilla = programacion.cuadrillas.filter(vehiculo=self.vehiculo_id).first()
        return bool(cuadrilla and cuadrilla.conductor_solo)

    @property
    def personas_asignadas(self):
        """Lista [(persona, es_conductor)] del personal del recorrido, para plantillas."""
        personas = []
        if self.conductor:
            personas.append((self.conductor, True))
        if self.ayudante:
            personas.append((self.ayudante, False))
        if self.ayudante2:
            personas.append((self.ayudante2, False))
        return personas

    def save(self, *args, **kwargs):
        # Guardamos el recorrido primero
        super().save(*args, **kwargs)
        # Recalculamos el estado de la orden padre según sus recorridos.
        _recalcular_estado_orden(self.orden)



class Manifiesto(models.Model):
    # ============================================================
    #  NOTA DE NOMENCLATURA (importante):
    #  En el CÓDIGO/BACK se llama "Manifiesto" (modelo, vistas, URLs,
    #  related_name recorrido.manifiesto, plantillas manifiesto_*).
    #  En la INTERFAZ/FRONT se muestra como "ACTA DE SERVICIO".
    #  Es la ejecución de la orden: el conductor registra lo realizado
    #  (succión/sondeo/lavado/tiempos/km) y el cliente firma su conformidad.
    #  NO renombrar el modelo/URLs; solo cambia el texto visible.
    # ============================================================
    # --- Estado del ciclo de firma ---
    # PENDIENTE_FIRMA: el conductor ya cargó los datos operativos (paso1-4) y se generó el QR;
    #                  falta que el funcionario del cliente complete la encuesta y firme.
    # FIRMADO:         el cliente ya firmó. El token público deja de ser utilizable.
    ESTADO_FIRMA_CHOICES = [
        ('PENDIENTE_FIRMA', 'Pendiente firma cliente'),
        ('FIRMADO', 'Firmado'),
    ]

    # Relación uno a uno con el recorrido. Cada viaje tiene un único manifiesto.
    recorrido = models.OneToOneField(Recorrido, on_delete=models.CASCADE, related_name='manifiesto')

    # Token aleatorio para el enlace público (QR) que abre el cliente sin iniciar sesión.
    token_publico = models.UUIDField(default=uuid.uuid4, editable=False, null=True, unique=True)
    estado_firma = models.CharField(max_length=20, choices=ESTADO_FIRMA_CHOICES, default='PENDIENTE_FIRMA')

    # --- Cabecera ---
    auxiliar1 = models.CharField(max_length=100, blank=True, verbose_name="Auxiliar 1")
    auxiliar2 = models.CharField(max_length=100, blank=True, verbose_name="Auxiliar 2")

    # --- Sección: Succión y Transporte ---
    succ_canecas = models.BooleanField(default=False, verbose_name="Canecas")
    succ_canecas_cant = models.CharField(max_length=20, blank=True, verbose_name="Ton/M³ Canecas")
    succ_pozos_inspeccion = models.BooleanField(default=False, verbose_name="Pozos de inspección")
    succ_pozos_inspeccion_cant = models.CharField(max_length=20, blank=True, verbose_name="Ton/M³ Pozos")
    succ_pozos_septicos = models.BooleanField(default=False, verbose_name="Pozos Sépticos")
    succ_pozos_septicos_cant = models.CharField(max_length=20, blank=True, verbose_name="Ton/M³ Sépticos")
    succ_tanques = models.BooleanField(default=False, verbose_name="Tanques")
    succ_tanques_cant = models.CharField(max_length=20, blank=True, verbose_name="Ton/M³ Tanques")
    succ_trampas_grasa = models.BooleanField(default=False, verbose_name="Trampas de Grasa")
    succ_trampas_grasa_cant = models.CharField(max_length=20, blank=True, verbose_name="Ton/M³ Trampas")
    succ_otros = models.CharField(max_length=100, blank=True, verbose_name="Otros (Succión)")
    succ_otros_cant = models.CharField(max_length=20, blank=True, verbose_name="Ton/M³ Otros")

    # --- Sección: Sondeo ---
    sond_red_aguas_lluvias = models.BooleanField(default=False, verbose_name="Red de agua lluvias")
    sond_red_aguas_lluvias_cant = models.CharField(max_length=50, blank=True, verbose_name="H/ML (Lluvias)") 
    sond_red_aguas_negras = models.BooleanField(default=False, verbose_name="Red de aguas negras")
    sond_red_aguas_negras_cant = models.CharField(max_length=50, blank=True, verbose_name="H/ML (Negras)") 
    sond_red_acueducto = models.BooleanField(default=False, verbose_name="Red Acueducto")
    sond_red_acueducto_cant = models.CharField(max_length=50, blank=True, verbose_name="H/ML (Acueducto)") 
    sond_correctivo = models.BooleanField(default=False, verbose_name="Sondeo Correctivo")
    sond_correctivo_cant = models.CharField(max_length=50, blank=True, verbose_name="Valor (Correctivo)") 
    sond_preventivo = models.BooleanField(default=False, verbose_name="Sondeo Preventivo")
    sond_preventivo_cant = models.CharField(max_length=50, blank=True, verbose_name="Valor (Preventivo)") 
    sond_diametro = models.CharField(max_length=50, blank=True, verbose_name="Diámetro")

    # --- Sección: Lavado ---
    lavado_concepto = models.CharField(max_length=100, blank=True, verbose_name="Concepto de Lavado")
    lavado_cantidad = models.CharField(max_length=50, blank=True, verbose_name="Cantidad (Lavado)")
    lavado_correctivo = models.CharField(max_length=100, blank=True, verbose_name="Lavado Correctivo")
    lavado_preventivo = models.CharField(max_length=100, blank=True, verbose_name="Lavado Preventivo")

    # --- Sección: Transporte ---
    transporte_tipo = models.CharField(max_length=100, blank=True, verbose_name="Tipo de Transporte")
    transporte_cantidad = models.CharField(max_length=50, blank=True, verbose_name="Cantidad (Transporte)")
    
    # --- Tiempos y Medidores ---
    tiempo_inicio_operativo = models.TimeField(null=True, blank=True, verbose_name="H. Inicio Operativo")
    tiempo_final_operativo = models.TimeField(null=True, blank=True, verbose_name="H. Final Operativo")
    tiempo_llegada_disposicion = models.TimeField(null=True, blank=True, verbose_name="H. Llegada sitio Disposición") 
    tiempo_salida_disposicion = models.TimeField(null=True, blank=True, verbose_name="H. Salida sitio Disposición") 
    # Bloque "Tiempos de recorrido": eran los kilómetros del tablero y ahora
    # son las horas de cada punto de la ruta.
    hora_salida_solmed = models.TimeField(null=True, blank=True, verbose_name="H. Salida SolMed")
    hora_llegada_empresa = models.TimeField(null=True, blank=True, verbose_name="H. Llegada Empresa")
    hora_llegada_disposicion = models.TimeField(null=True, blank=True, verbose_name="H. Llegada Sitio Disposición")
    hora_llegada_solmed = models.TimeField(null=True, blank=True, verbose_name="H. Llegada SolMed")
    
    # --- Evaluación de Satisfacción ---
    SATISFACCION_CHOICES = [(1, 'Deficiente'), (2, 'Regular'), (3, 'Bueno'), (4, 'Excelente')]
    eval_atencion = models.IntegerField(choices=SATISFACCION_CHOICES, null=True, blank=True)
    eval_amabilidad = models.IntegerField(choices=SATISFACCION_CHOICES, null=True, blank=True)
    eval_solucion_inquietudes = models.IntegerField(choices=SATISFACCION_CHOICES, null=True, blank=True)
    eval_asesoria = models.IntegerField(choices=SATISFACCION_CHOICES, null=True, blank=True)
    eval_puntualidad = models.IntegerField(choices=SATISFACCION_CHOICES, null=True, blank=True)
    eval_calidad_servicio = models.IntegerField(choices=SATISFACCION_CHOICES, null=True, blank=True)
    eval_oportunidad = models.IntegerField(choices=SATISFACCION_CHOICES, null=True, blank=True)
    eval_cumplimiento_condiciones = models.IntegerField(choices=SATISFACCION_CHOICES, null=True, blank=True)
    eval_solucion_problemas = models.IntegerField(choices=SATISFACCION_CHOICES, null=True, blank=True)
    eval_volveria_contratar = models.IntegerField(choices=SATISFACCION_CHOICES, null=True, blank=True)
    eval_nos_recomendaria = models.IntegerField(choices=SATISFACCION_CHOICES, null=True, blank=True)

    # --- Cierre y Firma ---
    observaciones = models.TextField(blank=True)
    
    # Datos del responsable de la EMPRESA (el que firma en la app)
    nombre_responsable_cliente = models.CharField(max_length=200, blank=True, verbose_name="Nombre Responsable Cliente")
    firma_cliente = models.ImageField(upload_to='firmas_manifiestos/', blank=True, null=True)

    # Datos del responsable de SOLMED (se llena en el Paso 4)
    nombre_responsable_empresa = models.CharField(max_length=200, blank=True, verbose_name="Nombre Responsable Solmed")
    
    # --- PDF Generado ---
    fecha_creacion = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Manifiesto del Recorrido #{self.recorrido.id}"
    


class Pago(models.Model):
    METODO_CHOICES = [
        ('TRANSFERENCIA', 'Transferencia'),
        ('EFECTIVO', 'Efectivo'),
        ('CONSIGNACION', 'Consignación'),
        ('OTRO', 'Otro'),
    ]

    # Cada pago está ligado a una Orden de Servicio. En CASCADE: eliminar la orden
    # desde el admin también borra sus pagos (limpieza total de una orden mal creada).
    orden = models.ForeignKey(OrdenServicio, on_delete=models.CASCADE, related_name='pagos')
    
    fecha_pago = models.DateTimeField(default=timezone.now, verbose_name="Fecha y Hora del Pago")
    monto = models.DecimalField(max_digits=10, decimal_places=2)
    metodo_pago = models.CharField(max_length=50, choices=METODO_CHOICES, default='TRANSFERENCIA')
    notas = models.TextField(blank=True, help_text="Notas adicionales, número de referencia, etc.")
    
    class Meta:
        ordering = ['-fecha_pago']

    def __str__(self):
        return f"Pago de {self.monto} para Orden #{self.orden.pk}"

    # --- LÓGICA DE AUTOMATIZACIÓN ---
    def _actualizar_estado_orden(self):
        """
        Esta función se llama cada vez que se guarda o borra un pago.
        Calcula el total pagado y actualiza el estado de la orden padre.
        """
        orden = self.orden
        # Sumamos todos los pagos registrados para esta orden
        total_pagado = orden.pagos.aggregate(total=Sum('monto'))['total'] or 0.00
        
        if total_pagado >= orden.valor_servicio:
            orden.estado_pago = 'PAGADO'
        elif total_pagado > 0:
            orden.estado_pago = 'ABONADO'
        else:
            orden.estado_pago = 'PENDIENTE'
        
        orden.save()

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs) # Guarda el pago
        self._actualizar_estado_orden() # Actualiza la orden

    def delete(self, *args, **kwargs):
        super().delete(*args, **kwargs) # Borra el pago
        self._actualizar_estado_orden() # Actualiza la orden


class Dispositor(models.Model):
    """
    Gestor / planta o celda de seguridad autorizada para la disposición final de
    residuos. Es parametrizable desde el admin para alimentar el desplegable de
    'Dispositor final' de la encuesta del conductor (trazabilidad de la cuna a la tumba).
    """
    # PROVEEDOR: gestor externo (disposición final REAL — el camión queda vacío).
    # INTERNO:   el contenido NO se dispone: queda en un camión (dejar cargado /
    #            trasiego a placa) o en los tanques de SOLMED. Es carga PENDIENTE.
    TIPO_CHOICES = [
        ('PROVEEDOR', 'Proveedor externo (disposición final)'),
        ('INTERNO', 'Destino interno (sin disposición)'),
    ]

    nombre = models.CharField(max_length=200, verbose_name="Nombre del gestor / dispositor")
    tipo = models.CharField(max_length=10, choices=TIPO_CHOICES, default='PROVEEDOR')
    descripcion = models.CharField(
        max_length=255, blank=True,
        help_text="Tipo de planta o celda, licencia ambiental, ciudad, etc."
    )
    activo = models.BooleanField(
        default=True,
        help_text="Desmárcalo para ocultarlo de los formularios sin borrar el histórico."
    )

    class Meta:
        verbose_name = "Dispositor final autorizado"
        verbose_name_plural = "Dispositores finales autorizados"
        ordering = ['nombre']

    # Nombres exactos de los destinos internos (sembrados por migración) que
    # tienen comportamiento especial al convertir la programación en orden.
    DEJAR_CARRO_CARGADO = 'DEJAR CARRO CARGADO'
    TRASIEGO_PLACA = 'TRASIEGO A ------ PLACA'
    TANQUES = ('TRASIEGO TANQUE AUXILIAR', 'TRASIEGO TANQUE SUBTERRANEO')
    # El servicio pasa sin disposición y SIN dejar nada pendiente: el camión no
    # queda cargado y no hay contenido que rastrear (p. ej. sondeo o lavado).
    SIN_DISPOSICION = 'NO HAY DISPOSICIÓN'

    def __str__(self):
        return self.nombre


class DocumentoDispositor(models.Model):
    """
    Documento del expediente de un proveedor de disposición final (Dispositor):
    RUT, cámara de comercio, cédula del representante legal, certificación
    bancaria y documentos ambientales. Los ambientales admiten varios; en los
    demás, el más reciente cargado es el que rige (los anteriores quedan de
    soporte histórico).
    """
    TIPO_CHOICES = [
        ('RUT', 'RUT'),
        ('CAMARA_COMERCIO', 'Cámara de Comercio'),
        ('CEDULA_REP_LEGAL', 'Cédula del representante legal'),
        ('CERTIFICACION_BANCARIA', 'Certificación bancaria'),
        ('DOC_AMBIENTAL', 'Documento ambiental'),
    ]
    # Tipos que admiten varios documentos a la vez (los demás muestran el más reciente).
    TIPOS_MULTIPLES = ('DOC_AMBIENTAL',)

    dispositor = models.ForeignKey(Dispositor, on_delete=models.CASCADE, related_name='documentos')
    tipo = models.CharField(max_length=30, choices=TIPO_CHOICES)
    archivo = models.FileField(upload_to='dispositores_documentos/')
    descripcion = models.CharField(max_length=255, blank=True)
    fecha_subida = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['tipo', '-fecha_subida']
        verbose_name = "Documento del proveedor (dispositor)"
        verbose_name_plural = "Documentos de los proveedores (dispositores)"

    def __str__(self):
        return f"{self.get_tipo_display()} - {self.dispositor.nombre}"


class Banco(models.Model):
    """
    Catálogo de bancos (y billeteras como Nequi o Daviplata) para los datos de
    pago de los proveedores. Se siembra por migración y se amplía desde el admin.
    """
    nombre = models.CharField(max_length=100, unique=True)
    activo = models.BooleanField(
        default=True,
        help_text="Desmárcalo para ocultarlo del desplegable sin borrar el histórico."
    )

    class Meta:
        ordering = ['nombre']
        verbose_name = "Banco"
        verbose_name_plural = "Bancos"

    def __str__(self):
        return self.nombre


class Proveedor(models.Model):
    """
    Proveedor general de bienes y servicios (compras, mantenimiento, insumos...).
    Es DISTINTO del proveedor de disposición final (Dispositor): este no participa
    en la operación de residuos; lleva sus datos de facturación, contactos, datos
    bancarios para pagos y un expediente de documentos con nombre libre.
    """
    TIPO_CUENTA_CHOICES = [
        ('AHORROS', 'Ahorros'),
        ('CORRIENTE', 'Corriente'),
        ('NEQUI', 'Nequi'),
        ('DAVIPLATA', 'Daviplata'),
        ('OTRA', 'Otra'),
    ]

    nit = models.CharField(max_length=30, verbose_name="NIT")
    razon_social = models.CharField(max_length=200, verbose_name="Razón social")
    nombre_comercial = models.CharField(max_length=200, blank=True, verbose_name="Nombre comercial")
    direccion = models.CharField(max_length=255, blank=True, verbose_name="Dirección")

    # Datos de pago
    banco = models.ForeignKey(
        Banco, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='proveedores'
    )
    tipo_cuenta = models.CharField(
        max_length=10, choices=TIPO_CUENTA_CHOICES, blank=True,
        verbose_name="Tipo de cuenta"
    )
    numero_cuenta = models.CharField(max_length=50, blank=True, verbose_name="No. de cuenta")

    activo = models.BooleanField(
        default=True,
        help_text="Desmárcalo para archivarlo sin borrar su expediente."
    )

    class Meta:
        ordering = ['razon_social']
        verbose_name = "Proveedor general"
        verbose_name_plural = "Proveedores generales"

    def __str__(self):
        return self.nombre_comercial or self.razon_social


class ContactoProveedor(models.Model):
    """
    Contacto de un proveedor general (hasta MAX_CONTACTOS por proveedor, con
    nombre propio): a quién llamar o escribir, de qué área, correo y celular.
    """
    MAX_CONTACTOS = 3

    proveedor = models.ForeignKey(Proveedor, on_delete=models.CASCADE, related_name='contactos')
    # Todos opcionales a nivel de modelo: el formulario exige el nombre cuando
    # la fila trae algún dato, y una fila vaciada equivale a quitar el contacto.
    nombre = models.CharField(max_length=120, blank=True)
    area = models.CharField(max_length=120, blank=True, verbose_name="Área")
    correo = models.EmailField(blank=True)
    celular = models.CharField(max_length=30, blank=True)

    class Meta:
        ordering = ['id']
        verbose_name = "Contacto del proveedor"
        verbose_name_plural = "Contactos del proveedor"

    def __str__(self):
        return f"{self.nombre} ({self.proveedor})"


class DocumentoProveedor(models.Model):
    """
    Documento del expediente de un proveedor general. Sin tipos fijos: cada
    documento se carga con un nombre libre (RUT, cámara, certificación, etc.).
    """
    proveedor = models.ForeignKey(Proveedor, on_delete=models.CASCADE, related_name='documentos')
    nombre = models.CharField(max_length=150, verbose_name="Nombre del documento")
    archivo = models.FileField(upload_to='proveedores_documentos/')
    fecha_subida = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-fecha_subida']
        verbose_name = "Documento del proveedor general"
        verbose_name_plural = "Documentos de los proveedores generales"

    def __str__(self):
        return f"{self.nombre} - {self.proveedor}"


class EncuestaConductor(models.Model):
    """
    Encuesta de cierre que llena EL CONDUCTOR una vez firmada el acta por el
    cliente. Son siete preguntas de Sí/No sobre seguridad vial y su propia
    salud: evidencia de cumplimiento del PESV (Plan Estratégico de Seguridad
    Vial) de SOLMED SAS. Diligenciarla marca el recorrido como COMPLETADO
    (es obligatoria).

    La última pregunta (condición de riesgo o casi-accidente) abre el tipo de
    evento y su descripción para poder investigarlo.
    """
    SI_NO_CHOICES = [('SI', 'Sí'), ('NO', 'No')]

    TIPO_INCIDENTE_CHOICES = [
        ('FALLA_MECANICA', 'Falla mecánica (Varada)'),
        ('INCIDENTE_MENOR', 'Incidente menor (Roce o golpe simple)'),
        ('SINIESTRO_TERCEROS', 'Siniestro vial con terceros'),
    ]

    # Preguntas en las que responder "SÍ" es la señal de alerta (las demás se
    # alertan al responder "NO"). Se usa para los indicadores del tablero.
    PREGUNTAS_ALERTA_SI = ('presento_fatiga', 'molestias_fisicas', 'condicion_riesgo')

    recorrido = models.OneToOneField(
        Recorrido, on_delete=models.CASCADE, related_name='encuesta_conductor'
    )

    # --- 1. Fatiga ---
    presento_fatiga = models.CharField(
        max_length=2, choices=SI_NO_CHOICES,
        verbose_name="¿Presentó síntomas de fatiga, cansancio o microsueños durante el desarrollo de la ruta?"
    )

    # --- 2. Pausas activas ---
    realizo_pausas_activas = models.CharField(
        max_length=2, choices=SI_NO_CHOICES,
        verbose_name="¿Realizó las pausas activas recomendadas durante el trayecto "
                     "(al menos 05-10 minutos por cada 2 horas de conducción)?"
    )

    # --- 3. Molestias físicas ---
    molestias_fisicas = models.CharField(
        max_length=2, choices=SI_NO_CHOICES,
        verbose_name="¿Ha experimentado molestias físicas (lumbalgia, dolor de cuello o piernas) "
                     "durante o al finalizar el recorrido?"
    )

    # --- 4. Tiempos de la ruta ---
    tiempos_adecuados = models.CharField(
        max_length=2, choices=SI_NO_CHOICES,
        verbose_name="¿Considera que los tiempos asignados para la ruta son adecuados y realistas "
                     "sin necesidad de exceder los límites de velocidad?"
    )

    # --- 5. Condiciones de la cabina ---
    cabina_optima = models.CharField(
        max_length=2, choices=SI_NO_CHOICES,
        verbose_name="¿El asiento, cinturón de seguridad y controles de la cabina se encuentran "
                     "en condiciones óptimas de confort y funcionamiento?"
    )

    # --- 6. Zonas de descanso ---
    zonas_seguras_descanso = models.CharField(
        max_length=2, choices=SI_NO_CHOICES,
        verbose_name="¿Dispuso de zonas seguras y autorizadas para realizar sus paradas de descanso "
                     "o alimentación durante la ruta?"
    )

    # --- 7. Condición de riesgo / casi-accidente (con detalle si es SÍ) ---
    condicion_riesgo = models.CharField(
        max_length=2, choices=SI_NO_CHOICES,
        verbose_name="¿Estuvo involucrado o presenció alguna condición de riesgo o casi-accidente "
                     "durante el turno?"
    )
    tipo_incidente = models.CharField(
        max_length=20, choices=TIPO_INCIDENTE_CHOICES, blank=True,
        verbose_name="Tipo de evento"
    )
    descripcion_incidente = models.TextField(
        blank=True, verbose_name="Descripción de lo ocurrido"
    )

    # --- PDF generado (evidencia documental independiente) ---
    fecha_diligenciamiento = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Encuesta de cierre del conductor"
        verbose_name_plural = "Encuestas de cierre del conductor"

    # Las siete preguntas, en el orden del formato.
    CAMPOS_PREGUNTAS = (
        'presento_fatiga', 'realizo_pausas_activas', 'molestias_fisicas',
        'tiempos_adecuados', 'cabina_optima', 'zonas_seguras_descanso',
        'condicion_riesgo',
    )

    def __str__(self):
        return f"Encuesta de cierre - Recorrido #{self.recorrido_id}"

    def respuestas(self):
        """
        Las siete preguntas con su respuesta, para el PDF y las vistas:
        [{'numero', 'pregunta', 'respuesta', 'alerta'}]. `alerta` marca la
        respuesta que exige atención (según PREGUNTAS_ALERTA_SI).
        """
        items = []
        for i, campo in enumerate(self.CAMPOS_PREGUNTAS, start=1):
            valor = getattr(self, campo)
            esperado_si = campo in self.PREGUNTAS_ALERTA_SI
            items.append({
                'numero': i,
                'pregunta': self._meta.get_field(campo).verbose_name,
                'respuesta': dict(self.SI_NO_CHOICES).get(valor, '—'),
                'alerta': (valor == 'SI') if esperado_si else (valor == 'NO'),
            })
        return items

    @property
    def tiene_alertas(self):
        """True si alguna respuesta exige atención (para avisos y estadística)."""
        return any(item['alerta'] for item in self.respuestas())

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        # Diligenciar la encuesta de cierre marca el recorrido como COMPLETADO,
        # lo que a su vez actualiza el estado de la orden padre (lógica de Recorrido.save).
        recorrido = self.recorrido
        if recorrido.estado != 'COMPLETADO':
            recorrido.estado = 'COMPLETADO'
            recorrido.save()


class TipoResiduo(models.Model):
    """
    Catálogo de residuos para la "Caracterización del Residuo" de la
    programación (antes se llamaba Transporte). Alimenta el desplegable y se
    pueden crear nombres nuevos desde el mismo formulario, que quedan
    disponibles para las siguientes programaciones.

    Ojo: `Programacion.transporte_tipo` sigue guardando el NOMBRE como texto
    (no una FK), porque ese valor se copia tal cual al acta (Manifiesto), que
    también lo guarda como texto. Este modelo es el catálogo de sugerencias.
    """
    nombre = models.CharField(max_length=100, unique=True)
    activo = models.BooleanField(
        default=True,
        help_text="Desmárcalo para ocultarlo del desplegable sin borrar el histórico."
    )

    class Meta:
        ordering = ['nombre']
        verbose_name = "Residuo (caracterización)"
        verbose_name_plural = "Residuos (caracterización)"

    def __str__(self):
        return self.nombre


class Bascula(models.Model):
    """
    Báscula (empresa/lugar de pesaje) para la programación: cuando "¿Pesan en
    báscula?" es Sí, se elige en cuál. Catálogo administrable desde el popup
    del propio formulario (agregar/eliminar); si una báscula ya fue usada por
    programaciones, en vez de borrarse se desactiva (PROTECT).
    """
    nombre = models.CharField(max_length=150, unique=True, verbose_name="Empresa / lugar")
    direccion = models.CharField(max_length=255, blank=True)
    activo = models.BooleanField(
        default=True,
        help_text="Desmárcalo para ocultarla del desplegable sin borrar el histórico."
    )

    class Meta:
        ordering = ['nombre']
        verbose_name = "Báscula"
        verbose_name_plural = "Básculas"

    def __str__(self):
        return self.nombre


class SitioInicio(models.Model):
    """
    Sitio donde el personal inicia el turno / ingresa antes del servicio
    (bodega, sede del cliente, taller…). Catálogo del desplegable "Sitio de
    inicio" de la programación; se pueden crear nuevos desde el mismo
    formulario y quedan disponibles para las siguientes programaciones.
    """
    nombre = models.CharField(max_length=150, unique=True)
    activo = models.BooleanField(
        default=True,
        help_text="Desmárcalo para ocultarlo del desplegable sin borrar el histórico."
    )

    class Meta:
        ordering = ['nombre']
        verbose_name = "Sitio de inicio"
        verbose_name_plural = "Sitios de inicio"

    def __str__(self):
        return self.nombre


# Cursos que se le pueden EXIGIR al ayudante desde la programación. No son
# obligatorios en su expediente: cada programación decide si este servicio los
# requiere (ver Programacion.exige_curso_alturas / exige_curso_confinados).
CURSOS_EXIGIBLES = [
    ('CURSO_ALTURAS', 'curso de alturas'),
    ('CURSO_CONFINADOS', 'curso de espacios confinados'),
]


def cursos_faltantes_ayudante(ayudante, exige_alturas=False, exige_confinados=False):
    """
    Devuelve los motivos por los que un ayudante NO cumple con los cursos que
    exige la programación. Un curso vencido cuenta igual que uno que falta.
    Si el documento no tiene vigencia registrada se considera vigente.
    Lista vacía = el ayudante cumple.
    """
    exigidos = []
    if exige_alturas:
        exigidos.append('CURSO_ALTURAS')
    if exige_confinados:
        exigidos.append('CURSO_CONFINADOS')
    if not exigidos or ayudante is None:
        return []

    etiquetas = dict(CURSOS_EXIGIBLES)
    documentos = ayudante.documentos_personales.filter(tipo__in=exigidos)
    por_tipo = {}
    for documento in documentos:
        por_tipo.setdefault(documento.tipo, []).append(documento)

    motivos = []
    for tipo in exigidos:
        copias = por_tipo.get(tipo, [])
        if not copias:
            motivos.append(f"no tiene cargado el {etiquetas[tipo]}")
            continue
        # Basta con que una copia esté vigente (sin fecha = sin control de vigencia).
        vigentes = [d for d in copias if not d.vencido]
        if not vigentes:
            ultimo = max(copias, key=lambda d: d.fecha_vencimiento)
            motivos.append(
                f"tiene el {etiquetas[tipo]} vencido "
                f"({ultimo.fecha_vencimiento.strftime('%d/%m/%Y')})"
            )
    return motivos


class Programacion(models.Model):
    """
    Programación anticipada: paso PREVIO a la Orden de Servicio.

    La persona que planea diligencia esto el día anterior (antes de mediodía) para
    organizar al personal. Reproduce el formato operativo de SOLMED: cabecera del
    servicio, checklist operativo (báscula, registro fotográfico, paleada, SG,
    cursos) y las cuadrillas (conductor + placa + ayudante) en el modelo hijo
    `ProgramacionCuadrilla`. Al confirmarla se genera la OrdenServicio y un
    Recorrido por cada cuadrilla con vehículo, y ambas quedan enlazadas.
    """
    ESTADO_CHOICES = [
        ('BORRADOR', 'Borrador'),
        ('CONFIRMADA', 'Confirmada'),
        ('CONVERTIDA', 'Convertida en orden'),
        ('CANCELADA', 'Cancelada'),
    ]
    SI_NO_CHOICES = [('SI', 'Sí'), ('NO', 'No')]
    PALEADA_CHOICES = [
        ('SAVICOL', 'Palea Savicol'),
        ('EMPOLLACOL', 'Palea Empollacol'),
        ('SOLO_PALEADA', 'Solo requiere paleada'),
        ('NO_REQUIERE', 'No requiere paleada'),
    ]

    # --- Cabecera del servicio ---
    fecha = models.DateField(verbose_name="Fecha del servicio")
    # Antes se llamaba "Hora ingreso a bodega", pero el turno no siempre inicia
    # en la bodega: la hora va aparte y el lugar se elige en `sitio_inicio`.
    # El nombre del campo se conserva por compatibilidad.
    hora_ingreso_bodega = models.TimeField(null=True, blank=True, verbose_name="Hora de ingreso")
    sitio_inicio = models.ForeignKey(
        SitioInicio, on_delete=models.PROTECT, null=True, blank=True,
        related_name='programaciones', verbose_name="Sitio de inicio"
    )
    hora_servicio = models.TimeField(null=True, blank=True, verbose_name="Hora del servicio")

    cliente = models.ForeignKey(Cliente, on_delete=models.PROTECT, related_name='programaciones')
    # Sede del cliente a la que corresponde el servicio (si el cliente tiene
    # sedes). Su dirección se arrastra a la orden. `sede` (texto) queda como
    # campo legado por compatibilidad; ya no se usa en el formulario.
    sede_cliente = models.ForeignKey(
        Sede, on_delete=models.PROTECT, null=True, blank=True,
        related_name='programaciones', verbose_name="Sede del cliente"
    )
    sede = models.CharField(max_length=150, blank=True)
    # Tercero del cliente donde se recoge el servicio (para los clientes que
    # manejan terceros en lugar de sedes). Su dirección y contacto se arrastran
    # a la orden. Excluyente con la sede: el servicio ocurre en un solo lugar.
    tercero = models.ForeignKey(
        Tercero, on_delete=models.PROTECT, null=True, blank=True,
        related_name='programaciones', verbose_name="Tercero del cliente"
    )
    direccion = models.CharField(
        max_length=255, blank=True,
        help_text="Se arrastra a la orden al convertir. Si se deja vacío se usa la dirección del cliente."
    )
    # HISTÓRICO: la documentación al cliente ya no se envía desde la
    # programación sino desde el Centro de correos (modelo EnvioCorreo). Estos
    # dos campos se conservan solo por las programaciones viejas.
    correo_seguridad_social = models.EmailField(
        blank=True, verbose_name="Correo del cliente (histórico)",
        help_text="Ya no se usa: los correos al cliente salen del Centro de correos."
    )
    adjuntos_correo = models.JSONField(
        default=list, blank=True,
        verbose_name="Documentos del correo (tokens, histórico)",
    )
    observaciones_servicio = models.TextField(
        blank=True, verbose_name="Observaciones detalladas del servicio a prestar"
    )

    # --- Checklist operativo (desplegables del formato) ---
    paleada = models.CharField(
        max_length=20, choices=PALEADA_CHOICES, blank=True,
        verbose_name="¿Se requiere paleada?"
    )

    # Se planean aquí y se arrastran a la orden al convertir (los adjuntos se
    # cargan luego en la orden, cuando ya se prestó el servicio).
    bascula = models.CharField(
        max_length=20, choices=OrdenServicio.BASCULA_CHOICES, blank=True,
        verbose_name="¿Pesan en báscula?"
    )
    # En cuál báscula se pesa (solo cuando la respuesta es Sí/'PESAN').
    bascula_sitio = models.ForeignKey(
        Bascula, on_delete=models.PROTECT, null=True, blank=True,
        related_name='programaciones', verbose_name="Báscula"
    )
    registro_fotografico = models.CharField(
        max_length=2, choices=SI_NO_CHOICES, blank=True,
        verbose_name="¿Requiere registro fotográfico?"
    )

    responsable_sg = models.CharField(
        max_length=2, choices=SI_NO_CHOICES, blank=True,
        verbose_name="¿Se requiere SGC?"
    )

    # --- Disposición final ---
    # Si se realizará disposición final, se indica con cuál proveedor/gestor
    # (modelo Dispositor, parametrizable desde el admin).
    requiere_disposicion_final = models.CharField(
        max_length=2, choices=SI_NO_CHOICES, blank=True,
        verbose_name="¿Se realizará disposición final?"
    )
    dispositor_final = models.ForeignKey(
        Dispositor, on_delete=models.PROTECT, null=True, blank=True,
        related_name='programaciones', verbose_name="Proveedor de disposición final"
    )
    # Cuando NO hay disposición y el destino es "TRASIEGO A ------ PLACA":
    # el camión al que se pasa el contenido (queda cargado).
    trasiego_vehiculo = models.ForeignKey(
        Vehiculo, on_delete=models.PROTECT, null=True, blank=True,
        related_name='trasiegos_recibidos', verbose_name="Placa a la que se trasiega"
    )

    # --- Cursos exigidos al ayudante para ESTE servicio ---
    # No son obligatorios en el expediente del ayudante: solo se validan cuando
    # la programación los marca en 'SI'. Si el ayudante asignado no los tiene
    # (o los tiene vencidos), no se deja guardar ni convertir en orden.
    exige_curso_alturas = models.CharField(
        max_length=2, choices=SI_NO_CHOICES, blank=True,
        verbose_name="El ayudante debe tener curso de alturas"
    )
    exige_curso_confinados = models.CharField(
        max_length=2, choices=SI_NO_CHOICES, blank=True,
        verbose_name="El ayudante debe tener curso de espacios confinados"
    )

    nombre_contacto_recibe = models.CharField(
        max_length=200, blank=True, verbose_name="Nombre / contacto de quien recibe el servicio"
    )

    # --- Instrucciones del servicio (primera parte del Acta de servicio) ---
    # Lo que ANTES llenaba el conductor en el acta (Succión y Transporte / Sondeo /
    # Lavado / Transporte) ahora lo define el asesor aquí. Al generar la orden y
    # cuando el conductor cierra el acta, estos valores se copian tal cual al
    # Manifiesto (ver `instrucciones_acta` y GenerarManifiestoView): el conductor
    # ya no los diligencia, solo los recibe fijos. Mismos nombres que en Manifiesto
    # para poder copiarlos campo a campo.
    # Succión y Transporte
    succ_canecas = models.BooleanField(default=False, verbose_name="Canecas")
    succ_canecas_cant = models.CharField(max_length=20, blank=True, verbose_name="Ton/M³ Canecas")
    succ_pozos_inspeccion = models.BooleanField(default=False, verbose_name="Pozos de inspección")
    succ_pozos_inspeccion_cant = models.CharField(max_length=20, blank=True, verbose_name="Ton/M³ Pozos")
    succ_pozos_septicos = models.BooleanField(default=False, verbose_name="Pozos Sépticos")
    succ_pozos_septicos_cant = models.CharField(max_length=20, blank=True, verbose_name="Ton/M³ Sépticos")
    succ_tanques = models.BooleanField(default=False, verbose_name="Tanques")
    succ_tanques_cant = models.CharField(max_length=20, blank=True, verbose_name="Ton/M³ Tanques")
    succ_trampas_grasa = models.BooleanField(default=False, verbose_name="Trampas de Grasa")
    succ_trampas_grasa_cant = models.CharField(max_length=20, blank=True, verbose_name="Ton/M³ Trampas")
    succ_otros = models.CharField(max_length=100, blank=True, verbose_name="Otros (Succión)")
    succ_otros_cant = models.CharField(max_length=20, blank=True, verbose_name="Ton/M³ Otros")
    # Sondeo
    sond_red_aguas_lluvias = models.BooleanField(default=False, verbose_name="Red de agua lluvias")
    sond_red_aguas_lluvias_cant = models.CharField(max_length=50, blank=True, verbose_name="H/ML (Lluvias)")
    sond_red_aguas_negras = models.BooleanField(default=False, verbose_name="Red de aguas negras")
    sond_red_aguas_negras_cant = models.CharField(max_length=50, blank=True, verbose_name="H/ML (Negras)")
    sond_red_acueducto = models.BooleanField(default=False, verbose_name="Red Acueducto")
    sond_red_acueducto_cant = models.CharField(max_length=50, blank=True, verbose_name="H/ML (Acueducto)")
    sond_correctivo = models.BooleanField(default=False, verbose_name="Sondeo Correctivo")
    sond_correctivo_cant = models.CharField(max_length=50, blank=True, verbose_name="Valor (Correctivo)")
    sond_preventivo = models.BooleanField(default=False, verbose_name="Sondeo Preventivo")
    sond_preventivo_cant = models.CharField(max_length=50, blank=True, verbose_name="Valor (Preventivo)")
    sond_diametro = models.CharField(max_length=50, blank=True, verbose_name="Diámetro")
    # Lavado
    lavado_concepto = models.CharField(max_length=100, blank=True, verbose_name="Concepto de Lavado")
    lavado_cantidad = models.CharField(max_length=50, blank=True, verbose_name="Cantidad (Lavado)")
    lavado_correctivo = models.CharField(max_length=100, blank=True, verbose_name="Lavado Correctivo")
    lavado_preventivo = models.CharField(max_length=100, blank=True, verbose_name="Lavado Preventivo")
    # Transporte
    transporte_tipo = models.CharField(max_length=100, blank=True, verbose_name="Tipo de Transporte")
    transporte_cantidad = models.CharField(max_length=50, blank=True, verbose_name="Cantidad (Transporte)")

    estado = models.CharField(max_length=20, choices=ESTADO_CHOICES, default='BORRADOR')

    # Orden generada al convertir la programación (queda enlazada). En CASCADE:
    # eliminar la orden desde el admin también borra la programación que la originó,
    # para poder limpiar por completo una que quedó mal.
    orden = models.OneToOneField(
        OrdenServicio, on_delete=models.CASCADE, null=True, blank=True,
        related_name='programacion_origen'
    )

    creado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
        related_name='programaciones_creadas', null=True, blank=True
    )
    fecha_creacion = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-fecha_creacion']
        verbose_name = "Programación"
        verbose_name_plural = "Programaciones"

    # Campos de la "primera parte del acta" que el asesor define aquí y que se
    # copian al Manifiesto. Mismo orden agrupado que el formato físico.
    CAMPOS_INSTRUCCIONES_ACTA = (
        'succ_canecas', 'succ_canecas_cant',
        'succ_pozos_inspeccion', 'succ_pozos_inspeccion_cant',
        'succ_pozos_septicos', 'succ_pozos_septicos_cant',
        'succ_tanques', 'succ_tanques_cant',
        'succ_trampas_grasa', 'succ_trampas_grasa_cant',
        'succ_otros', 'succ_otros_cant',
        'sond_red_aguas_lluvias', 'sond_red_aguas_lluvias_cant',
        'sond_red_aguas_negras', 'sond_red_aguas_negras_cant',
        'sond_red_acueducto', 'sond_red_acueducto_cant',
        'sond_correctivo', 'sond_correctivo_cant',
        'sond_preventivo', 'sond_preventivo_cant',
        'sond_diametro',
        'lavado_concepto', 'lavado_cantidad', 'lavado_correctivo', 'lavado_preventivo',
        'transporte_tipo', 'transporte_cantidad',
    )

    @property
    def numero(self):
        """
        La programación se identifica con el número de SU orden (pedido del
        usuario: un solo consecutivo para ambas). Un borrador aún no tiene
        número: lo toma al generar la orden.
        """
        return self.orden_id

    def __str__(self):
        numero = f"#{self.orden_id}" if self.orden_id else f"(borrador {self.pk})"
        return f"Programación {numero} - {self.cliente.nombre} ({self.fecha})"

    def instrucciones_acta(self):
        """Valores de la primera parte del acta, listos para copiar al Manifiesto."""
        return {campo: getattr(self, campo) for campo in self.CAMPOS_INSTRUCCIONES_ACTA}

    def resumen_checklist(self):
        """
        El bloque superior de la hoja del conductor, tal como el formato:
        PALEADA / BÁSCULA / SE REALIZA DISPOSICIÓN a la izquierda y
        SE REQUIERE SISO / REGISTRO FOTOGRÁFICO / AYUDANTE CON CURSOS a la
        derecha. Devuelve (izquierda, derecha), cada una [(etiqueta, valor)].
        """
        def si_no(valor, texto_si='SÍ'):
            return texto_si if valor == 'SI' else 'NO'

        bascula = 'NO'
        if self.bascula == 'PESAN':
            bascula = 'SÍ — SUBIR FOTO'
            if self.bascula_sitio_id:
                bascula += f' ({self.bascula_sitio.nombre})'
        elif self.bascula == 'PESO_CLIENTE':
            bascula = 'BÁSCULA DEL CLIENTE'

        if self.requiere_disposicion_final == 'SI':
            disposicion = (self.dispositor_final.nombre if self.dispositor_final_id
                           else 'SÍ')
        elif self.requiere_disposicion_final == 'NO':
            disposicion = (self.dispositor_final.nombre if self.dispositor_final_id
                           else 'NO')
        else:
            disposicion = '—'

        cursos = [etiqueta for campo, etiqueta in (
            ('exige_curso_alturas', 'Alturas'),
            ('exige_curso_confinados', 'Espacios confinados'),
        ) if getattr(self, campo) == 'SI']

        izquierda = [
            ('PALEADA', self.get_paleada_display() if self.paleada else 'NO'),
            ('BÁSCULA', bascula),
            ('SE REALIZA DISPOSICIÓN', disposicion),
        ]
        derecha = [
            ('SE REQUIERE SISO', si_no(self.responsable_sg)),
            ('REGISTRO FOTOGRÁFICO',
             'SÍ — SUBIR FOTOS' if self.registro_fotografico == 'SI' else 'NO'),
            ('AYUDANTE CON CURSOS', ', '.join(cursos) if cursos else 'NO'),
        ]
        return izquierda, derecha

    def resumen_instrucciones(self):
        """
        Lista legible de lo que el asesor instruyó (para mostrárselo fijo al
        conductor). Solo incluye lo marcado o con texto; devuelve [] si no hay nada.
        """
        # (etiqueta, ¿está activo?, cantidad asociada)
        items = [
            ("Canecas", self.succ_canecas, self.succ_canecas_cant),
            ("Pozos de inspección", self.succ_pozos_inspeccion, self.succ_pozos_inspeccion_cant),
            ("Pozos sépticos", self.succ_pozos_septicos, self.succ_pozos_septicos_cant),
            ("Tanques", self.succ_tanques, self.succ_tanques_cant),
            ("Trampas de grasa", self.succ_trampas_grasa, self.succ_trampas_grasa_cant),
            (f"Otros: {self.succ_otros}" if self.succ_otros else "Otros", bool(self.succ_otros), self.succ_otros_cant),
            ("Sondeo red aguas lluvias", self.sond_red_aguas_lluvias, self.sond_red_aguas_lluvias_cant),
            ("Sondeo red aguas negras", self.sond_red_aguas_negras, self.sond_red_aguas_negras_cant),
            ("Sondeo red acueducto", self.sond_red_acueducto, self.sond_red_acueducto_cant),
            ("Sondeo correctivo", self.sond_correctivo, self.sond_correctivo_cant),
            ("Sondeo preventivo", self.sond_preventivo, self.sond_preventivo_cant),
            (f"Diámetro: {self.sond_diametro}" if self.sond_diametro else "Diámetro", bool(self.sond_diametro), ""),
            (f"Lavado: {self.lavado_concepto}" if self.lavado_concepto else "Lavado", bool(self.lavado_concepto), self.lavado_cantidad),
            (f"Lavado correctivo: {self.lavado_correctivo}", bool(self.lavado_correctivo), ""),
            (f"Lavado preventivo: {self.lavado_preventivo}", bool(self.lavado_preventivo), ""),
            (f"Residuo: {self.transporte_tipo}" if self.transporte_tipo else "Caracterización del residuo", bool(self.transporte_tipo), self.transporte_cantidad),
        ]
        resumen = []
        for etiqueta, activo, cantidad in items:
            if not activo:
                continue
            resumen.append(f"{etiqueta} ({cantidad})" if cantidad else etiqueta)
        return resumen

    @property
    def exige_alturas(self):
        return self.exige_curso_alturas == 'SI'

    @property
    def exige_confinados(self):
        return self.exige_curso_confinados == 'SI'

    def incumplimientos_cursos(self, solo_con_vehiculo=False):
        """
        Ayudantes asignados que no cumplen con los cursos exigidos por esta
        programación. Devuelve [(cuadrilla, [motivos]), ...]; vacío = todo en orden.
        Con `solo_con_vehiculo` se revisan únicamente las filas que generan recorrido.
        """
        if not (self.exige_alturas or self.exige_confinados):
            return []
        cuadrillas = self.cuadrillas.select_related('ayudante')
        if solo_con_vehiculo:
            cuadrillas = cuadrillas.filter(vehiculo__isnull=False)
        problemas = []
        for cuadrilla in cuadrillas:
            motivos = cursos_faltantes_ayudante(
                cuadrilla.ayudante, self.exige_alturas, self.exige_confinados
            )
            if motivos:
                problemas.append((cuadrilla, motivos))
        return problemas

    @property
    def puede_convertirse(self):
        """Se puede generar la orden si no tiene una, no está cancelada y hay al menos una cuadrilla con vehículo."""
        return (
            self.orden_id is None
            and self.estado in ('BORRADOR', 'CONFIRMADA')
            and self.cuadrillas.filter(vehiculo__isnull=False).exists()
        )

    def direccion_del_servicio(self):
        """
        A dónde va el equipo: la dirección del tercero elegido, si no la de la
        sede, si no la de la programación, si no la del cliente. La usan tanto
        la creación de la orden como su corrección posterior.
        """
        return (
            (self.tercero.direccion if self.tercero_id else '')
            or (self.sede_cliente.direccion if self.sede_cliente_id else '')
            or self.direccion or self.cliente.direccion or 'Por definir'
        )

    def convertir_en_orden(self, usuario):
        """
        Genera la OrdenServicio y un Recorrido por CADA cuadrilla con vehículo
        (misma fecha del servicio), enlaza ambas y marca la programación como
        CONVERTIDA. Idempotente: si ya tiene orden, la devuelve sin duplicar.
        """
        if self.orden_id:
            return self.orden

        cuadrillas = list(self.cuadrillas.filter(vehiculo__isnull=False))
        if not cuadrillas:
            raise ValueError("La programación no tiene ninguna cuadrilla con vehículo asignado.")

        # Los cursos exigidos se vuelven a comprobar aquí: la vigencia pudo
        # vencerse entre la creación de la programación y la generación de la orden.
        problemas = self.incumplimientos_cursos(solo_con_vehiculo=True)
        if problemas:
            detalle = "; ".join(
                f"{c.ayudante.get_full_name() or c.ayudante.username} {' y '.join(motivos)}"
                for c, motivos in problemas
            )
            raise ValueError(
                f"No se puede generar la orden: esta programación exige cursos y {detalle}."
            )

        direccion_servicio = self.direccion_del_servicio()

        # Si el servicio se recoge donde un tercero del cliente, sus datos
        # quedan registrados en la descripción de la orden.
        descripcion = self.observaciones_servicio or f'Orden generada desde la programación #{self.pk}'
        if self.tercero_id:
            t = self.tercero
            datos = ", ".join(filter(None, [
                t.direccion, t.ciudad,
                f"Tel: {t.telefono}" if t.telefono else '',
                f"Contacto: {t.persona_contacto}" if t.persona_contacto else '',
            ]))
            descripcion += f"\n\nServicio donde el tercero: {t.nombre}"
            if datos:
                descripcion += f" ({datos})"

        # Conciliación de "Transporte - Cantidad": si el asesor no la llenó al
        # programar (lo usual), la orden queda pendiente de conciliar.
        conciliacion = 'CONCILIADA' if (self.transporte_cantidad or '').strip() else 'PENDIENTE'

        with transaction.atomic():
            orden = OrdenServicio.objects.create(
                cliente=self.cliente,
                asesor=usuario,
                direccion_servicio=direccion_servicio,
                descripcion=descripcion,
                bascula=self.bascula,
                registro_fotografico=self.registro_fotografico,
                estado_conciliacion=conciliacion,
            )
            for c in cuadrillas:
                Recorrido.objects.create(
                    orden=orden,
                    vehiculo=c.vehiculo,
                    conductor=c.conductor,
                    ayudante=c.ayudante,
                    ayudante2=c.ayudante2,
                    fecha_recorrido=self.fecha,
                )
            self.orden = orden
            self.estado = 'CONVERTIDA'
            self.save()
            # Actualiza el estado de carga de los camiones según la disposición.
            self._actualizar_carga_vehiculos(orden, [c.vehiculo for c in cuadrillas], usuario)
        return orden

    def _actualizar_carga_vehiculos(self, orden, vehiculos, usuario=None):
        """
        Lleva el rastro de la carga pendiente de disposición:
          - Disposición SÍ (proveedor): los camiones del servicio quedan vacíos.
          - NO + "DEJAR CARRO CARGADO": los camiones del servicio quedan CARGADOS.
          - NO + "TRASIEGO A PLACA": el camión destino queda CARGADO y los del
            servicio vacíos (trasegaron su contenido).
          - NO + trasiego a tanque: los camiones quedan vacíos (el contenido pasa
            a los tanques de SOLMED; queda registrado en la programación para
            estadística).
        Si la pregunta quedó sin responder, no se toca nada.
        Cada cambio deja su registro en el historial (MovimientoCargaVehiculo).
        """
        detalle = f"Orden #{orden.numero_orden} del {self.fecha.strftime('%d/%m/%Y')}"

        def cargar(v, nota):
            v.cargado = True
            v.cargado_detalle = nota
            v.save(update_fields=['cargado', 'cargado_detalle'])
            MovimientoCargaVehiculo.objects.create(
                vehiculo=v, accion='CARGA', nota=nota, orden=orden,
                registrado_por=usuario)

        def descargar(v, nota, dispositor=None):
            # El movimiento se registra SIEMPRE, aunque el camión no estuviera
            # marcado como cargado: la disposición ocurrió y es la trazabilidad
            # del residuo (antes se perdía justo en el caso más común).
            v.cargado = False
            v.cargado_detalle = ''
            v.save(update_fields=['cargado', 'cargado_detalle'])
            MovimientoCargaVehiculo.objects.create(
                vehiculo=v, accion='DESCARGA', nota=nota, orden=orden,
                dispositor=dispositor, registrado_por=usuario)

        if self.requiere_disposicion_final == 'SI':
            for v in vehiculos:
                descargar(v, f"{detalle}: se dispuso con {self.dispositor_final.nombre}"
                          if self.dispositor_final_id else f"{detalle}: disposición final",
                          self.dispositor_final if self.dispositor_final_id else None)
            return
        if self.requiere_disposicion_final != 'NO' or not self.dispositor_final_id:
            return

        destino = self.dispositor_final.nombre
        if destino == Dispositor.DEJAR_CARRO_CARGADO:
            for v in vehiculos:
                cargar(v, f"{detalle}: quedó cargado (sin disposición)")
        elif destino == Dispositor.TRASIEGO_PLACA and self.trasiego_vehiculo_id:
            destino_v = self.trasiego_vehiculo
            cargar(destino_v, f"{detalle}: recibió trasiego (sin disposición)")
            for v in vehiculos:
                if v.pk != destino_v.pk:
                    descargar(v, f"{detalle}: trasegó su contenido a {destino_v.placa}")
        elif destino in Dispositor.TANQUES:
            for v in vehiculos:
                descargar(v, f"{detalle}: contenido a {destino.title()} (tanques SOLMED)")
        elif destino == Dispositor.SIN_DISPOSICION:
            # El servicio no deja nada pendiente: si el camión venía cargado de
            # antes, ese pendiente sigue siendo suyo (no se toca).
            pass


class ProgramacionCuadrilla(models.Model):
    """
    Una fila del bloque CONDUCTOR / PLACA / AYUDANTE del formato de programación.
    Cada cuadrilla con vehículo genera un Recorrido al convertir la programación.
    `ayudante_novedad` captura cómo cubre el turno el ayudante ese día (dónde lo
    inicia o lo termina, si retorna a bodega o si apoya una disposición).
    """
    # Agrupadas por momento del turno: cómo lo inicia, cómo lo termina y apoyos.
    NOVEDAD_CHOICES = [
        # Inicio del turno
        ('INICIA_CLIENTE', 'Inicia turno donde el cliente'),
        ('INICIA_BODEGA', 'Inicia en bodega'),
        ('INICIA_BODEGA_TARDE', 'Ingresa tarde a bodega (el conductor llegó tarde)'),
        ('INICIA_PARQUEADERO', 'Inicia en parqueadero'),
        ('PUNTO_ENCUENTRO', 'Punto de encuentro'),
        # Fin del turno
        ('TERMINA_CLIENTE', 'Termina turno donde el cliente'),
        ('TERMINA_DISPOSICION', 'Termina turno en el sitio de disposición'),
        ('TERMINA_INGRESO_BOGOTA', 'Termina ingreso a Bogotá'),
        ('RETORNA_BODEGA', 'Retorna a bodega'),
        # Apoyos
        ('APOYA_DISPOSICION', 'Apoya disposición de:'),
    ]
    # Novedad que requiere indicar de cuál vehículo se apoya la disposición.
    APOYA_DISPOSICION = 'APOYA_DISPOSICION'

    # Novedades que le exigen al ayudante subir una FOTO como evidencia. Las
    # sube desde un enlace con token que le llega por correo (no tiene usuario).
    NOVEDADES_CON_FOTO = (
        'INICIA_CLIENTE', 'TERMINA_CLIENTE', 'INICIA_PARQUEADERO', 'PUNTO_ENCUENTRO',
        # El ingreso tarde se sustenta con la foto de la hora de llegada: es la
        # evidencia de que la demora no fue del ayudante sino del conductor.
        'INICIA_BODEGA_TARDE',
    )
    # Días que el enlace del ayudante sigue sirviendo después del servicio.
    DIAS_VIGENCIA_ACCESO = 7

    programacion = models.ForeignKey(Programacion, on_delete=models.CASCADE, related_name='cuadrillas')
    conductor = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
        related_name='cuadrillas_como_conductor', null=True, blank=True
    )
    vehiculo = models.ForeignKey(
        Vehiculo, on_delete=models.PROTECT, related_name='cuadrillas',
        null=True, blank=True, verbose_name="Placa / vehículo"
    )
    # El servicio se presta SIN ayudante y así estaba previsto. Es distinto de
    # dejar el campo vacío: eso no dice si va solo o si falta asignarlo. Se
    # marca a propósito para que quede en el registro del servicio.
    conductor_solo = models.BooleanField(
        default=False, verbose_name="El conductor va solo (sin ayudante)"
    )
    ayudante = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
        related_name='cuadrillas_como_ayudante', null=True, blank=True
    )
    ayudante2 = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
        related_name='cuadrillas_como_ayudante2', null=True, blank=True,
        verbose_name="Segundo ayudante (opcional)"
    )
    # Novedades del turno de cada ayudante. Son de selección MÚLTIPLE: se guardan
    # como códigos separados por coma (ej. "INICIA_CLIENTE,RETORNA_BODEGA").
    ayudante_novedad = models.CharField(
        max_length=200, blank=True, default='', verbose_name="Novedades del ayudante"
    )
    ayudante2_novedad = models.CharField(
        max_length=200, blank=True, default='', verbose_name="Novedades del segundo ayudante"
    )
    # Vehículo del que cada ayudante apoya la disposición (solo si marcó
    # "Apoya disposición de:" en sus novedades).
    apoya_disposicion_vehiculo = models.ForeignKey(
        Vehiculo, on_delete=models.PROTECT, null=True, blank=True,
        related_name='cuadrillas_apoyo_ayudante', verbose_name="Apoya disposición del vehículo"
    )
    ayudante2_apoya_disposicion_vehiculo = models.ForeignKey(
        Vehiculo, on_delete=models.PROTECT, null=True, blank=True,
        related_name='cuadrillas_apoyo_ayudante2', verbose_name="Apoya disposición del vehículo (2º ayudante)"
    )
    orden_fila = models.PositiveSmallIntegerField(default=0, help_text="Orden de la fila en el formato")

    # Enlace personal de cada ayudante (sin usuario ni contraseña) para ver su
    # servicio y subir las fotos que le exijan sus novedades. Uno por ayudante.
    token_ayudante = models.UUIDField(default=uuid.uuid4, editable=False, null=True, unique=True)
    token_ayudante2 = models.UUIDField(default=uuid.uuid4, editable=False, null=True, unique=True)

    @staticmethod
    def novedades_display(csv):
        """Etiquetas legibles de una lista de novedades guardada como CSV."""
        etiquetas = dict(ProgramacionCuadrilla.NOVEDAD_CHOICES)
        return [etiquetas.get(c, c) for c in csv.split(',') if c]

    # ---------- Acceso del ayudante por token ----------

    def ayudante_de(self, slot):
        """El ayudante 1 o 2 de la cuadrilla (None si no hay)."""
        return self.ayudante if slot == 1 else self.ayudante2

    def novedades_de(self, slot):
        """Códigos de novedad marcados para ese ayudante."""
        csv = self.ayudante_novedad if slot == 1 else self.ayudante2_novedad
        return [c for c in (csv or '').split(',') if c]

    def token_de(self, slot):
        return self.token_ayudante if slot == 1 else self.token_ayudante2

    def fotos_pedidas(self, slot):
        """
        Novedades de ese ayudante que exigen foto: [{'codigo', 'etiqueta'}].
        Vacío si no le toca subir ninguna.
        """
        etiquetas = dict(self.NOVEDAD_CHOICES)
        return [
            {'codigo': codigo, 'etiqueta': etiquetas.get(codigo, codigo)}
            for codigo in self.novedades_de(slot)
            if codigo in self.NOVEDADES_CON_FOTO
        ]

    @property
    def fecha_limite_acceso(self):
        """Hasta cuándo sirve el enlace del ayudante."""
        return self.programacion.fecha + datetime.timedelta(days=self.DIAS_VIGENCIA_ACCESO)

    @property
    def acceso_vigente(self):
        return timezone.localdate() <= self.fecha_limite_acceso

    class Meta:
        ordering = ['orden_fila', 'id']
        verbose_name = "Cuadrilla de programación"
        verbose_name_plural = "Cuadrillas de programación"

    def __str__(self):
        placa = self.vehiculo.placa if self.vehiculo else 'sin placa'
        return f"Cuadrilla ({placa}) - {self.programacion}"


class FotoAyudante(models.Model):
    """
    Foto que sube el AYUDANTE como evidencia de una novedad de su turno (inicia
    donde el cliente, termina donde el cliente, inicia en parqueadero o punto de
    encuentro). La sube desde el enlace con token que le llega por correo, sin
    usuario ni contraseña. Puede haber varias por novedad.
    """
    cuadrilla = models.ForeignKey(
        ProgramacionCuadrilla, on_delete=models.CASCADE, related_name='fotos_ayudantes'
    )
    # 1 = ayudante, 2 = segundo ayudante de esa cuadrilla.
    slot = models.PositiveSmallIntegerField(
        choices=[(1, 'Ayudante'), (2, 'Segundo ayudante')]
    )
    novedad = models.CharField(max_length=30, help_text="Código de la novedad que la exige")
    archivo = models.ImageField(upload_to='fotos_ayudantes/')
    fecha_subida = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['fecha_subida']
        verbose_name = "Foto del ayudante"
        verbose_name_plural = "Fotos de los ayudantes"

    def __str__(self):
        return f"{self.get_novedad_display_label()} - {self.persona_nombre}"

    def get_novedad_display_label(self):
        return dict(ProgramacionCuadrilla.NOVEDAD_CHOICES).get(self.novedad, self.novedad)

    @property
    def persona(self):
        return self.cuadrilla.ayudante_de(self.slot)

    @property
    def persona_nombre(self):
        persona = self.persona
        if persona is None:
            return "—"
        return persona.get_full_name() or persona.username


class DocumentoPersonal(models.Model):
    """
    Documento del expediente de una persona (conductor o ayudante): cédula,
    seguridad social, licencia de conducción, cursos, etc. Los documentos que
    vencen (licencia, seguridad social) llevan fecha de vencimiento con alerta.
    La antelación es de 20 días, como en los vehículos, SALVO la seguridad
    social: se renueva cada mes, así que con 20 días viviría en alerta; se
    avisa solo cuando quedan 3 días.

    El expediente de una persona = todos sus DocumentoPersonal. En el expediente
    de la orden se muestran EN VIVO los documentos del conductor/ayudante de cada
    recorrido (enlace, no copia): actualizar un documento se refleja en todas las
    órdenes.
    """
    DIAS_ALERTA_VENCIMIENTO = 20
    # La seguridad social se renueva CADA MES: con la antelación general
    # estaría en alerta 20 de 30 días. Se avisa a los 3 días del vencimiento.
    DIAS_ALERTA_COBERTURA = 3
    # Nombre viejo, conservado por compatibilidad.
    DIAS_ALERTA_SEGURIDAD_SOCIAL = DIAS_ALERTA_COBERTURA

    # Documentos que acreditan la COBERTURA de la persona. Cualquiera de los
    # dos vigente la deja al día: al que acaba de ingresar todavía no se le
    # puede cargar la planilla del mes, pero sí su afiliación a la ARL, que es
    # lo que lo cubre desde el primer día (pedido de la clienta, ago-2026).
    TIPOS_COBERTURA = ('SEGURIDAD_SOCIAL', 'ARL')

    TIPO_CHOICES = [
        ('CEDULA', 'Cédula de ciudadanía'),
        ('SEGURIDAD_SOCIAL', 'Seguridad social (EPS/ARL/Pensión)'),
        ('ARL', 'Afiliación a ARL (personal nuevo)'),
        ('LICENCIA', 'Licencia de conducción'),
        ('CURSO_ALTURAS', 'Certificado curso de alturas'),
        ('CURSO_CONFINADOS', 'Certificado espacios confinados'),
        ('OTRO', 'Otro documento'),
    ]

    usuario = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name='documentos_personales'
    )
    tipo = models.CharField(max_length=20, choices=TIPO_CHOICES)
    archivo = models.FileField(upload_to='personal_documentos/')
    descripcion = models.CharField(
        max_length=200, blank=True,
        help_text="Detalle del documento, sobre todo si el tipo es 'Otro'."
    )
    # Mes que cubre el documento (formato AAAA-MM). Solo aplica a la seguridad
    # social, que se carga cada mes: se considera "al día" si existe la del mes actual.
    periodo = models.CharField(
        max_length=7, blank=True, verbose_name="Mes que cubre (seguridad social)",
        help_text="Formato AAAA-MM. La seguridad social se carga cada mes."
    )
    fecha_vencimiento = models.DateField(
        null=True, blank=True, verbose_name="Fecha de vencimiento (si aplica)"
    )
    fecha_subida = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['tipo', '-fecha_subida']
        verbose_name = "Documento del personal"
        verbose_name_plural = "Documentos del personal"

    def __str__(self):
        return f"{self.get_tipo_display()} - {self.usuario.get_full_name() or self.usuario.username}"

    @property
    def dias_restantes(self):
        if not self.fecha_vencimiento:
            return None
        return (self.fecha_vencimiento - timezone.localdate()).days

    @property
    def vencido(self):
        dias = self.dias_restantes
        return dias is not None and dias < 0

    @property
    def dias_alerta(self):
        """Antelación del aviso según el tipo (la SS mensual avisa a 3 días)."""
        if self.tipo in self.TIPOS_COBERTURA:
            return self.DIAS_ALERTA_COBERTURA
        return self.DIAS_ALERTA_VENCIMIENTO

    @property
    def por_vencer(self):
        dias = self.dias_restantes
        return dias is not None and 0 <= dias <= self.dias_alerta

    @property
    def vigente(self):
        """
        Tiene vigencia registrada (fecha de vencimiento) y aún no está vencido.
        Es la base para saber si la seguridad social está al día: ya NO depende
        del mes calendario, sino de la vigencia que se pone a mano al cargarla.
        """
        return self.fecha_vencimiento is not None and not self.vencido

    @property
    def tiene_alerta(self):
        return self.vencido or self.por_vencer


class PerfilPersona(models.Model):
    """
    Datos personales de una persona (extiende la cuenta de usuario). La ficha de
    la persona = cuenta (User) + este perfil + su expediente de documentos.
    """
    usuario = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='perfil'
    )
    numero_documento = models.CharField(max_length=30, blank=True, verbose_name="Número de documento (cédula)")
    telefono = models.CharField(max_length=30, blank=True, verbose_name="Teléfono")
    cargo = models.CharField(max_length=100, blank=True, verbose_name="Cargo")
    direccion = models.CharField(max_length=255, blank=True, verbose_name="Dirección")

    # Persona retirada (antiguo empleado). Se conserva para trazabilidad, pero ya
    # no se puede asignar en programaciones, recorridos ni planificación.
    retirado = models.BooleanField(default=False, verbose_name="Retirado")
    fecha_retiro = models.DateField(null=True, blank=True, verbose_name="Fecha de retiro")

    class Meta:
        verbose_name = "Perfil de persona"
        verbose_name_plural = "Perfiles de personas"

    def __str__(self):
        return f"Perfil de {self.usuario.get_full_name() or self.usuario.username}"

class EnvioCorreo(models.Model):
    """
    Un correo de documentación enviado desde el Centro de correos. El envío ya
    no depende de la programación: hay clientes que piden la información varios
    días antes del servicio, cuando la programación todavía no existe.

    Se guarda una copia fiel de lo enviado (destinatarios, asunto, mensaje y la
    lista de adjuntos como texto) para que el historial no cambie aunque los
    documentos del sistema se reemplacen después. `adjuntos` conserva los
    tokens marcados para poder reutilizar el envío como plantilla.
    """
    ESTADO_CHOICES = [
        ('ENVIADO', 'Enviado'),
        ('FALLIDO', 'Fallido'),
    ]

    cliente = models.ForeignKey(
        Cliente, on_delete=models.PROTECT, null=True, blank=True,
        related_name='envios_correo', verbose_name="Cliente",
    )
    destinatarios = models.CharField(
        max_length=500, verbose_name="Destinatarios",
        help_text="Uno o varios correos separados por coma.",
    )
    asunto = models.CharField(max_length=200, verbose_name="Asunto")
    mensaje = models.TextField(blank=True, verbose_name="Mensaje")
    # A dónde se dirigieron las RESPUESTAS del cliente (encabezado Reply-To).
    # Vacío = a la cuenta del sistema / al valor global de settings.
    responder_a = models.CharField(
        max_length=500, blank=True, verbose_name="Responder a",
        help_text="Correo al que llegan las respuestas de quien lo recibe.",
    )
    # Tokens de los documentos adjuntados (mismo formato que usaba la
    # programación; la resolución vive en views._resolver_adjunto_correo).
    adjuntos = models.JSONField(default=list, blank=True)
    # Copia en texto de lo que efectivamente se adjuntó: [nombre, ...].
    adjuntos_detalle = models.JSONField(default=list, blank=True)
    enviado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True,
        related_name='envios_correo', verbose_name="Enviado por",
    )
    fecha = models.DateTimeField(auto_now_add=True, verbose_name="Fecha de envío")
    estado = models.CharField(max_length=10, choices=ESTADO_CHOICES, default='ENVIADO')
    # Detalle del fallo cuando el servidor de correo rechazó el envío.
    error = models.TextField(blank=True)

    class Meta:
        ordering = ['-fecha']
        verbose_name = "Envío de correo"
        verbose_name_plural = "Envíos de correo"

    def __str__(self):
        return f"{self.asunto} → {self.destinatarios} ({self.get_estado_display()})"

    @property
    def lista_destinatarios(self):
        return [d.strip() for d in self.destinatarios.split(',') if d.strip()]


class MovimientoCargaVehiculo(models.Model):
    """
    Historial de cargas y descargas de residuo de un camión. Cada cambio del
    estado `Vehiculo.cargado` deja un registro: los automáticos (al generar la
    orden, según la disposición final) y los manuales (botón en el expediente
    del vehículo, con nota obligatoria de a dónde se dispuso o por qué).
    """
    ACCION_CHOICES = [
        ('CARGA', 'Carga'),
        ('DESCARGA', 'Descarga'),
    ]

    vehiculo = models.ForeignKey(
        'Vehiculo', on_delete=models.CASCADE, related_name='movimientos_carga',
    )
    accion = models.CharField(max_length=10, choices=ACCION_CHOICES)
    nota = models.CharField(
        max_length=255,
        help_text="De dónde viene la carga o a dónde se dispuso.",
    )
    # La orden que cargó el camión (o la que lo descargó). Es la trazabilidad
    # que el plan de trabajo muestra al asignar la disposición: "XYZ456,
    # cargado por la orden #22207". SET_NULL para no bloquear el borrado de
    # una orden desde el admin: el movimiento sobrevive como histórico.
    orden = models.ForeignKey(
        'OrdenServicio', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='movimientos_carga', verbose_name="Orden relacionada",
    )
    # Proveedor donde se dispuso el contenido (cuando aplica).
    dispositor = models.ForeignKey(
        'Dispositor', on_delete=models.PROTECT, null=True, blank=True,
        related_name='descargas_registradas', verbose_name="Proveedor de disposición",
    )
    registrado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True,
        related_name='movimientos_carga_registrados',
    )
    fecha = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-fecha']
        verbose_name = "Movimiento de carga del vehículo"
        verbose_name_plural = "Movimientos de carga de los vehículos"

    def __str__(self):
        return f"{self.get_accion_display()} {self.vehiculo.placa}: {self.nota}"


class NovedadOperacional(models.Model):
    """
    Fila del bloque NOVEDADES OPERACIONALES de la hoja del conductor: lo que
    pasó durante la jornada (varada, stand-by, tanqueo…). Solo se guardan las
    que el conductor marca, cada una con su observación y sus horas.
    """
    TIPO_CHOICES = [
        ('HOROMETRO', 'Horómetro'),
        ('MONTALLANTAS', 'Montallantas'),
        ('STANDBY', 'Stand by'),
        ('VARADA', 'Varada'),
        ('TANQUEO_EXTERNO', 'Tanqueo externo'),
        ('CAMBIO_CONDUCTOR', 'Cambio de conductor'),
        ('COMPRA_REPUESTO', 'Compra de repuesto'),
        ('DEMORA_DISPOSITOR', 'Demora en la recepción del dispositor'),
        ('DEMORA_CLIENTE', 'Demora en la atención del cliente'),
        ('RETEN_POLICIA', 'Retén de policía'),
        ('INMOVILIZACION', 'Inmovilización'),
        ('APOYO', 'Apoyo a…'),
    ]

    manifiesto = models.ForeignKey(
        Manifiesto, on_delete=models.CASCADE, related_name='novedades_operacionales'
    )
    tipo = models.CharField(max_length=20, choices=TIPO_CHOICES)
    observacion = models.CharField(max_length=255, blank=True, verbose_name="Observaciones")
    hora_inicio = models.TimeField(null=True, blank=True, verbose_name="Hora inicio")
    hora_final = models.TimeField(null=True, blank=True, verbose_name="Hora final")

    class Meta:
        # Una fila por tipo y acta: el formulario las reescribe al guardar.
        unique_together = [('manifiesto', 'tipo')]
        ordering = ['tipo']
        verbose_name = "Novedad operacional"
        verbose_name_plural = "Novedades operacionales"

    def __str__(self):
        return f"{self.get_tipo_display()} — acta del recorrido {self.manifiesto.recorrido_id}"


class MedidaACPM(models.Model):
    """
    Fila del bloque CONTROL DE ACPM: la medida inicial del tanque y hasta dos
    tanqueadas, cada una con su foto de soporte (el medidor o la factura).
    """
    INICIAL = 'INICIAL'
    TIPO_CHOICES = [
        (INICIAL, 'Medida inicial'),
        ('TANQUEADA_1', 'Medida tanqueada 1'),
        ('TANQUEADA_2', 'Medida tanqueada 2'),
    ]

    manifiesto = models.ForeignKey(
        Manifiesto, on_delete=models.CASCADE, related_name='medidas_acpm'
    )
    tipo = models.CharField(max_length=15, choices=TIPO_CHOICES)
    medida = models.CharField(
        max_length=50, blank=True, verbose_name="Medida",
        help_text="Lo que marca el medidor o los galones tanqueados.",
    )
    foto = models.ImageField(upload_to='acpm_fotos/', null=True, blank=True)

    class Meta:
        unique_together = [('manifiesto', 'tipo')]
        ordering = ['tipo']
        verbose_name = "Medida de ACPM"
        verbose_name_plural = "Control de ACPM"

    def __str__(self):
        return f"{self.get_tipo_display()}: {self.medida or '—'}"
