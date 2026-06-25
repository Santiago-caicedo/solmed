# gestion/models.py
import uuid
from django.db import models
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

    # --- Campos de Seguimiento ---
    estado_orden = models.CharField(max_length=20, choices=ESTADO_ORDEN_CHOICES, default='PROGRAMADA')
    estado_pago = models.CharField(max_length=20, choices=ESTADO_PAGO_CHOICES, default='PENDIENTE')

    def __str__(self):
        return f"Orden #{self.numero_orden} - {self.cliente.nombre}"

    


class DocumentoOrden(models.Model):
    orden = models.ForeignKey(OrdenServicio, on_delete=models.CASCADE, related_name='documentos')
    archivo = models.FileField(upload_to='ordenes_documentos/')
    descripcion = models.CharField(max_length=255, blank=True)
    fecha_subida = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        # Devuelve solo el nombre del archivo, no la ruta completa
        return self.archivo.name.split('/')[-1]





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
    
    fecha_recorrido = models.DateField()
    estado = models.CharField(max_length=20, choices=ESTADO_CHOICES, default='PROGRAMADO')
    descripcion = models.CharField(max_length=255, blank=True, help_text="Descripción específica de este recorrido si es necesaria")

    def __str__(self):
        return f"Recorrido del {self.fecha_recorrido} para Orden #{self.orden.numero_orden}"
    
    def save(self, *args, **kwargs):
        # Guardamos el recorrido primero
        super().save(*args, **kwargs)
        
        # Ahora, actualizamos el estado de la orden padre
        orden = self.orden
        recorridos_de_la_orden = orden.recorridos.all()
        total_recorridos = recorridos_de_la_orden.count()
        completados = recorridos_de_la_orden.filter(estado='COMPLETADO').count()

        if total_recorridos == 0:
            orden.estado_orden = 'PROGRAMADA'
        elif completados == total_recorridos:
            orden.estado_orden = 'FINALIZADA'
        else:
            orden.estado_orden = 'EN_EJECUCION'
        
        orden.save()



class Manifiesto(models.Model):
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

    # Cada pago está ligado a una Orden de Servicio
    orden = models.ForeignKey(OrdenServicio, on_delete=models.PROTECT, related_name='pagos')
    
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
    nombre = models.CharField(max_length=200, verbose_name="Nombre del gestor / dispositor")
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