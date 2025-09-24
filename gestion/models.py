# gestion/models.py
from django.db import models
from django.conf import settings # Para relacionar con el usuario/asesor

class Cliente(models.Model):
    nombre = models.CharField(max_length=200, help_text="Nombre de la empresa o persona cliente")
    identificacion = models.CharField(max_length=50, unique=True, help_text="NIT, Cédula u otro identificador único")
    telefono = models.CharField(max_length=20, blank=True)
    email = models.EmailField(blank=True)
    direccion = models.CharField(max_length=255, blank=True)

    def __str__(self):
        return self.nombre

class Vehiculo(models.Model):
    ESTADO_CHOICES = [
        ('DISPONIBLE', 'Disponible'),
        ('EN_SERVICIO', 'En Servicio'),
        ('MANTENIMIENTO', 'Mantenimiento'),
    ]

    placa = models.CharField(max_length=10, unique=True, help_text="Placa del vehículo")
    marca = models.CharField(max_length=50)
    modelo = models.CharField(max_length=50)
    capacidad = models.CharField(max_length=100, help_text="Ej: '3 toneladas', '20 m³'")
    estado = models.CharField(max_length=20, choices=ESTADO_CHOICES, default='DISPONIBLE')

    def __str__(self):
        return f"{self.marca} {self.modelo} ({self.placa})"

class OrdenServicio(models.Model):
    ESTADO_ORDEN_CHOICES = [
        ('PENDIENTE', 'Pendiente'),
        ('EN_PROCESO', 'En Proceso'),
        ('FINALIZADA', 'Finalizada'),
        ('CANCELADA', 'Cancelada'),
    ]
    ESTADO_PAGO_CHOICES = [
        ('PENDIENTE', 'Pendiente'),
        ('PAGADO', 'Pagado'),
        ('ABONADO', 'Abonado'),
    ]

    # Relaciones
    cliente = models.ForeignKey(Cliente, on_delete=models.PROTECT, related_name='ordenes')
    vehiculo_asignado = models.ForeignKey(Vehiculo, on_delete=models.SET_NULL, null=True, blank=True, related_name='ordenes')
    asesor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='ordenes_creadas')

    # Detalles de la orden
    numero_orden = models.AutoField(primary_key=True)
    fecha_creacion = models.DateTimeField(auto_now_add=True)
    fecha_servicio = models.DateField()
    direccion_servicio = models.CharField(max_length=255)
    descripcion = models.TextField()
    valor_servicio = models.DecimalField(max_digits=10, decimal_places=2, default=0.00, help_text="Costo del servicio")

    # Seguimiento
    estado_orden = models.CharField(max_length=20, choices=ESTADO_ORDEN_CHOICES, default='PENDIENTE')
    estado_pago = models.CharField(max_length=20, choices=ESTADO_PAGO_CHOICES, default='PENDIENTE')

    def __str__(self):
        return f"Orden #{self.numero_orden} - {self.cliente.nombre}"

    def save(self, *args, **kwargs):
        # Lógica para actualizar el estado del vehículo automáticamente
        if self.pk is not None:
            # Obtiene la versión antigua de la orden desde la BD
            orden_antigua = OrdenServicio.objects.get(pk=self.pk)
            # Si se está finalizando o cancelando la orden, liberar el vehículo
            if self.estado_orden in ['FINALIZADA', 'CANCELADA'] and orden_antigua.vehiculo_asignado:
                vehiculo = orden_antigua.vehiculo_asignado
                vehiculo.estado = 'DISPONIBLE'
                vehiculo.save()
        
        # Si se asigna un vehículo a una orden activa, marcarlo como "En Servicio"
        if self.vehiculo_asignado and self.estado_orden not in ['FINALIZADA', 'CANCELADA']:
            vehiculo = self.vehiculo_asignado
            if vehiculo.estado == 'DISPONIBLE':
                vehiculo.estado = 'EN_SERVICIO'
                vehiculo.save()

        super().save(*args, **kwargs) # Llama al método save original


class DocumentoOrden(models.Model):
    orden = models.ForeignKey(OrdenServicio, on_delete=models.CASCADE, related_name='documentos')
    archivo = models.FileField(upload_to='ordenes_documentos/')
    descripcion = models.CharField(max_length=255, blank=True)
    fecha_subida = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        # Devuelve solo el nombre del archivo, no la ruta completa
        return self.archivo.name.split('/')[-1]