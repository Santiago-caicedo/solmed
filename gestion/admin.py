# gestion/admin.py
from django.contrib import admin
from .models import Cliente, Vehiculo, OrdenServicio

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
    list_display = ('numero_orden', 'cliente', 'fecha_servicio', 'vehiculo_asignado', 'estado_orden', 'estado_pago')
    list_filter = ('estado_orden', 'estado_pago', 'fecha_servicio')
    search_fields = ('numero_orden', 'cliente__nombre')
    autocomplete_fields = ['cliente', 'vehiculo_asignado'] # Mejora la selección