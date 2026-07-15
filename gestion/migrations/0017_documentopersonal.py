# Generated manually: expediente documental del personal (conductores/ayudantes).

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('gestion', '0016_programacion_formato_operativo'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='DocumentoPersonal',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('tipo', models.CharField(choices=[('CEDULA', 'Cédula de ciudadanía'), ('SEGURIDAD_SOCIAL', 'Seguridad social (EPS/ARL/Pensión)'), ('LICENCIA', 'Licencia de conducción'), ('CURSO_ALTURAS', 'Certificado curso de alturas'), ('CURSO_CONFINADOS', 'Certificado espacios confinados'), ('OTRO', 'Otro documento')], max_length=20)),
                ('archivo', models.FileField(upload_to='personal_documentos/')),
                ('descripcion', models.CharField(blank=True, help_text="Detalle del documento, sobre todo si el tipo es 'Otro'.", max_length=200)),
                ('fecha_vencimiento', models.DateField(blank=True, null=True, verbose_name='Fecha de vencimiento (si aplica)')),
                ('fecha_subida', models.DateTimeField(auto_now_add=True)),
                ('usuario', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='documentos_personales', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'verbose_name': 'Documento del personal',
                'verbose_name_plural': 'Documentos del personal',
                'ordering': ['tipo', '-fecha_subida'],
            },
        ),
    ]
