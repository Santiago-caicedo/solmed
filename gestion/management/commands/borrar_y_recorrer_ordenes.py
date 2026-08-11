"""
Borra un RANGO de órdenes de servicio y CORRE los números de las siguientes
para que no quede hueco en el consecutivo.

    python manage.py borrar_y_recorrer_ordenes 22213 22216              # vista previa
    python manage.py borrar_y_recorrer_ordenes 22213 22216 --confirmar
    python manage.py borrar_y_recorrer_ordenes 22213 22216 --confirmar --borrar-archivos

Borrar una orden arrastra en cascada sus recorridos, actas de servicio (con
firma y PDF), encuestas de cierre, documentos, pagos y la programación que la
originó. Es IRREVERSIBLE: por eso, sin --confirmar solo muestra qué pasaría.

Después del borrado, las órdenes que quedan por encima del rango se renumeran
de forma consecutiva empezando en el primer número liberado, así que el hueco
se cierra y la siguiente orden nueva sigue el consecutivo sin saltos.

OJO: los PDF de actas ya firmadas llevan impreso el número viejo (no se
regeneran), y las notas de carga de los vehículos también lo mencionan.
"""
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from gestion.models import (
    DocumentoOrden, FotoAyudante, Manifiesto, OrdenServicio,
)
from gestion.renumeracion import hijos_de, mover_orden


