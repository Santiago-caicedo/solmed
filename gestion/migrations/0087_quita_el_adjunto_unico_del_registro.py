# Oct-2026: el adjunto único del registro fotográfico se reemplazó por la
# tabla FotoRegistro (una fila por foto, anclada a su sede). La 0086 ya copió
# lo que había; aquí solo se quita la columna. DESTRUCTIVA: respaldar antes.
from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('gestion', '0086_registro_fotografico_por_sede'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='ordenservicio',
            name='registro_fotografico_adjunto',
        ),
    ]
