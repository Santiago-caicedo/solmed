# gestion/urls.py
from django.urls import path
from . import views

app_name = 'gestion'

urlpatterns = [
    # La nueva URL del dashboard será la raíz
    path('', views.DashboardView.as_view(), name='dashboard'),
    
    # Las URLs de las órdenes ahora tendrán un prefijo
    path('ordenes/', views.ListaOrdenesView.as_view(), name='lista_ordenes'),
    path('ordenes/nueva/', views.CrearOrdenView.as_view(), name='crear_orden'),
    path('ordenes/<int:pk>/', views.OrdenServicioDetailView.as_view(), name='detalle_orden'),
    path('ordenes/<int:pk>/editar/', views.ActualizarOrdenView.as_view(), name='actualizar_orden'),
    path('recorrido/<int:pk>/firmar/', views.GenerarManifiestoView.as_view(), name='firmar_manifiesto'),
    path('recorrido/<int:pk>/firmar/<str:step>/', views.GenerarManifiestoView.as_view(), name='firmar_manifiesto_step'),

    # --- Encuesta + firma del cliente vía QR ---
    path('recorrido/<int:pk>/qr/', views.ManifiestoQRView.as_view(), name='manifiesto_qr'),
    path('api/manifiesto/<int:pk>/estado/', views.manifiesto_estado_json, name='manifiesto_estado'),
    # Página pública (sin login) que abre el cliente al escanear el QR.
    path('manifiesto-cliente/<uuid:token>/', views.EncuestaPublicaView.as_view(), name='encuesta_publica'),

    # Aquí añadiremos las URLs para Clientes y Vehículos más adelante

    path('vehiculos/', views.ListaVehiculosView.as_view(), name='lista_vehiculos'),
    path('vehiculos/<int:pk>/', views.VehiculoDetailView.as_view(), name='detalle_vehiculo'),
    path('vehiculos/nuevo/', views.CrearVehiculoView.as_view(), name='crear_vehiculo'),
    path('vehiculos/<int:pk>/editar/', views.ActualizarVehiculoView.as_view(), name='actualizar_vehiculo'),

    # --- AÑADIR ESTAS LÍNEAS PARA CLIENTES ---
    path('clientes/', views.ListaClientesView.as_view(), name='lista_clientes'),
    path('clientes/nuevo/', views.CrearClienteView.as_view(), name='crear_cliente'),
    path('clientes/<int:pk>/editar/', views.ActualizarClienteView.as_view(), name='actualizar_cliente'),

    path('usuarios/', views.ListaUsuariosView.as_view(), name='lista_usuarios'),
    path('usuarios/nuevo/', views.CrearUsuarioView.as_view(), name='crear_usuario'),
    path('usuarios/<int:pk>/editar/', views.ActualizarUsuarioView.as_view(), name='actualizar_usuario'),

    path('api/calendario/', views.feed_calendario, name='feed_calendario'),
    path('calendario/', views.CalendarioView.as_view(), name='calendario'),

    path('reportes/', views.ReportesView.as_view(), name='reportes'),

    path('dashboard-conductor/', views.DashboardConductorView.as_view(), name='dashboard_conductor'),
    path('dashboard/redirect/', views.dashboard_redirect_view, name='dashboard_redirect'),
    path('mis-recorridos/', views.MisRecorridosView.as_view(), name='mis_recorridos'),
    path('planificacion/', views.PlanificacionView.as_view(), name='planificacion'),

    path('ordenes/<int:orden_pk>/registrar-pago/', views.RegistrarPagoView.as_view(), name='registrar_pago'),

]