# Casilla «Sumar estas horas al historial de horas trabajadas» en las
# actividades del plan (oct-2026), igual que en las novedades (0009).

from django.db import migrations, models


def marcar_las_que_ya_sumaban(apps, schema_editor):
    """
    Hasta ahora toda actividad con sus dos horas sumaba en el centro de
    control. Se marca la casilla en esas para que las horas trabajadas de
    nadie cambien con el despliegue.
    """
    Asignacion = apps.get_model('planes', 'Asignacion')
    Asignacion.objects.filter(hora__isnull=False, hora_fin__isnull=False).update(suma_horas=True)


class Migration(migrations.Migration):

    dependencies = [
        ('planes', '0009_novedad_suma_horas'),
    ]

    operations = [
        migrations.AddField(
            model_name='asignacion',
            name='suma_horas',
            field=models.BooleanField(default=False, verbose_name='Sumar estas horas al historial de horas trabajadas'),
        ),
        migrations.RunPython(marcar_las_que_ya_sumaban, migrations.RunPython.noop),
    ]
