"""
Mover una orden de servicio a otro número (consecutivo).

El número de la orden es su clave primaria, así que "renumerar" es en realidad
copiar la fila al número nuevo, llevarse todo lo que cuelga de ella y borrar la
vieja. Lo usan los comandos `renumerar_orden` y `borrar_y_recorrer_ordenes`.
"""
from django.db import transaction
from django.db.models import Max

from .models import OrdenServicio


def relaciones_orden():
    """Todo lo que apunta a una orden (recorridos, pagos, documentos, programación)."""
    return OrdenServicio._meta.related_objects


def hijos_de(numero):
    """[(nombre legible, cuántos)] de lo que cuelga de esa orden."""
    return [
        (rel.related_model._meta.verbose_name_plural,
         rel.related_model.objects.filter(**{rel.field.attname: numero}).count())
        for rel in relaciones_orden()
    ]


def plan_reubicacion(actual, nuevo):
    """
    Qué movimientos hacen falta para que la orden `actual` pase a ser la
    `nuevo` SIN dejar huecos ni duplicados: [(viejo, nuevo), ...] en el orden
    en que deben ejecutarse.

    Si el número destino está libre, es un solo movimiento. Si está ocupado,
    las órdenes que hay entre medias se corren un puesto para hacerle sitio:
    bajar la orden empuja a las de abajo hacia arriba, y subirla las empuja
    hacia abajo. El orden relativo de todas las demás se conserva.
    """
    if actual == nuevo:
        return []
    if not OrdenServicio.objects.filter(pk=nuevo).exists():
        return [(actual, nuevo)]

    if nuevo < actual:
        # Baja: las de [nuevo, actual) suben una posición, de mayor a menor
        # para que el destino de cada una esté siempre libre.
        entre = OrdenServicio.objects.filter(
            pk__gte=nuevo, pk__lt=actual).order_by('-pk')
        movimientos = [(o.pk, o.pk + 1) for o in entre]
    else:
        # Sube: las de (actual, nuevo] bajan una posición, de menor a mayor.
        entre = OrdenServicio.objects.filter(
            pk__gt=actual, pk__lte=nuevo).order_by('pk')
        movimientos = [(o.pk, o.pk - 1) for o in entre]
    return movimientos + [(actual, nuevo)]


@transaction.atomic
def reubicar_orden(actual, nuevo):
    """
    Cambia el número de una orden colocándola en su sitio del consecutivo,
    corriendo las que estorben. Devuelve la lista de movimientos aplicados.
    """
    movimientos = plan_reubicacion(actual, nuevo)
    if not movimientos:
        return []

    # La orden que se mueve se aparta a un número libre por encima de todo
    # mientras se corren las demás; si no, chocaría con ellas al pasar.
    tope = OrdenServicio.objects.aggregate(m=Max('numero_orden'))['m'] or 0
    aparcadero = max(tope, nuevo, actual) + 1
    mover_orden(actual, aparcadero)
    for viejo, destino in movimientos[:-1]:
        mover_orden(viejo, destino)
    mover_orden(aparcadero, nuevo)
    return movimientos


@transaction.atomic
def mover_orden(actual, nuevo):
    """
    Cambia el número de la orden `actual` a `nuevo`, arrastrando sus hijos.
    El número nuevo debe estar libre (quien llama lo garantiza).
    """
    orden = OrdenServicio.objects.get(pk=actual)
    # `fecha_creacion` es auto_now_add: Django la reescribe con la fecha de hoy
    # en TODO insert, así que hay que guardarla y devolverla con un UPDATE.
    fecha_creacion = orden.fecha_creacion

    orden.pk = nuevo
    orden._state.adding = True
    orden.save(force_insert=True)
    OrdenServicio.objects.filter(pk=nuevo).update(fecha_creacion=fecha_creacion)

    # Los hijos pasan a apuntar al número nuevo...
    for rel in relaciones_orden():
        rel.related_model.objects.filter(
            **{rel.field.attname: actual}).update(**{rel.field.attname: nuevo})

    # ...y la fila vieja queda sin hijos, así que su borrado no arrastra nada.
    OrdenServicio.objects.filter(pk=actual).delete()
