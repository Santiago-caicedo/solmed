"""
Formatos de preliquidación exigidos por clientes puntuales (sep-2026).

Dos clientes piden su propia tabla. El resto sigue con el formato normal de
SOLMED. Se identifican por **NIT**, no por id: el id cambia entre la base del
servidor y las de prueba, el NIT no.

- **D1** solo en las sedes de Ibagué y Sibaté. Si la preliquidación mezcla una
  orden de otra sede, sale el formato normal (decisión de Santiago: más vale
  el formato de siempre que una tabla a medias).
- **MECÁNICOS ASOCIADOS** en todas sus sedes.

Para añadir o quitar un cliente, o una sede de D1, se edita `FORMATOS`.
"""
import unicodedata

# clave: cómo se llama el formato en el código y en las plantillas.
# sedes: None = todas; si no, la sede de CADA orden debe contener uno de esos
#        textos (ya normalizados, sin tildes y en mayúsculas).
FORMATOS = {
    '9002769621': {'clave': 'd1', 'nombre': 'D1', 'sedes': ('IBAGUE', 'SIBATE')},
    '891102723': {'clave': 'mecanicos', 'nombre': 'Mecánicos Asociados', 'sedes': None},
}

# Los formatos que piden los seis datos de D1 (pesos, unitarios, flete y destrucción).
CON_DETALLE_D1 = ('d1',)


def normalizar(texto):
    """Mayúsculas y sin tildes, para comparar nombres de sede sin sorpresas."""
    sin_tildes = unicodedata.normalize('NFKD', str(texto or ''))
    return ''.join(c for c in sin_tildes if not unicodedata.combining(c)).upper().strip()


def solo_digitos(nit):
    """El NIT sin puntos, guiones ni dígito de verificación separado."""
    return ''.join(c for c in str(nit or '') if c.isdigit())


def _formato_del_cliente(cliente):
    """La ficha de formato de ese cliente, o None si va con el de siempre."""
    if cliente is None:
        return None
    buscado = solo_digitos(cliente.identificacion)
    for nit, ficha in FORMATOS.items():
        propio = solo_digitos(nit)
        # El NIT puede venir con o sin dígito de verificación: basta que uno
        # empiece por el otro (9002769621 ↔ 900276962).
        if buscado and (buscado.startswith(propio) or propio.startswith(buscado)):
            return ficha
    return None


def sede_aplica(cliente, sede):
    """¿Esa sede es de las que llevan el formato propio del cliente?"""
    ficha = _formato_del_cliente(cliente)
    if ficha is None:
        return False
    if ficha['sedes'] is None:
        return True
    nombre = normalizar(sede)
    return any(s in nombre for s in ficha['sedes'])


def pide_detalle_d1(cliente, sede):
    """
    ¿Esa orden se cobra con el desglose de D1 (pesos, unitarios, flete y
    destrucción) en vez del precio global? Pide las DOS cosas: que el cliente
    lleve un formato con desglose y que la sede sea de las que aplican.
    """
    ficha = _formato_del_cliente(cliente)
    return (ficha is not None and ficha['clave'] in CON_DETALLE_D1
            and sede_aplica(cliente, sede))


def formato_de(cliente, sedes):
    """
    El formato que le toca a una preliquidación de `cliente` cuyas órdenes se
    prestaron en `sedes`. Devuelve '' (el de siempre) si el cliente no tiene
    formato propio, si no hay órdenes, o si ALGUNA sede queda por fuera.
    """
    ficha = _formato_del_cliente(cliente)
    if ficha is None:
        return ''
    sedes = list(sedes)
    if not sedes:
        return ''
    if ficha['sedes'] is not None and not all(sede_aplica(cliente, s) for s in sedes):
        return ''
    return ficha['clave']
