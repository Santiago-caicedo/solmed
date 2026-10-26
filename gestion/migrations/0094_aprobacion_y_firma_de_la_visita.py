# La visita técnica se SOLICITA y el cliente la aprueba desde un enlace de un
# solo uso (token de aprobación); al final firma desde otro enlace (token de
# firma), como en el acta de servicio (oct-2026, pedido de Santiago).
import uuid

from django.db import migrations, models


def poner_tokens(apps, schema_editor):
    """Las visitas ya existentes reciben cada una su token (el default se evalúa una sola vez)."""
    VisitaTecnica = apps.get_model('gestion', 'VisitaTecnica')
    for visita in VisitaTecnica.objects.all():
        visita.token_aprobacion = uuid.uuid4()
        visita.save(update_fields=['token_aprobacion'])


class Migration(migrations.Migration):

    dependencies = [
        ('gestion', '0093_visitas_tecnicas'),
    ]

    operations = [
        migrations.AddField(
            model_name='visitatecnica',
            name='token_aprobacion',
            field=models.UUIDField(default=uuid.uuid4, editable=False, null=True),
        ),
        migrations.RunPython(poner_tokens, migrations.RunPython.noop),
        migrations.AddField(
            model_name='visitatecnica',
            name='solicitud_enviada_en',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='visitatecnica',
            name='aprobada_en',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='visitatecnica',
            name='aprobada_por',
            field=models.CharField(blank=True, max_length=200, verbose_name='Quién aprobó por el cliente'),
        ),
        migrations.AddField(
            model_name='visitatecnica',
            name='cargo_aprobo',
            field=models.CharField(blank=True, max_length=150),
        ),
        migrations.AddField(
            model_name='visitatecnica',
            name='comentario_cliente',
            field=models.TextField(blank=True, verbose_name='Comentario del cliente a la solicitud'),
        ),
        migrations.AddField(
            model_name='visitatecnica',
            name='token_firma',
            field=models.UUIDField(blank=True, editable=False, null=True, unique=True),
        ),
        migrations.AddField(
            model_name='visitatecnica',
            name='firmada_en',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AlterField(
            model_name='visitatecnica',
            name='estado',
            field=models.CharField(choices=[('PROGRAMADA', 'Pendiente de aprobación'), ('CONFIRMADA', 'Aprobada por el cliente'), ('REPROGRAMADA', 'Reprogramada · pendiente de aprobación'), ('REALIZADA', 'Realizada'), ('CANCELADA', 'Cancelada')], default='PROGRAMADA', max_length=15),
        ),
        migrations.AlterField(
            model_name='visitatecnica',
            name='hora_inicio',
            field=models.TimeField(blank=True, null=True, verbose_name='Hora de ingreso'),
        ),
    ]
