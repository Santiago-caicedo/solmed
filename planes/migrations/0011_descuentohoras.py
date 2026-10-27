# Descuentos de horas en actividades y novedades del plan (oct-2026).

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('planes', '0010_asignacion_suma_horas'),
    ]

    operations = [
        migrations.CreateModel(
            name='DescuentoHoras',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('minutos', models.PositiveSmallIntegerField()),
                ('motivo', models.CharField(max_length=120)),
                ('asignacion', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='descuentos', to='planes.asignacion')),
                ('novedad', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='descuentos', to='planes.novedad')),
            ],
            options={
                'verbose_name': 'Descuento de horas del plan',
                'verbose_name_plural': 'Descuentos de horas del plan',
                'ordering': ['id'],
            },
        ),
        migrations.AddConstraint(
            model_name='descuentohoras',
            constraint=models.CheckConstraint(
                condition=(models.Q(asignacion__isnull=False, novedad__isnull=True)
                           | models.Q(asignacion__isnull=True, novedad__isnull=False)),
                name='descuento_de_una_actividad_o_una_novedad'),
        ),
    ]
