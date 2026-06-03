"""
Script de creacion de usuarios iniciales para Solmed CRM.
Ejecutar con:  venv/Scripts/python.exe crear_usuarios.py
"""
import os
import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()

from django.contrib.auth.models import User, Group
from django.db import transaction


usuarios = [
    {
        "username": "admin_solmed",
        "password": "Admin2026*",
        "first_name": "Administrador",
        "last_name": "Solmed",
        "email": "admin@solmed.com",
        "is_superuser": True,
        "is_staff": True,
        "group": None,
    },
    {
        "username": "asesor1",
        "password": "Asesor2026*",
        "first_name": "Ana",
        "last_name": "Asesora",
        "email": "asesor1@solmed.com",
        "is_superuser": False,
        "is_staff": False,
        "group": "Asesores",
    },
    {
        "username": "planificador1",
        "password": "Planif2026*",
        "first_name": "Pedro",
        "last_name": "Planificador",
        "email": "planificador1@solmed.com",
        "is_superuser": False,
        "is_staff": False,
        "group": "Planificadores",
    },
    {
        "username": "conductor1",
        "password": "Conductor2026*",
        "first_name": "Carlos",
        "last_name": "Conductor",
        "email": "conductor1@solmed.com",
        "is_superuser": False,
        "is_staff": False,
        "group": "Conductores",
    },
]


def main():
    print("=" * 60)
    print("Creando usuarios Solmed CRM")
    print("=" * 60)

    with transaction.atomic():
        for data in usuarios:
            user, created = User.objects.get_or_create(
                username=data["username"],
                defaults={
                    "email": data["email"],
                    "first_name": data["first_name"],
                    "last_name": data["last_name"],
                    "is_superuser": data["is_superuser"],
                    "is_staff": data["is_staff"],
                },
            )
            user.email = data["email"]
            user.first_name = data["first_name"]
            user.last_name = data["last_name"]
            user.is_superuser = data["is_superuser"]
            user.is_staff = data["is_staff"]
            user.set_password(data["password"])
            user.save()

            if data["group"]:
                try:
                    grupo = Group.objects.get(name=data["group"])
                    user.groups.clear()
                    user.groups.add(grupo)
                    rol = data["group"]
                except Group.DoesNotExist:
                    rol = f"(grupo '{data['group']}' no existe)"
            else:
                user.groups.clear()
                rol = "Superusuario"

            estado = "creado" if created else "actualizado"
            print(f"[{estado.upper():11}] {user.username:18} -> {rol}")

    print("=" * 60)
    print("Listo.")


if __name__ == "__main__":
    main()
