"""
Festivos de Colombia (oct-2026): para la estadística de la programación, que
cuenta quién trabajó en fin de semana o festivo. No hay librería en el
proyecto para esto, así que se calculan con las reglas de la Ley 51 de 1983
(«Ley Emiliani»): unos son fijos, otros se corren al lunes siguiente y otros
dependen de la Semana Santa.
"""
import datetime
from functools import lru_cache

# Siempre en su día.
FIJOS = [(1, 1), (5, 1), (7, 20), (8, 7), (12, 8), (12, 25)]
# Se corren al lunes siguiente si no caen en lunes.
TRASLADABLES = [(1, 6), (3, 19), (6, 29), (8, 15), (10, 12), (11, 1), (11, 11)]


def domingo_de_pascua(anio):
    """Domingo de Resurrección (algoritmo anónimo gregoriano)."""
    a = anio % 19
    b, c = divmod(anio, 100)
    d, e = divmod(b, 4)
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    mes, dia = divmod(h + l - 7 * m + 114, 31)
    return datetime.date(anio, mes, dia + 1)


def _al_lunes(fecha):
    return fecha + datetime.timedelta(days=(7 - fecha.weekday()) % 7)


@lru_cache(maxsize=32)
def festivos_de(anio):
    """El conjunto de festivos de ese año."""
    dias = {datetime.date(anio, m, d) for m, d in FIJOS}
    dias |= {_al_lunes(datetime.date(anio, m, d)) for m, d in TRASLADABLES}
    pascua = domingo_de_pascua(anio)
    dias.add(pascua - datetime.timedelta(days=3))              # Jueves Santo
    dias.add(pascua - datetime.timedelta(days=2))              # Viernes Santo
    dias.add(_al_lunes(pascua + datetime.timedelta(days=39)))  # Ascensión
    dias.add(_al_lunes(pascua + datetime.timedelta(days=60)))  # Corpus Christi
    dias.add(_al_lunes(pascua + datetime.timedelta(days=68)))  # Sagrado Corazón
    return frozenset(dias)


def es_festivo(fecha):
    return fecha in festivos_de(fecha.year)


def es_fin_de_semana_o_festivo(fecha):
    """Sábado, domingo o festivo de Colombia."""
    return fecha.weekday() >= 5 or es_festivo(fecha)


def es_dominical(fecha):
    """Domingo o festivo: lo que en Colombia se paga como dominical."""
    return fecha.weekday() == 6 or es_festivo(fecha)


# Jornada máxima semanal (Ley 2101 de 2021): baja por etapas cada 15 de julio.
JORNADA_MAXIMA = [
    (datetime.date(2026, 7, 15), 42),
    (datetime.date(2025, 7, 15), 44),
    (datetime.date(2024, 7, 15), 46),
    (datetime.date(2023, 7, 15), 47),
]


def jornada_maxima_semanal(fecha):
    """Las horas semanales máximas vigentes en esa fecha."""
    for desde, horas in JORNADA_MAXIMA:
        if fecha >= desde:
            return horas
    return 48
