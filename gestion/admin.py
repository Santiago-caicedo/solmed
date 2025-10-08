# gestion/admin.py
from django.contrib import admin
from .models import Cliente, DocumentoOrden, Vehiculo, OrdenServicio

@admin.register(Cliente)
class ClienteAdmin(admin.ModelAdmin):
    list_display = ('nombre', 'identificacion', 'telefono', 'email')
    search_fields = ('nombre', 'identificacion')

@admin.register(Vehiculo)
class VehiculoAdmin(admin.ModelAdmin):
    list_display = ('placa', 'marca', 'modelo', 'capacidad', 'estado')
    list_filter = ('estado', 'marca')
    search_fields = ('placa', 'marca', 'modelo')

@admin.register(OrdenServicio)
class OrdenServicioAdmin(admin.ModelAdmin):
    # --- CORRECCIÓN AQUÍ ---
    # Eliminamos 'fecha_servicio' de ambas listas
    list_display = ('numero_orden', 'cliente', 'display_vehiculos', 'estado_orden', 'estado_pago')
    list_filter = ('estado_orden', 'estado_pago', 'cliente') # Reemplazamos fecha_servicio por cliente
    
    search_fields = ('numero_orden', 'cliente__nombre')

    def display_vehiculos(self, obj):
        # Usamos el nombre correcto 'vehiculo_asignado'
        return ", ".join([vehiculo.placa for vehiculo in obj.vehiculo_asignado.all()])
    
    display_vehiculos.short_description = 'Vehículos Asignados'
    
    display_vehiculos.short_description = 'Vehículos Asignados'
class DocumentoOrdenAdmin(admin.ModelAdmin):
    list_display = ('orden', 'archivo', 'descripcion', 'fecha_subida')