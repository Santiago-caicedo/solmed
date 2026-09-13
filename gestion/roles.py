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


def es_de(nombres_grupos, grupos):
    """True si alguno de los grupos de la persona está en `grupos`."""
    return any(nombre in grupos for nombre in nombres_grupos)
