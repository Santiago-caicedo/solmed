# Oct-2026: el registro fotográfico pasó de sedes/terceros a PUNTOS del
# cliente (ver PuntoRegistro). La 0088 ya convirtió lo marcado y las fotos;
# aquí solo se quitan los campos viejos.
from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('gestion', '0088_puntos_de_registro_fotografico'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='fotoregistro',
            name='sede',
        ),
        migrations.RemoveField(
            model_name='fotoregistro',
            name='tercero',
        ),
        migrations.RemoveField(
            model_name='ordenservicio',
            name='sedes_registro',
        ),
        migrations.RemoveField(
            model_name='ordenservicio',
            name='terceros_registro',
        ),
        migrations.RemoveField(
            model_name='programacion',
            name='sedes_registro',
        ),
        migrations.RemoveField(
            model_name='programacion',
            name='terceros_registro',
        ),
    ]
