# gestion/models.py
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
    certificaciones bancarias, RIT, certificados de Contraloría y Procuraduría.
    Algunos llevan fecha (RUT, cámara). La certificación bancaria puede tener
    varias (una por cuenta/banco), distinguidas por `entidad`.
    """
    TIPO_CHOICES = [
        ('RUT', 'RUT'),
        ('CAMARA_COMERCIO', 'Cámara de Comercio'),
        ('CEDULA_REP_LEGAL', 'Cédula del representante legal'),
        ('CEDULA_REP_SUPLENTE', 'Cédula del representante legal suplente'),
        ('ESTADOS_FINANCIEROS', 'Estados financieros'),
        ('CERTIFICACION_BANCARIA', 'Certificación bancaria'),
        ('RIT', 'RIT'),
        ('CERT_CONTRALORIA', 'Certificado de la Contraloría'),
        ('CERT_PROCURADURIA', 'Certificado de la Procuraduría'),
    ]
    # Tipos que llevan fecha del documento (para que las áreas la conozcan).
    TIPOS_CON_FECHA = ('RUT', 'CAMARA_COMERCIO')
    # Tipo que admite varios (una certificación por cuenta/banco).
    TIPO_MULTIPLE = 'CERTIFICACION_BANCARIA'
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
        return f"{self.get_tipo_display()}{' - ' + self.entidad if self.entidad else ''}"


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

    def __str__(self):
        return f"Orden #{self.numero_orden} - {self.cliente.nombre}"

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
    horometro_inicio = models.TimeField(null=True, blank=True, verbose_name="H. Inicio (Horómetro)")
    horometro_final = models.TimeField(null=True, blank=True, verbose_name="H. Final (Horómetro)")
    km_salida_solmed = models.IntegerField(null=True, blank=True, verbose_name="Salida SolMed (Km)")
    km_llegada_empresa = models.IntegerField(null=True, blank=True, verbose_name="Llegada Empresa (Km)")
    km_llegada_disposicion = models.IntegerField(null=True, blank=True, verbose_name="Llegada Sitio Disposición (Km)")
    km_llegada_solmed = models.IntegerField(null=True, blank=True, verbose_name="Llegada Solmed (Km)") 
    
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
    pdf_generado = models.FileField(upload_to='manifiestos_pdf/', blank=True, null=True)
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

    def __str__(self):
        return self.nombre


class EncuestaConductor(models.Model):
    """
    Encuesta operativa que llena EL CONDUCTOR al cerrar el servicio, una vez firmado
    el manifiesto del cliente. Es evidencia de cumplimiento del PESV (Plan Estratégico
    de Seguridad Vial) y de la gestión ambiental de SOLMED SAS.
    Diligenciarla marca automáticamente el recorrido como COMPLETADO (es obligatoria).
    """
    SI_NO_CHOICES = [('SI', 'Sí'), ('NO', 'No')]

    NIVEL_COMBUSTIBLE_CHOICES = [
        ('1/4', '¼'),
        ('1/2', '½'),
        ('3/4', '¾'),
        ('FULL', 'Full'),
    ]

    TIPO_RESIDUO_CHOICES = [
        ('AGUAS_DOM_SEPT', 'Aguas domésticas/sépticas'),
        ('AGUAS_LLUVIAS', 'Aguas lluvias'),
        ('TRAMPAS_GRASA', 'Trampas de grasa'),
        ('AGUAS_HIDROCARBURADAS', 'Aguas hidrocarburadas (RESPEL)'),
        ('OTROS_RESPEL', 'Otros RESPEL'),
        ('ORGANICOS', 'Orgánicos'),
        ('ESCOMBROS', 'Escombros'),
    ]

    RIESGO_VIAL_CHOICES = [
        ('NINGUNA', 'Ninguna'),
        ('VIA_MAL_ESTADO', 'Vía en mal estado/huecos'),
        ('FALTA_ILUMINACION', 'Falta de iluminación'),
        ('SENALIZACION_DEFICIENTE', 'Señalización deficiente'),
        ('PUNTO_CRITICO', 'Punto crítico de accidentes'),
    ]

    TIPO_INCIDENTE_CHOICES = [
        ('FALLA_MECANICA', 'Falla mecánica (Varada)'),
        ('INCIDENTE_MENOR', 'Incidente menor (Roce o golpe simple)'),
        ('SINIESTRO_TERCEROS', 'Siniestro vial con terceros'),
    ]

    recorrido = models.OneToOneField(
        Recorrido, on_delete=models.CASCADE, related_name='encuesta_conductor'
    )

    # --- 1. Control de Fatiga y Nivel de Combustible ---
    presento_fatiga = models.CharField(
        max_length=2, choices=SI_NO_CHOICES,
        verbose_name="¿Presentó síntomas de fatiga, cansancio o microsueños durante la ruta?"
    )
    nivel_combustible = models.CharField(
        max_length=4, choices=NIVEL_COMBUSTIBLE_CHOICES,
        verbose_name="Nivel de combustible al cierre del servicio"
    )

    # --- 2. Caracterización del Residuo y Dispositor Final ---
    tipo_residuo = models.CharField(
        max_length=30, choices=TIPO_RESIDUO_CHOICES,
        verbose_name="Tipo de residuo transportado"
    )
    dispositor_final = models.ForeignKey(
        Dispositor, on_delete=models.PROTECT, related_name='encuestas',
        verbose_name="Dispositor final / destino autorizado"
    )

    # --- 3. Reporte de Novedades en la Vía ---
    riesgo_vial = models.CharField(
        max_length=30, choices=RIESGO_VIAL_CHOICES, default='NINGUNA',
        verbose_name="Condiciones de riesgo identificadas en la infraestructura vial"
    )

    # --- 4. Gestión de Incidentes en Ruta ---
    hubo_incidente = models.CharField(
        max_length=2, choices=SI_NO_CHOICES,
        verbose_name="¿Se presentó algún incidente, varada o evento vial durante el trayecto?"
    )
    tipo_incidente = models.CharField(
        max_length=20, choices=TIPO_INCIDENTE_CHOICES, blank=True,
        verbose_name="Tipo de evento"
    )
    descripcion_incidente = models.TextField(
        blank=True, verbose_name="Descripción del incidente (opcional)"
    )

    # --- PDF generado (evidencia documental independiente) ---
    pdf_generado = models.FileField(upload_to='encuestas_conductor_pdf/', blank=True, null=True)
    fecha_diligenciamiento = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Encuesta de cierre del conductor"
        verbose_name_plural = "Encuestas de cierre del conductor"

    def __str__(self):
        return f"Encuesta de cierre - Recorrido #{self.recorrido_id}"

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        # Diligenciar la encuesta de cierre marca el recorrido como COMPLETADO,
        # lo que a su vez actualiza el estado de la orden padre (lógica de Recorrido.save).
        recorrido = self.recorrido
        if recorrido.estado != 'COMPLETADO':
            recorrido.estado = 'COMPLETADO'
            recorrido.save()


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
    hora_ingreso_bodega = models.TimeField(null=True, blank=True, verbose_name="Hora ingreso a bodega")
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
    direccion = models.CharField(
        max_length=255, blank=True,
        help_text="Se arrastra a la orden al convertir. Si se deja vacío se usa la dirección del cliente."
    )
    correo_seguridad_social = models.EmailField(
        blank=True, verbose_name="Correo del cliente (seguridad social)",
        help_text="Correo del cliente a donde se comparten los documentos de seguridad social."
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

    def __str__(self):
        return f"Programación #{self.pk} - {self.cliente.nombre} ({self.fecha})"

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

        # La dirección del servicio: la de la sede elegida, si no la de la
        # programación, si no la del cliente.
        direccion_servicio = (
            (self.sede_cliente.direccion if self.sede_cliente_id else '')
            or self.direccion or self.cliente.direccion or 'Por definir'
        )

        with transaction.atomic():
            orden = OrdenServicio.objects.create(
                cliente=self.cliente,
                asesor=usuario,
                direccion_servicio=direccion_servicio,
                descripcion=self.observaciones_servicio or f'Orden generada desde la programación #{self.pk}',
                bascula=self.bascula,
                registro_fotografico=self.registro_fotografico,
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
            self._actualizar_carga_vehiculos(orden, [c.vehiculo for c in cuadrillas])
        return orden

    def _actualizar_carga_vehiculos(self, orden, vehiculos):
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
        """
        detalle = f"Orden #{orden.numero_orden} del {self.fecha.strftime('%d/%m/%Y')}"
        if self.requiere_disposicion_final == 'SI':
            for v in vehiculos:
                if v.cargado:
                    v.cargado = False
                    v.cargado_detalle = ''
                    v.save(update_fields=['cargado', 'cargado_detalle'])
            return
        if self.requiere_disposicion_final != 'NO' or not self.dispositor_final_id:
            return

        destino = self.dispositor_final.nombre
        if destino == Dispositor.DEJAR_CARRO_CARGADO:
            for v in vehiculos:
                v.cargado = True
                v.cargado_detalle = f"{detalle}: quedó cargado (sin disposición)"
                v.save(update_fields=['cargado', 'cargado_detalle'])
        elif destino == Dispositor.TRASIEGO_PLACA and self.trasiego_vehiculo_id:
            destino_v = self.trasiego_vehiculo
            destino_v.cargado = True
            destino_v.cargado_detalle = f"{detalle}: recibió trasiego (sin disposición)"
            destino_v.save(update_fields=['cargado', 'cargado_detalle'])
            for v in vehiculos:
                if v.pk != destino_v.pk and v.cargado:
                    v.cargado = False
                    v.cargado_detalle = ''
                    v.save(update_fields=['cargado', 'cargado_detalle'])
        elif destino in Dispositor.TANQUES:
            for v in vehiculos:
                if v.cargado:
                    v.cargado = False
                    v.cargado_detalle = ''
                    v.save(update_fields=['cargado', 'cargado_detalle'])


