"""
Pruebas del plan de trabajo diario.

Se corren con `python manage.py test planes` (o junto a todo: `manage.py test`).
"""
import datetime

from django.contrib.auth.models import Group, User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from gestion.models import (
    Cliente, OrdenServicio, PerfilPersona, Proveedor, Recorrido, Vehiculo,
)

from .forms import AsignacionForm, NovedadForm
from .models import Asignacion, Novedad, PlanDia

CLAVE = 'Solmed.Pruebas.2026'


class BasePlan(TestCase):
    """Escenario mínimo: gestión, personal operativo y un vehículo."""

    def setUp(self):
        self.asesor = self.persona('asesor', 'Asesores', 'Ana', 'Ruiz')
        self.admin = self.persona('admin', 'Administradores')
        self.conductor = self.persona('conductor', 'Conductores', 'Carlos', 'Pérez')
        self.ayudante = self.persona('ayudante', 'Ayudantes', 'Luis', 'Gómez')
        self.camion = Vehiculo.objects.create(
            placa='WHB123', marca='Kenworth', modelo='2019', capacidad='10 m³')
        self.hoy = timezone.localdate()
        self.url = reverse('planes:plan_dia')

    @staticmethod
    def persona(username, rol=None, nombre='', apellido='', superusuario=False):
        if superusuario:
            usuario = User.objects.create_superuser(username, 'x@y.co', CLAVE)
        else:
            usuario = User.objects.create_user(username, 'x@y.co', CLAVE)
        usuario.first_name = nombre or username.capitalize()
        usuario.last_name = apellido
        usuario.save()
        if rol:
            usuario.groups.add(Group.objects.get_or_create(name=rol)[0])
        PerfilPersona.objects.get_or_create(usuario=usuario)
        return usuario

    def entrar(self, usuario):
        self.assertTrue(self.client.login(username=usuario.username, password=CLAVE))
        return usuario

    def asignar(self, personas, tipo, vehiculos=None, **extra):
        """POST de una asignación desde el panel, como lo manda el navegador."""
        datos = {'submit_asignacion': '1', 'fecha': self.hoy.isoformat(),
                 'tipo': tipo, 'personas': [p.pk for p in personas],
                 'vehiculos': [v.pk for v in (vehiculos or [])],
                 'orden_numero': '', 'detalle': '', 'hora': ''}
        datos.update(extra)
        return self.client.post(self.url, datos)


class AccesoAlPlanTests(BasePlan):
    """El plan dice quién es cada cliente y qué hace cada persona: solo gestión."""

    def urls(self):
        return [reverse('planes:plan_dia'), reverse('planes:historial'),
                reverse('planes:novedades'),
                reverse('planes:plan_pdf', args=[self.hoy.isoformat()])]

    def test_gestion_si_entra(self):
        for usuario in (self.asesor, self.admin,
                        self.persona('root', superusuario=True)):
            self.entrar(usuario)
            for url in self.urls():
                with self.subTest(usuario=usuario.username, url=url):
                    self.assertEqual(self.client.get(url).status_code, 200)

    def test_ningun_otro_rol_entra(self):
        for usuario in (self.conductor,
                        self.persona('plani', 'Planificadores'),
                        self.persona('talento', 'Talento Humano'),
                        self.persona('siso', 'SISO')):
            self.entrar(usuario)
            for url in self.urls():
                with self.subTest(usuario=usuario.username, url=url):
                    self.assertEqual(self.client.get(url).status_code, 403)

    def test_sin_sesion_va_al_login(self):
        for url in self.urls():
            with self.subTest(url=url):
                respuesta = self.client.get(url)
                self.assertEqual(respuesta.status_code, 302)
                self.assertIn('/login/', respuesta.url)

    def test_el_menu_se_lo_ofrece_a_gestion_y_a_nadie_mas(self):
        self.entrar(self.asesor)
        self.assertContains(self.client.get(self.url), 'Plan de trabajo')
        self.entrar(self.conductor)
        respuesta = self.client.get(reverse('gestion:dashboard_conductor'))
        self.assertNotContains(respuesta, 'Plan de trabajo')


