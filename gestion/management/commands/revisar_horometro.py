"""
Muestra qué se perdería al aplicar la migración 0056, que BORRA las columnas
`horometro_inicio` y `horometro_final` de las actas (Manifiesto).

Se consulta con SQL directo, no por el ORM, porque el modelo ya no tiene esos
campos: así el comando sirve igual antes y después de traer el código nuevo.

    python manage.py revisar_horometro                 # resumen + listado
    python manage.py revisar_horometro --csv copia.csv # además guarda el respaldo

Si la migración ya se aplicó, lo dice y no hace nada.
"""
import csv

from django.core.management.base import BaseCommand
from django.db import connection

TABLA = 'gestion_manifiesto'
COLUMNAS = ('horometro_inicio', 'horometro_final')


class Command(BaseCommand):
    help = ("Muestra las actas con horómetro que borraría la migración 0056 "
            "(opcionalmente las guarda en un CSV).")

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
                    "La migración 0056 ya está aplicada: las columnas del horómetro "
                    "no existen. No hay nada que revisar."))
                return

            # Solo las actas que tienen ALGO en el horómetro: lo demás no se pierde.
            cursor.execute(f"""
                SELECT m.recorrido_id, r.orden_id, r.fecha_recorrido,
                       m.horometro_inicio, m.horometro_final
                  FROM {TABLA} m
                  JOIN gestion_recorrido r ON r.id = m.recorrido_id
                 WHERE m.horometro_inicio IS NOT NULL
                    OR m.horometro_final IS NOT NULL
                 ORDER BY r.fecha_recorrido DESC, r.orden_id
            """)
            filas = cursor.fetchall()
            cursor.execute(f"SELECT COUNT(*) FROM {TABLA}")
            total_actas = cursor.fetchone()[0]

        if not filas:
            self.stdout.write(self.style.SUCCESS(
                f"Ninguna de las {total_actas} acta(s) tiene datos de horómetro: "
                "la migración 0056 no borra información."))
            return

        self.stdout.write(self.style.WARNING(
            f"\nLa migración 0056 BORRARÁ el horómetro de {len(filas)} acta(s) "
            f"(de {total_actas} en total):\n"))
        self.stdout.write(f"  {'ORDEN':>8}  {'FECHA':<12}  {'INICIO':<8}  {'FINAL':<8}")
        self.stdout.write(f"  {'-' * 8}  {'-' * 12}  {'-' * 8}  {'-' * 8}")
        for _recorrido_id, orden_id, fecha, inicio, final in filas:
            self.stdout.write(
                f"  {orden_id or '—':>8}  {str(fecha):<12}  "
                f"{str(inicio or '—'):<8}  {str(final or '—'):<8}")

        if opciones['csv']:
            with open(opciones['csv'], 'w', newline='', encoding='utf-8') as fh:
                escritor = csv.writer(fh)
                escritor.writerow(['recorrido_id', 'orden', 'fecha_recorrido',
                                   'horometro_inicio', 'horometro_final'])
                escritor.writerows(filas)
            self.stdout.write(self.style.SUCCESS(
                f"\nRespaldo guardado en {opciones['csv']}."))
        else:
            self.stdout.write(
                "\nPara guardar un respaldo antes de migrar:\n"
                "  python manage.py revisar_horometro --csv horometro_respaldo.csv")
