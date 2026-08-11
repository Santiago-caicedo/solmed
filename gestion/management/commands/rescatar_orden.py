"""
Trae una orden de servicio COMPLETA desde una base de RESCATE (una copia de la
base restaurada a un punto en el tiempo) hacia la base de producción, sin tocar
nada de lo que ya hay.

Sirve cuando se borró una orden por error y no se puede restaurar la base
entera porque ya hay trabajo nuevo encima.

    # 1. En el .env: DB_RESCATE_HOST=<endpoint de la copia restaurada>
    # 2. Vista previa (no escribe nada):
    python manage.py rescatar_orden 22214
    # 3. Traerla de verdad (al primer número libre):
    python manage.py rescatar_orden 22214 --confirmar
    # ...o a un número concreto que esté libre:
    python manage.py rescatar_orden 22214 --confirmar --numero 22240

Se traen: la orden, su programación con la cuadrilla y las fotos de los
ayudantes, los recorridos, el acta con sus novedades y medidas de ACPM, la
encuesta de cierre, los pagos y los documentos.

Los datos que la orden solo REFERENCIA (cliente, vehículos, personal) no se
copian: se buscan en producción, que es donde siguen estando. Si alguno ya no
existe, el comando lo dice y no escribe nada.

Los ARCHIVOS (PDF del acta, firma, fotos) no se copian: las filas quedan
apuntando a las mismas rutas del storage. Si también se borraron de S3, hay que
recuperarlos aparte (versionado del bucket) o regenerarlos.
"""
from django.core.management.base import BaseCommand, CommandError
from django.db import connections, transaction
from django.db.models import Max

from gestion.models import (
    DocumentoOrden, EncuestaConductor, FotoAyudante, Manifiesto, MedidaACPM,
    NovedadOperacional, OrdenServicio, Pago, Programacion, ProgramacionCuadrilla,
    Recorrido,
)

RESCATE = 'rescate'


def _valores(obj, saltar=()):
    """Los campos concretos del objeto, listos para reconstruirlo en otra base."""
    datos = {}
    for campo in obj._meta.concrete_fields:
        if campo.primary_key or campo.attname in saltar:
            continue
        datos[campo.attname] = getattr(obj, campo.attname)
    return datos


def _auto_fechas(modelo):
    """Campos auto_now_add: Django los pisa al insertar, hay que devolverlos."""
    return [c.attname for c in modelo._meta.concrete_fields
            if getattr(c, 'auto_now_add', False)]


def _crear(modelo, original, cambios):
    """
    Inserta una copia de `original` en la base por defecto, conservando las
    fechas automáticas. Usa bulk_create para NO disparar la lógica de save()
    (que recalcularía estados y reescribiría el consecutivo).
    """
    datos = _valores(original)
    datos.update(cambios)
    autos = {c: datos[c] for c in _auto_fechas(modelo) if datos.get(c) is not None}
    copia = modelo(**datos)
    modelo.objects.bulk_create([copia])
    if autos:
        modelo.objects.filter(pk=copia.pk).update(**autos)
    return copia


