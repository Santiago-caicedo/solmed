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
    Cliente, DisposicionOrden, OrdenServicio, PerfilPersona, Proveedor, Recorrido,
    Vehiculo,
)

from .forms import AsignacionForm, NovedadForm
from .models import Asignacion, Novedad, PlanDia

CLAVE = 'Solmed.Pruebas.2026'


def archivo(nombre='documento.pdf', contenido=b'%PDF-1.4 prueba'):
    """Un archivo cualquiera para los campos FileField."""
    from django.core.files.uploadedfile import SimpleUploadedFile
    return SimpleUploadedFile(nombre, contenido, content_type='application/pdf')


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

    def asignar(self, personas, tipo, vehiculos=None, ordenes=None, **extra):
        """
        POST de una asignación desde el panel, como lo manda el navegador.
        Para DISPOSICION_FINAL las casillas son ÓRDENES sin disponer.
        """
        datos = {'submit_asignacion': '1', 'fecha': self.hoy.isoformat(),
                 'tipo': tipo, 'personas': [p.pk for p in personas],
                 'vehiculos': [v.pk for v in (vehiculos or [])],
                 'ordenes': [o.pk for o in (ordenes or [])],
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

    def test_la_disposicion_exige_marcar_ordenes_sin_disponer(self):
        self.asignar([self.conductor], 'DISPOSICION_FINAL', [self.camion])
        self.assertFalse(Asignacion.objects.exists(),
                         "sin órdenes marcadas no hay nada que disponer")

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
    La disposición se registra asignándole a alguien la actividad: el
    pendiente es DE LA ORDEN (sep-2026), así que el picker ofrece órdenes sin
    disponer, cada una queda con su registro y quitar la actividad la deja
    otra vez sin disponer.
    """

    def setUp(self):
        super().setUp()
        self.entrar(self.admin)
        self.cliente = Cliente.objects.create(nombre='Cliente X', identificacion='900')
        self.orden = self._orden_pendiente(self.camion)

    def _orden_pendiente(self, vehiculo):
        """Un servicio sin disposición final: la orden queda sin disponer."""
        from gestion.models import Dispositor, Programacion, ProgramacionCuadrilla
        destino, _ = Dispositor.objects.get_or_create(
            nombre=Dispositor.DEJAR_CARRO_CARGADO, defaults={'tipo': 'INTERNO'})
        programacion = Programacion.objects.create(
            cliente=self.cliente, fecha=self.hoy,
            requiere_disposicion_final='NO', dispositor_final=destino)
        ProgramacionCuadrilla.objects.create(
            programacion=programacion, conductor=self.conductor, vehiculo=vehiculo)
        orden = programacion.convertir_en_orden(self.admin)
        assert orden.estado_disposicion == 'PENDIENTE'
        return orden

    def refrescar(self):
        self.orden.refresh_from_db()
        return self.orden

    def test_asignar_la_disposicion_deja_la_orden_dispuesta(self):
        self.asignar([self.conductor], 'DISPOSICION_FINAL', ordenes=[self.orden])
        self.assertEqual(self.refrescar().estado_disposicion, 'DISPUESTA')
        registro = self.orden.disposicion_vigente
        self.assertEqual(registro.via, 'PLAN')
        self.assertEqual(registro.fecha, self.hoy)
        self.assertEqual(registro.registrado_por, self.admin)
        self.assertIn('Carlos Pérez', registro.nota)
        asignacion = Asignacion.objects.get()
        self.assertEqual(asignacion.orden, self.orden, "una sola orden: queda en la asignación")
        self.assertEqual(list(asignacion.disposiciones.all()), [registro])
        self.assertEqual([v.placa for v in asignacion.vehiculos.all()], ['WHB123'],
                         "la placa de la orden queda solo de referencia")

    def test_el_registro_guarda_el_gestor(self):
        from gestion.models import Dispositor
        gestor = Dispositor.objects.create(nombre='Relleno Doña Juana')
        self.asignar([self.conductor], 'DISPOSICION_FINAL', ordenes=[self.orden],
                     dispositor=gestor.pk)
        self.assertEqual(self.refrescar().disposicion_vigente.dispositor, gestor)

    def test_asignarla_a_dos_personas_dispone_la_orden_una_sola_vez(self):
        self.asignar([self.conductor, self.ayudante], 'DISPOSICION_FINAL',
                     ordenes=[self.orden])
        self.assertEqual(Asignacion.objects.count(), 2, "cada uno tiene su fila")
        self.assertEqual(DisposicionOrden.objects.count(), 1)
        primera, segunda = Asignacion.objects.order_by('pk')
        self.assertEqual(set(primera.disposiciones.all()), set(segunda.disposiciones.all()))

    def test_una_orden_ya_dispuesta_no_se_ofrece_ni_se_acepta(self):
        self.asignar([self.conductor], 'DISPOSICION_FINAL', ordenes=[self.orden])
        self.asignar([self.ayudante], 'DISPOSICION_FINAL', ordenes=[self.orden])
        self.assertEqual(Asignacion.objects.count(), 1, "la segunda no pasó")
        contenido = self.client.get(self.url).content.decode()
        self.assertNotIn(f'name="ordenes" value="{self.orden.pk}"', contenido)

    def test_un_viaje_puede_disponer_ordenes_de_placas_distintas(self):
        otro = Vehiculo.objects.create(placa='OTR222', marca='m', modelo='2020',
                                       capacidad='1')
        ajena = self._orden_pendiente(otro)
        self.asignar([self.conductor], 'DISPOSICION_FINAL', ordenes=[self.orden, ajena])
        asignacion = Asignacion.objects.get()
        self.assertEqual({v.placa for v in asignacion.vehiculos.all()}, {'WHB123', 'OTR222'})
        self.assertEqual(asignacion.disposiciones.count(), 2, "un registro por orden")
        self.assertIsNone(asignacion.orden, "varias órdenes: la traza vive en los registros")
        self.assertEqual(asignacion.ordenes_dispuestas,
                         sorted([self.orden.numero_orden, ajena.numero_orden]))
        for orden in (self.orden, ajena):
            orden.refresh_from_db()
            self.assertEqual(orden.estado_disposicion, 'DISPUESTA')

    def test_quitar_la_asignacion_deja_la_orden_otra_vez_sin_disponer(self):
        self.asignar([self.conductor], 'DISPOSICION_FINAL', ordenes=[self.orden])
        registro = self.refrescar().disposicion_vigente
        asignacion = Asignacion.objects.get()
        self.client.post(reverse('planes:eliminar_asignacion', args=[asignacion.pk]),
                         {'fecha': self.hoy.isoformat()})
        self.assertEqual(self.refrescar().estado_disposicion, 'PENDIENTE',
                         "si la disposición no se hizo, el residuo sigue pendiente")
        registro.refresh_from_db()
        self.assertTrue(registro.deshecha, "el historial no se borra, se marca")
        self.assertIn('Se quitó del plan', registro.deshecha_nota)
        self.assertIsNone(self.orden.disposicion_vigente)

    def test_quitar_a_uno_de_dos_encargados_no_deshace_la_disposicion(self):
        self.asignar([self.conductor, self.ayudante], 'DISPOSICION_FINAL',
                     ordenes=[self.orden])
        una = Asignacion.objects.first()
        self.client.post(reverse('planes:eliminar_asignacion', args=[una.pk]),
                         {'fecha': self.hoy.isoformat()})
        self.assertEqual(self.refrescar().estado_disposicion, 'DISPUESTA',
                         "el otro sigue encargado de disponerla")

    def test_quitar_una_asignacion_revive_solo_sus_ordenes(self):
        segunda = self._orden_pendiente(self.camion)
        self.asignar([self.conductor], 'DISPOSICION_FINAL', ordenes=[self.orden])
        self.asignar([self.ayudante], 'DISPOSICION_FINAL', ordenes=[segunda])
        de_la_primera = Asignacion.objects.get(persona=self.conductor)
        self.client.post(reverse('planes:eliminar_asignacion', args=[de_la_primera.pk]),
                         {'fecha': self.hoy.isoformat()})
        self.assertEqual(self.refrescar().estado_disposicion, 'PENDIENTE')
        segunda.refresh_from_db()
        self.assertEqual(segunda.estado_disposicion, 'DISPUESTA', "la otra sigue dispuesta")

    def test_el_tablero_ofrece_cada_orden_sin_disponer_como_casilla(self):
        respuesta = self.client.get(self.url)
        self.assertEqual([o.pk for o in respuesta.context['ordenes_pendientes']],
                         [self.orden.pk])
        contenido = respuesta.content.decode()
        self.assertIn(f'name="ordenes" value="{self.orden.pk}"', contenido)
        self.assertIn(f'#{self.orden.numero_orden}', contenido)
        self.assertIn('Cliente X', contenido)
        self.assertNotIn('name="cargas"', contenido)

    def test_la_disposicion_sale_en_el_plan_y_en_su_pdf(self):
        self.asignar([self.conductor], 'DISPOSICION_FINAL', ordenes=[self.orden])
        contexto = self.client.get(self.url).context
        fila = [f for g in contexto['grupos'] for f in g['filas']
                if f['persona'] == self.conductor][0]
        self.assertEqual(fila['asignaciones'][0].tipo, 'DISPOSICION_FINAL')
        self.assertContains(self.client.get(self.url), f'#{self.orden.numero_orden}')
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

    def test_en_el_pdf_el_servicio_se_nombra_por_su_orden_y_su_cliente(self):
        """
        En el plan impreso, «Servicio programado» no le decía nada al equipo:
        va el número de la orden y a quién se le presta.
        """
        cliente = Cliente.objects.create(nombre='ALIMENTOS DEL VALLE',
                                         identificacion='900')
        orden = OrdenServicio.objects.create(
            cliente=cliente, asesor=self.admin, direccion_servicio='x',
            descripcion='y')
        Recorrido.objects.create(orden=orden, vehiculo=self.camion,
                                 conductor=self.conductor, fecha_recorrido=self.hoy)

        servicio = self.client.get(self.url).context['grupos']
        fila = [f for g in servicio for f in g['filas']
                if f['persona'] == self.conductor][0]
        self.assertEqual(fila['servicios'][0]['cliente'], 'ALIMENTOS DEL VALLE')

        respuesta = self.client.get(
            reverse('planes:plan_pdf', args=[self.hoy.isoformat()]))
        self.assertEqual(respuesta.status_code, 200)
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


class FichaDelDiaTests(BasePlan):
    """
    El popup del tablero: al pinchar a alguien con plan, su hoja del día —
    quién es, si sus papeles están al día y todo lo que tiene asignado.
    """

    def setUp(self):
        super().setUp()
        self.entrar(self.admin)
        self.cli = Cliente.objects.create(nombre='Cliente X', identificacion='900')
        self.orden = OrdenServicio.objects.create(
            cliente=self.cli, asesor=self.admin, direccion_servicio='x', descripcion='y')
        self.url = reverse('planes:ficha_persona', args=[self.conductor.pk])

    def ficha(self, persona=None, fecha=None):
        url = reverse('planes:ficha_persona', args=[(persona or self.conductor).pk])
        return self.client.get(url, {'fecha': (fecha or self.hoy).isoformat()})

    # ---------- acceso ----------

    def test_la_ficha_es_solo_del_administrador(self):
        for usuario in (self.asesor, self.conductor):
            with self.subTest(usuario=usuario.username):
                self.entrar(usuario)
                self.assertEqual(self.ficha().status_code, 403)

    def test_sin_sesion_no_se_abre(self):
        self.client.logout()
        respuesta = self.ficha()
        self.assertEqual(respuesta.status_code, 302)
        self.assertIn('/login/', respuesta.url)

    # ---------- quién es ----------

    def test_muestra_los_datos_de_la_persona(self):
        perfil = PerfilPersona.objects.get(usuario=self.conductor)
        perfil.numero_documento = '1098765432'
        perfil.telefono = '300 123 4567'
        perfil.save()
        respuesta = self.ficha()
        self.assertContains(respuesta, 'Carlos Pérez')
        self.assertContains(respuesta, '1098765432')
        self.assertContains(respuesta, '300 123 4567')
        self.assertContains(respuesta, 'Conductores')

    def test_los_papeles_dicen_su_estado(self):
        from gestion.models import DocumentoPersonal
        DocumentoPersonal.objects.create(
            usuario=self.conductor, tipo='SEGURIDAD_SOCIAL', archivo=archivo(),
            fecha_vencimiento=self.hoy + datetime.timedelta(days=40))
        DocumentoPersonal.objects.create(
            usuario=self.conductor, tipo='LICENCIA', archivo=archivo(),
            fecha_vencimiento=self.hoy + datetime.timedelta(days=10))
        papeles = {p['nombre']: p for p in self.ficha().context['papeles']}
        self.assertEqual(papeles['Seguridad social (EPS/ARL/Pensión)']['nivel'], 'ok')
        self.assertEqual(papeles['Licencia de conducción']['nivel'], 'aviso')
        self.assertIn('vence en 10 días', papeles['Licencia de conducción']['texto'])

    def test_un_papel_vencido_sale_en_alto_y_uno_que_falta_lo_dice(self):
        from gestion.models import DocumentoPersonal
        DocumentoPersonal.objects.create(
            usuario=self.conductor, tipo='SEGURIDAD_SOCIAL', archivo=archivo(),
            fecha_vencimiento=self.hoy - datetime.timedelta(days=3))
        papeles = {p['nombre']: p for p in self.ficha().context['papeles']}
        self.assertEqual(papeles['Seguridad social (EPS/ARL/Pensión)']['nivel'], 'alto')
        self.assertEqual(papeles['Licencia de conducción']['nivel'], 'falta')

    def test_al_conductor_se_le_pide_licencia_y_al_ayudante_no(self):
        nombres = [p['nombre'] for p in self.ficha().context['papeles']]
        self.assertIn('Licencia de conducción', nombres)
        nombres = [p['nombre'] for p in self.ficha(self.ayudante).context['papeles']]
        self.assertNotIn('Licencia de conducción', nombres)

    # ---------- qué le tocó ----------

    def test_trae_el_servicio_del_dia_con_sus_horas(self):
        from gestion.models import Manifiesto
        recorrido = Recorrido.objects.create(
            orden=self.orden, vehiculo=self.camion, conductor=self.conductor,
            fecha_recorrido=self.hoy)
        Manifiesto.objects.create(
            recorrido=recorrido, hora_salida_solmed=datetime.time(6, 30),
            hora_llegada_solmed=datetime.time(15, 45))
        respuesta = self.ficha()
        servicio = respuesta.context['servicios'][0]
        self.assertEqual(servicio['orden'], self.orden.pk)
        self.assertEqual(servicio['horas'], '06:30–15:45')
        self.assertContains(respuesta, 'En servicio')

    def test_trae_las_actividades_con_su_placa_y_su_orden(self):
        from gestion.models import Dispositor
        gestor = Dispositor.objects.create(nombre='Relleno Doña Juana')
        plan = PlanDia.objects.create(fecha=self.hoy, creado_por=self.admin)
        a = Asignacion.objects.create(
            plan=plan, persona=self.conductor, tipo='DISPOSICION_FINAL',
            orden=self.orden, dispositor=gestor, registrado_por=self.admin)
        a.vehiculos.set([self.camion])
        respuesta = self.ficha()
        self.assertEqual(list(respuesta.context['asignaciones']), [a])
        self.assertContains(respuesta, 'Disposición final')
        self.assertContains(respuesta, self.camion.placa)
        self.assertContains(respuesta, 'Relleno Doña Juana')
        self.assertContains(respuesta, 'La asignó')

    def test_trae_las_novedades_vigentes_de_ese_dia(self):
        Novedad.objects.create(
            persona=self.conductor, tipo='VACACIONES',
            fecha_inicio=self.hoy - datetime.timedelta(days=2),
            fecha_fin=self.hoy + datetime.timedelta(days=5), registrado_por=self.admin)
        respuesta = self.ficha()
        self.assertEqual(len(respuesta.context['novedades']), 1)
        self.assertContains(respuesta, 'Vacaciones')

    def test_solo_trae_lo_de_esa_persona_y_ese_dia(self):
        plan = PlanDia.objects.create(fecha=self.hoy, creado_por=self.admin)
        Asignacion.objects.create(plan=plan, persona=self.ayudante, tipo='TRASTEO',
                                  registrado_por=self.admin)
        otro_dia = PlanDia.objects.create(
            fecha=self.hoy + datetime.timedelta(days=1), creado_por=self.admin)
        Asignacion.objects.create(plan=otro_dia, persona=self.conductor,
                                  tipo='TRASTEO', registrado_por=self.admin)
        self.assertEqual(list(self.ficha().context['asignaciones']), [])

    def test_un_dia_sin_nada_lo_dice(self):
        self.assertContains(self.ficha(), 'no tiene nada asignado')

    # ---------- el disparador en el tablero ----------

    def test_solo_es_pinchable_quien_tiene_plan(self):
        plan = PlanDia.objects.create(fecha=self.hoy, creado_por=self.admin)
        Asignacion.objects.create(plan=plan, persona=self.conductor, tipo='TRASTEO',
                                  registrado_por=self.admin)
        contenido = self.client.get(self.url_tablero()).content.decode()
        # Por el atributo del disparador: la clase también aparece en el JS,
        # y `data-persona` lo usa el botón «+» de asignar.
        self.assertEqual(contenido.count('nombre-ficha" data-ficha'), 1)
        self.assertIn(f'data-ficha="{self.conductor.pk}"', contenido)
        self.assertNotIn(f'data-ficha="{self.ayudante.pk}"', contenido)

    def test_el_tablero_trae_el_modal_una_sola_vez(self):
        contenido = self.client.get(self.url_tablero()).content.decode()
        self.assertEqual(contenido.count('id="modal-ficha"'), 1)

    def url_tablero(self):
        return reverse('planes:plan_dia')


class CorreoDeAsignacionTests(BasePlan):
    """
    La casilla «Avisar por correo a los asignados» del panel: marcada, cada
    persona recibe su actividad al correo; sin marcar no sale nada; y ni la
    falta de correo ni un fallo del SMTP frenan la asignación.
    """

    def setUp(self):
        super().setUp()
        self.entrar(self.admin)
        self.conductor.email = 'conductor@solmed.co'
        self.conductor.save()
        self.ayudante.email = 'ayudante@solmed.co'
        self.ayudante.save()

    def test_sin_marcar_la_casilla_no_sale_ningun_correo(self):
        from django.core import mail
        self.asignar([self.conductor], 'LAVADA', vehiculos=[self.camion])
        self.assertEqual(Asignacion.objects.count(), 1)
        self.assertEqual(len(mail.outbox), 0)

    def test_marcada_avisa_a_cada_asignado_con_su_actividad(self):
        from django.core import mail
        respuesta = self.asignar([self.conductor, self.ayudante], 'LAVADA',
                                 vehiculos=[self.camion], notificar='1')
        self.assertEqual(respuesta.status_code, 302)
        self.assertEqual(len(mail.outbox), 2)
        destinos = {m.to[0] for m in mail.outbox}
        self.assertEqual(destinos, {'conductor@solmed.co', 'ayudante@solmed.co'})
        correo = mail.outbox[0]
        self.assertIn('Plan de trabajo', correo.subject)
        self.assertIn('Lavada de vehículo', correo.subject)
        self.assertIn('Lavada de vehículo', correo.body)
        self.assertIn(self.camion.placa, correo.body)
        self.assertIn(self.hoy.strftime('%d/%m/%Y'), correo.body)
        # Versión HTML de marca adjunta.
        html = correo.alternatives[0][0]
        self.assertIn('SOLMED', html)
        self.assertIn('Lavada de vehículo', html)

    def test_sin_correo_registrado_avisa_pero_asigna_igual(self):
        from django.core import mail
        self.ayudante.email = ''
        self.ayudante.save()
        respuesta = self.asignar([self.conductor, self.ayudante], 'TRASTEO',
                                 notificar='1')
        self.assertEqual(Asignacion.objects.count(), 2)
        self.assertEqual(len(mail.outbox), 1, "al que sí tiene correo")
        mensajes = [str(m) for m in respuesta.wsgi_request._messages]
        self.assertTrue(any('no tiene correo registrado' in m for m in mensajes))

    def test_un_fallo_del_smtp_no_tumba_la_asignacion(self):
        from unittest.mock import patch
        with patch('django.core.mail.EmailMultiAlternatives.send',
                   side_effect=OSError('sin red')):
            respuesta = self.asignar([self.conductor], 'TRASTEO', notificar='1')
        self.assertEqual(Asignacion.objects.count(), 1,
                         "la actividad queda aunque el correo no salga")
        mensajes = [str(m) for m in respuesta.wsgi_request._messages]
        self.assertTrue(any('No salió el correo' in m for m in mensajes))

    def test_la_casilla_esta_en_el_panel(self):
        respuesta = self.client.get(self.url)
        self.assertContains(respuesta, 'name="notificar"')
        self.assertContains(respuesta, 'Avisar por correo a los asignados')


