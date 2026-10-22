# Los tipos de los vehículos de la flota, según el correo de la SISO
# (oct-2026), y las placas que mencionó y aún no estaban en el sistema. A las
# nuevas la oficina les completa marca, modelo y capacidad en su ficha; a las
# que ya tenían tipo no se les toca.

from django.db import migrations

TIPOS = {
    'WGY347': 'VACIO_DOBLE',
    'OBC727': 'VACIO_DOBLE',
    'OBB178': 'VACIO_SENCILLO',
    'WNN675': 'HINO',
    'VCP886': 'VOLQUETA',
    'OBA400': 'VACTOR',
    'WNO623': 'CAMIONETA',
}


def poner_tipos(apps, schema_editor):
    Vehiculo = apps.get_model('gestion', 'Vehiculo')
    for placa, tipo in TIPOS.items():
        vehiculo, _creado = Vehiculo.objects.get_or_create(
            placa=placa, defaults={'marca': '', 'modelo': '', 'capacidad': ''})
        if not vehiculo.tipo:
            vehiculo.tipo = tipo
            vehiculo.save(update_fields=['tipo'])


class Migration(migrations.Migration):

    dependencies = [
        ('gestion', '0091_preoperacional_y_tipo_de_vehiculo'),
    ]

    operations = [
        migrations.RunPython(poner_tipos, migrations.RunPython.noop),
    ]
