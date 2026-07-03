# Generated manually: expande Programacion al formato operativo real y
# añade el modelo hijo ProgramacionCuadrilla (conductor/placa/ayudante).

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('gestion', '0015_programacion'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        # --- Campos del modelo mínimo que se reemplazan ---
        migrations.RemoveField(model_name='programacion', name='vehiculo'),
        migrations.RemoveField(model_name='programacion', name='conductor'),
        migrations.RemoveField(model_name='programacion', name='ayudante'),
        migrations.RemoveField(model_name='programacion', name='direccion_servicio'),
        migrations.RemoveField(model_name='programacion', name='descripcion'),

        # --- Cabecera del servicio ---
        migrations.AlterField(
            model_name='programacion',
            name='fecha',
            field=models.DateField(verbose_name='Fecha del servicio'),
        ),
        migrations.AddField(
            model_name='programacion',
            name='hora_ingreso_bodega',
            field=models.TimeField(blank=True, null=True, verbose_name='Hora ingreso a bodega'),
        ),
        migrations.AddField(
            model_name='programacion',
            name='hora_servicio',
            field=models.TimeField(blank=True, null=True, verbose_name='Hora del servicio'),
        ),
        migrations.AddField(
            model_name='programacion',
            name='sede',
            field=models.CharField(blank=True, max_length=150),
        ),
        migrations.AddField(
            model_name='programacion',
            name='direccion',
            field=models.CharField(blank=True, help_text='Se arrastra a la orden al convertir. Si se deja vacío se usa la dirección del cliente.', max_length=255),
        ),
        migrations.AddField(
            model_name='programacion',
            name='correo_seguridad_social',
            field=models.EmailField(blank=True, help_text='Correo del cliente a donde se comparten los documentos de seguridad social.', max_length=254, verbose_name='Correo del cliente (seguridad social)'),
        ),
        migrations.AddField(
            model_name='programacion',
            name='observaciones_servicio',
            field=models.TextField(blank=True, verbose_name='Observaciones detalladas del servicio a prestar'),
        ),

        # --- Checklist operativo ---
        migrations.AddField(
            model_name='programacion',
            name='bascula',
            field=models.CharField(blank=True, choices=[('PESAN', 'Pesan'), ('NO_PESAN', 'No pesan'), ('PESO_CLIENTE', 'Peso del cliente')], max_length=20, verbose_name='Báscula'),
        ),
        migrations.AddField(
            model_name='programacion',
            name='bascula_adjunto',
            field=models.FileField(blank=True, null=True, upload_to='programaciones/', verbose_name='Adjunto báscula'),
        ),
        migrations.AddField(
            model_name='programacion',
            name='registro_fotografico',
            field=models.CharField(blank=True, choices=[('SI', 'Sí'), ('NO', 'No')], max_length=2, verbose_name='Registro fotográfico'),
        ),
        migrations.AddField(
            model_name='programacion',
            name='registro_fotografico_adjunto',
            field=models.FileField(blank=True, null=True, upload_to='programaciones/', verbose_name='Adjunto registro fotográfico'),
        ),
        migrations.AddField(
            model_name='programacion',
            name='paleada',
            field=models.CharField(blank=True, choices=[('SAVICOL', 'Palea Savicol'), ('EMPOLLACOL', 'Palea Empollacol'), ('NO_REQUIERE', 'No requiere paleada')], max_length=20, verbose_name='Paleada'),
        ),
        migrations.AddField(
            model_name='programacion',
            name='responsable_sg',
            field=models.CharField(blank=True, choices=[('SI', 'Sí'), ('NO', 'No')], max_length=2, verbose_name='Responsable SG'),
        ),
        migrations.AddField(
            model_name='programacion',
            name='responsable_sg_adjunto',
            field=models.FileField(blank=True, null=True, upload_to='programaciones/', verbose_name='Adjunto documentos seguridad social'),
        ),
        migrations.AddField(
            model_name='programacion',
            name='ayudantes_cursos',
            field=models.CharField(blank=True, choices=[('ALTURAS', 'Alturas'), ('CONFINADOS', 'Confinados'), ('NO_REQUIERE', 'No requiere')], max_length=20, verbose_name='Ayudantes con cursos'),
        ),
        migrations.AddField(
            model_name='programacion',
            name='ayudantes_cursos_adjunto',
            field=models.FileField(blank=True, null=True, upload_to='programaciones/', verbose_name='Adjunto cursos'),
        ),
        migrations.AddField(
            model_name='programacion',
            name='nombre_contacto_recibe',
            field=models.CharField(blank=True, max_length=200, verbose_name='Nombre / contacto de quien recibe el servicio'),
        ),

        # --- Modelo hijo: cuadrillas (conductor / placa / ayudante) ---
        migrations.CreateModel(
            name='ProgramacionCuadrilla',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('conductor_novedad', models.CharField(blank=True, choices=[('NORMAL', 'Normal / trabaja'), ('INICIA_BODEGA', 'Inicia en bodega'), ('INCAPACIDAD', 'Incapacidad'), ('DESCANSA', 'Descansa'), ('PERMISO', 'Permiso')], default='NORMAL', max_length=20)),
                ('ayudante_novedad', models.CharField(blank=True, choices=[('NORMAL', 'Normal / trabaja'), ('INICIA_BODEGA', 'Inicia en bodega'), ('INCAPACIDAD', 'Incapacidad'), ('DESCANSA', 'Descansa'), ('PERMISO', 'Permiso')], default='NORMAL', max_length=20)),
                ('orden_fila', models.PositiveSmallIntegerField(default=0, help_text='Orden de la fila en el formato')),
                ('ayudante', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='cuadrillas_como_ayudante', to=settings.AUTH_USER_MODEL)),
                ('conductor', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='cuadrillas_como_conductor', to=settings.AUTH_USER_MODEL)),
                ('programacion', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='cuadrillas', to='gestion.programacion')),
                ('vehiculo', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='cuadrillas', to='gestion.vehiculo', verbose_name='Placa / vehículo')),
            ],
            options={
                'verbose_name': 'Cuadrilla de programación',
                'verbose_name_plural': 'Cuadrillas de programación',
                'ordering': ['orden_fila', 'id'],
            },
        ),
    ]
