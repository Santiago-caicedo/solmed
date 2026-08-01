"""
Banderas de rol para las plantillas.

Antes el menú decidía con `user.groups.all.0.name`, que depende del ORDEN de
los grupos: alguien con dos roles podía perder secciones. Aquí se calculan una
sola vez por petición y con la misma lógica que los mixins de las vistas.
"""


def roles(request):
    user = getattr(request, 'user', None)
    if user is None or not user.is_authenticated:
        return {}

    nombres = set(user.groups.values_list('name', flat=True))
    # El rol Administradores hace todo lo del superusuario DENTRO de la app;
    # lo único que no puede es entrar al admin de Django (necesita is_staff).
    es_administrador = user.is_superuser or 'Administradores' in nombres

    return {
        'es_administrador': es_administrador,
        'es_asesor': es_administrador or 'Asesores' in nombres,
        'es_planificador': es_administrador or 'Planificadores' in nombres,
        # Un administrador que además esté en Conductores no ve el menú del
        # conductor: manda su rol de gestión.
        'es_conductor': 'Conductores' in nombres and not es_administrador,
        'puede_admin_django': user.is_staff or user.is_superuser,
    }
