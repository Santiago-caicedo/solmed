# Generated manually for the Programación module (paso previo a la orden).

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('gestion', '0014_recorrido_ayudante'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='Programacion',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('fecha', models.DateField(verbose_name='Fecha del primer recorrido')),
                ('direccion_servicio', models.CharField(blank=True, help_text='Se arrastra a la orden al convertir. Si se deja vacío se usa la dirección del cliente.', max_length=255)),
                ('descripcion', models.TextField(blank=True, help_text='Descripción del servicio previsto')),
                ('estado', models.CharField(choices=[('BORRADOR', 'Borrador'), ('CONFIRMADA', 'Confirmada'), ('CONVERTIDA', 'Convertida en orden'), ('CANCELADA', 'Cancelada')], default='BORRADOR', max_length=20)),
                ('fecha_creacion', models.DateTimeField(auto_now_add=True)),
                ('ayudante', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='programaciones_como_ayudante', to=settings.AUTH_USER_MODEL)),
                ('cliente', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='programaciones', to='gestion.cliente')),
                ('conductor', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='programaciones_como_conductor', to=settings.AUTH_USER_MODEL)),
                ('creado_por', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='programaciones_creadas', to=settings.AUTH_USER_MODEL)),
                ('orden', models.OneToOneField(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='programacion_origen', to='gestion.ordenservicio')),
                ('vehiculo', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='programaciones', to='gestion.vehiculo', verbose_name='Vehículo a asignar')),
            ],
            options={
                'verbose_name': 'Programación',
                'verbose_name_plural': 'Programaciones',
                'ordering': ['-fecha_creacion'],
            },
        ),
    ]
