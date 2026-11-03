"""
Accesos por persona del rol ASESORES (nov-2026, pedido de Santiago).

Hasta ahora la autorización iba solo por rol: todo asesor podía lo mismo.
Desde la ficha de la persona, un administrador marca con casillas lo que
cada asesor puede y no puede hacer («Gestionar accesos»). Las casillas
sirven para RECORTAR lo que el rol ya podía (p. ej. quitarle Clientes) y
también para AMPLIARLE módulos que eran solo de administradores (Plan de
trabajo, Facturación…), decisión de Santiago.

Cómo funciona:
- El catálogo de abajo (MODULOS) es la única lista de lo que se puede marcar.
  Cada acción tiene una clave `modulo.accion`. Las marcadas `base=True` son
  las que el rol tenía de siempre: un asesor SIN registro de accesos (los que
  ya existían al desplegar, y los nuevos) tiene exactamente esas, así nada
  cambia hasta que un administrador toque sus casillas.
- Las vistas declaran `acceso = 'ordenes.ver'` (y `acceso_escribir` para el
  POST). Los mixins de gestion/views.py consultan `autoriza()`:
    * administradores: todo, siempre (las casillas no les aplican);
    * asesores: por sus casillas; si la vista no declara `acceso`, se sigue
      decidiendo por rol como antes;
    * los demás roles: como antes, por rol (las casillas no les aplican).
- El menú y los botones de las plantillas usan `acceso.modulo.accion`
  (context processor `roles`), así lo que no se puede abrir tampoco se ofrece.

La CARTERA de clientes sigue aplicando aparte: un asesor con acceso a un
módulo ve en él solo sus clientes, donde ese módulo la recorta.
"""

