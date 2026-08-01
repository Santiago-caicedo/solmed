"""
Borra TODAS las órdenes de servicio con todo lo que cuelga de ellas —
recorridos, actas (manifiestos), encuestas de cierre, documentos, pagos y la
PROGRAMACIÓN que las originó (con sus cuadrillas y las fotos de los
ayudantes)— y también las programaciones que quedaron sin orden (borradores
o canceladas). Deja intactos clientes, vehículos, personal y los catálogos
(sitios, residuos, básculas, proveedores).

Es DESTRUCTIVO e irreversible, así que por defecto solo MUESTRA lo que
borraría; para ejecutar de verdad hay que pasar --confirmar.

    python manage.py borrar_ordenes                  # vista previa (no borra)
    python manage.py borrar_ordenes --confirmar
    python manage.py borrar_ordenes --confirmar --borrar-archivos

--borrar-archivos elimina además del storage (disco o S3) los PDF de actas y
encuestas, las firmas, los adjuntos de la orden y las fotos de los ayudantes
de lo borrado. Sin ese flag, los archivos quedan huérfanos en el storage
(se pueden revisar luego con `auditar_archivos`).
"""
from django.core.management.base import BaseCommand
from django.db import transaction

from gestion.models import (
    DocumentoOrden, EncuestaConductor, FotoAyudante, Manifiesto, OrdenServicio,
    Pago, Programacion, ProgramacionCuadrilla, Recorrido,
)


class Command(BaseCommand):
    help = ("Borra todas las órdenes de servicio y sus programaciones "
            "(vista previa por defecto; ejecuta con --confirmar).")

    def add_arguments(self, parser):
        parser.add_argument(
            '--confirmar', action='store_true',
            help='Ejecuta el borrado de verdad (sin esto, solo muestra el resumen).',
        )
        parser.add_argument(
            '--borrar-archivos', action='store_true',
            help='Elimina también del storage los archivos de lo borrado (PDFs, firmas, fotos, adjuntos).',
        )

    # (modelo, campos de archivo) de todo lo que cae con las órdenes.
    ARCHIVOS = [
        (Manifiesto, ('pdf_generado', 'firma_cliente')),
        (EncuestaConductor, ('pdf_generado',)),
        (DocumentoOrden, ('archivo',)),
        (FotoAyudante, ('archivo',)),
        (OrdenServicio, ('bascula_adjunto', 'registro_fotografico_adjunto')),
    ]

    def handle(self, *args, **opciones):
        conteos = [
            ('Órdenes de servicio', OrdenServicio.objects.count()),
            ('Programaciones (con orden y borradores)', Programacion.objects.count()),
            ('Cuadrillas', ProgramacionCuadrilla.objects.count()),
            ('Recorridos', Recorrido.objects.count()),
            ('Actas de servicio (manifiestos)', Manifiesto.objects.count()),
            ('Encuestas de cierre', EncuestaConductor.objects.count()),
            ('Documentos de órdenes', DocumentoOrden.objects.count()),
            ('Fotos de ayudantes', FotoAyudante.objects.count()),
            ('Pagos', Pago.objects.count()),
        ]

        self.stdout.write(self.style.MIGRATE_HEADING('Esto se borraría:'))
        for etiqueta, n in conteos:
            self.stdout.write(f'  {etiqueta}: {n}')
        total = sum(n for _, n in conteos)

        if total == 0:
            self.stdout.write(self.style.SUCCESS('No hay nada que borrar.'))
            return

        if not opciones['confirmar']:
            self.stdout.write('')
            self.stdout.write(self.style.WARNING(
                'VISTA PREVIA: no se borró nada. Para ejecutar de verdad:\n'
                '  python manage.py borrar_ordenes --confirmar'
            ))
            return

        # Con --borrar-archivos: se recogen las referencias ANTES de borrar las
        # filas (después ya no habría cómo saber qué archivos eran).
        archivos = []
        if opciones['borrar_archivos']:
            for modelo, campos in self.ARCHIVOS:
                for obj in modelo.objects.all().iterator():
                    for campo in campos:
                        f = getattr(obj, campo)
                        if f and f.name:
                            archivos.append((f.storage, f.name))

        with transaction.atomic():
            # Borrar las órdenes arrastra recorridos, actas, encuestas,
            # documentos, pagos y la programación de origen (con cuadrillas y
            # fotos de ayudantes). Luego caen las programaciones sin orden.
            _, por_modelo = OrdenServicio.objects.all().delete()
            _, por_modelo2 = Programacion.objects.all().delete()

        for etiqueta, n in conteos:
            if n:
                self.stdout.write(self.style.SUCCESS(f'  Borrado — {etiqueta}: {n}'))

        # Los archivos se eliminan DESPUÉS de confirmar la transacción: si el
        # borrado fallara, no habríamos tocado el storage.
        if opciones['borrar_archivos']:
            borrados, fallidos = 0, 0
            for storage, nombre in archivos:
                try:
                    storage.delete(nombre)
                    borrados += 1
                except Exception:
                    fallidos += 1
            self.stdout.write(self.style.SUCCESS(
                f'  Archivos eliminados del storage: {borrados}'
            ))
            if fallidos:
                self.stdout.write(self.style.WARNING(
                    f'  Archivos que no se pudieron eliminar: {fallidos} '
                    f'(revisa con auditar_archivos)'
                ))
        else:
            self.stdout.write(self.style.WARNING(
                'Los archivos (PDFs, firmas, fotos) quedaron en el storage. '
                'Para borrarlos también, usa --borrar-archivos.'
            ))

        self.stdout.write(self.style.SUCCESS('Listo: órdenes y programaciones eliminadas.'))
