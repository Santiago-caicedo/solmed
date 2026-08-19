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
    """
    El plan es SOLO de administradores (decisión del usuario, ago-2026):
    reparte a todo el personal y registra sus novedades de recursos humanos.
    Ni siquiera los asesores entran.
    """

    def urls(self):
        return [reverse('planes:plan_dia'), reverse('planes:historial'),
                reverse('planes:novedades'),
                reverse('planes:plan_pdf', args=[self.hoy.isoformat()])]

    def test_solo_el_superusuario_y_el_administrador_entran(self):
        for usuario in (self.admin, self.persona('root', superusuario=True)):
            self.entrar(usuario)
            for url in self.urls():
                with self.subTest(usuario=usuario.username, url=url):
                    self.assertEqual(self.client.get(url).status_code, 200)

    def test_ningun_otro_rol_entra_ni_el_asesor(self):
        for usuario in (self.asesor, self.conductor,
                        self.persona('plani', 'Planificadores'),
                        self.persona('talento', 'Talento Humano'),
                        self.persona('siso', 'SISO')):
            self.entrar(usuario)
            for url in self.urls():
                with self.subTest(usuario=usuario.username, url=url):
                    self.assertEqual(self.client.get(url).status_code, 403)

    def test_el_bloqueo_no_depende_del_metodo(self):
        self.entrar(self.asesor)
        url = reverse('planes:plan_dia')
        for metodo in (self.client.get, self.client.post, self.client.head):
            self.assertEqual(metodo(url).status_code, 403)

    def test_sin_sesion_va_al_login(self):
        for url in self.urls():
            with self.subTest(url=url):
                respuesta = self.client.get(url)
                self.assertEqual(respuesta.status_code, 302)
                self.assertIn('/login/', respuesta.url)

    def test_el_menu_solo_se_lo_ofrece_al_administrador(self):
        self.entrar(self.admin)
        self.assertContains(self.client.get(self.url), 'Plan de trabajo')
        # El asesor ni lo ve en el menú (miramos una página que sí puede abrir).
        self.entrar(self.asesor)
        self.assertNotContains(self.client.get(reverse('gestion:lista_ordenes')),
                               'Plan de trabajo')
        self.entrar(self.conductor)
        self.assertNotContains(self.client.get(reverse('gestion:dashboard_conductor')),
                               'Plan de trabajo')


class TableroTests(BasePlan):
    """La formación del día: todo el personal, agrupado, con lo suyo."""

    def contexto(self, fecha=None):
        self.entrar(self.admin)
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
                servicio = filas[nombre]['servicios'][0]
                self.assertEqual(servicio['orden'], orden.numero_orden)
                self.assertEqual(servicio['placa'], 'WHB123')
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
        self.entrar(self.admin)
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
        self.entrar(self.admin)

    def test_una_actividad_se_asigna_a_varias_personas_de_un_solo_envio(self):
        self.asignar([self.conductor, self.ayudante], 'LAVADA', [self.camion])
        self.assertEqual(Asignacion.objects.count(), 2)
        self.assertEqual(PlanDia.objects.count(), 1, "un solo plan por día")
        plan = PlanDia.objects.get()
        self.assertEqual(plan.fecha, self.hoy)
        self.assertEqual(plan.creado_por, self.admin)
        for asignacion in Asignacion.objects.all():
            self.assertEqual(asignacion.placas, 'WHB123')
            self.assertEqual(asignacion.registrado_por, self.admin)

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

    def test_la_disposicion_solo_admite_camiones_cargados(self):
        self.assertFalse(self.camion.cargado)
        self.asignar([self.conductor], 'DISPOSICION_FINAL', [self.camion])
        self.assertFalse(Asignacion.objects.exists(),
                         "un camión vacío no tiene nada que disponer")

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


