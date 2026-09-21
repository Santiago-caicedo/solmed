"""
Los roles de la operación en un solo sitio.

El «Conductor - Ayudante» (sep-2026, pedido de la clienta) es un híbrido: no
tiene usuario ni contraseña —como los ayudantes—, todo le llega al correo, y
cabe en CUALQUIERA de los dos puestos de la cuadrilla. Por eso los
desplegables de conductor y de ayudante ofrecen a los de su grupo y a él.
"""

CONDUCTORES = 'Conductores'
AYUDANTES = 'Ayudantes'
CONDUCTOR_AYUDANTE = 'Conductor - Ayudante'

# Quién puede ir en cada puesto de la cuadrilla.
GRUPOS_CONDUCTOR = (CONDUCTORES, CONDUCTOR_AYUDANTE)
GRUPOS_AYUDANTE = (AYUDANTES, CONDUCTOR_AYUDANTE)


# Quién trabaja la pantalla de BÁSCULAS (sep-2026, pedido de la clienta: una
# persona dedicada a subir los tiquetes de pesaje). Los asesores ya podían
# subirlos desde cada orden; a los dos cargos de oficina esta pantalla les
# estrena módulo: antes su cuenta solo existía por el expediente.
GRUPOS_BASCULA = ('Asesores', 'Auxiliares Administrativas', 'Administrativo')


def es_de(nombres_grupos, grupos):
    """True si alguno de los grupos de la persona está en `grupos`."""
    return any(nombre in grupos for nombre in nombres_grupos)
