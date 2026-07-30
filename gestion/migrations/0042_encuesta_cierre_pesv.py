"""
La encuesta de cierre pasa a ser siete preguntas de Sí/No sobre seguridad vial
y salud del conductor (PESV). Sale la sección ambiental (tipo de residuo,
dispositor final, nivel de combustible) y las novedades en la vía.

`hubo_incidente` se RENOMBRA a `condicion_riesgo` (la pregunta 7) para no perder
las respuestas ya registradas ni su relación con el tipo y la descripción del
evento. Las cinco preguntas nuevas quedan VACÍAS en las encuestas anteriores: no
se les inventa una respuesta, porque son evidencia de cumplimiento.
"""
from django.db import migrations, models

SI_NO = [('SI', 'Sí'), ('NO', 'No')]


class Migration(migrations.Migration):

    dependencies = [
        ('gestion', '0041_ordenservicio_estado_conciliacion_and_more'),
    ]

    operations = [
        # --- La pregunta 7 conserva lo ya respondido ---
        migrations.RenameField(
            model_name='encuestaconductor',
            old_name='hubo_incidente',
            new_name='condicion_riesgo',
        ),
        migrations.AlterField(
            model_name='encuestaconductor',
            name='condicion_riesgo',
            field=models.CharField(
                choices=SI_NO, max_length=2,
                verbose_name='¿Estuvo involucrado o presenció alguna condición de riesgo o casi-accidente durante el turno?',
            ),
        ),

        # --- Preguntas nuevas (vacías en el histórico) ---
        migrations.AddField(
            model_name='encuestaconductor',
            name='realizo_pausas_activas',
            field=models.CharField(
                choices=SI_NO, default='', max_length=2,
                verbose_name='¿Realizó las pausas activas recomendadas durante el trayecto (al menos 05-10 minutos por cada 2 horas de conducción)?',
            ),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name='encuestaconductor',
            name='molestias_fisicas',
            field=models.CharField(
                choices=SI_NO, default='', max_length=2,
                verbose_name='¿Ha experimentado molestias físicas (lumbalgia, dolor de cuello o piernas) durante o al finalizar el recorrido?',
            ),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name='encuestaconductor',
            name='tiempos_adecuados',
            field=models.CharField(
                choices=SI_NO, default='', max_length=2,
                verbose_name='¿Considera que los tiempos asignados para la ruta son adecuados y realistas sin necesidad de exceder los límites de velocidad?',
            ),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name='encuestaconductor',
            name='cabina_optima',
            field=models.CharField(
                choices=SI_NO, default='', max_length=2,
                verbose_name='¿El asiento, cinturón de seguridad y controles de la cabina se encuentran en condiciones óptimas de confort y funcionamiento?',
            ),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name='encuestaconductor',
            name='zonas_seguras_descanso',
            field=models.CharField(
                choices=SI_NO, default='', max_length=2,
                verbose_name='¿Dispuso de zonas seguras y autorizadas para realizar sus paradas de descanso o alimentación durante la ruta?',
            ),
            preserve_default=False,
        ),

        # --- Textos actualizados ---
        migrations.AlterField(
            model_name='encuestaconductor',
            name='presento_fatiga',
            field=models.CharField(
                choices=SI_NO, max_length=2,
                verbose_name='¿Presentó síntomas de fatiga, cansancio o microsueños durante el desarrollo de la ruta?',
            ),
        ),
        migrations.AlterField(
            model_name='encuestaconductor',
            name='descripcion_incidente',
            field=models.TextField(blank=True, verbose_name='Descripción de lo ocurrido'),
        ),

        # --- Sale la sección ambiental y las novedades en la vía ---
        migrations.RemoveField(model_name='encuestaconductor', name='dispositor_final'),
        migrations.RemoveField(model_name='encuestaconductor', name='tipo_residuo'),
        migrations.RemoveField(model_name='encuestaconductor', name='nivel_combustible'),
        migrations.RemoveField(model_name='encuestaconductor', name='riesgo_vial'),
    ]
