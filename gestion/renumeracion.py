"""
Mover una orden de servicio a otro número (consecutivo).

El número de la orden es su clave primaria, así que "renumerar" es en realidad
copiar la fila al número nuevo, llevarse todo lo que cuelga de ella y borrar la
vieja. Lo usan los comandos `renumerar_orden` y `borrar_y_recorrer_ordenes`.
"""
from django.db import transaction

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