class ProgramacionCuadrilla(models.Model):
    """
    Una fila del bloque CONDUCTOR / PLACA / AYUDANTE del formato de programación.
    Cada cuadrilla con vehículo genera un Recorrido al convertir la programación.
    `ayudante_novedad` captura cómo cubre el turno el ayudante ese día (dónde lo
    inicia o lo termina, si retorna a bodega o si apoya una disposición).
    """
    NOVEDAD_CHOICES = [
        ('TERMINA_CLIENTE', 'Termina turno donde el cliente'),
        ('TERMINA_DISPOSICION', 'Termina turno en el sitio de disposición'),
        ('RETORNA_BODEGA', 'Retorna a bodega'),
        ('INICIA_CLIENTE', 'Inicia turno donde el cliente'),
        ('APOYA_DISPOSICION', 'Apoya disposición de:'),
    ]
    # Novedad que requiere indicar de cuál vehículo se apoya la disposición.
    APOYA_DISPOSICION = 'APOYA_DISPOSICION'

    programacion = models.ForeignKey(Programacion, on_delete=models.CASCADE, related_name='cuadrillas')
    conductor = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
        related_name='cuadrillas_como_conductor', null=True, blank=True
    )
    vehiculo = models.ForeignKey(
        Vehiculo, on_delete=models.PROTECT, related_name='cuadrillas',
        null=True, blank=True, verbose_name="Placa / vehículo"
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

    @staticmethod
    def novedades_display(csv):
        """Etiquetas legibles de una lista de novedades guardada como CSV."""
        etiquetas = dict(ProgramacionCuadrilla.NOVEDAD_CHOICES)
        return [etiquetas.get(c, c) for c in csv.split(',') if c]

    class Meta:
        ordering = ['orden_fila', 'id']
        verbose_name = "Cuadrilla de programación"
        verbose_name_plural = "Cuadrillas de programación"

    def __str__(self):
        placa = self.vehiculo.placa if self.vehiculo else 'sin placa'
        return f"Cuadrilla ({placa}) - Programación #{self.programacion_id}"


class DocumentoPersonal(models.Model):
    """
    Documento del expediente de una persona (conductor o ayudante): cédula,
    seguridad social, licencia de conducción, cursos, etc. Los documentos que
    vencen (licencia, seguridad social) llevan fecha de vencimiento con alerta,
    igual que los documentos de los vehículos (misma antelación de 20 días).

    El expediente de una persona = todos sus DocumentoPersonal. En el expediente
    de la orden se muestran EN VIVO los documentos del conductor/ayudante de cada
    recorrido (enlace, no copia): actualizar un documento se refleja en todas las
    órdenes.
    """
    DIAS_ALERTA_VENCIMIENTO = 20

    TIPO_CHOICES = [
        ('CEDULA', 'Cédula de ciudadanía'),
        ('SEGURIDAD_SOCIAL', 'Seguridad social (EPS/ARL/Pensión)'),
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
    def por_vencer(self):
        dias = self.dias_restantes
        return dias is not None and 0 <= dias <= self.DIAS_ALERTA_VENCIMIENTO

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