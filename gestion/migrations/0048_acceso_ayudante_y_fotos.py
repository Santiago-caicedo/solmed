"""
Acceso del ayudante por token (sin usuario ni contraseña) y sus fotos.

Los tokens son ÚNICOS, así que no se pueden añadir con un default: todas las
filas existentes quedarían con el mismo valor y la restricción fallaría. Se
añaden primero sin restricción, se le da un UUID distinto a cada cuadrilla y
solo entonces se marcan como únicos.
"""
import uuid

import django.db.models.deletion
from django.db import migrations, models


def poblar_tokens(apps, schema_editor):
    ProgramacionCuadrilla = apps.get_model('gestion', 'ProgramacionCuadrilla')
    for cuadrilla in ProgramacionCuadrilla.objects.all().only('pk'):
        ProgramacionCuadrilla.objects.filter(pk=cuadrilla.pk).update(
            token_ayudante=uuid.uuid4(), token_ayudante2=uuid.uuid4()
        )


class Migration(migrations.Migration):

    dependencies = [
        ('gestion', '0047_tiporesiduo'),
    ]

    operations = [
        # 1) Se añaden sin unicidad (todas las filas quedan en NULL).
        migrations.AddField(
            model_name='programacioncuadrilla',
            name='token_ayudante',
            field=models.UUIDField(default=uuid.uuid4, editable=False, null=True),
        ),
        migrations.AddField(
            model_name='programacioncuadrilla',
            name='token_ayudante2',
            field=models.UUIDField(default=uuid.uuid4, editable=False, null=True),
        ),
        # 2) Un token distinto por cuadrilla existente.
        migrations.RunPython(poblar_tokens, migrations.RunPython.noop),
        # 3) Ahora sí, únicos.
        migrations.AlterField(
            model_name='programacioncuadrilla',
            name='token_ayudante',
            field=models.UUIDField(default=uuid.uuid4, editable=False, null=True, unique=True),
        ),
        migrations.AlterField(
            model_name='programacioncuadrilla',
            name='token_ayudante2',
            field=models.UUIDField(default=uuid.uuid4, editable=False, null=True, unique=True),
        ),
        migrations.CreateModel(
            name='FotoAyudante',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('slot', models.PositiveSmallIntegerField(choices=[(1, 'Ayudante'), (2, 'Segundo ayudante')])),
                ('novedad', models.CharField(help_text='Código de la novedad que la exige', max_length=30)),
                ('archivo', models.ImageField(upload_to='fotos_ayudantes/')),
                ('fecha_subida', models.DateTimeField(auto_now_add=True)),
                ('cuadrilla', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='fotos_ayudantes', to='gestion.programacioncuadrilla')),
            ],
            options={
                'verbose_name': 'Foto del ayudante',
                'verbose_name_plural': 'Fotos de los ayudantes',
                'ordering': ['fecha_subida'],
            },
        ),
    ]
