# Reconstruye el saldo del histórico de cargas: hasta la 0065 el "pendiente de
# disposición" era un booleano en el vehículo (una sola marca); ahora cada
# CARGA queda pendiente hasta que una DESCARGA la salda. Este backfill recorre
# los movimientos de cada camión en orden y enlaza cada DESCARGA con las CARGAS
# anteriores aún sin saldar — que era lo que físicamente pasaba: al vaciar el
# camión salía todo lo acumulado. Las CARGAS posteriores a la última DESCARGA
# quedan pendientes, que debe coincidir con los camiones hoy marcados cargados.
from django.db import migrations


def saldar(apps, schema_editor):
    Movimiento = apps.get_model('gestion', 'MovimientoCargaVehiculo')
    Vehiculo = apps.get_model('gestion', 'Vehiculo')

    for vehiculo in Vehiculo.objects.all():
        pendientes = []
        for m in (Movimiento.objects.filter(vehiculo=vehiculo)
                  .order_by('fecha', 'pk')):
            if m.accion == 'CARGA':
                pendientes.append(m)
            elif m.accion == 'DESCARGA' and pendientes:
                Movimiento.objects.filter(
                    pk__in=[c.pk for c in pendientes]).update(descarga=m)
                pendientes = []
        # Camión marcado cargado SIN fila de carga (marcas anteriores al
        # historial, migración 0052): se le crea su fila para que el pendiente
        # no se pierda al pasar a la regla nueva.
        if vehiculo.cargado and not pendientes:
            pendientes = [Movimiento.objects.create(
                vehiculo=vehiculo, accion='CARGA',
                nota=(vehiculo.cargado_detalle
                      or 'Registro migrado: estaba marcado cargado')[:255])]
        # El espejo del vehículo se recalcula con la misma regla del modelo
        # (aquí en versión histórica: sin acceso a métodos del modelo real).
        cargado = bool(pendientes)
        if vehiculo.cargado != cargado:
            vehiculo.cargado = cargado
            if not cargado:
                vehiculo.cargado_detalle = ''
            vehiculo.save(update_fields=['cargado', 'cargado_detalle'])


def deshacer(apps, schema_editor):
    apps.get_model('gestion', 'MovimientoCargaVehiculo').objects.update(descarga=None)


class Migration(migrations.Migration):

    dependencies = [
        ('gestion', '0065_movimientocargavehiculo_descarga'),
    ]

    operations = [
        migrations.RunPython(saldar, deshacer),
    ]
