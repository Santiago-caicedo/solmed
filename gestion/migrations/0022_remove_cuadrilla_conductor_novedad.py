# Generated manually: quita la novedad del conductor en las cuadrillas.

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('gestion', '0021_mover_bascula_registro_a_orden'),
    ]

    operations = [
        migrations.RemoveField(model_name='programacioncuadrilla', name='conductor_novedad'),
    ]