class Command(BaseCommand):
    help = ("Borra las órdenes de un rango y corre la numeración de las "
            "siguientes (vista previa por defecto; ejecuta con --confirmar).")

    def add_arguments(self, parser):
        parser.add_argument('desde', type=int, help='Primer número a borrar (incluido).')
        parser.add_argument('hasta', type=int, help='Último número a borrar (incluido).')
        parser.add_argument(
            '--confirmar', action='store_true',
            help='Ejecuta de verdad (sin esto, solo muestra qué pasaría).',
        )
        parser.add_argument(
            '--borrar-archivos', action='store_true',
            help='Elimina también del storage los archivos de lo borrado '
                 '(PDFs, firmas, fotos, adjuntos).',
        )

    def handle(self, *args, **opciones):
        desde, hasta = opciones['desde'], opciones['hasta']
        if desde > hasta:
            raise CommandError("El número inicial no puede ser mayor que el final.")

        a_borrar = list(OrdenServicio.objects.filter(
            numero_orden__gte=desde, numero_orden__lte=hasta
        ).select_related('cliente').order_by('numero_orden'))
        if not a_borrar:
            raise CommandError(
                f"No hay ninguna orden entre la #{desde} y la #{hasta}.")

        posteriores = list(OrdenServicio.objects.filter(
            numero_orden__gt=hasta
        ).select_related('cliente').order_by('numero_orden'))
        # Las siguientes se renumeran consecutivas desde el primer hueco.
        movimientos = [(o.numero_orden, desde + i) for i, o in enumerate(posteriores)]

        # --- Vista previa ---
        self.stdout.write(self.style.MIGRATE_HEADING(
            f'\nSE BORRARÍAN {len(a_borrar)} orden(es) entre la #{desde} y la #{hasta}:'))
        firmadas = 0
        for orden in a_borrar:
            self.stdout.write(self.style.MIGRATE_LABEL(
                f'\n  #{orden.numero_orden} — {orden.cliente.nombre}'))
            self.stdout.write(
                f'      Creada: {orden.fecha_creacion:%d/%m/%Y}   '
                f'Estado: {orden.get_estado_orden_display()}')
            self.stdout.write(f'      Dirección: {orden.direccion_servicio or "—"}')
            # Fecha del servicio, placa y conductor: es lo que permite
            # reconocer de verdad cuál orden es cuál antes de borrarla.
            for rec in orden.recorridos.select_related('vehiculo', 'conductor'):
                quien = (rec.conductor.get_full_name() or rec.conductor.username
                         ) if rec.conductor else 'sin conductor'
                self.stdout.write(
                    f'      Servicio: {rec.fecha_recorrido:%d/%m/%Y} · '
                    f'placa {rec.vehiculo.placa if rec.vehiculo else "—"} · {quien}')
            detalle = ' · '.join(f'{etiqueta}: {cuantos}'
                                 for etiqueta, cuantos in hijos_de(orden.numero_orden)
                                 if cuantos)
            if detalle:
                self.stdout.write(f'      Arrastra → {detalle}')
            actas = Manifiesto.objects.filter(recorrido__orden=orden)
            n_firmadas = actas.filter(estado_firma='FIRMADO').count()
            if n_firmadas:
                firmadas += n_firmadas
                self.stdout.write(self.style.WARNING(
                    f'      ⚠ {n_firmadas} acta(s) FIRMADA(S) por el cliente'))

        if firmadas:
            self.stdout.write(self.style.WARNING(
                f'\n  ATENCIÓN: se perderían {firmadas} acta(s) ya firmada(s) '
                f'por el cliente, con su firma y su PDF.'))

        if movimientos:
            self.stdout.write(self.style.MIGRATE_HEADING(
                f'\nY SE RENUMERARÍAN {len(movimientos)} orden(es):'))
            for (viejo, nuevo), orden in zip(movimientos, posteriores):
                self.stdout.write(
                    f'  #{viejo}  →  #{nuevo}   {orden.cliente.nombre}')
            self.stdout.write(
                f'\n  La próxima orden nueva sería la #{movimientos[-1][1] + 1}.')
        else:
            self.stdout.write(
                '\nNo hay órdenes posteriores: no hay nada que renumerar. '
                f'La próxima orden nueva sería la #{max(desde, OrdenServicio.NUMERO_INICIAL)}.')

        if not opciones['confirmar']:
            self.stdout.write(self.style.WARNING(
                '\nVISTA PREVIA: no se cambió nada. Para ejecutarlo de verdad:\n'
                f'  python manage.py borrar_y_recorrer_ordenes {desde} {hasta} --confirmar'))
            return

        # Referencias a los archivos ANTES de borrar las filas (después ya no
        # habría cómo saber cuáles eran).
        archivos = []
        if opciones['borrar_archivos']:
            numeros = [o.numero_orden for o in a_borrar]
            fuentes = [
                (Manifiesto.objects.filter(recorrido__orden__in=numeros),
                 ('pdf_generado', 'firma_cliente')),
                (DocumentoOrden.objects.filter(orden__in=numeros), ('archivo',)),
                (FotoAyudante.objects.filter(
                    cuadrilla__programacion__orden__in=numeros), ('archivo',)),
                (OrdenServicio.objects.filter(numero_orden__in=numeros),
                 ('bascula_adjunto', 'registro_fotografico_adjunto')),
            ]
            for consulta, campos in fuentes:
                for obj in consulta.iterator():
                    for campo in campos:
                        f = getattr(obj, campo)
                        if f and f.name:
                            archivos.append((f.storage, f.name))

        with transaction.atomic():
            OrdenServicio.objects.filter(
                numero_orden__gte=desde, numero_orden__lte=hasta).delete()
            # De menor a mayor: cada destino ya quedó libre (borrado o movido).
            for viejo, nuevo in movimientos:
                mover_orden(viejo, nuevo)

        self.stdout.write(self.style.SUCCESS(
            f'\nListo: {len(a_borrar)} orden(es) borrada(s) y '
            f'{len(movimientos)} renumerada(s).'))

        if opciones['borrar_archivos']:
            borrados, fallidos = 0, 0
            for storage, nombre in archivos:
                try:
                    storage.delete(nombre)
                    borrados += 1
                except Exception:
                    fallidos += 1
            self.stdout.write(self.style.SUCCESS(
                f'  Archivos eliminados del storage: {borrados}'))
            if fallidos:
                self.stdout.write(self.style.WARNING(
                    f'  Archivos que no se pudieron eliminar: {fallidos} '
                    f'(revísalos con auditar_archivos).'))
        else:
            self.stdout.write(self.style.WARNING(
                '  Los archivos (PDFs, firmas, fotos) de lo borrado quedaron en '
                'el storage. Para eliminarlos también, usa --borrar-archivos.'))

        self.stdout.write(self.style.WARNING(
            '  Recuerda: los PDF de actas firmadas que se renumeraron siguen '
            'mostrando el número viejo (no se regeneran).'))
