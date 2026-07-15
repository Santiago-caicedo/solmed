# Generated manually: periodo (mes AAAA-MM) para la seguridad social mensual.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('gestion', '0018_programacion_quitar_campos_personal'),
    ]

    operations = [
        migrations.AddField(
            model_name='documentopersonal',
            name='periodo',
            field=models.CharField(blank=True, help_text='Formato AAAA-MM. La seguridad social se carga cada mes.', max_length=7, verbose_name='Mes que cubre (seguridad social)'),
        ),
    ]
