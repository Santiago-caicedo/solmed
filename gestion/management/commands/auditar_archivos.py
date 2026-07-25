"""
Audita los archivos referenciados en la base de datos contra el storage real
(S3 en producción). Lista los que FALTAN (registros cuyo archivo no está en el
bucket) — típicamente documentos subidos cuando se guardaba en disco local.

Uso:
    python manage.py auditar_archivos
        Solo reporta: cuántos archivos hay y cuáles faltan en el storage.

    python manage.py auditar_archivos --reparar-desde /ruta/al/media
        Para cada archivo que falta, si existe en esa carpeta local
        (/ruta/al/media/<nombre>), lo sube al storage (S3). Útil para migrar
        los que quedaron en el disco del servidor.

Ejecutar en el servidor (donde el IAM Role da acceso a S3).
"""
import os

from django.apps import apps
from django.core.files.base import File
from django.core.management.base import BaseCommand
from django.db import models


class Command(BaseCommand):
    help = "Revisa qué archivos referenciados en la BD faltan en el storage (S3) y opcionalmente los repara desde el disco local."

    def add_arguments(self, parser):
        parser.add_argument(
            '--reparar-desde', default=None, metavar='DIR',
            help='Carpeta local (ej. el MEDIA_ROOT antiguo) desde donde subir al storage los archivos que falten.',
        )

    def _campos_archivo(self, model):
        return [
            f.name for f in model._meta.get_fields()
            if isinstance(f, models.FileField)
        ]

    def handle(self, *args, **options):
        reparar_dir = options['reparar_desde']
        if reparar_dir and not os.path.isdir(reparar_dir):
            self.stderr.write(self.style.ERROR(f"No existe la carpeta: {reparar_dir}"))
            return

        total = faltan = reparados = 0
        faltantes = []

        for model in apps.get_app_config('gestion').get_models():
            campos = self._campos_archivo(model)
            if not campos:
                continue
            for obj in model.objects.all().iterator():
                for campo in campos:
                    filefield = getattr(obj, campo)
                    if not filefield:
                        continue
                    total += 1
                    try:
                        existe = filefield.storage.exists(filefield.name)
                    except Exception as e:
                        existe = False
                        self.stderr.write(f"  (error consultando {filefield.name}: {e})")
                    if existe:
                        continue

                    faltan += 1
                    etiqueta = f"{model.__name__} #{obj.pk} .{campo} -> {filefield.name}"
                    faltantes.append(etiqueta)

                    if reparar_dir:
                        ruta_local = os.path.join(reparar_dir, filefield.name)
                        if os.path.isfile(ruta_local):
                            with open(ruta_local, 'rb') as fh:
                                # save() reescribe el archivo en el storage con el
                                # mismo nombre (por eso no cambia lo guardado en BD).
                                filefield.storage.save(filefield.name, File(fh))
                            reparados += 1
                            self.stdout.write(self.style.SUCCESS(f"  SUBIDO: {etiqueta}"))
                        else:
                            self.stdout.write(self.style.WARNING(
                                f"  FALTA y no está en local: {etiqueta}"))
                    else:
                        self.stdout.write(self.style.WARNING(f"  FALTA: {etiqueta}"))

        self.stdout.write("")
        self.stdout.write(f"Archivos revisados: {total}")
        self.stdout.write(f"Faltan en el storage: {faltan}")
        if reparar_dir:
            self.stdout.write(f"Reparados (subidos desde local): {reparados}")
            pendientes = faltan - reparados
            if pendientes:
                self.stdout.write(self.style.WARNING(
                    f"Aún faltan {pendientes}: no estaban en {reparar_dir}. Hay que recargarlos a mano."))
        elif faltan:
            self.stdout.write(self.style.WARNING(
                "Para repararlos desde el disco del servidor: "
                "python manage.py auditar_archivos --reparar-desde /ruta/al/media"))
