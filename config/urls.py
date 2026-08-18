# config/urls.py
from django.contrib import admin
from django.urls import path, include
from django.contrib.auth import views as auth_views
from django.shortcuts import redirect

# Importaciones para servir archivos en desarrollo (si no las tienes)
from django.conf import settings
from django.conf.urls.static import static

urlpatterns = [
    path('admin/', admin.site.urls),

    # --- NUEVAS RUTAS DE AUTENTICACIÓN Y RAÍZ ---
    # Página de Login: usa la vista integrada de Django pero con nuestra plantilla personalizada
    path('login/', auth_views.LoginView.as_view(template_name='gestion/login.html'), name='login'),
    
    # Ruta de Logout: usa la vista integrada de Django
    path('logout/', auth_views.LogoutView.as_view(), name='logout'),
    
    # Ruta Raíz ('/'): Si el usuario está logueado, lo lleva al dashboard. Si no, al login.
    # Cada rol tiene su propia casa (el tablero es solo del administrador):
    # de eso se encarga dashboard_redirect.
    path('', lambda request: redirect('gestion:dashboard_redirect' if request.user.is_authenticated else 'login'), name='root'),

    # El plan de trabajo diario vive en su propia app, bajo /app/plan/.
    path('app/plan/', include('planes.urls')),

    # Movemos toda la aplicación 'gestion' a un prefijo '/app/'
    path('app/', include('gestion.urls')),
]

# Servir archivos media en desarrollo
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)