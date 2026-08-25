# Enlaza las disposiciones ya asignadas en el plan con la DESCARGA que
# registraron en su momento, para que quitarlas del plan siga reviviendo su
# pendiente con la regla nueva (cada asignación deshace SUS descargas, no el
# camión entero). Se reconocen por su nota — aplicar_descarga siempre escribió
# "Plan del dd/mm/aaaa..." — más el camión y la orden de la asignación.
from django.db import migrations


def enlazar(apps, schema_editor):
    Asignacion = apps.get_model('planes', 'Asignacion')
    Movimiento = apps.get_model('gestion', 'MovimientoCargaVehiculo')

    disposiciones = (Asignacion.objects.filter(tipo='DISPOSICION_FINAL')
                     .prefetch_related('vehiculos').select_related('plan'))
    for asignacion in disposiciones:
        vehiculo = asignacion.vehiculos.first()
        if vehiculo is None:
            continue
        candidatas = Movimiento.objects.filter(
            vehiculo=vehiculo, accion='DESCARGA',
            orden=asignacion.orden,
            nota__startswith=f"Plan del {asignacion.plan.fecha.strftime('%d/%m/%Y')}",
        )
        asignacion.descargas.add(*candidatas)


class Migration(migrations.Migration):

    dependencies = [
        ('planes', '0003_asignacion_descargas'),
        ('gestion', '0066_saldar_cargas_historicas'),
    ]

    operations = [
        migrations.RunPython(enlazar, migrations.RunPython.noop),
    ]
