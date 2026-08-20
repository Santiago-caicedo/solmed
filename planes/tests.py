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


class FiltrosDelRegistroDeNovedadesTests(BasePlan):
    """
    El histórico se filtra por trabajador, novedad y FECHA. Las fechas
    trabajan por cruce: una novedad que abarca varios días aparece si
    cualquiera de ellos cae en el rango consultado.
    """

    def setUp(self):
        super().setUp()
        self.entrar(self.admin)
        self.url = reverse('planes:novedades')
        # Vacaciones del día 10 al 20 (rango largo).
        self.vacaciones = Novedad.objects.create(
            persona=self.conductor, tipo='VACACIONES',
            fecha_inicio=datetime.date(2026, 8, 10),
            fecha_fin=datetime.date(2026, 8, 20), registrado_por=self.admin)
        # Una cita médica de un solo día, el 15.
        self.cita = Novedad.objects.create(
            persona=self.ayudante, tipo='PERMISO_CITA_MEDICA',
            fecha_inicio=datetime.date(2026, 8, 15), registrado_por=self.admin)
        # Una incapacidad vieja, en julio.
        self.vieja = Novedad.objects.create(
            persona=self.conductor, tipo='INCAPACIDAD_EPS',
            fecha_inicio=datetime.date(2026, 7, 1),
            fecha_fin=datetime.date(2026, 7, 5), registrado_por=self.admin)

    def filtrar(self, **parametros):
        contexto = self.client.get(self.url, parametros).context
        return list(contexto['novedades'])

    def test_sin_filtros_salen_todas(self):
        self.assertEqual(len(self.filtrar()), 3)

    def test_un_dia_dentro_del_rango_trae_la_novedad_larga(self):
        """Se consulta el 14 y las vacaciones del 10 al 20 deben aparecer."""
        resultado = self.filtrar(desde='2026-08-14', hasta='2026-08-14')
        self.assertEqual(resultado, [self.vacaciones])

    def test_un_rango_que_cruza_trae_las_que_se_solapan(self):
        resultado = self.filtrar(desde='2026-08-15', hasta='2026-08-16')
        self.assertCountEqual(resultado, [self.vacaciones, self.cita])

    def test_un_rango_por_fuera_no_trae_nada(self):
        self.assertEqual(self.filtrar(desde='2026-09-01', hasta='2026-09-30'), [])

    def test_solo_desde_trae_lo_que_termina_de_esa_fecha_en_adelante(self):
        resultado = self.filtrar(desde='2026-08-01')
        self.assertCountEqual(resultado, [self.vacaciones, self.cita])
        self.assertNotIn(self.vieja, resultado)

    def test_solo_hasta_trae_lo_que_empieza_antes_de_esa_fecha(self):
        resultado = self.filtrar(hasta='2026-07-31')
        self.assertEqual(resultado, [self.vieja])

    def test_una_novedad_de_un_solo_dia_se_encuentra_por_su_fecha(self):
        """La cita del 15 (sin fecha final) aparece al consultar ese día."""
        resultado = self.filtrar(desde='2026-08-15', hasta='2026-08-15')
        self.assertIn(self.cita, resultado)
        self.assertIn(self.vacaciones, resultado, "el 15 cae dentro del 10–20")
        self.assertNotIn(self.vieja, resultado)

    def test_esa_misma_cita_no_aparece_el_dia_siguiente(self):
        resultado = self.filtrar(desde='2026-08-16', hasta='2026-08-16')
        self.assertNotIn(self.cita, resultado, "sin fecha final vale un solo día")
        self.assertIn(self.vacaciones, resultado)

    def test_la_fecha_se_combina_con_el_trabajador_y_la_novedad(self):
        resultado = self.filtrar(desde='2026-08-01', hasta='2026-08-31',
                                 q='Carlos')
        self.assertEqual(resultado, [self.vacaciones])

        resultado = self.filtrar(desde='2026-08-01', hasta='2026-08-31',
                                 tipo='PERMISO_CITA_MEDICA')
        self.assertEqual(resultado, [self.cita])

    def test_se_busca_al_trabajador_por_su_cedula(self):
        self.conductor.perfil.numero_documento = '1098765432'
        self.conductor.perfil.save()
        resultado = self.filtrar(q='10987')
        self.assertCountEqual(resultado, [self.vacaciones, self.vieja])

    def test_una_fecha_mal_escrita_se_ignora_en_vez_de_reventar(self):
        self.assertEqual(len(self.filtrar(desde='no-es-fecha')), 3)

    def test_los_filtros_puestos_se_devuelven_a_la_pantalla(self):
        contexto = self.client.get(self.url, {'q': 'Carlos', 'tipo': 'VACACIONES',
                                              'desde': '2026-08-01',
                                              'hasta': '2026-08-31'}).context
        self.assertEqual(contexto['filtros'], {
            'q': 'Carlos', 'tipo': 'VACACIONES',
            'desde': '2026-08-01', 'hasta': '2026-08-31'})
        self.assertTrue(contexto['hay_filtros'])

    def test_la_pantalla_ofrece_los_cuatro_filtros(self):
        contenido = self.client.get(self.url).content.decode()
        for campo in ('name="q"', 'name="tipo"', 'name="desde"', 'name="hasta"'):
            with self.subTest(campo=campo):
                self.assertIn(campo, contenido)
        self.assertIn('Vigentes hoy', contenido)


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


