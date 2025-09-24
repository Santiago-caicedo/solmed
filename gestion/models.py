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
    vehiculo_asignado = models.ManyToManyField(Vehiculo, related_name='ordenes', blank=True)
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

    


class DocumentoOrden(models.Model):
    orden = models.ForeignKey(OrdenServicio, on_delete=models.CASCADE, related_name='documentos')
    archivo = models.FileField(upload_to='ordenes_documentos/')
    descripcion = models.CharField(max_length=255, blank=True)
    fecha_subida = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        # Devuelve solo el nombre del archivo, no la ruta completa
        return self.archivo.name.split('/')[-1]