class TableroTests(BasePlan):
    """La formación del día: todo el personal, agrupado, con lo suyo."""

    def contexto(self, fecha=None):
        self.entrar(self.asesor)
        url = self.url + (f'?fecha={fecha.isoformat()}' if fecha else '')
        return self.client.get(url).context

    def test_todo_el_personal_activo_aparece_agrupado_por_cargo(self):
        contexto = self.contexto()
        cargos = [g['cargo'] for g in contexto['grupos']]
        self.assertEqual(cargos[:2], ['Conductores', 'Ayudantes'],
                         "la operación va primero, como en el formato")
        nombres = [f['nombre'] for g in contexto['grupos'] for f in g['filas']]
        for esperado in ('Carlos Pérez', 'Luis Gómez', 'Ana Ruiz'):
            self.assertIn(esperado, nombres)

    def test_los_retirados_y_superadministradores_no_salen(self):
        retirado = self.persona('retirado', 'Conductores', 'Zoe')
        PerfilPersona.objects.filter(usuario=retirado).update(retirado=True)
        self.persona('root', superusuario=True)
        nombres = [f['nombre'] for g in self.contexto()['grupos'] for f in g['filas']]
        self.assertNotIn('Zoe', nombres)
        self.assertNotIn('Root', nombres)

    def test_un_servicio_programado_entra_solo_al_plan(self):
        cliente = Cliente.objects.create(nombre='Cliente X', identificacion='900')
        orden = OrdenServicio.objects.create(
            cliente=cliente, asesor=self.asesor, direccion_servicio='x',
            descripcion='y')
        Recorrido.objects.create(
            orden=orden, vehiculo=self.camion, conductor=self.conductor,
            ayudante=self.ayudante, fecha_recorrido=self.hoy)

        filas = {f['nombre']: f for g in self.contexto()['grupos'] for f in g['filas']}
        for nombre in ('Carlos Pérez', 'Luis Gómez'):
            with self.subTest(persona=nombre):
                self.assertEqual(len(filas[nombre]['servicios']), 1)
                self.assertIn(str(orden.numero_orden), filas[nombre]['servicios'][0])
                self.assertIn('WHB123', filas[nombre]['servicios'][0])
                self.assertTrue(filas[nombre]['con_plan'])

    def test_una_orden_cancelada_no_manda_a_nadie_a_servicio(self):
        cliente = Cliente.objects.create(nombre='Cliente X', identificacion='900')
        orden = OrdenServicio.objects.create(
            cliente=cliente, asesor=self.asesor, direccion_servicio='x',
            descripcion='y', estado_orden='CANCELADA')
        Recorrido.objects.create(orden=orden, vehiculo=self.camion,
                                 conductor=self.conductor, fecha_recorrido=self.hoy)
        OrdenServicio.objects.filter(pk=orden.pk).update(estado_orden='CANCELADA')
        filas = {f['nombre']: f for g in self.contexto()['grupos'] for f in g['filas']}
        self.assertEqual(filas['Carlos Pérez']['servicios'], [])

    def test_el_contador_de_formacion_cuenta_bien(self):
        self.entrar(self.asesor)
        self.asignar([self.conductor], 'LAVADA', [self.camion])
        contexto = self.contexto()
        conductores = [g for g in contexto['grupos'] if g['cargo'] == 'Conductores'][0]
        self.assertEqual(conductores['con_plan'], 1)
        self.assertEqual(contexto['con_plan'], 1)
        self.assertEqual(contexto['sin_plan'], contexto['total_personas'] - 1)


