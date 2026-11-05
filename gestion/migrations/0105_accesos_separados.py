"""
Casillas separadas en «Gestionar accesos» (nov-2026, Santiago): los dos tipos
de proveedor y las dos pantallas de fotos se abren por separado. Las claves
viejas siguen valiendo para la parte que conservan (`proveedores` = disposición
final, `fotos` = fotos de ayudantes); a quien ya las tenía marcadas se le
marca igual la parte nueva, así al desplegar nadie gana ni pierde acceso.
"""
from django.db import migrations

EQUIVALENCIAS = {
    'proveedores.ver': 'otros_proveedores.ver',
    'proveedores.editar': 'otros_proveedores.editar',
    'proveedores.eliminar': 'otros_proveedores.eliminar',
    'fotos.ver': 'fotos_servicios.ver',
}


def separar(apps, schema_editor):
    AccesosAsesor = apps.get_model('gestion', 'AccesosAsesor')
    for registro in AccesosAsesor.objects.all():
        claves = set(registro.claves or [])
        nuevas = claves | {EQUIVALENCIAS[c] for c in claves if c in EQUIVALENCIAS}
        if nuevas != claves:
            registro.claves = sorted(nuevas)
            registro.save(update_fields=['claves'])


class Migration(migrations.Migration):

    dependencies = [
        ('gestion', '0104_gastos'),
    ]

    operations = [
        migrations.RunPython(separar, migrations.RunPython.noop),
    ]
