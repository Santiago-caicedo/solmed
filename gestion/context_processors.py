"""
Banderas de rol para las plantillas.

Antes el menú decidía con `user.groups.all.0.name`, que depende del ORDEN de
los grupos: alguien con dos roles podía perder secciones. Aquí se calculan una
sola vez por petición y con la misma lógica que los mixins de las vistas.

Nov-2026 (accesos por persona del asesor, ver gestion/accesos.py): además va
`acceso`, un dict {modulo: {accion: bool}} para `{% if acceso.ordenes.ver %}`.
Para un administrador todo es True; para un asesor, sus casillas; para los
demás roles, todo False (ellos siguen con sus banderas de rol de siempre).
Las banderas que incluían al asesor (`ve_personal`, `ve_basculas`…) se
recortan con sus casillas, así el menú no ofrece lo que no puede abrir.
"""

from .accesos import para_plantilla
from .roles import GRUPOS_BASCULA, GRUPOS_DISPOSICION_FINAL, GRUPOS_PESV


def roles(request):
    user = getattr(request, 'user', None)
    if user is None or not user.is_authenticated:
        return {}

    nombres = set(user.groups.values_list('name', flat=True))
    # El rol Administradores hace todo lo del superusuario DENTRO de la app;
    # lo único que no puede es entrar al admin de Django (necesita is_staff).
    es_administrador = user.is_superuser or 'Administradores' in nombres

    # Talento Humano solo trabaja el módulo de Personal: no es asesor.
    es_talento_humano = 'Talento Humano' in nombres and not es_administrador

    acceso = para_plantilla(user)
    # Un asesor (no administrador) solo cuenta como tal en cada módulo si
    # tiene la casilla; los demás roles entran por su grupo, como siempre.
    es_asesor = 'Asesores' in nombres and not es_administrador

    def asesor_con(clave):
        modulo, accion = clave.split('.')
        return es_asesor and acceso[modulo][accion]

    def otro_rol_en(grupos):
        return bool((nombres - {'Asesores'}) & set(grupos))

    return {
        'es_administrador': es_administrador,
        'es_asesor': es_administrador or 'Asesores' in nombres,
        'es_talento_humano': es_talento_humano,
        'acceso': acceso,
        # Quién puede entrar al módulo de Personal.
        've_personal': (es_administrador or asesor_con('personal.ver')
                        or es_talento_humano),
        # Quién crea y edita personas (Talento Humano siempre; el asesor, con casilla).
        'edita_personal': (es_administrador or asesor_con('personal.editar')
                           or es_talento_humano),
        'es_planificador': es_administrador or 'Planificadores' in nombres,
        # Quién ve la pantalla de básculas (ver GRUPOS_BASCULA en roles.py).
        've_basculas': (es_administrador or asesor_con('basculas.ver')
                        or otro_rol_en(GRUPOS_BASCULA)),
        # Quién ve el gestor de disposiciones finales (GRUPOS_DISPOSICION_FINAL).
        've_disposiciones_finales': (es_administrador or asesor_con('certificados.ver')
                                     or otro_rol_en(GRUPOS_DISPOSICION_FINAL)),
        # Quién SUBE tiquetes y quién sube/envía certificados (los botones de
        # esas pantallas): los cargos de oficina siempre; el asesor, con casilla.
        'sube_basculas': (es_administrador or asesor_con('basculas.subir')
                          or otro_rol_en(GRUPOS_BASCULA)),
        'gestiona_certificados': (es_administrador or asesor_con('certificados.gestionar')
                                  or otro_rol_en(GRUPOS_DISPOSICION_FINAL)),
        # Quién ve la carpeta del PESV (GRUPOS_PESV).
        've_pesv': es_administrador or bool(nombres & set(GRUPOS_PESV)),
        # Un administrador que además esté en Conductores no ve el menú del
        # conductor: manda su rol de gestión.
        'es_conductor': 'Conductores' in nombres and not es_administrador,
        'puede_admin_django': user.is_staff or user.is_superuser,
        # Encabezados del menú: solo si hay algo debajo.
        've_operacion': any(acceso[m]['ver'] for m in (
            'calendario', 'plan', 'disposiciones', 'visitas', 'cotizaciones', 'programacion',
            'ordenes', 'fotos', 'correos')),
        've_gestion': any(acceso[m]['ver'] for m in (
            'clientes', 'vehiculos', 'proveedores', 'documentacion', 'facturacion', 'gastos')),
    }
