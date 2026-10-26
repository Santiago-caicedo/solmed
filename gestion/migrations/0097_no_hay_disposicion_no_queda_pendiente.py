# «NO HAY DISPOSICIÓN» no deja nada que disponer (oct-2026, Santiago): las
# órdenes que quedaron SIN DISPONER con ese destino pasan a «No aplica», salvo
# que ya tengan una disposición registrada.
from django.db import migrations

SIN_DISPOSICION = 'NO HAY DISPOSICIÓN'


def sacar_del_pendiente(apps, schema_editor):
    OrdenServicio = apps.get_model('gestion', 'OrdenServicio')
    DisposicionOrden = apps.get_model('gestion', 'DisposicionOrden')
    con_registro = DisposicionOrden.objects.filter(deshecha=False).values('orden_id')
    n = (OrdenServicio.objects
         .filter(estado_disposicion='PENDIENTE',
                 programacion_origen__requiere_disposicion_final='NO',
                 programacion_origen__dispositor_final__nombre=SIN_DISPOSICION)
         .exclude(pk__in=con_registro)
         .update(estado_disposicion='NO_APLICA'))
    if n:
        print(f"\n  «NO HAY DISPOSICIÓN»: {n} orden(es) salieron de Disposiciones (No aplica).")


class Migration(migrations.Migration):

    dependencies = [
        ('gestion', '0096_asesoras_del_cliente'),
    ]

    operations = [
        migrations.RunPython(sacar_del_pendiente, migrations.RunPython.noop),
    ]