class ImportarDisposicionesTests(BasePlan):
    """
    El comando que carga en el plan las disposiciones que ya se hicieron pero
    nunca se registraron (venían en un Excel). Resuelve datos abreviados
    —placa de 3 letras, nombre de pila, «SOLO» sin ayudante— contra la base.
    """

    def setUp(self):
        super().setUp()
        import tempfile
        self.carpeta = tempfile.mkdtemp()
        self.cli = Cliente.objects.create(nombre='CREPES & WAFFLES', identificacion='900')
        self.orden = OrdenServicio.objects.create(
            cliente=self.cli, asesor=self.admin, direccion_servicio='x', descripcion='y')
        # El conductor y el ayudante de BasePlan se llaman Carlos Pérez y Luis Gómez.

    def csv(self, *filas, cabecera='FECHA,CLIENTE,VEHÍCULO,ORDEN,CONDUCTOR,AYUDANTE'):
        import os
        ruta = os.path.join(self.carpeta, 'disposiciones.csv')
        with open(ruta, 'w', encoding='utf-8-sig') as f:
            f.write(cabecera + '\n')
            for fila in filas:
                f.write(fila + '\n')
        return ruta

    def correr(self, ruta, **opciones):
        from io import StringIO
        from django.core.management import call_command
        salida = StringIO()
        call_command('importar_disposiciones', ruta, stdout=salida, stderr=salida, **opciones)
        return salida.getvalue()

    def fila(self, **cambios):
        datos = {'fecha': '02/08/2026', 'cliente': 'CREPES', 'vehiculo': 'WHB',
                 'orden': f'#{self.orden.pk}', 'conductor': 'CARLOS', 'ayudante': 'LUIS'}
        datos.update(cambios)
        return ','.join([datos['fecha'], datos['cliente'], datos['vehiculo'],
                         datos['orden'], datos['conductor'], datos['ayudante']])

    # ---------- vista previa ----------

    def test_por_defecto_no_escribe_nada(self):
        salida = self.correr(self.csv(self.fila()))
        self.assertIn('Vista previa', salida)
        self.assertFalse(Asignacion.objects.exists())
        self.assertFalse(PlanDia.objects.exists())

    # ---------- lo que deja ----------

    def test_registra_la_disposicion_para_el_conductor_y_su_ayudante(self):
        self.correr(self.csv(self.fila()), confirmar=True)
        plan = PlanDia.objects.get()
        self.assertEqual(plan.fecha, datetime.date(2026, 8, 2))
        asignaciones = Asignacion.objects.all()
        self.assertEqual(asignaciones.count(), 2)
        for a in asignaciones:
            self.assertEqual(a.tipo, 'DISPOSICION_FINAL')
            self.assertEqual(a.orden, self.orden)
            self.assertEqual(a.placas, 'WHB123')
        self.assertCountEqual([a.persona for a in asignaciones],
                              [self.conductor, self.ayudante])

    def test_solo_significa_sin_ayudante(self):
        self.correr(self.csv(self.fila(ayudante='SOLO')), confirmar=True)
        self.assertEqual(Asignacion.objects.count(), 1)
        self.assertEqual(Asignacion.objects.get().persona, self.conductor)

    def test_el_movimiento_queda_fechado_el_dia_real_no_el_de_la_importacion(self):
        from django.utils import timezone as tz
        from gestion.models import MovimientoCargaVehiculo
        self.correr(self.csv(self.fila()), confirmar=True)
        movimiento = MovimientoCargaVehiculo.objects.get()
        self.assertEqual(movimiento.accion, 'DESCARGA')
        self.assertEqual(movimiento.orden, self.orden)
        self.assertEqual(tz.localtime(movimiento.fecha).date(), datetime.date(2026, 8, 2))
        self.assertIn('histórico', movimiento.nota)

    def test_un_solo_movimiento_por_disposicion_aunque_vayan_dos_personas(self):
        from gestion.models import MovimientoCargaVehiculo
        self.correr(self.csv(self.fila()), confirmar=True)
        self.assertEqual(Asignacion.objects.count(), 2)
        self.assertEqual(MovimientoCargaVehiculo.objects.count(), 1)

    def test_no_toca_el_estado_de_carga_de_hoy(self):
        """El histórico no decide la foto de hoy; el comando lo advierte."""
        self.camion.cargado = True
        self.camion.cargado_detalle = 'Orden #22999'
        self.camion.save()
        salida = self.correr(self.csv(self.fila()), confirmar=True)
        self.camion.refresh_from_db()
        self.assertTrue(self.camion.cargado)
        self.assertIn('no se tocó', salida)
        self.assertIn(self.camion.placa, salida)

    def test_correrlo_dos_veces_no_duplica(self):
        ruta = self.csv(self.fila())
        self.correr(ruta, confirmar=True)
        salida = self.correr(ruta, confirmar=True)
        self.assertEqual(Asignacion.objects.count(), 2)
        self.assertEqual(PlanDia.objects.count(), 1)
        self.assertIn('ya estaban', salida)

    def test_varias_disposiciones_del_mismo_dia_comparten_el_plan(self):
        otra = OrdenServicio.objects.create(
            cliente=self.cli, asesor=self.admin, direccion_servicio='x', descripcion='y')
        self.correr(self.csv(self.fila(),
                             self.fila(orden=f'#{otra.pk}', ayudante='SOLO')),
                    confirmar=True)
        self.assertEqual(PlanDia.objects.count(), 1)
        self.assertEqual(Asignacion.objects.count(), 3)

    # ---------- lo que no deja pasar ----------

    def test_una_orden_que_no_existe_frena_la_importacion(self):
        from django.core.management.base import CommandError
        with self.assertRaises(CommandError):
            self.correr(self.csv(self.fila(orden='#99999')), confirmar=True)
        self.assertFalse(Asignacion.objects.exists())

    def test_una_placa_ambigua_frena_la_importacion(self):
        from django.core.management.base import CommandError
        Vehiculo.objects.create(placa='WHB999', marca='m', modelo='2020', capacidad='1')
        with self.assertRaises(CommandError) as caso:
            self.correr(self.csv(self.fila(vehiculo='WHB')), confirmar=True)
        self.assertFalse(Asignacion.objects.exists())

    def test_un_nombre_que_no_esta_frena_la_importacion(self):
        from django.core.management.base import CommandError
        with self.assertRaises(CommandError):
            self.correr(self.csv(self.fila(conductor='FULANO')), confirmar=True)
        self.assertFalse(Asignacion.objects.exists())

    def test_con_omitir_errores_entra_lo_que_si_resolvio(self):
        self.correr(self.csv(self.fila(), self.fila(conductor='FULANO')),
                    confirmar=True, omitir_errores=True)
        self.assertEqual(Asignacion.objects.count(), 2)

    def test_el_nombre_se_busca_dentro_de_su_rol(self):
        """OSCAR puede ser un conductor y otro OSCAR un ayudante."""
        conductor = self.persona('oscarc', 'Conductores', 'OSCAR', 'PEÑA')
        ayudante = self.persona('oscara', 'Ayudantes', 'OSCAR', 'TAMAYO')
        self.correr(self.csv(self.fila(conductor='OSCAR', ayudante='OSCAR')),
                    confirmar=True)
        personas = {a.persona for a in Asignacion.objects.all()}
        self.assertEqual(personas, {conductor, ayudante})

    def test_avisa_si_el_cliente_del_csv_no_es_el_de_la_orden(self):
        salida = self.correr(self.csv(self.fila(cliente='OTRO CLIENTE')))
        self.assertIn('OJO', salida)
        self.assertIn('CREPES & WAFFLES', salida)

    def test_un_csv_sin_las_columnas_necesarias_no_corre(self):
        from django.core.management.base import CommandError
        ruta = self.csv('02/08/2026,CREPES', cabecera='FECHA,CLIENTE')
        with self.assertRaises(CommandError) as caso:
            self.correr(ruta)
        self.assertIn('faltan columnas', str(caso.exception))
