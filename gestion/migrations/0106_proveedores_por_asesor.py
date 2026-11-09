"""
Proveedores de disposición final por asesor (nov-2026, Santiago): desde ahora
cada asesora ve solo los proveedores que tiene marcados en «Gestionar
accesos» y, de cada uno, los tipos de documento marcados. Decisión de
Santiago: al desplegar nadie pierde nada, así que a quien hoy ve el módulo
(`proveedores.ver`) se le marcan todos los proveedores que existen, con todos
sus documentos. Los que se creen después nacen ocultos.

A las asesoras sin registro de accesos (tenían «lo de siempre») se les crea
uno con lo de siempre más los proveedores, para que no los pierdan.
"""
from django.db import migrations

TIPOS = ('RUT', 'CAMARA_COMERCIO', 'CEDULA_REP_LEGAL', 'CERTIFICACION_BANCARIA', 'DOC_AMBIENTAL')


def marcar_todo(apps, schema_editor):
    from gestion.accesos import BASE
    AccesosAsesor = apps.get_model('gestion', 'AccesosAsesor')
    Dispositor = apps.get_model('gestion', 'Dispositor')
    User = apps.get_model('auth', 'User')
    claves_provs = set()
    for pk in Dispositor.objects.filter(tipo='PROVEEDOR').values_list('pk', flat=True):
        claves_provs.add(f'proveedores.p{pk}')
        claves_provs |= {f'proveedores.p{pk}_{t}' for t in TIPOS}
    if not claves_provs:
        return
    asesores = (User.objects.filter(groups__name='Asesores', is_superuser=False)
                .exclude(groups__name='Administradores').distinct())
    for usuario in asesores:
        registro = AccesosAsesor.objects.filter(usuario=usuario).first()
        claves = set(registro.claves or []) if registro else set(BASE)
        if 'proveedores.ver' not in claves:
            continue
        nuevas = claves | claves_provs
        if registro is None:
            AccesosAsesor.objects.create(usuario=usuario, claves=sorted(nuevas))
        elif nuevas != claves:
            registro.claves = sorted(nuevas)
            registro.save(update_fields=['claves'])


class Migration(migrations.Migration):

    dependencies = [
        ('gestion', '0105_accesos_separados'),
        ('auth', '0012_alter_user_first_name_max_length'),
    ]

    operations = [
        migrations.RunPython(marcar_todo, migrations.RunPython.noop),
    ]
