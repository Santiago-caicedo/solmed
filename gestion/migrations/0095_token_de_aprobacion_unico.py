# Aparte de la 0094 para que el UNIQUE se ponga después de repartir los tokens
# (PostgreSQL no deja alterar la tabla en la misma transacción con filas recién tocadas).
import uuid

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('gestion', '0094_aprobacion_y_firma_de_la_visita'),
    ]

    operations = [
        migrations.AlterField(
            model_name='visitatecnica',
            name='token_aprobacion',
            field=models.UUIDField(default=uuid.uuid4, editable=False, unique=True),
        ),
    ]
