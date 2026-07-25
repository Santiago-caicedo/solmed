# gestion/admin.py
from django.contrib import admin
from .models import Cliente, Dispositor, DocumentoOrden, DocumentoPersonal, EncuestaConductor, Manifiesto, PerfilPersona, Programacion, ProgramacionCuadrilla, Sede, Vehiculo, OrdenServicio


class SedeInline(admin.TabularInline):
    model = Sede
    extra = 0


@admin.register(Cliente)
class ClienteAdmin(admin.ModelAdmin):
    list_display = ('nombre', 'identificacion', 'telefono', 'email')
    search_fields = ('nombre', 'identificacion')
    inlines = [SedeInline]

@admin.register(Vehiculo)
class VehiculoAdmin(admin.ModelAdmin):
    list_display = ('placa', 'marca', 'modelo', 'capacidad', 'estado')
    list_filter = ('estado', 'marca')
    search_fields = ('placa', 'marca', 'modelo')

@admin.register(OrdenServicio)
class OrdenServicioAdmin(admin.ModelAdmin):
    """
    Eliminar una orden aquí borra EN CASCADA todo lo asociado: recorridos,
    manifiestos, encuestas de conductor, documentos, pagos y la programación que
    la originó. La página de confirmación de Django lista todo antes de borrar.
    """
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
    """
    Eliminar una programación aquí borra también su ORDEN generada y todo lo que
    cuelga de ella (recorridos, manifiestos, encuestas, documentos y pagos): se
    limpia por completo, como si nunca se hubiera creado.
    """
    list_display = ('id', 'cliente', 'fecha', 'hora_servicio', 'estado', 'orden')
    list_filter = ('estado', 'fecha')
    search_fields = ('cliente__nombre', 'cuadrillas__vehiculo__placa')
    autocomplete_fields = ('cliente',)
    inlines = [ProgramacionCuadrillaInline]

    def _borrar_con_orden(self, programacion):
        """
        Borra la programación y su orden asociada. Al borrar la orden, la
        programación cae por CASCADE (Programacion.orden), así que basta con
        borrar la orden cuando existe.
        """
        if programacion.orden_id:
            programacion.orden.delete()   # cascada: recorridos, pagos, ... y la programación
        else:
            programacion.delete()

    def delete_model(self, request, obj):
        self._borrar_con_orden(obj)

    def delete_queryset(self, request, queryset):
        for obj in queryset:
            self._borrar_con_orden(obj)


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