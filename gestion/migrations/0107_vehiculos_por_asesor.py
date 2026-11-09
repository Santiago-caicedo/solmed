"""
Vehículos por asesor (nov-2026, Santiago, igual que los proveedores de
disposición en la 0106): desde ahora cada asesora ve en el módulo Vehículos
solo los que tiene marcados en «Gestionar accesos» y, de cada uno, los
papeles marcados (SOAT, tecnomecánica, tarjeta de propiedad). Al desplegar
nadie pierde nada: a quien hoy ve el módulo (`vehiculos.ver`) se le marcan
todos los vehículos que existen, con sus tres papeles. Los que se creen
después nacen ocultos.

A las asesoras sin registro de accesos se les crea uno con lo de siempre más
los vehículos.
"""
from django.db import migrations

TIPOS = ('SOAT', 'TECNOMECANICA', 'TARJETA')


def marcar_todo(apps, schema_editor):
    from gestion.accesos import BASE
    AccesosAsesor = apps.get_model('gestion', 'AccesosAsesor')
    Vehiculo = apps.get_model('gestion', 'Vehiculo')
    User = apps.get_model('auth', 'User')
    claves_vehs = set()
    for pk in Vehiculo.objects.values_list('pk', flat=True):
        claves_vehs.add(f'vehiculos.v{pk}')
        claves_vehs |= {f'vehiculos.v{pk}_{t}' for t in TIPOS}
    if not claves_vehs:
        return
    asesores = (User.objects.filter(groups__name='Asesores', is_superuser=False)
                .exclude(groups__name='Administradores').distinct())
    for usuario in asesores:
        registro = AccesosAsesor.objects.filter(usuario=usuario).first()
        claves = set(registro.claves or []) if registro else set(BASE)
        if 'vehiculos.ver' not in claves:
            continue
        nuevas = claves | claves_vehs
        if registro is None:
            AccesosAsesor.objects.create(usuario=usuario, claves=sorted(nuevas))
        elif nuevas != claves:
            registro.claves = sorted(nuevas)
            registro.save(update_fields=['claves'])


class Migration(migrations.Migration):

    dependencies = [
        ('gestion', '0106_proveedores_por_asesor'),
    ]

    operations = [
        migrations.RunPython(marcar_todo, migrations.RunPython.noop),
    ]