# Las acciones de cada módulo: (sufijo, nombre, descripción, base).
# `base` = lo tenía el rol Asesores antes de los accesos por persona.
MODULOS = [
    {
        'clave': 'calendario', 'nombre': 'Calendario', 'icono': 'bi-calendar3',
        'descripcion': 'La agenda de servicios, por día y por placa.',
        'acciones': [
            ('ver', 'Ver el calendario', 'Entra al calendario y ve los servicios de sus clientes.', True),
        ],
    },
    {
        'clave': 'visitas', 'nombre': 'Visitas técnicas', 'icono': 'bi-clipboard2-pulse',
        'descripcion': 'Las visitas antes de cotizar y programar (formato GC-F-01).',
        'acciones': [
            ('ver', 'Ver las visitas', 'La lista, el detalle y el PDF de cada visita.', True),
            ('gestionar', 'Programar y registrar', 'Programar, editar, reenviar la solicitud, registrar el campo y la firma.', True),
        ],
    },
    {
        'clave': 'programacion', 'nombre': 'Programación', 'icono': 'bi-calendar-plus',
        'descripcion': 'La programación de los servicios antes de volverse órdenes.',
        'acciones': [
            ('ver', 'Ver las programaciones', 'La lista de programaciones.', True),
            ('editar', 'Crear y editar', 'Crear y editar programaciones, puntos de registro fotográfico y catálogos (básculas, sitios, residuos).', True),
            ('convertir', 'Convertir y cancelar', 'Convertir una programación en orden de servicio o cancelarla.', True),
        ],
    },
    {
        'clave': 'ordenes', 'nombre': 'Órdenes de servicio', 'icono': 'bi-clipboard-data',
        'descripcion': 'El seguimiento de cada servicio: expediente, acta, soportes.',
        'acciones': [
            ('ver', 'Ver las órdenes', 'La lista, el expediente, el acta y los PDF (acta, encuesta, preoperacional).', True),
            ('editar', 'Editar y llenar el acta', 'Editar la orden y el recorrido, llenar el acta y sus tiempos, subir soportes y fotos, registrar el preoperacional.', True),
            ('conciliar', 'Conciliar', 'Conciliar las órdenes y ver la pantalla de conciliaciones.', True),
            ('anular_firma', 'Anular la firma del acta', 'Anular la firma y la encuesta del cliente de un acta (con doble confirmación).', True),
            ('numero', 'Cambiar el número de la orden', 'Cambiar el consecutivo de una orden. Era solo de administradores.', False),
        ],
    },
    {
        'clave': 'fotos', 'nombre': 'Fotos', 'icono': 'bi-images',
        'descripcion': 'Las fotos de los ayudantes y el registro fotográfico de los servicios, por día.',
        'acciones': [
            ('ver', 'Ver las fotos', '«Fotos de ayudantes» y «Fotos de servicios».', True),
        ],
    },
    {
        'clave': 'correos', 'nombre': 'Centro de correos', 'icono': 'bi-envelope-paper',
        'descripcion': 'Los correos de documentación que se le envían al cliente.',
        'acciones': [
            ('ver', 'Ver los correos', 'La lista de envíos y el detalle de cada uno.', True),
            ('enviar', 'Enviar correos', 'Armar y enviar correos con documentos y actas firmadas.', True),
        ],
    },
    {
        'clave': 'clientes', 'nombre': 'Clientes', 'icono': 'bi-buildings',
        'descripcion': 'Los clientes de su cartera, con su ficha e histórico.',
        'acciones': [
            ('ver', 'Ver los clientes', 'La lista, la ficha y el histórico de cada cliente.', True),
            ('editar', 'Crear y editar', 'Crear clientes y editar sus datos. Asignar asesoras sigue siendo de administradores.', True),
            ('eliminar', 'Eliminar', 'Eliminar un cliente sin movimientos. Era solo de administradores.', False),
        ],
    },
    {
        'clave': 'vehiculos', 'nombre': 'Vehículos', 'icono': 'bi-truck-front',
        'descripcion': 'La flota, con su hoja de vida y sus filtros y aceite.',
        'acciones': [
            ('ver', 'Ver los vehículos', 'La lista y la ficha de cada vehículo.', True),
            ('editar', 'Crear y editar', 'Crear y editar vehículos y registrar cambios de filtros y aceite.', True),
            ('eliminar', 'Eliminar', 'Eliminar un vehículo. Era solo de administradores.', False),
        ],
    },
    {
        'clave': 'proveedores', 'nombre': 'Proveedores', 'icono': 'bi-recycle',
        'descripcion': 'Los gestores de disposición y los proveedores generales.',
        'acciones': [
            ('ver', 'Ver los proveedores', 'Las listas y la ficha de cada proveedor.', True),
            ('editar', 'Crear y editar', 'Crear y editar proveedores y sus documentos.', True),
            ('eliminar', 'Eliminar', 'Eliminar un proveedor. Era solo de administradores.', False),
        ],
    },
    {
        'clave': 'documentacion', 'nombre': 'Documentación', 'icono': 'bi-folder-fill',
        'descripcion': 'Los documentos internos de SOLMED.',
        'acciones': [
            ('ver', 'Ver la documentación', 'Consultar y descargar los documentos.', True),
            ('editar', 'Subir y quitar', 'Subir documentos nuevos y quitar los que sobren.', True),
        ],
    },
    {
        'clave': 'personal', 'nombre': 'Personal', 'icono': 'bi-people-fill',
        'descripcion': 'El personal de la empresa, con su expediente.',
        'acciones': [
            ('ver', 'Ver el personal', 'La lista y la ficha de cada persona.', True),
            ('editar', 'Crear y editar', 'Crear personas, editar cuentas y roles, cambiar contraseñas, cargar documentos, retirar y reactivar.', True),
            ('centro_control', 'Centro de control', 'El centro de control de cada persona (pantalla, PDF y Excel) y cambiar la fecha de retiro. Era solo de administradores.', False),
            ('eliminar', 'Eliminar', 'Eliminar una persona sin servicios. Era solo de administradores.', False),
        ],
    },
    {
        'clave': 'basculas', 'nombre': 'Básculas', 'icono': 'bi-speedometer2',
        'descripcion': 'La cola de tiquetes de báscula por subir.',
        'acciones': [
            ('ver', 'Ver la pantalla de básculas', 'Los servicios con tiquete pendiente y los ya subidos.', True),
            ('subir', 'Subir tiquetes', 'Subir el tiquete de báscula de un servicio.', True),
        ],
    },
    {
        'clave': 'certificados', 'nombre': 'Certificados de disposición', 'icono': 'bi-folder2-open',
        'descripcion': 'El gestor documental de los certificados de disposición final.',
        'acciones': [
            ('ver', 'Ver las carpetas', 'Las carpetas de certificados por cliente.', True),
            ('gestionar', 'Subir y enviar', 'Subir certificados a la carpeta y enviárselos al cliente.', True),
            ('eliminar', 'Quitar certificados', 'Quitar un certificado de la carpeta. Era solo de administradores.', False),
        ],
    },
    # ----- Lo que era SOLO de administradores (se le puede abrir a un asesor) -----
    {
        'clave': 'tablero', 'nombre': 'Tablero', 'icono': 'bi-grid-1x2-fill', 'de_administradores': True,
        'descripcion': 'El tablero general y el gráfico de tiempo laborado. Las cifras de clientes salen solo de su cartera; flota, personal y PESV son de toda la empresa.',
        'acciones': [
            ('ver', 'Ver el tablero', 'El tablero y el tiempo laborado de todo el personal.', False),
        ],
    },
    {
        'clave': 'plan', 'nombre': 'Plan de trabajo', 'icono': 'bi-journal-check', 'de_administradores': True,
        'descripcion': 'El reparto diario de todo el personal y sus novedades de recursos humanos.',
        'acciones': [
            ('ver', 'Ver el plan', 'El plan de cada día, el historial, las novedades y los PDF.', False),
            ('editar', 'Asignar y registrar', 'Asignar actividades, registrar novedades, notas y actividades nuevas, y quitarlas.', False),
        ],
    },
    {
        'clave': 'disposiciones', 'nombre': 'Disposiciones', 'icono': 'bi-recycle', 'de_administradores': True,
        'descripcion': 'La trazabilidad del residuo de cada servicio hasta su disposición final. Solo lo de los clientes de su cartera.',
        'acciones': [
            ('ver', 'Ver las disposiciones', 'La trazabilidad, las agendadas, el historial y el Excel.', False),
            ('editar', 'Registrar y corregir', 'Registrar, agendar, confirmar y cancelar disposiciones, y corregirlas a mano en el expediente.', False),
        ],
    },
    {
        'clave': 'facturacion', 'nombre': 'Facturación', 'icono': 'bi-receipt', 'de_administradores': True,
        'descripcion': 'Las preliquidaciones y facturas internas, solo las de los clientes de su cartera.',
        'acciones': [
            ('ver', 'Ver la facturación', 'Las facturas, su PDF y Excel, y los correos con los que se enviaron.', False),
            ('editar', 'Preliquidar y facturar', 'Preliquidar órdenes, crear y editar facturas y registrar pagos.', False),
        ],
    },
    {
        'clave': 'reportes', 'nombre': 'Reportes', 'icono': 'bi-bar-chart-line-fill', 'de_administradores': True,
        'descripcion': 'Los reportes del sistema, calculados solo con los clientes de su cartera.',
        'acciones': [
            ('ver', 'Ver los reportes', 'La pantalla de reportes.', False),
        ],
    },
]