class Command(BaseCommand):
    help = ("Recupera una orden borrada desde la base de rescate "
            "(vista previa por defecto; ejecuta con --confirmar).")

    def add_arguments(self, parser):
        parser.add_argument('numero_orden', type=int,
                            help='Número que tenía la orden en la base de rescate.')
        parser.add_argument('--numero', type=int, default=None,
                            help='Número con el que quedará en producción '
                                 '(por defecto, el siguiente libre).')
        parser.add_argument('--confirmar', action='store_true',
                            help='Escribe de verdad (sin esto, solo muestra el plan).')

    def handle(self, *args, **opciones):
        if RESCATE not in connections:
            raise CommandError(
                "No hay base de rescate configurada. Define DB_RESCATE_HOST "
                "(y DB_RESCATE_NAME/USER/PASSWORD si son distintos) en el .env.")

        viejo = opciones['numero_orden']
        try:
            orden = OrdenServicio.objects.using(RESCATE).select_related(
                'cliente', 'asesor').get(pk=viejo)
        except OrdenServicio.DoesNotExist:
            raise CommandError(
                f"En la base de rescate no existe la orden #{viejo}.")

        # --- Lo que se va a traer ---
        recorridos = list(Recorrido.objects.using(RESCATE).filter(orden=orden))
        rec_ids = [r.pk for r in recorridos]
        actas = list(Manifiesto.objects.using(RESCATE).filter(recorrido_id__in=rec_ids))
        acta_ids = [a.pk for a in actas]
        novedades = list(NovedadOperacional.objects.using(RESCATE)
                         .filter(manifiesto_id__in=acta_ids))
        medidas = list(MedidaACPM.objects.using(RESCATE).filter(manifiesto_id__in=acta_ids))
        encuestas = list(EncuestaConductor.objects.using(RESCATE)
                         .filter(recorrido_id__in=rec_ids))
        pagos = list(Pago.objects.using(RESCATE).filter(orden=orden))
        documentos = list(DocumentoOrden.objects.using(RESCATE).filter(orden=orden))
        programacion = Programacion.objects.using(RESCATE).filter(orden=orden).first()
        cuadrillas, fotos = [], []
        if programacion:
            cuadrillas = list(ProgramacionCuadrilla.objects.using(RESCATE)
                              .filter(programacion=programacion))
            fotos = list(FotoAyudante.objects.using(RESCATE)
                         .filter(cuadrilla_id__in=[c.pk for c in cuadrillas]))

        # --- Número de destino ---
        nuevo = opciones['numero']
        if nuevo is None:
            ultimo = OrdenServicio.objects.aggregate(m=Max('numero_orden'))['m'] or 0
            nuevo = max(ultimo + 1, OrdenServicio.NUMERO_INICIAL)
        if OrdenServicio.objects.filter(pk=nuevo).exists():
            raise CommandError(
                f"El número #{nuevo} ya está ocupado en producción. Elige otro "
                f"con --numero.")

        self.stdout.write(self.style.MIGRATE_HEADING(
            f"\nSe recuperaría la orden #{viejo} de la base de rescate, "
            f"y en producción quedaría como la #{nuevo}:\n"))
        self.stdout.write(f"  Cliente: {orden.cliente.nombre}")
        self.stdout.write(f"  Creada:  {orden.fecha_creacion:%d/%m/%Y %H:%M}")
        self.stdout.write(f"  Estado:  {orden.get_estado_orden_display()}")
        for etiqueta, cuantos in [
            ('Programación de origen', 1 if programacion else 0),
            ('Cuadrillas', len(cuadrillas)),
            ('Fotos de ayudantes', len(fotos)),
            ('Recorridos', len(recorridos)),
            ('Actas de servicio', len(actas)),
            ('Novedades operacionales', len(novedades)),
            ('Medidas de ACPM', len(medidas)),
            ('Encuestas de cierre', len(encuestas)),
            ('Pagos', len(pagos)),
            ('Documentos', len(documentos)),
        ]:
            if cuantos:
                self.stdout.write(f"  {etiqueta}: {cuantos}")
        for acta in actas:
            if acta.estado_firma == 'FIRMADO':
                self.stdout.write(self.style.SUCCESS(
                    f"  El acta viene FIRMADA por {acta.nombre_responsable_cliente or 'el cliente'}."))

        # --- Lo que la orden referencia y debe seguir existiendo en producción ---
        faltantes = self._referencias_faltantes(
            [orden] + recorridos + cuadrillas + ([programacion] if programacion else [])
            + pagos + documentos + actas + encuestas + novedades + medidas + fotos)
        if faltantes:
            self.stdout.write(self.style.ERROR(
                "\nNo se puede rescatar: en producción ya no existen estos datos "
                "que la orden necesita:"))
            for f in sorted(faltantes):
                self.stdout.write(f"  {f}")
            raise CommandError(
                "Restaura primero esos registros (o pídeselos a la base de rescate).")

        if not opciones['confirmar']:
            self.stdout.write(self.style.WARNING(
                "\nVISTA PREVIA: no se escribió nada. Para hacerlo de verdad:\n"
                f"  python manage.py rescatar_orden {viejo} --confirmar"
                + (f" --numero {nuevo}" if opciones['numero'] else "")))
            return

        with transaction.atomic():
            nueva_orden = _crear(OrdenServicio, orden, {'numero_orden': nuevo})

            if programacion:
                nueva_prog = _crear(Programacion, programacion, {'orden_id': nuevo})
                for cuadrilla in cuadrillas:
                    nueva_cuad = _crear(ProgramacionCuadrilla, cuadrilla,
                                        {'programacion_id': nueva_prog.pk})
                    for foto in fotos:
                        if foto.cuadrilla_id == cuadrilla.pk:
                            _crear(FotoAyudante, foto, {'cuadrilla_id': nueva_cuad.pk})

            for recorrido in recorridos:
                nuevo_rec = _crear(Recorrido, recorrido, {'orden_id': nuevo})
                for acta in actas:
                    if acta.recorrido_id != recorrido.pk:
                        continue
                    nueva_acta = _crear(Manifiesto, acta, {'recorrido_id': nuevo_rec.pk})
                    for nov in novedades:
                        if nov.manifiesto_id == acta.pk:
                            _crear(NovedadOperacional, nov,
                                   {'manifiesto_id': nueva_acta.pk})
                    for med in medidas:
                        if med.manifiesto_id == acta.pk:
                            _crear(MedidaACPM, med, {'manifiesto_id': nueva_acta.pk})
                for enc in encuestas:
                    if enc.recorrido_id == recorrido.pk:
                        _crear(EncuestaConductor, enc, {'recorrido_id': nuevo_rec.pk})

            for pago in pagos:
                _crear(Pago, pago, {'orden_id': nuevo})
            for doc in documentos:
                _crear(DocumentoOrden, doc, {'orden_id': nuevo})

        self.stdout.write(self.style.SUCCESS(
            f"\nListo: la orden volvió como la #{nuevo}, con todo lo suyo."))
        self.stdout.write(self.style.WARNING(
            "  Los archivos (PDF del acta, firma, fotos) NO se copiaron: las "
            "filas apuntan a las mismas rutas del storage. Comprueba con "
            "`auditar_archivos` cuáles faltan."))

    def _referencias_faltantes(self, objetos):
        """Claves foráneas (cliente, vehículo, personal...) que ya no existen aquí."""
        faltan = set()
        for obj in objetos:
            for campo in obj._meta.concrete_fields:
                if not campo.is_relation or campo.related_model in (
                        OrdenServicio, Programacion, ProgramacionCuadrilla,
                        Recorrido, Manifiesto):
                    continue
                valor = getattr(obj, campo.attname)
                if valor is None:
                    continue
                if not campo.related_model.objects.filter(pk=valor).exists():
                    faltan.add(f"{campo.related_model._meta.verbose_name} #{valor} "
                               f"(la usa {obj._meta.verbose_name})")
        return faltan
