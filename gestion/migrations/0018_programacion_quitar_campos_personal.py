# Generated manually: quita del checklist de Programacion los campos que ahora
# viven en el expediente del personal (cursos y adjunto de seguridad social).

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('gestion', '0017_documentopersonal'),
    ]

    operations = [
        migrations.RemoveField(model_name='programacion', name='responsable_sg_adjunto'),
        migrations.RemoveField(model_name='programacion', name='ayudantes_cursos'),
        migrations.RemoveField(model_name='programacion', name='ayudantes_cursos_adjunto'),
    ]