class AsignacionesTests(BasePlan):
    """El alta desde el panel: varias personas de una, y lo que cada actividad exige."""

    def setUp(self):
        super().setUp()
        self.entrar(self.asesor)

    def test_una_actividad_se_asigna_a_varias_personas_de_un_solo_envio(self):
        self.asignar([self.conductor, self.ayudante], 'LAVADA', [self.camion])
        self.assertEqual(Asignacion.objects.count(), 2)
        self.assertEqual(PlanDia.objects.count(), 1, "un solo plan por día")
        plan = PlanDia.objects.get()
        self.assertEqual(plan.fecha, self.hoy)
        self.assertEqual(plan.creado_por, self.asesor)
        for asignacion in Asignacion.objects.all():
            self.assertEqual(asignacion.placas, 'WHB123')
            self.assertEqual(asignacion.registrado_por, self.asesor)

    def test_dos_altas_del_mismo_dia_comparten_el_plan(self):
        self.asignar([self.conductor], 'TECNOMECANICA', [self.camion])
        self.asignar([self.ayudante], 'TRASTEO')
        self.assertEqual(PlanDia.objects.count(), 1)
        self.assertEqual(PlanDia.objects.get().asignaciones.count(), 2)

    def test_sin_personas_no_se_crea_nada(self):
        self.asignar([], 'TRASTEO')
        self.assertFalse(Asignacion.objects.exists())
        self.assertFalse(PlanDia.objects.exists())

    def test_las_actividades_de_placa_exigen_el_vehiculo(self):
        for tipo in ('TECNOMECANICA', 'LAVADA', 'MANT_INTERNO', 'APOYO_SERVICIO'):
            with self.subTest(tipo=tipo):
                self.asignar([self.conductor], tipo)
                self.assertFalse(Asignacion.objects.filter(tipo=tipo).exists())

    def test_la_disposicion_final_exige_una_orden_que_exista(self):
        self.asignar([self.conductor], 'DISPOSICION_FINAL', [self.camion],
                     orden_numero='99999')
        self.assertFalse(Asignacion.objects.exists())

        cliente = Cliente.objects.create(nombre='Cliente X', identificacion='900')
        orden = OrdenServicio.objects.create(
            cliente=cliente, asesor=self.asesor, direccion_servicio='x',
            descripcion='y')
        self.asignar([self.conductor], 'DISPOSICION_FINAL', [self.camion],
                     orden_numero=str(orden.numero_orden))
        self.assertEqual(Asignacion.objects.get().orden, orden)

    def test_el_acompanamiento_y_otra_actividad_exigen_el_detalle(self):
        for tipo in ('ACOMPANAMIENTO', 'OTRA'):
            with self.subTest(tipo=tipo):
                self.asignar([self.conductor], tipo, detalle='   ')
                self.assertFalse(Asignacion.objects.filter(tipo=tipo).exists())
        self.asignar([self.conductor], 'ACOMPANAMIENTO',
                     detalle='Acompañar la visita de la ARL')
        self.assertTrue(Asignacion.objects.exists())

    def test_lo_que_la_actividad_no_pide_no_se_guarda(self):
        proveedor = Proveedor.objects.create(nit='900', razon_social='Taller Sur')
        self.asignar([self.conductor], 'TRASTEO', hora='08:00',
                     proveedor=proveedor.pk, detalle='Trasteo de la bodega')
        asignacion = Asignacion.objects.get()
        self.assertIsNone(asignacion.hora)
        self.assertIsNone(asignacion.proveedor)

    def test_el_mantenimiento_externo_guarda_su_proveedor(self):
        proveedor = Proveedor.objects.create(nit='900', razon_social='Taller Sur')
        self.asignar([self.conductor], 'MANT_EXTERNO', [self.camion],
                     proveedor=proveedor.pk)
        self.assertEqual(Asignacion.objects.get().proveedor, proveedor)

    def test_una_persona_retirada_no_recibe_asignaciones(self):
        PerfilPersona.objects.filter(usuario=self.conductor).update(retirado=True)
        self.asignar([self.conductor], 'TRASTEO')
        self.assertFalse(Asignacion.objects.exists())

    def test_quitar_una_asignacion(self):
        self.asignar([self.conductor], 'LAVADA', [self.camion])
        asignacion = Asignacion.objects.get()
        self.client.post(reverse('planes:eliminar_asignacion', args=[asignacion.pk]),
                         {'fecha': self.hoy.isoformat()})
        self.assertFalse(Asignacion.objects.exists())

    def test_los_apoyos_guardan_su_hora(self):
        self.asignar([self.ayudante], 'APOYO_DISPOSICION', [self.camion],
                     hora='14:30')
        self.assertEqual(Asignacion.objects.get().hora, datetime.time(14, 30))