# Todas las claves válidas, y las que el rol Asesores tenía de siempre.
TODAS = frozenset(f"{m['clave']}.{a[0]}" for m in MODULOS for a in m['acciones'])
BASE = frozenset(f"{m['clave']}.{a[0]}" for m in MODULOS for a in m['acciones'] if a[3])

# Dónde «vive» un asesor al iniciar sesión, en orden de preferencia
# (dashboard_redirect_view): la primera pantalla que pueda abrir.
CASAS = [
    ('ordenes.ver', 'gestion:lista_ordenes'),
    ('programacion.ver', 'gestion:lista_programaciones'),
    ('calendario.ver', 'gestion:calendario'),
    ('visitas.ver', 'gestion:lista_visitas'),
    ('clientes.ver', 'gestion:lista_clientes'),
    ('correos.ver', 'gestion:centro_correos'),
    ('personal.ver', 'gestion:lista_personal'),
    ('basculas.ver', 'gestion:basculas'),
    ('certificados.ver', 'gestion:disposiciones_finales'),
    ('vehiculos.ver', 'gestion:lista_vehiculos'),
    ('proveedores.ver', 'gestion:lista_dispositores'),
    ('fotos.ver', 'gestion:fotos_servicios'),
    ('documentacion.ver', 'gestion:documentacion'),
    ('tablero.ver', 'gestion:dashboard'),
    ('plan.ver', 'planes:plan_dia'),
    ('disposiciones.ver', 'gestion:trazabilidad_disposiciones'),
    ('facturacion.ver', 'gestion:lista_facturas'),
    ('reportes.ver', 'gestion:reportes'),
]


