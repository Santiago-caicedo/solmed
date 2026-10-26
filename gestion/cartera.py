"""
La CARTERA de clientes de cada asesora comercial (oct-2026, pedido de Santiago).

A cada cliente se le asignan, desde su ficha (pestaña «Asesora comercial»),
una o varias asesoras de SOLMED. Desde entonces:

- Una ASESORA (rol Asesores, sin ser administradora) solo ve y gestiona lo de
  los clientes de su cartera: fichas, órdenes, programaciones, actas, visitas
  técnicas, correos, fotos, calendario, básculas y certificados. Lo demás no
  existe para ella (404) y los desplegables de cliente solo le ofrecen los
  suyos. Un cliente SIN asesora asignada no lo ve ninguna asesora.
- Los ADMINISTRADORES (y el superusuario) ven todo, como siempre, y son los
  únicos que asignan o cambian la asesora de un cliente.
- Los demás roles (auxiliares, SISO, planificadores, conductores…) NO tienen
  cartera: sus pantallas siguen exactamente igual. La cartera solo recorta a
  las asesoras, para no interrumpir ninguna otra cadena.

Decisiones de Santiago (oct-2026): varias asesoras por cliente; el cliente
que crea una asesora queda en su cartera; lo no asignado solo lo ven los
administradores.
"""
from .models import Cliente


def es_administrador(user):
    """Misma definición que en views.es_administrador (aquí para no importar views)."""
    return bool(user) and user.is_authenticated and (
        user.is_superuser or user.groups.filter(name='Administradores').exists())


def tiene_cartera(user):
    """
    ¿A esta persona la recorta la cartera? Solo a las asesoras que no son
    administradoras. Se memoriza en el usuario: se consulta muchas veces por
    petición.
    """
    if not user or not user.is_authenticated:
        return False
    if not hasattr(user, '_tiene_cartera'):
        user._tiene_cartera = (not es_administrador(user)
                               and user.groups.filter(name='Asesores').exists())
    return user._tiene_cartera


def clientes_de(user):
    """Los clientes que esta persona puede ver: su cartera, o todos si no la recorta."""
    if tiene_cartera(user):
        return Cliente.objects.filter(asesoras=user)
    return Cliente.objects.all()


def solo_cartera(queryset, user, campo='cliente'):
    """
    Deja en el queryset solo lo de los clientes de la cartera de `user`, por
    el camino `campo` hasta el cliente ('cliente', 'orden__cliente', 'pk'…).
    Si a la persona no la recorta la cartera, devuelve el queryset intacto.
    """
    if not tiene_cartera(user):
        return queryset
    return queryset.filter(**{f'{campo}__in': Cliente.objects.filter(asesoras=user)})


def puede_ver_cliente(user, cliente):
    """¿Este cliente (objeto o id) está al alcance de la persona?"""
    if not tiene_cartera(user):
        return True
    pk = getattr(cliente, 'pk', cliente)
    return pk is not None and Cliente.objects.filter(pk=pk, asesoras=user).exists()
