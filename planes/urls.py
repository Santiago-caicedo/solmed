# planes/urls.py — plan de trabajo diario (bajo /app/plan/)
from django.urls import path

from . import views

app_name = 'planes'

urlpatterns = [
    path('', views.PlanDiaView.as_view(), name='plan_dia'),
    path('historial/', views.HistorialPlanesView.as_view(), name='historial'),
    path('novedades/', views.HistorialNovedadesView.as_view(), name='novedades'),
    # La hoja del día de una persona (fragmento para el popup del tablero).
    path('ficha/<int:pk>/', views.FichaPersonaPlanView.as_view(), name='ficha_persona'),
    path('asignacion/<int:pk>/eliminar/', views.EliminarAsignacionView.as_view(),
         name='eliminar_asignacion'),
    path('novedad/<int:pk>/eliminar/', views.EliminarNovedadView.as_view(),
         name='eliminar_novedad'),
    path('pdf/<str:fecha>/', views.PlanPDFView.as_view(), name='plan_pdf'),
]