class NovedadesTests(BasePlan):
    """La sección 2 del formato: rangos de fechas y su registro."""

    def setUp(self):
        super().setUp()
        self.entrar(self.asesor)

    def registrar(self, **extra):
        datos = {'submit_novedad': '1', 'fecha': self.hoy.isoformat(),
                 'persona': self.conductor.pk, 'tipo': 'VACACIONES',
                 'fecha_inicio': self.hoy.isoformat(), 'fecha_fin': '',
                 'hora': '', 'detalle': ''}
        datos.update(extra)
        return self.client.post(self.url, datos)

    def test_una_novedad_con_rango_aparece_todos_sus_dias(self):
        fin = self.hoy + datetime.timedelta(days=10)
        self.registrar(fecha_fin=fin.isoformat())
        novedad = Novedad.objects.get()
        self.assertEqual(novedad.registrado_por, self.asesor)

        intermedio = self.hoy + datetime.timedelta(days=5)
        self.assertIn(novedad, Novedad.del_dia(intermedio))
        self.assertIn(novedad, Novedad.del_dia(self.hoy))
        self.assertIn(novedad, Novedad.del_dia(fin))
        self.assertNotIn(novedad, Novedad.del_dia(fin + datetime.timedelta(days=1)))

    def test_sin_fecha_final_es_solo_del_dia_de_inicio(self):
        self.registrar(tipo='PERMISO_PERSONAL', hora='10:00')
        novedad = Novedad.objects.get()
        self.assertIn(novedad, Novedad.del_dia(self.hoy))
        self.assertNotIn(novedad,
                         Novedad.del_dia(self.hoy + datetime.timedelta(days=1)))

    def test_la_fecha_final_no_puede_ser_anterior_a_la_inicial(self):
        form = NovedadForm({'persona': self.conductor.pk, 'tipo': 'VACACIONES',
                            'fecha_inicio': self.hoy.isoformat(),
                            'fecha_fin': (self.hoy - datetime.timedelta(days=1)).isoformat(),
                            'hora': '', 'detalle': ''})
        self.assertFalse(form.is_valid())
        self.assertIn('fecha_fin', form.errors)

    def test_la_novedad_marca_a_la_persona_en_el_tablero(self):
        self.registrar()
        contexto = self.client.get(self.url).context
        fila = [f for g in contexto['grupos'] for f in g['filas']
                if f['persona'] == self.conductor][0]
        self.assertEqual(len(fila['novedades']), 1)
        self.assertTrue(fila['con_plan'])

    def test_eliminar_una_novedad_registrada_por_error(self):
        self.registrar()
        novedad = Novedad.objects.get()
        self.client.post(reverse('planes:eliminar_novedad', args=[novedad.pk]),
                         {'fecha': self.hoy.isoformat()})
        self.assertFalse(Novedad.objects.exists())

    def test_el_registro_de_novedades_filtra_por_nombre_y_tipo(self):
        self.registrar()
        self.registrar(persona=self.ayudante.pk, tipo='INCAPACIDAD_EPS')

        contexto = self.client.get(reverse('planes:novedades'),
                                   {'q': 'Carlos'}).context
        self.assertEqual([n.persona for n in contexto['novedades']],
                         [self.conductor])
        contexto = self.client.get(reverse('planes:novedades'),
                                   {'tipo': 'INCAPACIDAD_EPS'}).context
        self.assertEqual([n.tipo for n in contexto['novedades']],
                         ['INCAPACIDAD_EPS'])


class PdfYRegistroTests(BasePlan):
    """El documento del día y el historial."""

    def setUp(self):
        super().setUp()
        self.entrar(self.asesor)

    def test_el_pdf_del_dia_se_descarga_generado_al_momento(self):
        self.asignar([self.conductor], 'LAVADA', [self.camion])
        respuesta = self.client.get(
            reverse('planes:plan_pdf', args=[self.hoy.isoformat()]))
        self.assertEqual(respuesta.status_code, 200)
        self.assertEqual(respuesta['Content-Type'], 'application/pdf')
        self.assertIn(f'plan_trabajo_{self.hoy.isoformat()}.pdf',
                      respuesta['Content-Disposition'])
        self.assertTrue(respuesta.content.startswith(b'%PDF'))

    def test_el_pdf_sale_aunque_el_dia_este_vacio(self):
        respuesta = self.client.get(
            reverse('planes:plan_pdf', args=[self.hoy.isoformat()]))
        self.assertEqual(respuesta.status_code, 200)
        self.assertTrue(respuesta.content.startswith(b'%PDF'))

    def test_una_fecha_invalida_es_404(self):
        self.assertEqual(self.client.get(
            reverse('planes:plan_pdf', args=['no-es-fecha'])).status_code, 404)

    def test_las_observaciones_del_dia_se_guardan(self):
        self.client.post(self.url, {'submit_notas': '1',
                                    'fecha': self.hoy.isoformat(),
                                    'notas': 'Reunión de seguridad a las 7 am'})
        self.assertEqual(PlanDia.objects.get().notas,
                         'Reunión de seguridad a las 7 am')

    def test_el_historial_lista_los_dias_planeados(self):
        manana = self.hoy + datetime.timedelta(days=1)
        self.asignar([self.conductor], 'TRASTEO')
        self.client.post(self.url, {'submit_asignacion': '1',
                                    'fecha': manana.isoformat(),
                                    'tipo': 'TRASTEO',
                                    'personas': [self.ayudante.pk],
                                    'orden_numero': '', 'detalle': '', 'hora': ''})
        contexto = self.client.get(reverse('planes:historial')).context
        self.assertEqual([p.fecha for p in contexto['planes']],
                         [manana, self.hoy])
        self.assertEqual(contexto['planes'][0].n_asignaciones, 1)

    def test_el_plan_de_otro_dia_se_abre_con_su_fecha(self):
        manana = self.hoy + datetime.timedelta(days=1)
        respuesta = self.client.get(self.url, {'fecha': manana.isoformat()})
        self.assertEqual(respuesta.context['fecha'], manana)

    def test_una_fecha_mal_escrita_cae_en_hoy(self):
        respuesta = self.client.get(self.url, {'fecha': 'basura'})
        self.assertEqual(respuesta.context['fecha'], self.hoy)
