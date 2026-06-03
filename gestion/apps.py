# gestion/apps.py
from django.apps import AppConfig

def crear_roles(sender, **kwargs):
    """
    Esta función se ejecuta después de cada migración para crear los roles
    y asignarles los permisos correctos.
    """
    from django.contrib.auth.models import Group, Permission
    from django.contrib.contenttypes.models import ContentType
    
    # Define los roles y los permisos que cada uno debe tener.
    # La estructura es: 'Nombre del Rol': {'nombre_del_modelo': ['permiso1', 'permiso2']}
    ROLES = {
        "Asesores": {
            "ordenservicio": ["add", "change", "view", "delete"],
            "cliente": ["add", "change", "view", "delete"],
            "vehiculo": ["add", "change", "view", "delete"],
            "documentoorden": ["add", "change", "view", "delete"],
            "manifiesto": ["add", "change", "view", "delete"],
        },
        "Conductores": {
            "ordenservicio": ["view"],
            "vehiculo": ["view"],
            "manifiesto": ["add", "view"], # Permitirles crear y ver manifiestos
        },

        "Planificadores": {
            "recorrido": ["view", "change"], # Puede ver y MODIFICAR recorridos
            "vehiculo": ["view"],             # Necesita ver la lista de vehículos
            "user": ["view"],                 # Necesita ver la lista de usuarios (conductores)
            "ordenservicio": ["view"],        # Necesita ver las órdenes a las que pertenecen los recorridos
        }
        
    }

    for nombre_rol, permisos_rol in ROLES.items():
        # Crea el grupo si no existe, o lo obtiene si ya existe.
        grupo, created = Group.objects.get_or_create(name=nombre_rol)
        
        if created:
            print(f"Grupo '{nombre_rol}' creado.")
        
        # Limpiamos los permisos actuales para evitar duplicados en caso de cambios
        grupo.permissions.clear()

        # Iteramos sobre los modelos definidos para este rol
        for modelo, lista_permisos in permisos_rol.items():
            try:
                # Obtenemos el "tipo de contenido" (el modelo) al que se aplican los permisos.
                # El modelo 'user' vive en la app 'auth', el resto en 'gestion'.
                app_label = 'auth' if modelo == 'user' else 'gestion'
                ct = ContentType.objects.get(app_label=app_label, model=modelo)
                
                # Iteramos sobre la lista de permisos (add, change, view, delete)
                for codename_permiso in lista_permisos:
                    # Construimos el nombre clave del permiso (ej: 'add_ordenservicio')
                    codename = f"{codename_permiso}_{modelo}"
                    
                    # Obtenemos el objeto Permiso y lo añadimos al grupo
                    permiso = Permission.objects.get(content_type=ct, codename=codename)
                    grupo.permissions.add(permiso)

            except ContentType.DoesNotExist:
                print(f"Modelo '{modelo}' no encontrado. Omitiendo permisos.")
            except Permission.DoesNotExist:
                 print(f"Permiso '{codename}' no encontrado. Omitiendo.")

class GestionConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'gestion'

    def ready(self):
        """
        Este método se llama cuando la aplicación está lista.
        Conectamos la señal post_migrate con nuestra función crear_roles.
        """
        from django.db.models.signals import post_migrate
        
        # Conecta la señal
        post_migrate.connect(crear_roles, sender=self)