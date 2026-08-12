"""
Muestra qué se perdería al aplicar la migración que convierte el bloque de
KILÓMETROS del acta en TIEMPOS DE RECORRIDO: las cuatro columnas dejan de ser
números (kilometraje del tablero) y pasan a ser horas, así que lo registrado
en ellas no se puede conservar.

Se consulta con SQL directo, no por el ORM, porque el modelo ya no tiene esos
campos: así el comando sirve igual antes y después de traer el código nuevo.

    python manage.py revisar_kilometros                 # resumen + listado
    python manage.py revisar_kilometros --csv copia.csv # además guarda el respaldo

Si la migración ya se aplicó, lo dice y no hace nada.
"""
import csv

from django.core.management.base import BaseCommand
from django.db import connection

TABLA = 'gestion_manifiesto'
COLUMNAS = ('km_salida_solmed', 'km_llegada_empresa',
            'km_llegada_disposicion', 'km_llegada_solmed')


class Command(BaseCommand):
    help = ("Muestra las actas con kilómetros que borraría la migración que "
            "los convierte en horas (opcionalmente los guarda en un CSV).")

    def add_arguments(self, parser):
        parser.add_argument(
            '--csv', dest='csv', default=None,
            help='Ruta donde guardar un respaldo CSV de lo que se va a borrar.',
        )

    def handle(self, *args, **opciones):
        with connection.cursor() as cursor:
            existentes = {c.name for c in connection.introspection.get_table_description(
                cursor, TABLA)}
            faltan = [c for c in COLUMNAS if c not in existentes]
            if faltan:
                self.stdout.write(self.style.SUCCESS(
                    "La migración ya está aplicada: las columnas de kilómetros "
                    "no existen. No hay nada que revisar."))
                return

            columnas = ', '.join(f'm.{c}' for c in COLUMNAS)
            condicion = ' OR '.join(f'm.{c} IS NOT NULL' for c in COLUMNAS)
            cursor.execute(f"""
                SELECT r.orden_id, r.fecha_recorrido, {columnas}
                  FROM {TABLA} m
                  JOIN gestion_recorrido r ON r.id = m.recorrido_id
                 WHERE {condicion}
                 ORDER BY r.fecha_recorrido DESC, r.orden_id
            """)
            filas = cursor.fetchall()
            cursor.execute(f"SELECT COUNT(*) FROM {TABLA}")
            total_actas = cursor.fetchone()[0]

        if not filas:
            self.stdout.write(self.style.SUCCESS(
                f"Ninguna de las {total_actas} acta(s) tiene kilómetros "
                "registrados: la migración no borra información."))
            return

        self.stdout.write(self.style.WARNING(
            f"\nLa migración BORRARÁ los kilómetros de {len(filas)} acta(s) "
            f"(de {total_actas} en total):\n"))
        self.stdout.write(
            f"  {'ORDEN':>8}  {'FECHA':<12}  {'SAL.SOLMED':>10}  "
            f"{'LL.EMPRESA':>10}  {'LL.DISPOS.':>10}  {'LL.SOLMED':>10}")
        self.stdout.write(f"  {'-' * 8}  {'-' * 12}  {'-' * 10}  {'-' * 10}  "
                          f"{'-' * 10}  {'-' * 10}")
        for orden_id, fecha, *kms in filas:
            valores = '  '.join(f"{str(k if k is not None else '—'):>10}" for k in kms)
            self.stdout.write(f"  {orden_id or '—':>8}  {str(fecha):<12}  {valores}")

        if opciones['csv']:
            with open(opciones['csv'], 'w', newline='', encoding='utf-8') as fh:
                escritor = csv.writer(fh)
                escritor.writerow(['orden', 'fecha_recorrido', *COLUMNAS])
                escritor.writerows(filas)
            self.stdout.write(self.style.SUCCESS(
                f"\nRespaldo guardado en {opciones['csv']}."))
        else:
            self.stdout.write(
                "\nPara guardar un respaldo antes de migrar:\n"
                "  python manage.py revisar_kilometros --csv kilometros_respaldo.csv")
