# gestion/models.py
from django.db import models
from django.conf import settings # Para relacionar con el usuario/asesor
from django.db.models import Sum
from django.utils import timezone


class Cliente(models.Model):
    # --- Campos existentes ---
    nombre = models.CharField(max_length=200, help_text="Razón Social de la empresa cliente")
    identificacion = models.CharField(max_length=50, unique=True, help_text="NIT o Cédula")
    direccion = models.CharField(max_length=255, blank=True)
    
    # --- Nuevos campos ---
    ciudad = models.CharField(max_length=100, blank=True)
    persona_contacto = models.CharField(max_length=200, blank=True, verbose_name="Persona de Contacto")
    cargo_contacto = models.CharField(max_length=200, blank=True, verbose_name="Cargo del Contacto")
    
    # --- Campos existentes re-contextualizados ---
    email = models.EmailField(blank=True, help_text="Correo electrónico del contacto")
    telefono = models.CharField(max_length=20, blank=True, help_text="Teléfono del contacto")

    def __str__(self):
        return self.nombre

class Vehiculo(models.Model):
    ESTADO_CHOICES = [
        ('OPERATIVO', 'Operativo'),
        ('MANTENIMIENTO', 'Mantenimiento'),
    ]

    placa = models.CharField(max_length=10, unique=True, help_text="Placa del vehículo")
    marca = models.CharField(max_length=50)
    modelo = models.CharField(max_length=50)
    capacidad = models.CharField(max_length=100, help_text="Ej: '3 toneladas', '20 m³'")
    estado = models.CharField(max_length=20, choices=ESTADO_CHOICES, default='OPERATIVO')

    def __str__(self):
        return f"{self.marca} {self.modelo} ({self.placa})"

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
    # Relación uno a uno con el recorrido. Cada viaje tiene un único manifiesto.
    recorrido = models.OneToOneField(Recorrido, on_delete=models.CASCADE, related_name='manifiesto')

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
    tiempo_inicio_operativo = models.TimeField(null=True, blank=True)
    tiempo_final_operativo = models.TimeField(null=True, blank=True)
    horometro_inicio = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    horometro_final = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    km_salida_solmed = models.IntegerField(null=True, blank=True)
    km_llegada_empresa = models.IntegerField(null=True, blank=True)
    km_llegada_disposicion = models.IntegerField(null=True, blank=True)
    
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