"""
Siembra el destino interno "NO HAY DISPOSICIÓN": el servicio pasa sin
disposición final y SIN dejar nada pendiente (el camión no queda cargado).
Antes, responder "No" obligaba a elegir dónde quedaba el contenido, aunque en
servicios como sondeo o lavado no quede contenido que rastrear.
"""
from django.db import migrations

NOMBRE = 'NO HAY DISPOSICIÓN'
DESCRIPCION = 'El servicio pasa sin disposición y sin dejar carga pendiente.'


def sembrar(apps, schema_editor):
    Dispositor = apps.get_model('gestion', 'Dispositor')
    Dispositor.objects.update_or_create(
        nombre=NOMBRE,
        defaults={'tipo': 'INTERNO', 'descripcion': DESCRIPCION, 'activo': True},
    )


def quitar(apps, schema_editor):
    Dispositor = apps.get_model('gestion', 'Dispositor')
    # Solo si ninguna programación lo usó (dispositor_final es PROTECT).
    Dispositor.objects.filter(nombre=NOMBRE, programaciones__isnull=True).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('gestion', '0053_envio_correo_responder_a'),
    ]

    operations = [
        migrations.RunPython(sembrar, quitar),
    ]