def es_administrador(user):
    """Superusuario o rol Administradores (igual que en views y cartera)."""
    return bool(user) and user.is_authenticated and (
        user.is_superuser or user.groups.filter(name='Administradores').exists()
    )


def es_asesor(user):
    """Está en el rol Asesores (sin importar si además es administrador)."""
    return bool(user) and user.is_authenticated and user.groups.filter(name='Asesores').exists()


def normalizar(claves):
    """
    Deja solo claves válidas y completa la coherencia: cualquier acción de un
    módulo exige poder VERLO (sin «ver» no hay menú ni pantalla donde hacerla).
    """
    claves = set(claves) & TODAS
    for clave in list(claves):
        modulo = clave.split('.', 1)[0]
        if f'{modulo}.ver' in TODAS:
            claves.add(f'{modulo}.ver')
    return claves


def accesos_de(user):
    """
    Las claves que esta persona tiene. Se calcula una vez por petición (se
    guarda en el objeto `user`): administradores todo; asesores lo de sus
    casillas (o lo de siempre si nadie se las ha tocado); los demás, nada
    (a ellos no les aplican las casillas: siguen por rol).
    """
    if user is None or not user.is_authenticated:
        return frozenset()
    cache = getattr(user, '_accesos', None)
    if cache is not None:
        return cache
    if es_administrador(user):
        accesos = TODAS
    elif es_asesor(user):
        from .models import AccesosAsesor
        registro = AccesosAsesor.objects.filter(usuario=user).only('claves').first()
        accesos = BASE if registro is None else frozenset(normalizar(registro.claves or []))
    else:
        accesos = frozenset()
    user._accesos = accesos
    return accesos


def tiene_acceso(user, clave):
    """¿Puede hacer esto? Para administradores siempre sí."""
    return clave in accesos_de(user)


def autoriza(user, por_rol, acceso=None, acceso_escribir=None, escribe=False):
    """
    La decisión de una vista. `por_rol` es lo que decía el mixin de siempre
    (p. ej. «es admin o asesor»). Para administradores manda `por_rol` (que
    siempre los deja pasar); para asesores mandan las casillas cuando la
    vista declara `acceso`; para los demás roles, `por_rol` tal cual.
    """
    if es_administrador(user):
        return True
    if not es_asesor(user) or acceso is None:
        return por_rol
    if not tiene_acceso(user, acceso):
        return False
    if escribe and acceso_escribir and not tiene_acceso(user, acceso_escribir):
        return False
    return True


def para_plantilla(user):
    """`acceso.modulo.accion` en las plantillas: {modulo: {accion: bool}}."""
    accesos = accesos_de(user)
    return {m['clave']: {a[0]: f"{m['clave']}.{a[0]}" in accesos for a in m['acciones']}
            for m in MODULOS}


def casa_de_asesor(user):
    """El nombre de URL de la primera pantalla que el asesor puede abrir, o None."""
    accesos = accesos_de(user)
    for clave, nombre_url in CASAS:
        if clave in accesos:
            return nombre_url
    return None
