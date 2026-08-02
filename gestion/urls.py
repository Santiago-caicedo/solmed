# gestion/urls.py
from django.urls import path
from . import views

app_name = 'gestion'

urlpatterns = [
    # La nueva URL del dashboard será la raíz
    path('', views.DashboardView.as_view(), name='dashboard'),
    
    # Las URLs de las órdenes ahora tendrán un prefijo
    path('ordenes/', views.ListaOrdenesView.as_view(), name='lista_ordenes'),
    # Las órdenes NO se crean a mano: siempre nacen de una programación
    # (por eso no hay ruta 'ordenes/nueva/'). Aquí solo se ven y se editan.
    path('ordenes/<int:pk>/', views.OrdenServicioDetailView.as_view(), name='detalle_orden'),
    path('ordenes/<int:pk>/editar/', views.ActualizarOrdenView.as_view(), name='actualizar_orden'),
    path('recorrido/<int:pk>/editar/', views.EditarRecorridoView.as_view(), name='editar_recorrido'),
    path('recorrido/<int:pk>/eliminar/', views.EliminarRecorridoView.as_view(), name='eliminar_recorrido'),
    path('recorrido/<int:pk>/formato/', views.ActaFormatoView.as_view(), name='acta_formato'),
    path('recorrido/<int:pk>/firmar/', views.GenerarManifiestoView.as_view(), name='firmar_manifiesto'),
    path('recorrido/<int:pk>/firmar/<str:step>/', views.GenerarManifiestoView.as_view(), name='firmar_manifiesto_step'),

    # --- Encuesta + firma del cliente vía QR ---
    path('recorrido/<int:pk>/qr/', views.ManifiestoQRView.as_view(), name='manifiesto_qr'),
    path('api/manifiesto/<int:pk>/estado/', views.manifiesto_estado_json, name='manifiesto_estado'),

    # --- Encuesta de cierre del conductor (PESV + ambiental) ---
    path('recorrido/<int:pk>/encuesta-conductor/', views.EncuestaConductorView.as_view(), name='encuesta_conductor'),
    # Página pública (sin login) que abre el cliente al escanear el QR.
    path('manifiesto-cliente/<uuid:token>/', views.EncuestaPublicaView.as_view(), name='encuesta_publica'),

    # --- Acceso del ayudante por token (sin usuario ni contraseña) ---
    # Ve su servicio y sube las fotos que le exigen sus novedades.
    path('ayudante/<uuid:token>/', views.AccesoAyudanteView.as_view(), name='acceso_ayudante'),

    # Aquí añadiremos las URLs para Clientes y Vehículos más adelante

    path('vehiculos/', views.ListaVehiculosView.as_view(), name='lista_vehiculos'),
    path('vehiculos/<int:pk>/', views.VehiculoDetailView.as_view(), name='detalle_vehiculo'),
    path('vehiculos/nuevo/', views.CrearVehiculoView.as_view(), name='crear_vehiculo'),
    path('vehiculos/<int:pk>/editar/', views.ActualizarVehiculoView.as_view(), name='actualizar_vehiculo'),
    path('vehiculos/<int:pk>/eliminar/', views.EliminarVehiculoView.as_view(), name='eliminar_vehiculo'),
    # --- Filtros y aceites (mantenimiento del vehículo) ---
    path('vehiculos/<int:pk>/filtros-aceites/', views.RegistrarFiltroAceiteView.as_view(), name='registrar_filtro_aceite'),
    path('filtro-aceite/<int:pk>/eliminar/', views.EliminarFiltroAceiteView.as_view(), name='eliminar_filtro_aceite'),

    # --- AÑADIR ESTAS LÍNEAS PARA CLIENTES ---
    path('clientes/', views.ListaClientesView.as_view(), name='lista_clientes'),
    path('clientes/nuevo/', views.CrearClienteView.as_view(), name='crear_cliente'),
    path('clientes/<int:pk>/editar/', views.ActualizarClienteView.as_view(), name='actualizar_cliente'),
    # Borrado de registros nuevos (sin uso). Solo administradores.
    path('clientes/<int:pk>/eliminar/', views.EliminarClienteView.as_view(), name='eliminar_cliente'),

    path('usuarios/', views.ListaUsuariosView.as_view(), name='lista_usuarios'),
    path('usuarios/nuevo/', views.CrearUsuarioView.as_view(), name='crear_usuario'),
    path('usuarios/<int:pk>/editar/', views.ActualizarUsuarioView.as_view(), name='actualizar_usuario'),

    path('api/calendario/', views.feed_calendario, name='feed_calendario'),
    path('calendario/', views.CalendarioView.as_view(), name='calendario'),

    path('reportes/', views.ReportesView.as_view(), name='reportes'),

    # --- Documentación interna de SOLMED ---
    path('documentacion/', views.DocumentacionSolmedView.as_view(), name='documentacion'),
    path('documentacion/<int:pk>/eliminar/', views.EliminarDocumentoInternoView.as_view(), name='eliminar_documento_interno'),

    # --- Proveedores de disposición final (Dispositor) y su expediente ---
    path('proveedores/', views.ListaDispositoresView.as_view(), name='lista_dispositores'),
    path('proveedores/nuevo/', views.CrearDispositorView.as_view(), name='crear_dispositor'),
    path('proveedores/<int:pk>/', views.FichaDispositorView.as_view(), name='ficha_dispositor'),
    path('proveedores/<int:pk>/editar/', views.ActualizarDispositorView.as_view(), name='actualizar_dispositor'),
    path('proveedores/<int:pk>/eliminar/', views.EliminarDispositorView.as_view(), name='eliminar_dispositor'),
    path('documento-dispositor/<int:pk>/eliminar/', views.EliminarDocumentoDispositorView.as_view(), name='eliminar_documento_dispositor'),

    path('dashboard-conductor/', views.DashboardConductorView.as_view(), name='dashboard_conductor'),
    path('dashboard/redirect/', views.dashboard_redirect_view, name='dashboard_redirect'),
    path('mis-recorridos/', views.MisRecorridosView.as_view(), name='mis_recorridos'),
    path('historial/', views.HistorialConductorView.as_view(), name='historial_conductor'),
    path('conductor/orden/<int:pk>/', views.OrdenConductorDetailView.as_view(), name='detalle_orden_conductor'),
    path('planificacion/', views.PlanificacionView.as_view(), name='planificacion'),

    path('ordenes/<int:orden_pk>/registrar-pago/', views.RegistrarPagoView.as_view(), name='registrar_pago'),
    # Conciliación de "Transporte - Cantidad" (el asesor la hace durante el mes).
    path('ordenes/<int:pk>/conciliar/', views.ConciliarOrdenView.as_view(), name='conciliar_orden'),

    # --- Módulo de Programación (paso previo a la orden) ---
    path('programaciones/', views.ListaProgramacionesView.as_view(), name='lista_programaciones'),
    path('programaciones/nueva/', views.CrearProgramacionView.as_view(), name='crear_programacion'),
    path('programaciones/<int:pk>/editar/', views.ActualizarProgramacionView.as_view(), name='actualizar_programacion'),
    path('programaciones/<int:pk>/convertir/', views.ConvertirProgramacionView.as_view(), name='convertir_programacion'),
    path('programaciones/<int:pk>/cancelar/', views.CancelarProgramacionView.as_view(), name='cancelar_programacion'),
    # Catálogos que se administran desde los popups de la programación
    # (crear/eliminar por AJAX, sin salir del formulario).
    path('basculas/crear/', views.CrearBasculaView.as_view(), name='crear_bascula'),
    path('bascula/<int:pk>/eliminar/', views.EliminarBasculaView.as_view(), name='eliminar_bascula'),
    path('sitios-inicio/crear/', views.CrearSitioInicioView.as_view(), name='crear_sitio_inicio'),
    path('sitio-inicio/<int:pk>/eliminar/', views.EliminarSitioInicioView.as_view(), name='eliminar_sitio_inicio'),
    path('residuos/crear/', views.CrearTipoResiduoView.as_view(), name='crear_tipo_residuo'),
    path('residuo/<int:pk>/eliminar/', views.EliminarTipoResiduoView.as_view(), name='eliminar_tipo_residuo'),

    # --- Módulo Personal (personas: cuenta + datos + expediente) ---
    path('personal/', views.ListaPersonalView.as_view(), name='lista_personal'),
    path('personal/nueva/', views.CrearPersonaView.as_view(), name='crear_persona'),
    path('personal/<int:pk>/', views.FichaPersonaView.as_view(), name='ficha_persona'),
    path('personal/<int:pk>/cuenta/', views.EditarCuentaPersonaView.as_view(), name='editar_cuenta_persona'),
    path('personal/<int:pk>/seguridad-social/', views.HistorialSeguridadSocialView.as_view(), name='historial_seguridad_social'),
    path('personal/<int:pk>/password/', views.CambiarPasswordPersonaView.as_view(), name='cambiar_password_persona'),
    path('personal/<int:pk>/estado/', views.CambiarEstadoPersonaView.as_view(), name='cambiar_estado_persona'),
    path('personal/<int:pk>/eliminar/', views.EliminarPersonaView.as_view(), name='eliminar_persona'),
    path('documento-personal/<int:pk>/eliminar/', views.EliminarDocumentoPersonalView.as_view(), name='eliminar_documento_personal'),
    path('documento-personal/<int:pk>/vigencia/', views.ActualizarVigenciaDocumentoView.as_view(), name='vigencia_documento_personal'),

]