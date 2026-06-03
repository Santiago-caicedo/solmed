import uuid

from django.db import migrations, models


def poblar_tokens_y_estado(apps, schema_editor):
    """
    Los manifiestos ya existentes en la BD están firmados, así que se marcan como
    'FIRMADO' y se les asigna un token_publico único (uuid4 por fila) para no violar
    la restricción unique que se aplica en el paso siguiente.
    """
    Manifiesto = apps.get_model('gestion', 'Manifiesto')
    for manifiesto in Manifiesto.objects.all():
        manifiesto.token_publico = uuid.uuid4()
        manifiesto.estado_firma = 'FIRMADO'
        manifiesto.save(update_fields=['token_publico', 'estado_firma'])


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('gestion', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='manifiesto',
            name='token_publico',
            field=models.UUIDField(default=uuid.uuid4, editable=False, null=True),
        ),
        migrations.AddField(
            model_name='manifiesto',
            name='estado_firma',
            field=models.CharField(
                choices=[('PENDIENTE_FIRMA', 'Pendiente firma cliente'), ('FIRMADO', 'Firmado')],
                default='PENDIENTE_FIRMA',
                max_length=20,
            ),
        ),
        migrations.RunPython(poblar_tokens_y_estado, noop),
        migrations.AlterField(
            model_name='manifiesto',
            name='token_publico',
            field=models.UUIDField(default=uuid.uuid4, editable=False, null=True, unique=True),
        ),
    ]
