from django.db import migrations

# Proveedores / gestores de disposición final para el desplegable de la
# programación (y la encuesta del conductor). Se pueden ampliar desde el admin.
DISPOSITORES = [
    "APS SAS",
    "BIOCARBONO SAS",
    "BIOLODOS",
    "CEMEX",
    "CONSORCIO AQUAPLUS",
    "DIACO",
    "DULCOLSA",
    "ECOBIOR",
    "EKO BOJACA",
    "ENERGY ORGANIC SAS",
    "MAQUINAS AMARILLAS S.A.S.",
    "TRACOL SAS",
    "TRASIEGO TANQUE AUXILIAR",
    "TRASIEGO TANQUE SUBTERRANEO",
    "TRASIEGO A ------ PLACA",
    "TRATAR AMBIENTAL",
    "VEOLIA",
    "DEJAR CARRO CARGADO",
]


def crear(apps, schema_editor):
    Dispositor = apps.get_model('gestion', 'Dispositor')
    for nombre in DISPOSITORES:
        Dispositor.objects.get_or_create(nombre=nombre)


def borrar(apps, schema_editor):
    Dispositor = apps.get_model('gestion', 'Dispositor')
    Dispositor.objects.filter(nombre__in=DISPOSITORES).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('gestion', '0031_programacion_dispositor_final_and_more'),
    ]

    operations = [
        migrations.RunPython(crear, borrar),
    ]
