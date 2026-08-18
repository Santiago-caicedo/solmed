from django.contrib import admin

from .models import Asignacion, Novedad, PlanDia


class AsignacionInline(admin.TabularInline):
    model = Asignacion
    extra = 0
    autocomplete_fields = []


@admin.register(PlanDia)
class PlanDiaAdmin(admin.ModelAdmin):
    list_display = ('fecha', 'creado_por', 'fecha_creacion')
    date_hierarchy = 'fecha'
    inlines = [AsignacionInline]


@admin.register(Novedad)
class NovedadAdmin(admin.ModelAdmin):
    list_display = ('persona', 'tipo', 'fecha_inicio', 'fecha_fin', 'registrado_por')
    list_filter = ('tipo',)
    search_fields = ('persona__first_name', 'persona__last_name', 'persona__username')
