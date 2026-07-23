# gestion/admin.py
from django.contrib import admin
from .models import Cliente, Dispositor, DocumentoOrden, DocumentoPersonal, EncuestaConductor, Manifiesto, PerfilPersona, Programacion, ProgramacionCuadrilla, Vehiculo, OrdenServicio

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
    list_display = ('numero_orden', 'cliente', 'display_vehiculos', 'estado_orden', 'estado_pago')
    list_filter = ('estado_orden', 'estado_pago', 'cliente')
    search_fields = ('numero_orden', 'cliente__nombre')

    def get_queryset(self, request):
        # Precargamos los vehículos de los recorridos para no consultar por fila.
        return super().get_queryset(request).prefetch_related('recorridos__vehiculo')

    @admin.display(description='Vehículos Asignados')
    def display_vehiculos(self, obj):
        # Los vehículos ya no cuelgan de la orden, sino de cada recorrido.
        placas = sorted({
            recorrido.vehiculo.placa
            for recorrido in obj.recorridos.all() if recorrido.vehiculo_id
        })
        return ", ".join(placas) or "—"
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


@admin.register(DocumentoPersonal)
class DocumentoPersonalAdmin(admin.ModelAdmin):
    list_display = ('usuario', 'tipo', 'periodo', 'fecha_vencimiento', 'fecha_subida')
    list_filter = ('tipo',)
    search_fields = ('usuario__username', 'usuario__first_name', 'usuario__last_name')


@admin.register(PerfilPersona)
class PerfilPersonaAdmin(admin.ModelAdmin):
    list_display = ('usuario', 'numero_documento', 'telefono', 'cargo')
    search_fields = ('usuario__username', 'usuario__first_name', 'usuario__last_name', 'numero_documento')


@admin.register(EncuestaConductor)
class EncuestaConductorAdmin(admin.ModelAdmin):
    list_display = (
        'recorrido', 'fecha_diligenciamiento', 'presento_fatiga',
        'nivel_combustible', 'tipo_residuo', 'dispositor_final', 'hubo_incidente',
    )
    list_filter = ('presento_fatiga', 'hubo_incidente', 'riesgo_vial', 'tipo_residuo')
    search_fields = ('recorrido__orden__cliente__nombre',)