class DisposicionDesdeElPlanTests(BasePlan):
    """
    La descarga de un camión solo ocurre aquí: asignándole a alguien la
    disposición (decisión del usuario, ago-2026). El picker ofrece únicamente
    camiones cargados y la orden no se digita: la hereda de la carga.
    """

    def setUp(self):
        super().setUp()
        self.entrar(self.admin)
        self.cliente = Cliente.objects.create(nombre='Cliente X', identificacion='900')
        self.orden = self._orden_que_carga(self.camion)

    def _orden_que_carga(self, vehiculo):
        """Un servicio que deja el camión cargado (sin disposición)."""
        from gestion.models import Dispositor, Programacion, ProgramacionCuadrilla
        destino, _ = Dispositor.objects.get_or_create(
            nombre=Dispositor.DEJAR_CARRO_CARGADO, defaults={'tipo': 'INTERNO'})
        programacion = Programacion.objects.create(
            cliente=self.cliente, fecha=self.hoy,
            requiere_disposicion_final='NO', dispositor_final=destino)
        ProgramacionCuadrilla.objects.create(
            programacion=programacion, conductor=self.conductor, vehiculo=vehiculo)
        orden = programacion.convertir_en_orden(self.admin)
        vehiculo.refresh_from_db()
        assert vehiculo.cargado
        return orden

    def test_asignar_la_disposicion_descarga_el_camion(self):
        self.asignar([self.conductor], 'DISPOSICION_FINAL', [self.camion])
        self.camion.refresh_from_db()
        self.assertFalse(self.camion.cargado)
        self.assertEqual(self.camion.cargado_detalle, '')

    def test_la_orden_no_se_digita_la_hereda_de_la_carga(self):
        self.asignar([self.conductor], 'DISPOSICION_FINAL', [self.camion])
        self.assertEqual(Asignacion.objects.get().orden, self.orden)

    def test_el_movimiento_registra_responsable_orden_y_gestor(self):
        from gestion.models import Dispositor, MovimientoCargaVehiculo
        gestor = Dispositor.objects.create(nombre='Relleno Doña Juana')
        self.asignar([self.conductor], 'DISPOSICION_FINAL', [self.camion],
                     dispositor=gestor.pk)
        movimiento = MovimientoCargaVehiculo.objects.filter(accion='DESCARGA').get()
        self.assertEqual(movimiento.orden, self.orden)
        self.assertEqual(movimiento.dispositor, gestor)
        self.assertEqual(movimiento.registrado_por, self.admin)
        self.assertIn('Carlos Pérez', movimiento.nota)
        self.assertIn(f"{self.hoy:%d/%m/%Y}", movimiento.nota)

    def test_asignarla_a_dos_personas_descarga_el_camion_una_sola_vez(self):
        from gestion.models import MovimientoCargaVehiculo
        self.asignar([self.conductor, self.ayudante], 'DISPOSICION_FINAL',
                     [self.camion])
        self.assertEqual(Asignacion.objects.count(), 2, "cada uno tiene su fila")
        self.assertEqual(
            MovimientoCargaVehiculo.objects.filter(accion='DESCARGA').count(), 1)

    def test_no_se_puede_disponer_un_camion_vacio(self):
        vacio = Vehiculo.objects.create(placa='VAC000', marca='m', modelo='2020',
                                        capacidad='1')
        self.asignar([self.conductor], 'DISPOSICION_FINAL', [vacio])
        self.assertFalse(Asignacion.objects.filter(vehiculos=vacio).exists())

    def test_la_disposicion_se_asigna_de_a_un_camion(self):
        otro = Vehiculo.objects.create(placa='OTR222', marca='m', modelo='2020',
                                       capacidad='1')
        self._orden_que_carga(otro)
        self.asignar([self.conductor], 'DISPOSICION_FINAL', [self.camion, otro])
        self.assertFalse(Asignacion.objects.exists(),
                         "cada camión lleva su propia orden")

    def test_quitar_la_asignacion_devuelve_el_camion_a_cargado(self):
        self.asignar([self.conductor], 'DISPOSICION_FINAL', [self.camion])
        asignacion = Asignacion.objects.get()
        self.client.post(reverse('planes:eliminar_asignacion', args=[asignacion.pk]),
                         {'fecha': self.hoy.isoformat()})
        self.camion.refresh_from_db()
        self.assertTrue(self.camion.cargado,
                        "si la disposición no se hizo, el residuo sigue ahí")
        self.assertIn(str(self.orden.numero_orden), self.camion.cargado_detalle)

    def test_quitar_a_uno_de_dos_encargados_no_recarga_el_camion(self):
        self.asignar([self.conductor, self.ayudante], 'DISPOSICION_FINAL',
                     [self.camion])
        una = Asignacion.objects.first()
        self.client.post(reverse('planes:eliminar_asignacion', args=[una.pk]),
                         {'fecha': self.hoy.isoformat()})
        self.camion.refresh_from_db()
        self.assertFalse(self.camion.cargado, "el otro sigue encargado de disponerlo")

    def test_el_tablero_ofrece_la_placa_con_la_orden_que_la_cargo(self):
        contexto = self.client.get(self.url).context
        placa = [v for v in contexto['vehiculos'] if v.pk == self.camion.pk][0]
        self.assertTrue(placa.cargado)
        self.assertEqual(placa.orden_carga, self.orden.numero_orden)

    def test_la_pantalla_marca_cuales_placas_van_cargadas(self):
        contenido = self.client.get(self.url).content.decode()
        self.assertIn('data-cargado="1"', contenido)
        self.assertIn(f'cargado por la orden #{self.orden.numero_orden}', contenido)

    def test_la_disposicion_sale_en_el_plan_y_en_su_pdf(self):
        self.asignar([self.conductor], 'DISPOSICION_FINAL', [self.camion])
        contexto = self.client.get(self.url).context
        fila = [f for g in contexto['grupos'] for f in g['filas']
                if f['persona'] == self.conductor][0]
        self.assertEqual(fila['asignaciones'][0].tipo, 'DISPOSICION_FINAL')
        respuesta = self.client.get(
            reverse('planes:plan_pdf', args=[self.hoy.isoformat()]))
        self.assertTrue(respuesta.content.startswith(b'%PDF'))


