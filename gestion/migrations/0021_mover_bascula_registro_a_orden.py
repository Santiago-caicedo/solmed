# Generated manually: báscula y registro fotográfico pasan de Programacion a OrdenServicio.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('gestion', '0020_perfilpersona'),
    ]

    operations = [
        # --- Quitar de Programacion ---
        migrations.RemoveField(model_name='programacion', name='bascula'),
        migrations.RemoveField(model_name='programacion', name='bascula_adjunto'),
        migrations.RemoveField(model_name='programacion', name='registro_fotografico'),
        migrations.RemoveField(model_name='programacion', name='registro_fotografico_adjunto'),

        # --- Agregar a OrdenServicio ---
        migrations.AddField(
            model_name='ordenservicio',
            name='bascula',
            field=models.CharField(blank=True, choices=[('PESAN', 'Pesan'), ('NO_PESAN', 'No pesan'), ('PESO_CLIENTE', 'Peso del cliente')], max_length=20, verbose_name='Báscula'),
        ),
        migrations.AddField(
            model_name='ordenservicio',
            name='bascula_adjunto',
            field=models.FileField(blank=True, null=True, upload_to='ordenes_documentos/', verbose_name='Adjunto báscula'),
        ),
        migrations.AddField(
            model_name='ordenservicio',
            name='registro_fotografico',
            field=models.CharField(blank=True, choices=[('SI', 'Sí'), ('NO', 'No')], max_length=2, verbose_name='Registro fotográfico'),
        ),
        migrations.AddField(
            model_name='ordenservicio',
            name='registro_fotografico_adjunto',
            field=models.FileField(blank=True, null=True, upload_to='ordenes_documentos/', verbose_name='Adjunto registro fotográfico'),
        ),
    ]
