"""
Revisa el plan de trabajo buscando lo que pueda verse «arrastrado» a otros
días (nov-2026, pedido de Santiago: «una novedad o actividad de un día X se
sigue viendo en los días siguientes»). SOLO LEE: no cambia nada.

En el código, una novedad sale en cada día de su rango (de «Desde» a «Hasta»;
sin «Hasta», solo su día) y una actividad solo en el día de su plan. Este
comando lista los registros que explicarían el síntoma con datos reales:

  1. NOVEDADES DE VARIOS DÍAS: tienen «Hasta» posterior a «Desde», así que
     salen en todos esos días. Si el rango es largo o raro, quizá se puso un
     «Hasta» por error.
  2. NOVEDADES REGISTRADAS OTRO DÍA: se registraron en una fecha distinta a
     su «Desde» (p. ej. se cargó hoy una novedad de la semana pasada).
  3. ACTIVIDADES REPETIDAS EN DÍAS SEGUIDOS: la misma persona, el mismo tipo
     y el mismo detalle en días consecutivos.
  4. ACTIVIDADES DE VIAJES AGENDADOS: las que se crearon al agendar una
     disposición, con la fecha del viaje y su estado.

    python manage.py revisar_plan                  # los últimos 60 días
    python manage.py revisar_plan --dias 120       # otro periodo
    python manage.py revisar_plan --persona carlos # solo quien coincida
    python manage.py revisar_plan --rango 3        # novedades de 3 días o más
"""
import datetime
from collections import defaultdict

from django.core.management.base import BaseCommand
from django.db.models import Q
from django.utils import timezone

from planes.models import Asignacion, Novedad


class Command(BaseCommand):
    help = "Lista lo del plan de trabajo que puede verse en otros días (solo lee, no cambia nada)."

    def add_arguments(self, parser):
        parser.add_argument('--dias', type=int, default=60,
                            help="Cuántos días hacia atrás revisar (por defecto 60).")
        parser.add_argument('--persona', default='',
                            help="Solo las personas cuyo nombre o usuario contenga este texto.")
        parser.add_argument('--rango', type=int, default=2,
                            help="Mostrar novedades de este número de días o más (por defecto 2).")

    def handle(self, *args, dias, persona, rango, **opciones):
        hoy = timezone.localdate()
        desde = hoy - datetime.timedelta(days=dias)
        filtro_persona = Q()
        if persona:
            filtro_persona = (Q(persona__first_name__icontains=persona) | Q(persona__last_name__icontains=persona)
                              | Q(persona__username__icontains=persona))

        self.stdout.write(self.style.MIGRATE_HEADING(
            f"Plan de trabajo del {desde:%d/%m/%Y} al {hoy:%d/%m/%Y}{f' · persona: {persona}' if persona else ''}"))

        novedades = list(
            Novedad.objects.filter(filtro_persona)
            .filter(Q(fecha_inicio__gte=desde) | Q(fecha_fin__gte=desde))
            .select_related('persona', 'registrado_por', 'tipo_personalizado')
            .order_by('fecha_inicio', 'pk'))

        # ---- 1. Novedades de varios días ----
        largas = [n for n in novedades if n.fecha_fin and (n.fecha_fin - n.fecha_inicio).days + 1 >= rango]
        self._titulo(f"1. Novedades de {rango} días o más (salen en todos los días de su rango)", len(largas))
        for n in largas:
            dias_n = (n.fecha_fin - n.fecha_inicio).days + 1
            self.stdout.write(f"   #{n.pk:<6} {self._nombre(n.persona):30} {n.get_tipo_display():32} "
                              f"del {n.fecha_inicio:%d/%m/%Y} al {n.fecha_fin:%d/%m/%Y}  ({dias_n} días)"
                              f"{self._quien(n)}")

        # ---- 2. Novedades registradas en otra fecha ----
        otras = []
        for n in novedades:
            registrada = timezone.localtime(n.fecha_registro).date()
            if registrada != n.fecha_inicio:
                otras.append((n, registrada))
        self._titulo("2. Novedades registradas en una fecha distinta a su «Desde»", len(otras))
        for n, registrada in otras:
            hasta = f" al {n.fecha_fin:%d/%m/%Y}" if n.fecha_fin else " (un día)"
            self.stdout.write(f"   #{n.pk:<6} {self._nombre(n.persona):30} {n.get_tipo_display():32} "
                              f"desde {n.fecha_inicio:%d/%m/%Y}{hasta} · registrada el {registrada:%d/%m/%Y}"
                              f"{self._quien(n)}")

        # ---- 3. Actividades iguales en días seguidos ----
        actividades = list(
            Asignacion.objects.filter(filtro_persona, plan__fecha__gte=desde)
            .select_related('plan', 'persona', 'tipo_personalizado', 'viaje')
            .order_by('plan__fecha', 'pk'))
        grupos = defaultdict(list)
        for a in actividades:
            grupos[(a.persona_id, a.tipo, a.tipo_personalizado_id, (a.detalle or '').strip().lower())].append(a)
        repetidas = []
        for lista in grupos.values():
            fechas = sorted({a.plan.fecha for a in lista})
            if any((b - a).days == 1 for a, b in zip(fechas, fechas[1:])):
                repetidas.append((lista[0], fechas))
        self._titulo("3. Actividades iguales (persona, tipo y detalle) en días seguidos", len(repetidas))
        for a, fechas in repetidas:
            detalle = f" «{a.detalle}»" if a.detalle else ''
            self.stdout.write(f"   {self._nombre(a.persona):30} {a.get_tipo_display():28}{detalle}")
            self.stdout.write(f"      días: {', '.join(f'{f:%d/%m}' for f in fechas)}")

        # ---- 4. Actividades de viajes agendados ----
        de_viaje = [a for a in actividades if a.viaje_id]
        self._titulo("4. Actividades creadas al agendar una disposición", len(de_viaje))
        for a in de_viaje:
            self.stdout.write(f"   {self._nombre(a.persona):30} día del plan {a.plan.fecha:%d/%m/%Y} · "
                              f"viaje del {a.viaje.fecha:%d/%m/%Y} ({a.viaje.get_estado_display().lower()})")

        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS(
            "Listo. Este comando solo lee: no cambió nada. Para arreglar una novedad de rango "
            "equivocado, quítala en el plan y vuelve a registrarla con las fechas correctas."))

    # ---- ayudantes de formato ----
    def _titulo(self, texto, n):
        self.stdout.write("")
        estilo = self.style.WARNING if n else self.style.SUCCESS
        self.stdout.write(estilo(f"{texto}: {n}"))
        if not n:
            self.stdout.write("   (ninguna)")

    @staticmethod
    def _nombre(persona):
        return (persona.get_full_name() or persona.username)[:30]

    @staticmethod
    def _quien(novedad):
        if novedad.registrado_por_id:
            return f" · por {novedad.registrado_por.get_full_name() or novedad.registrado_por.username}"
        return ''