class HorasDeParticipacionTests(BasePlan):
    """Los servicios entran con las horas en que la cuadrilla participó."""

    def setUp(self):
        super().setUp()
        from gestion.models import Manifiesto  # noqa: F401 (se usa abajo)
        cliente = Cliente.objects.create(nombre='Cliente X', identificacion='900')
        self.orden = OrdenServicio.objects.create(
            cliente=cliente, asesor=self.asesor, direccion_servicio='x',
            descripcion='y')
        self.recorrido = Recorrido.objects.create(
            orden=self.orden, vehiculo=self.camion, conductor=self.conductor,
            ayudante=self.ayudante, fecha_recorrido=self.hoy)
        self.entrar(self.admin)

    def servicio_de(self, persona, fecha=None):
        fecha = fecha or self.hoy
        contexto = self.client.get(self.url, {'fecha': fecha.isoformat()}).context
        fila = [f for g in contexto['grupos'] for f in g['filas']
                if f['persona'] == persona][0]
        return fila['servicios'][0]

    def test_con_acta_salen_las_horas_reales_de_la_jornada(self):
        from gestion.models import Manifiesto
        Manifiesto.objects.create(
            recorrido=self.recorrido,
            hora_salida_solmed=datetime.time(6, 30),
            hora_llegada_solmed=datetime.time(15, 45))
        for persona in (self.conductor, self.ayudante):
            with self.subTest(persona=persona.username):
                self.assertEqual(self.servicio_de(persona)['horas'], '06:30–15:45')

    def test_sin_horas_de_ruta_se_usan_las_operativas(self):
        from gestion.models import Manifiesto
        Manifiesto.objects.create(
            recorrido=self.recorrido,
            tiempo_inicio_operativo=datetime.time(7, 0),
            tiempo_final_operativo=datetime.time(11, 30))
        self.assertEqual(self.servicio_de(self.conductor)['horas'], '07:00–11:30')

    def test_con_solo_la_hora_de_inicio_se_dice_desde(self):
        from gestion.models import Manifiesto
        Manifiesto.objects.create(recorrido=self.recorrido,
                                  tiempo_inicio_operativo=datetime.time(7, 0))
        self.assertEqual(self.servicio_de(self.conductor)['horas'], 'desde 07:00')

    def test_sin_acta_sale_la_hora_programada_marcada_como_prog(self):
        from gestion.models import Programacion
        programacion = Programacion.objects.create(
            cliente=self.orden.cliente, fecha=self.hoy,
            hora_servicio=datetime.time(8, 0), orden=self.orden,
            estado='CONVERTIDA')
        self.assertEqual(self.servicio_de(self.conductor)['horas'], 'prog. 08:00')

    def test_sin_acta_ni_programacion_no_se_inventan_horas(self):
        self.assertEqual(self.servicio_de(self.conductor)['horas'], '')

    def test_el_historico_tambien_aplica_a_dias_pasados(self):
        """Un día viejo con servicios se consulta y da PDF, sin plan manual."""
        from gestion.models import Manifiesto
        pasado = self.hoy - datetime.timedelta(days=30)
        Recorrido.objects.filter(pk=self.recorrido.pk).update(
            fecha_recorrido=pasado)
        Manifiesto.objects.create(
            recorrido=self.recorrido,
            hora_salida_solmed=datetime.time(6, 0),
            hora_llegada_solmed=datetime.time(14, 0))

        self.assertEqual(self.servicio_de(self.conductor, pasado)['horas'],
                         '06:00–14:00')
        respuesta = self.client.get(
            reverse('planes:plan_pdf', args=[pasado.isoformat()]))
        self.assertEqual(respuesta.status_code, 200)
        self.assertTrue(respuesta.content.startswith(b'%PDF'))

    def test_el_historial_lista_los_dias_que_solo_tuvieron_servicios(self):
        pasado = self.hoy - datetime.timedelta(days=30)
        Recorrido.objects.filter(pk=self.recorrido.pk).update(
            fecha_recorrido=pasado)
        contexto = self.client.get(reverse('planes:historial')).context
        filas = {f['fecha']: f for f in contexto['planes']}
        self.assertIn(pasado, filas, "el día con servicios entra sin plan manual")
        self.assertIsNone(filas[pasado]['plan'])
        self.assertEqual(filas[pasado]['n_servicios'], 1)
        self.assertEqual(filas[pasado]['n_asignaciones'], 0)


class NovedadesTests(BasePlan):
    """La sección 2 del formato: rangos de fechas y su registro."""

    def setUp(self):
        super().setUp()
        self.entrar(self.admin)

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
        self.assertEqual(novedad.registrado_por, self.admin)

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
        self.entrar(self.admin)

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
        self.assertEqual([p['fecha'] for p in contexto['planes']],
                         [manana, self.hoy])
        self.assertEqual(contexto['planes'][0]['n_asignaciones'], 1)

    def test_el_plan_de_otro_dia_se_abre_con_su_fecha(self):
        manana = self.hoy + datetime.timedelta(days=1)
        respuesta = self.client.get(self.url, {'fecha': manana.isoformat()})
        self.assertEqual(respuesta.context['fecha'], manana)

    def test_una_fecha_mal_escrita_cae_en_hoy(self):
        respuesta = self.client.get(self.url, {'fecha': 'basura'})
        self.assertEqual(respuesta.context['fecha'], self.hoy)
