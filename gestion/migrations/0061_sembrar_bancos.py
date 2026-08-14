# Siembra el catálogo de bancos para los datos de pago de los proveedores.
# La lista se amplía desde el admin; aquí van los comunes en Colombia.
from django.db import migrations

BANCOS = [
    'Bancolombia',
    'Banco de Bogotá',
    'Davivienda',
    'BBVA Colombia',
    'Banco de Occidente',
    'Banco Popular',
    'Banco AV Villas',
    'Banco Caja Social',
    'Scotiabank Colpatria',
    'Banco Agrario',
    'Itaú',
    'GNB Sudameris',
    'Bancoomeva',
    'Banco Pichincha',
    'Banco Falabella',
    'Banco W',
    'Banco Serfinanza',
    'Bancamía',
    'Lulo Bank',
    'Nu Colombia',
    'Nequi',
    'Daviplata',
]


def sembrar(apps, schema_editor):
    Banco = apps.get_model('gestion', 'Banco')
    for nombre in BANCOS:
        Banco.objects.get_or_create(nombre=nombre)


def revertir(apps, schema_editor):
    Banco = apps.get_model('gestion', 'Banco')
    Banco.objects.filter(nombre__in=BANCOS, proveedores__isnull=True).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('gestion', '0060_banco_proveedor_documentoproveedor_contactoproveedor'),
    ]

    operations = [
        migrations.RunPython(sembrar, revertir),
    ]
