# Generated manually: perfil de datos personales (ficha de la persona).

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('gestion', '0019_documentopersonal_periodo'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='PerfilPersona',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('numero_documento', models.CharField(blank=True, max_length=30, verbose_name='Número de documento (cédula)')),
                ('telefono', models.CharField(blank=True, max_length=30, verbose_name='Teléfono')),
                ('cargo', models.CharField(blank=True, max_length=100, verbose_name='Cargo')),
                ('direccion', models.CharField(blank=True, max_length=255, verbose_name='Dirección')),
                ('usuario', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name='perfil', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'verbose_name': 'Perfil de persona',
                'verbose_name_plural': 'Perfiles de personas',
            },
        ),
    ]
