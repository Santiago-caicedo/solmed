"""
El pendiente de disposición pasa del camión a LA ORDEN (decisión del usuario,
sep-2026). Traslada el historial de MovimientoCargaVehiculo al modelo nuevo:

  · Orden con una CARGA sin saldar            → estado PENDIENTE (sin disponer).
  · Cada DESCARGA de una orden                → un DisposicionOrden con su fecha,
    gestor, quién y vía (plan de trabajo si la enlazaba una asignación del
    plan; «reporte de la oficina» si la nota lo dice; si no, al convertir).
    Si la orden además sigue pendiente (se deshizo y se compensó con otra
    carga), el registro queda marcado como DESHECHO, no se pierde.
  · Orden con todo saldado o dispuesta al convertir → estado DISPUESTA.
  · Las asignaciones del plan que enlazaban descargas pasan a enlazar las
    disposiciones equivalentes.

Las cargas manuales sin orden no tienen a dónde ir (el camión ya no lleva
estado) y se dejan atrás: se cuentan en la salida. Sin reversa de datos.
"""
from django.db import migrations
from django.utils import timezone


def migrar(apps, schema_editor):
    Movimiento = apps.get_model('gestion', 'MovimientoCargaVehiculo')
    Orden = apps.get_model('gestion', 'OrdenServicio')
    Disposicion = apps.get_model('gestion', 'DisposicionOrden')
    Asignacion = apps.get_model('planes', 'Asignacion')

    movimientos = list(Movimiento.objects.select_related('descarga').order_by('fecha', 'pk'))
    sin_orden = sum(1 for m in movimientos if m.orden_id is None and m.accion == 'CARGA')
    por_orden = {}
    for m in movimientos:
        if m.orden_id:
            por_orden.setdefault(m.orden_id, []).append(m)

    # Descarga → asignaciones del plan que la enlazaban.
    asignaciones_de = {}
    for a in Asignacion.objects.prefetch_related('descargas'):
        for d in a.descargas.all():
            asignaciones_de.setdefault(d.pk, []).append(a)

    pendientes = dispuestas = registros = deshechos = 0
    for orden_id, movs in por_orden.items():
        cargas = [m for m in movs if m.accion == 'CARGA']
        pendiente = any(c.descarga_id is None for c in cargas)
        # Las descargas de la orden: las propias y las que saldaron sus cargas.
        descargas = {m.pk: m for m in movs if m.accion == 'DESCARGA'}
        for c in cargas:
            if c.descarga_id and c.descarga_id not in descargas:
                descargas[c.descarga_id] = c.descarga
        for d in sorted(descargas.values(), key=lambda m: (m.fecha, m.pk)):
            asignaciones = asignaciones_de.get(d.pk, [])
            if asignaciones:
                via = 'PLAN'
            elif 'reporte' in (d.nota or '').lower():
                via = 'REPORTE'
            else:
                via = 'CONVERTIR'
            registro = Disposicion.objects.create(
                orden_id=orden_id, fecha=timezone.localtime(d.fecha).date(),
                dispositor_id=d.dispositor_id, via=via, nota=(d.nota or '')[:255],
                registrado_por_id=d.registrado_por_id, deshecha=pendiente,
                deshecha_nota=('Migración: la orden volvió a quedar sin disponer'
                               if pendiente else ''),
            )
            Disposicion.objects.filter(pk=registro.pk).update(registrado_en=d.fecha)
            for a in asignaciones:
                a.disposiciones.add(registro)
            registros += 1
            deshechos += int(pendiente)
        estado = 'PENDIENTE' if pendiente else ('DISPUESTA' if descargas else 'NO_APLICA')
        Orden.objects.filter(pk=orden_id).update(estado_disposicion=estado)
        pendientes += estado == 'PENDIENTE'
        dispuestas += estado == 'DISPUESTA'

    print(f"\n  Disposiciones migradas a la orden: {pendientes} sin disponer, "
          f"{dispuestas} dispuestas, {registros} registro(s) "
          f"({deshechos} deshechos); {sin_orden} carga(s) manual(es) sin orden "
          f"quedaron atrás.")


class Migration(migrations.Migration):

    dependencies = [
        ('gestion', '0068_disposicion_de_la_orden'),
        ('planes', '0005_disposicion_de_la_orden'),
    ]

    operations = [
        migrations.RunPython(migrar, migrations.RunPython.noop),
    ]
