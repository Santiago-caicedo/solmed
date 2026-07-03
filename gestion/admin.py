# gestion/admin.py
from django.contrib import admin
from .models import Cliente, Dispositor, DocumentoOrden, EncuestaConductor, Manifiesto, Programacion, ProgramacionCuadrilla, Vehiculo, OrdenServicio

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



@admin.register(Manifiesto)
class ManifiestoAdmin(admin.ModelAdmin):
    list_display = (
        'id', 
        'recorrido', 
        'fecha_creacion', 
        'tiempo_inicio_operativo', 
        'horometro_inicio', 
        'km_salida_solmed'
    )
    list_filter = ('recorrido__fecha_recorrido',)
    search_fields = ('recorrido__orden__cliente__nombre',)


@admin.register(Dispositor)
class DispositorAdmin(admin.ModelAdmin):
    list_display = ('nombre', 'descripcion', 'activo')
    list_filter = ('activo',)
    search_fields = ('nombre', 'descripcion')


class ProgramacionCuadrillaInline(admin.TabularInline):
    model = ProgramacionCuadrilla
    extra = 0
    autocomplete_fields = ('vehiculo',)


@admin.register(Programacion)
class ProgramacionAdmin(admin.ModelAdmin):
    list_display = ('id', 'cliente', 'fecha', 'hora_servicio', 'estado', 'orden')
    list_filter = ('estado', 'fecha')
    search_fields = ('cliente__nombre', 'cuadrillas__vehiculo__placa')
    autocomplete_fields = ('cliente',)
    inlines = [ProgramacionCuadrillaInline]


@admin.register(EncuestaConductor)
class EncuestaConductorAdmin(admin.ModelAdmin):
    list_display = (
        'recorrido', 'fecha_diligenciamiento', 'presento_fatiga',
        'nivel_combustible', 'tipo_residuo', 'dispositor_final', 'hubo_incidente',
    )
    list_filter = ('presento_fatiga', 'hubo_incidente', 'riesgo_vial', 'tipo_residuo')
    search_fields = ('recorrido__orden__cliente__nombre',)