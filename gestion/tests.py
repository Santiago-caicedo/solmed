"""
Pruebas automáticas del CRM SOLMED.

Cubren las reglas de negocio que sostienen la operación: el consecutivo de
órdenes, la programación como única puerta de entrada, el rastro de la carga
de los camiones, el acta de servicio y su firma, la encuesta de cierre (PESV),
los accesos por rol, el expediente del personal y los módulos de apoyo
(correos, proveedores, documentación).

Cómo correrlas:

    python manage.py test gestion            # todas
    python manage.py test gestion.tests.ActaDeServicioTests   # una sola clase

Las pruebas NO tocan el `media/` del proyecto: los archivos que suben van a una
carpeta temporal que se borra al terminar (ver `medios_temporales`).
"""
import base64
import datetime
import glob
import io
import os
import re
import shutil
import tempfile
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth.models import Group, User
from django.core import mail
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from .forms import (
    DocumentoPersonalForm, EncuestaConductorForm, OrdenHistoricaForm, PagoForm,
    ProgramacionCuadrillaForm, ProgramacionForm, roles_asignables,
)
from .models import (
    Bascula, Cliente, Dispositor, DocumentoAmbientalCliente, DocumentoCorreoCliente,
    DocumentoDispositor, DocumentoInterno, DocumentoOrden, DocumentoPersonal,
    EncuestaConductor, EnvioCorreo, FotoAyudante, Manifiesto, MedidaACPM,
    MovimientoCargaVehiculo, NovedadOperacional, OrdenServicio, Pago, PerfilPersona,
    Programacion, ProgramacionCuadrilla, Proveedor, Recorrido, Sede, SitioInicio,
    Tercero, TipoResiduo, Vehiculo, cursos_faltantes_ayudante,
)
from .renumeracion import plan_reubicacion, reubicar_orden
from .views import (
    _acta_lista_para_firmar, _pendientes_orden, _resolver_adjunto_correo,
    _ss_vigente, _puede_programarse,
)


# --- Archivos: todo lo que suban las pruebas va a una carpeta temporal ---
MEDIA_TEMPORAL = tempfile.mkdtemp(prefix='solmed-pruebas-')

medios_temporales = override_settings(
    MEDIA_ROOT=MEDIA_TEMPORAL,
    STORAGES={
        'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
        'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'},
    },
)


def tearDownModule():
    shutil.rmtree(MEDIA_TEMPORAL, ignore_errors=True)


CLAVE = 'Solmed.Pruebas.2026'


def archivo(nombre='documento.pdf', contenido=b'%PDF-1.4 contenido de prueba'):
    """Un archivo cualquiera para los campos FileField."""
    return SimpleUploadedFile(nombre, contenido, content_type='application/pdf')


def png_bytes(ancho=40, alto=20):
    """Un PNG real (la firma del cliente se valida por su cabecera de bytes)."""
    from PIL import Image
    buffer = io.BytesIO()
    Image.new('RGB', (ancho, alto), 'white').save(buffer, format='PNG')
    return buffer.getvalue()


def firma_data_uri(datos=None):
    """La firma tal como la manda el pad del navegador."""
    return 'data:image/png;base64,' + base64.b64encode(datos or png_bytes()).decode()


def imagen(nombre='foto.png'):
    return SimpleUploadedFile(nombre, png_bytes(), content_type='image/png')


@medios_temporales
class BaseCRM(TestCase):
    """Utilidades compartidas: personas con rol, clientes, vehículos y servicios."""

    # ---------- construcción de datos ----------

    @staticmethod
    def grupo(nombre):
        return Group.objects.get_or_create(name=nombre)[0]

    @classmethod
    def persona(cls, username, rol=None, nombre='', apellido='',
                superusuario=False, correo=None):
        correo = correo if correo is not None else f'{username}@ejemplo.co'
        if superusuario:
            usuario = User.objects.create_superuser(username, correo, CLAVE)
        else:
            usuario = User.objects.create_user(username, correo, CLAVE)
        usuario.first_name = nombre or username.capitalize()
        usuario.last_name = apellido
        usuario.save()
        if rol:
            usuario.groups.add(cls.grupo(rol))
        PerfilPersona.objects.get_or_create(usuario=usuario)
        return usuario

    @staticmethod
    def con_ss(persona, dias=30):
        """Le carga una seguridad social vigente (requisito para programar)."""
        return DocumentoPersonal.objects.create(
            usuario=persona, tipo='SEGURIDAD_SOCIAL', archivo=archivo('ss.pdf'),
            fecha_vencimiento=timezone.localdate() + datetime.timedelta(days=dias),
        )

    @staticmethod
    def cliente(nombre='Transportes del Norte S.A.S.', **extra):
        datos = {'identificacion': '900123456-1', 'direccion': 'Cra 10 # 20-30',
                 'email': 'contacto@cliente.co'}
        datos.update(extra)
        return Cliente.objects.create(nombre=nombre, **datos)

    @staticmethod
    def vehiculo(placa='WHB123', **extra):
        datos = {'marca': 'Kenworth', 'modelo': '2019', 'capacidad': '10 m³'}
        datos.update(extra)
        return Vehiculo.objects.create(placa=placa, **datos)

    @classmethod
    def programacion(cls, cliente=None, conductor=None, vehiculo=None,
                     ayudante=None, fecha=None, **extra):
        """Programación con UNA cuadrilla lista para convertirse en orden."""
        cliente = cliente or cls.cliente()
        vehiculo = vehiculo or cls.vehiculo()
        programacion = Programacion.objects.create(
            cliente=cliente, fecha=fecha or timezone.localdate(), **extra)
        ProgramacionCuadrilla.objects.create(
            programacion=programacion, conductor=conductor,
            vehiculo=vehiculo, ayudante=ayudante)
        return programacion

    @classmethod
    def servicio_completo(cls):
        """
        El escenario típico: cliente, conductor con SS, camión y una orden ya
        generada desde su programación. Devuelve un dict con todas las piezas.
        """
        cliente = cls.cliente()
        conductor = cls.persona('conductor1', 'Conductores', 'Carlos', 'Pérez')
        cls.con_ss(conductor)
        asesor = cls.persona('asesor1', 'Asesores', 'Ana', 'Ruiz')
        vehiculo = cls.vehiculo()
        programacion = cls.programacion(
            cliente=cliente, conductor=conductor, vehiculo=vehiculo,
            observaciones_servicio='Succión de pozo séptico')
        orden = programacion.convertir_en_orden(asesor)
        # OJO con los nombres: las clases de prueba hacen
        # `self.__dict__.update(...)`, así que las claves NO pueden llamarse
        # como los ayudantes de esta clase (`cliente`, `vehiculo`, `persona`).
        return {
            'cli': cliente, 'conductor': conductor, 'asesor': asesor,
            'camion': vehiculo, 'programacion': programacion, 'orden': orden,
            'recorrido': orden.recorridos.first(),
        }

    # ---------- utilidades de sesión ----------

    def entrar(self, usuario):
        self.assertTrue(self.client.login(username=usuario.username, password=CLAVE))
        return usuario


# ============================================================
#  CONSECUTIVO DE ÓRDENES
# ============================================================
class ConsecutivoOrdenesTests(BaseCRM):
    """El número de orden arranca en 22207 y nunca lo calcula la base de datos."""

    def setUp(self):
        self.cli = self.cliente()
        self.asesor = self.persona('asesor', 'Asesores')

    def _orden(self):
        return OrdenServicio.objects.create(
            cliente=self.cli, asesor=self.asesor,
            direccion_servicio='Calle 1', descripcion='x')

    def test_la_primera_orden_arranca_en_el_numero_inicial(self):
        self.assertEqual(self._orden().numero_orden, OrdenServicio.NUMERO_INICIAL)

    def test_la_siguiente_orden_es_la_ultima_mas_uno(self):
        primera = self._orden()
        self.assertEqual(self._orden().numero_orden, primera.numero_orden + 1)

    def test_una_orden_historica_no_mueve_el_consecutivo_automatico(self):
        OrdenServicio.objects.create(
            numero_orden=15000, cliente=self.cli, asesor=self.asesor,
            direccion_servicio='', descripcion='histórica')
        self.assertEqual(self._orden().numero_orden, OrdenServicio.NUMERO_INICIAL)

    def test_la_programacion_muestra_el_numero_de_su_orden(self):
        programacion = self.programacion(
            cliente=self.cli, conductor=self.persona('c1', 'Conductores'))
        self.assertIsNone(programacion.numero, "un borrador no tiene número todavía")
        orden = programacion.convertir_en_orden(self.asesor)
        self.assertEqual(programacion.numero, orden.numero_orden)


# ============================================================
#  PROGRAMACIÓN → ORDEN (la única puerta de entrada)
# ============================================================
class ConversionProgramacionTests(BaseCRM):
    """`convertir_en_orden` es el corazón del sistema: qué crea y qué copia."""

    def setUp(self):
        self.asesor = self.persona('asesor', 'Asesores')
        self.conductor = self.persona('conductor', 'Conductores', 'Carlos', 'Pérez')
        self.con_ss(self.conductor)
        self.cli = self.cliente()
        self.camion = self.vehiculo()

    def test_genera_la_orden_con_un_recorrido_por_cuadrilla_con_vehiculo(self):
        programacion = self.programacion(
            cliente=self.cli, conductor=self.conductor, vehiculo=self.camion)
        # Una segunda cuadrilla SIN vehículo no genera recorrido.
        ProgramacionCuadrilla.objects.create(
            programacion=programacion, conductor=self.conductor)
        otro = self.vehiculo('ABC987')
        ProgramacionCuadrilla.objects.create(
            programacion=programacion, conductor=self.conductor, vehiculo=otro)

        orden = programacion.convertir_en_orden(self.asesor)

        self.assertEqual(orden.recorridos.count(), 2)
        self.assertEqual(
            sorted(r.vehiculo.placa for r in orden.recorridos.all()),
            sorted([self.camion.placa, otro.placa]))
        self.assertEqual(orden.cliente, self.cli)
        self.assertEqual(orden.asesor, self.asesor)

    def test_la_programacion_queda_convertida_y_enlazada(self):
        programacion = self.programacion(
            cliente=self.cli, conductor=self.conductor, vehiculo=self.camion)
        orden = programacion.convertir_en_orden(self.asesor)
        programacion.refresh_from_db()
        self.assertEqual(programacion.estado, 'CONVERTIDA')
        self.assertEqual(programacion.orden_id, orden.pk)
        self.assertEqual(orden.programacion_origen, programacion)

    def test_convertir_dos_veces_no_duplica_la_orden(self):
        programacion = self.programacion(
            cliente=self.cli, conductor=self.conductor, vehiculo=self.camion)
        primera = programacion.convertir_en_orden(self.asesor)
        segunda = programacion.convertir_en_orden(self.asesor)
        self.assertEqual(primera.pk, segunda.pk)
        self.assertEqual(OrdenServicio.objects.count(), 1)

    def test_sin_cuadrilla_con_vehiculo_no_se_puede_convertir(self):
        programacion = Programacion.objects.create(
            cliente=self.cli, fecha=timezone.localdate())
        ProgramacionCuadrilla.objects.create(
            programacion=programacion, conductor=self.conductor)
        self.assertFalse(programacion.puede_convertirse)
        with self.assertRaises(ValueError):
            programacion.convertir_en_orden(self.asesor)
        self.assertFalse(OrdenServicio.objects.exists())

    def test_el_recorrido_hereda_fecha_conductor_y_ayudantes(self):
        ayudante = self.persona('ayudante', 'Ayudantes', 'Luis', 'Gómez')
        ayudante2 = self.persona('ayudante2', 'Ayudantes', 'Iván', 'Mora')
        fecha = timezone.localdate() + datetime.timedelta(days=1)
        programacion = Programacion.objects.create(
            cliente=self.cli, fecha=fecha)
        ProgramacionCuadrilla.objects.create(
            programacion=programacion, conductor=self.conductor,
            vehiculo=self.camion, ayudante=ayudante, ayudante2=ayudante2)

        recorrido = programacion.convertir_en_orden(self.asesor).recorridos.first()

        self.assertEqual(recorrido.fecha_recorrido, fecha)
        self.assertEqual(recorrido.conductor, self.conductor)
        self.assertEqual(recorrido.ayudante, ayudante)
        self.assertEqual(recorrido.ayudante2, ayudante2)
        self.assertEqual(recorrido.estado, 'PROGRAMADO')

    def test_la_direccion_sale_del_tercero_antes_que_de_la_sede(self):
        sede = Sede.objects.create(cliente=self.cli, nombre='Sede Norte',
                                   direccion='Calle Sede 1')
        tercero = Tercero.objects.create(cliente=self.cli, nombre='Acopio Sur',
                                         direccion='Calle Tercero 9', ciudad='Cali',
                                         telefono='3001112233', persona_contacto='Pedro')
        programacion = self.programacion(
            cliente=self.cli, conductor=self.conductor, vehiculo=self.camion,
            sede_cliente=sede, tercero=tercero, direccion='Escrita a mano')
        orden = programacion.convertir_en_orden(self.asesor)
        self.assertEqual(orden.direccion_servicio, 'Calle Tercero 9')
        # Los datos del tercero quedan escritos en la descripción de la orden.
        self.assertIn('Acopio Sur', orden.descripcion)
        self.assertIn('Calle Tercero 9', orden.descripcion)
        self.assertIn('Pedro', orden.descripcion)

    def test_sin_tercero_la_direccion_sale_de_la_sede(self):
        sede = Sede.objects.create(cliente=self.cli, nombre='Sede Norte',
                                   direccion='Calle Sede 1')
        programacion = self.programacion(
            cliente=self.cli, conductor=self.conductor, vehiculo=self.camion,
            sede_cliente=sede, direccion='Escrita a mano')
        orden = programacion.convertir_en_orden(self.asesor)
        self.assertEqual(orden.direccion_servicio, 'Calle Sede 1')

    def test_sin_sede_ni_tercero_manda_la_direccion_escrita_y_luego_la_del_cliente(self):
        programacion = self.programacion(
            cliente=self.cli, conductor=self.conductor, vehiculo=self.camion,
            direccion='Escrita a mano')
        self.assertEqual(
            programacion.convertir_en_orden(self.asesor).direccion_servicio,
            'Escrita a mano')

        otra = self.programacion(
            cliente=self.cli, conductor=self.conductor,
            vehiculo=self.vehiculo('XYZ111'))
        self.assertEqual(
            otra.convertir_en_orden(self.asesor).direccion_servicio,
            self.cli.direccion)

    def test_el_checklist_operativo_se_arrastra_a_la_orden(self):
        programacion = self.programacion(
            cliente=self.cli, conductor=self.conductor, vehiculo=self.camion,
            bascula='PESAN', registro_fotografico='SI')
        orden = programacion.convertir_en_orden(self.asesor)
        self.assertEqual(orden.bascula, 'PESAN')
        self.assertEqual(orden.registro_fotografico, 'SI')
        self.assertTrue(orden.requiere_bascula)
        self.assertTrue(orden.requiere_registro_fotografico)

    def test_sin_cantidad_de_transporte_la_orden_queda_pendiente_de_conciliar(self):
        programacion = self.programacion(
            cliente=self.cli, conductor=self.conductor, vehiculo=self.camion)
        self.assertEqual(
            programacion.convertir_en_orden(self.asesor).estado_conciliacion,
            'PENDIENTE')

    def test_con_cantidad_de_transporte_la_orden_nace_conciliada(self):
        programacion = self.programacion(
            cliente=self.cli, conductor=self.conductor, vehiculo=self.camion,
            transporte_cantidad='12 m³')
        self.assertEqual(
            programacion.convertir_en_orden(self.asesor).estado_conciliacion,
            'CONCILIADA')

    def test_un_curso_vencido_impide_generar_la_orden(self):
        ayudante = self.persona('ayudante', 'Ayudantes', 'Luis', 'Gómez')
        DocumentoPersonal.objects.create(
            usuario=ayudante, tipo='CURSO_ALTURAS', archivo=archivo(),
            fecha_vencimiento=timezone.localdate() - datetime.timedelta(days=1))
        programacion = Programacion.objects.create(
            cliente=self.cli, fecha=timezone.localdate(), exige_curso_alturas='SI')
        ProgramacionCuadrilla.objects.create(
            programacion=programacion, conductor=self.conductor,
            vehiculo=self.camion, ayudante=ayudante)

        with self.assertRaises(ValueError) as caso:
            programacion.convertir_en_orden(self.asesor)
        self.assertIn('curso de alturas', str(caso.exception))
        self.assertFalse(OrdenServicio.objects.exists())

    def test_con_el_curso_vigente_la_orden_se_genera(self):
        ayudante = self.persona('ayudante', 'Ayudantes')
        DocumentoPersonal.objects.create(
            usuario=ayudante, tipo='CURSO_ALTURAS', archivo=archivo(),
            fecha_vencimiento=timezone.localdate() + datetime.timedelta(days=100))
        programacion = Programacion.objects.create(
            cliente=self.cli, fecha=timezone.localdate(), exige_curso_alturas='SI')
        ProgramacionCuadrilla.objects.create(
            programacion=programacion, conductor=self.conductor,
            vehiculo=self.camion, ayudante=ayudante)
        self.assertTrue(programacion.convertir_en_orden(self.asesor).pk)

    def test_cursos_faltantes_distingue_faltante_de_vencido_y_de_vigente(self):
        ayudante = self.persona('ayudante', 'Ayudantes', 'Luis', 'Gómez')
        self.assertEqual(
            cursos_faltantes_ayudante(ayudante, exige_alturas=True),
            ['no tiene cargado el curso de alturas'])

        DocumentoPersonal.objects.create(
            usuario=ayudante, tipo='CURSO_ALTURAS', archivo=archivo(),
            fecha_vencimiento=timezone.localdate() - datetime.timedelta(days=5))
        motivos = cursos_faltantes_ayudante(ayudante, exige_alturas=True)
        self.assertEqual(len(motivos), 1)
        self.assertIn('vencido', motivos[0])

        DocumentoPersonal.objects.create(
            usuario=ayudante, tipo='CURSO_ALTURAS', archivo=archivo(),
            fecha_vencimiento=timezone.localdate() + datetime.timedelta(days=5))
        self.assertEqual(cursos_faltantes_ayudante(ayudante, exige_alturas=True), [])

    def test_sin_cursos_exigidos_no_se_revisa_nada(self):
        ayudante = self.persona('ayudante', 'Ayudantes')
        self.assertEqual(cursos_faltantes_ayudante(ayudante), [])

    def test_el_resumen_del_checklist_traduce_el_formato_a_palabras(self):
        bascula = Bascula.objects.create(nombre='Báscula Centro')
        proveedor = Dispositor.objects.create(nombre='Gestor Ambiental S.A.')
        programacion = self.programacion(
            cliente=self.cli, conductor=self.conductor, vehiculo=self.camion,
            paleada='SAVICOL', bascula='PESAN', bascula_sitio=bascula,
            responsable_sg='SI', registro_fotografico='SI',
            requiere_disposicion_final='SI', dispositor_final=proveedor,
            exige_curso_alturas='SI')
        izquierda, derecha = programacion.resumen_checklist()
        izquierda, derecha = dict(izquierda), dict(derecha)
        self.assertEqual(izquierda['PALEADA'], 'Palea Savicol')
        self.assertIn('Báscula Centro', izquierda['BÁSCULA'])
        self.assertEqual(izquierda['SE REALIZA DISPOSICIÓN'], 'Gestor Ambiental S.A.')
        self.assertEqual(derecha['SE REQUIERE SISO'], 'SÍ')
        self.assertIn('SUBIR FOTOS', derecha['REGISTRO FOTOGRÁFICO'])
        self.assertEqual(derecha['AYUDANTE CON CURSOS'], 'Alturas')

    def test_el_resumen_de_instrucciones_solo_lista_lo_marcado(self):
        programacion = self.programacion(
            cliente=self.cli, conductor=self.conductor, vehiculo=self.camion,
            succ_canecas=True, succ_canecas_cant='5', succ_tanques=False,
            transporte_tipo='Lodos', transporte_cantidad='12 m³')
        resumen = programacion.resumen_instrucciones()
        self.assertIn('Canecas (5)', resumen)
        self.assertIn('Residuo: Lodos (12 m³)', resumen)
        self.assertNotIn('Tanques', resumen)

    def test_las_instrucciones_del_asesor_viajan_completas_al_acta(self):
        programacion = self.programacion(
            cliente=self.cli, conductor=self.conductor, vehiculo=self.camion,
            succ_pozos_septicos=True, succ_pozos_septicos_cant='3',
            sond_diametro='6 pulgadas', lavado_concepto='Tanque',
            transporte_tipo='Lodos')
        instrucciones = programacion.instrucciones_acta()
        # Todos los campos del acta que define el asesor están en el paquete.
        self.assertEqual(set(instrucciones),
                         set(Programacion.CAMPOS_INSTRUCCIONES_ACTA))
        self.assertTrue(instrucciones['succ_pozos_septicos'])
        self.assertEqual(instrucciones['sond_diametro'], '6 pulgadas')
        # Y son campos que el Manifiesto sabe recibir tal cual.
        campos_acta = {f.name for f in Manifiesto._meta.get_fields()}
        self.assertTrue(set(instrucciones).issubset(campos_acta))


# ============================================================
#  RASTRO DE LA CARGA DE LOS CAMIONES
# ============================================================
class CargaDeVehiculosTests(BaseCRM):
    """
    A dónde fue el residuo: la disposición de la programación mueve el estado
    `cargado` del camión y deja historial (MovimientoCargaVehiculo).
    """

    def setUp(self):
        self.asesor = self.persona('asesor', 'Asesores')
        self.conductor = self.persona('conductor', 'Conductores')
        self.con_ss(self.conductor)
        self.cli = self.cliente()
        self.camion = self.vehiculo()

    def _convertir(self, **extra):
        programacion = self.programacion(
            cliente=self.cli, conductor=self.conductor, vehiculo=self.camion, **extra)
        return programacion.convertir_en_orden(self.asesor)

    def test_la_disposicion_deja_constancia_aunque_el_camion_no_estuviera_cargado(self):
        """
        Antes no se registraba nada si el camión no venía marcado: la
        trazabilidad del residuo se perdía justo en el caso más común.
        """
        proveedor = Dispositor.objects.create(nombre='Gestor Ambiental S.A.')
        self.assertFalse(self.camion.cargado)
        orden = self._convertir(requiere_disposicion_final='SI',
                                dispositor_final=proveedor)
        movimiento = self.camion.movimientos_carga.get()
        self.assertEqual(movimiento.accion, 'DESCARGA')
        self.assertEqual(movimiento.dispositor, proveedor)
        self.assertEqual(movimiento.orden, orden, "el movimiento sabe de qué orden viene")

    def test_el_movimiento_de_carga_recuerda_la_orden_que_lo_cargo(self):
        destino = Dispositor.objects.create(
            nombre=Dispositor.DEJAR_CARRO_CARGADO, tipo='INTERNO')
        orden = self._convertir(requiere_disposicion_final='NO',
                                dispositor_final=destino)
        self.camion.refresh_from_db()
        self.assertEqual(self.camion.carga_actual.orden, orden)
        self.assertEqual(self.camion.orden_que_cargo, orden)

    def test_un_camion_vacio_no_tiene_orden_que_lo_cargo(self):
        self.assertIsNone(self.camion.carga_actual)
        self.assertIsNone(self.camion.orden_que_cargo)

    def test_la_disposicion_con_proveedor_descarga_el_camion(self):
        proveedor = Dispositor.objects.create(nombre='Gestor Ambiental S.A.')
        self.camion.cargado = True
        self.camion.cargado_detalle = 'De un servicio anterior'
        self.camion.save()

        self._convertir(requiere_disposicion_final='SI', dispositor_final=proveedor)

        self.camion.refresh_from_db()
        self.assertFalse(self.camion.cargado)
        self.assertEqual(self.camion.cargado_detalle, '')
        movimiento = self.camion.movimientos_carga.first()
        self.assertEqual(movimiento.accion, 'DESCARGA')
        self.assertEqual(movimiento.dispositor, proveedor)
        self.assertEqual(movimiento.registrado_por, self.asesor)

    def test_dejar_carro_cargado_deja_el_camion_pendiente(self):
        destino = Dispositor.objects.create(
            nombre=Dispositor.DEJAR_CARRO_CARGADO, tipo='INTERNO')
        orden = self._convertir(requiere_disposicion_final='NO',
                                dispositor_final=destino)
        self.camion.refresh_from_db()
        self.assertTrue(self.camion.cargado)
        self.assertIn(str(orden.numero_orden), self.camion.cargado_detalle)
        self.assertEqual(self.camion.movimientos_carga.first().accion, 'CARGA')

    def test_el_trasiego_carga_la_placa_destino_y_descarga_la_del_servicio(self):
        destino = Dispositor.objects.create(
            nombre=Dispositor.TRASIEGO_PLACA, tipo='INTERNO')
        receptor = self.vehiculo('ABC987')
        self.camion.cargado = True
        self.camion.save()

        self._convertir(requiere_disposicion_final='NO', dispositor_final=destino,
                        trasiego_vehiculo=receptor)

        self.camion.refresh_from_db()
        receptor.refresh_from_db()
        self.assertTrue(receptor.cargado, "el camión que recibe queda cargado")
        self.assertFalse(self.camion.cargado, "el del servicio trasegó su contenido")
        self.assertEqual(receptor.movimientos_carga.first().accion, 'CARGA')
        self.assertIn(receptor.placa, self.camion.movimientos_carga.first().nota)

    def test_el_trasiego_a_tanques_descarga_el_camion(self):
        destino = Dispositor.objects.create(
            nombre=Dispositor.TANQUES[0], tipo='INTERNO')
        self.camion.cargado = True
        self.camion.save()
        self._convertir(requiere_disposicion_final='NO', dispositor_final=destino)
        self.camion.refresh_from_db()
        self.assertFalse(self.camion.cargado)

    def test_sin_disposicion_no_toca_el_estado_del_camion(self):
        """«NO HAY DISPOSICIÓN»: el servicio pasa sin dejar nada pendiente."""
        destino = Dispositor.objects.create(
            nombre=Dispositor.SIN_DISPOSICION, tipo='INTERNO')
        self.camion.cargado = True
        self.camion.cargado_detalle = 'Pendiente viejo'
        self.camion.save()

        self._convertir(requiere_disposicion_final='NO', dispositor_final=destino)

        self.camion.refresh_from_db()
        self.assertTrue(self.camion.cargado, "el pendiente anterior sigue siendo suyo")
        self.assertEqual(self.camion.cargado_detalle, 'Pendiente viejo')
        self.assertFalse(self.camion.movimientos_carga.exists())

    def test_si_la_pregunta_quedo_sin_responder_no_se_toca_nada(self):
        self._convertir()
        self.camion.refresh_from_db()
        self.assertFalse(self.camion.cargado)
        self.assertFalse(MovimientoCargaVehiculo.objects.exists())

    def test_el_expediente_del_vehiculo_ya_no_descarga(self):
        """
        La disposición es trabajo de alguien: se asigna en el plan de trabajo
        (decisión del usuario, ago-2026). El botón del expediente se retiró.
        """
        self.camion.cargado = True
        self.camion.cargado_detalle = 'Orden #22207'
        self.camion.save()
        self.entrar(self.asesor)
        self.client.post(reverse('gestion:marcar_carga_vehiculo', args=[self.camion.pk]),
                         {'accion': 'DESCARGA', 'nota': 'Se dispuso en planta'})
        self.camion.refresh_from_db()
        self.assertTrue(self.camion.cargado, "solo el plan de trabajo descarga")
        self.assertFalse(MovimientoCargaVehiculo.objects.exists())

    def test_marcar_carga_a_mano_exige_la_nota_de_trazabilidad(self):
        self.entrar(self.asesor)
        self.client.post(reverse('gestion:marcar_carga_vehiculo', args=[self.camion.pk]),
                         {'accion': 'CARGA', 'nota': '   '})
        self.camion.refresh_from_db()
        self.assertFalse(self.camion.cargado, "sin nota no se registra la carga")
        self.assertFalse(MovimientoCargaVehiculo.objects.exists())

    def test_marcar_carga_a_mano_deja_el_camion_pendiente(self):
        self.entrar(self.asesor)
        self.client.post(reverse('gestion:marcar_carga_vehiculo', args=[self.camion.pk]),
                         {'accion': 'CARGA', 'nota': 'Recogida sin disposición'})
        self.camion.refresh_from_db()
        self.assertTrue(self.camion.cargado)
        self.assertIn('Recogida sin disposición', self.camion.cargado_detalle)

    def test_una_accion_desconocida_no_cambia_nada(self):
        self.entrar(self.asesor)
        self.client.post(reverse('gestion:marcar_carga_vehiculo', args=[self.camion.pk]),
                         {'accion': 'BORRAR', 'nota': 'x'})
        self.camion.refresh_from_db()
        self.assertFalse(self.camion.cargado)
        self.assertFalse(MovimientoCargaVehiculo.objects.exists())

    def test_el_conductor_no_marca_la_carga(self):
        self.entrar(self.conductor)
        respuesta = self.client.post(
            reverse('gestion:marcar_carga_vehiculo', args=[self.camion.pk]),
            {'accion': 'CARGA', 'nota': 'x'})
        self.assertEqual(respuesta.status_code, 403)
        self.camion.refresh_from_db()
        self.assertFalse(self.camion.cargado)


# ============================================================
#  ESTADOS DE ORDEN Y RECORRIDO
# ============================================================
class EstadosDeLaOrdenTests(BaseCRM):
    """El estado de la orden se deduce de sus recorridos, nunca se escribe a mano."""

    def setUp(self):
        datos = self.servicio_completo()
        self.orden = datos['orden']
        self.recorrido = datos['recorrido']
        self.conductor = datos['conductor']
        self.asesor = datos['asesor']

    def test_una_orden_con_recorridos_pendientes_queda_en_ejecucion(self):
        # OJO: el estado se recalcula al crear cada recorrido, así que una orden
        # recién generada ya sale como EN_EJECUCION (PROGRAMADA solo queda para
        # las órdenes que se quedan sin ningún recorrido).
        self.assertEqual(self.orden.estado_orden, 'EN_EJECUCION')

    def test_una_orden_sin_recorridos_vuelve_a_programada(self):
        from gestion.models import _recalcular_estado_orden
        self.recorrido.delete()
        _recalcular_estado_orden(self.orden)
        self.orden.refresh_from_db()
        self.assertEqual(self.orden.estado_orden, 'PROGRAMADA')

    def test_con_todos_los_recorridos_completados_la_orden_queda_finalizada(self):
        self.recorrido.estado = 'COMPLETADO'
        self.recorrido.save()
        self.orden.refresh_from_db()
        self.assertEqual(self.orden.estado_orden, 'FINALIZADA')

    def test_con_parte_de_los_recorridos_completados_la_orden_esta_en_ejecucion(self):
        Recorrido.objects.create(
            orden=self.orden, vehiculo=self.vehiculo('OTR456'),
            conductor=self.conductor, fecha_recorrido=timezone.localdate())
        self.recorrido.estado = 'COMPLETADO'
        self.recorrido.save()
        self.orden.refresh_from_db()
        self.assertEqual(self.orden.estado_orden, 'EN_EJECUCION')

    def test_la_encuesta_de_cierre_marca_el_recorrido_completado(self):
        Manifiesto.objects.create(recorrido=self.recorrido, estado_firma='FIRMADO')
        EncuestaConductor.objects.create(
            recorrido=self.recorrido, presento_fatiga='NO',
            realizo_pausas_activas='SI', molestias_fisicas='NO',
            tiempos_adecuados='SI', cabina_optima='SI',
            zonas_seguras_descanso='SI', condicion_riesgo='NO')
        self.recorrido.refresh_from_db()
        self.orden.refresh_from_db()
        self.assertEqual(self.recorrido.estado, 'COMPLETADO')
        self.assertEqual(self.orden.estado_orden, 'FINALIZADA')

    def test_una_orden_cancelada_no_cambia_de_estado_sola(self):
        self.orden.estado_orden = 'CANCELADA'
        self.orden.save()
        self.recorrido.estado = 'COMPLETADO'
        self.recorrido.save()
        self.orden.refresh_from_db()
        self.assertEqual(self.orden.estado_orden, 'CANCELADA')

    def test_el_responsable_y_los_auxiliares_del_acta_salen_del_recorrido(self):
        ayudante = self.persona('ayu', 'Ayudantes', 'Luis', 'Gómez')
        self.recorrido.ayudante = ayudante
        self.recorrido.save()
        self.assertEqual(self.recorrido.responsable_empresa, 'Carlos Pérez')
        self.assertEqual(self.recorrido.auxiliares, ('Luis Gómez', ''))

    def test_sin_conductor_el_responsable_queda_vacio(self):
        self.recorrido.conductor = None
        self.recorrido.save()
        self.assertEqual(self.recorrido.responsable_empresa, '')


# ============================================================
#  ACTA DE SERVICIO (Manifiesto): el asistente del conductor
# ============================================================
class ActaDeServicioTests(BaseCRM):
    """
    Lo que el conductor llena, lo que NO llena (viene del asesor) y las
    protecciones del acta ya firmada.
    """

    def setUp(self):
        datos = self.servicio_completo()
        self.__dict__.update(datos)
        self.programacion.succ_pozos_septicos = True
        self.programacion.succ_pozos_septicos_cant = '3'
        self.programacion.transporte_tipo = 'Lodos'
        self.programacion.save()
        self.ayudante = self.persona('ayu', 'Ayudantes', 'Luis', 'Gómez')
        self.recorrido.ayudante = self.ayudante
        self.recorrido.save()

    def url_paso(self, paso='paso3'):
        return reverse('gestion:firmar_manifiesto_step',
                       args=[self.recorrido.pk, paso])

    def datos_hoja(self, **extra):
        datos = {
            'tiempo_inicio_operativo': '07:00',
            'tiempo_final_operativo': '11:30',
            'hora_salida_solmed': '06:00',
            'hora_llegada_solmed': '13:00',
        }
        datos.update(extra)
        return datos

    def test_la_hoja_del_conductor_persiste_el_acta_de_una_vez(self):
        self.entrar(self.conductor)
        respuesta = self.client.post(self.url_paso('paso3'), self.datos_hoja())
        self.assertRedirects(respuesta, self.url_paso('paso4'))

        acta = Manifiesto.objects.get(recorrido=self.recorrido)
        self.assertEqual(acta.tiempo_inicio_operativo, datetime.time(7, 0))
        self.assertEqual(acta.hora_llegada_solmed, datetime.time(13, 0))
        self.assertEqual(acta.estado_firma, 'PENDIENTE_FIRMA')

    def test_las_dos_pantallas_del_asistente_abren(self):
        self.entrar(self.conductor)
        for paso in ('paso3', 'paso4'):
            with self.subTest(paso=paso):
                respuesta = self.client.get(self.url_paso(paso))
                self.assertEqual(respuesta.status_code, 200)

    def test_el_acta_copia_las_instrucciones_del_asesor_no_lo_que_mande_el_conductor(self):
        self.entrar(self.conductor)
        # El conductor intenta colar instrucciones y nombres que no le tocan.
        self.client.post(self.url_paso('paso3'), self.datos_hoja(
            succ_canecas='on', succ_pozos_septicos_cant='999',
            auxiliar1='Quien yo diga',
            nombre_responsable_empresa='Otro nombre'))

        acta = Manifiesto.objects.get(recorrido=self.recorrido)
        self.assertTrue(acta.succ_pozos_septicos, "vino de la programación")
        self.assertEqual(acta.succ_pozos_septicos_cant, '3')
        self.assertFalse(acta.succ_canecas, "el conductor no define el servicio")
        self.assertEqual(acta.auxiliar1, 'Luis Gómez')
        self.assertEqual(acta.nombre_responsable_empresa, 'Carlos Pérez')

    def test_el_cierre_guarda_las_observaciones_y_devuelve_al_conductor_a_su_orden(self):
        self.entrar(self.conductor)
        self.client.post(self.url_paso('paso3'), self.datos_hoja())
        respuesta = self.client.post(self.url_paso('paso4'),
                                     {'observaciones': 'Todo normal'})
        self.assertRedirects(respuesta, reverse('gestion:detalle_orden_conductor',
                                                args=[self.orden.pk]))
        acta = Manifiesto.objects.get(recorrido=self.recorrido)
        self.assertEqual(acta.observaciones, 'Todo normal')
        self.assertEqual(acta.tiempo_inicio_operativo, datetime.time(7, 0),
                         "el cierre no debe perder lo del paso anterior")

    def test_las_novedades_operacionales_se_guardan_y_al_desmarcarlas_se_borran(self):
        self.entrar(self.conductor)
        self.client.post(self.url_paso('paso3'), self.datos_hoja(**{
            'nov-VARADA-marcada': 'on',
            'nov-VARADA-observacion': 'Se pinchó una llanta',
            'nov-VARADA-hora_inicio': '08:00',
            'nov-VARADA-hora_final': '09:00',
        }))
        acta = Manifiesto.objects.get(recorrido=self.recorrido)
        novedad = acta.novedades_operacionales.get()
        self.assertEqual(novedad.tipo, 'VARADA')
        self.assertEqual(novedad.observacion, 'Se pinchó una llanta')
        self.assertEqual(novedad.hora_inicio, datetime.time(8, 0))

        # Volver a guardar sin marcarla la elimina.
        self.client.post(self.url_paso('paso3'), self.datos_hoja())
        self.assertFalse(NovedadOperacional.objects.exists())

    def test_el_control_de_acpm_guarda_la_medida(self):
        self.entrar(self.conductor)
        self.client.post(self.url_paso('paso3'), self.datos_hoja(**{
            'acpm-INICIAL-medida': '1/2 tanque',
        }))
        medida = MedidaACPM.objects.get()
        self.assertEqual(medida.tipo, 'INICIAL')
        self.assertEqual(medida.medida, '1/2 tanque')

    def test_otro_conductor_no_puede_llenar_un_acta_ajena(self):
        intruso = self.persona('conductor2', 'Conductores')
        self.entrar(intruso)
        respuesta = self.client.post(self.url_paso('paso3'), self.datos_hoja())
        self.assertRedirects(respuesta, reverse('gestion:dashboard_redirect'),
                             target_status_code=302)
        self.assertFalse(Manifiesto.objects.exists())

    def test_con_el_acta_firmada_el_conductor_ya_no_entra_al_asistente(self):
        Manifiesto.objects.create(recorrido=self.recorrido, estado_firma='FIRMADO')
        self.entrar(self.conductor)
        respuesta = self.client.get(self.url_paso('paso3'))
        self.assertRedirects(respuesta, reverse('gestion:detalle_orden_conductor',
                                                args=[self.orden.pk]))

    def test_gestion_si_corrige_los_datos_de_un_acta_firmada_sin_desfirmarla(self):
        Manifiesto.objects.create(recorrido=self.recorrido, estado_firma='FIRMADO',
                                  nombre_responsable_cliente='Quien recibió')
        self.entrar(self.asesor)
        self.client.post(self.url_paso('paso3'), self.datos_hoja())
        self.client.post(self.url_paso('paso4'), {'observaciones': 'Corregido'})

        acta = Manifiesto.objects.get(recorrido=self.recorrido)
        self.assertEqual(acta.estado_firma, 'FIRMADO',
                         "corregir datos NUNCA debe desfirmar el acta")
        self.assertEqual(acta.nombre_responsable_cliente, 'Quien recibió')
        self.assertEqual(acta.observaciones, 'Corregido')

    def test_el_qr_crea_el_acta_si_todavia_no_existe(self):
        self.entrar(self.asesor)
        respuesta = self.client.get(reverse('gestion:manifiesto_qr',
                                            args=[self.recorrido.pk]))
        self.assertEqual(respuesta.status_code, 200)
        acta = Manifiesto.objects.get(recorrido=self.recorrido)
        self.assertTrue(acta.succ_pozos_septicos, "nace con lo que definió el asesor")
        self.assertEqual(acta.auxiliar1, 'Luis Gómez')
        self.assertIn(str(acta.token_publico), respuesta.content.decode())

    def test_el_qr_no_duplica_ni_pisa_el_acta_existente(self):
        self.entrar(self.conductor)
        self.client.post(self.url_paso('paso3'), self.datos_hoja())
        acta = Manifiesto.objects.get(recorrido=self.recorrido)

        self.client.get(reverse('gestion:manifiesto_qr', args=[self.recorrido.pk]))

        self.assertEqual(Manifiesto.objects.count(), 1)
        acta.refresh_from_db()
        self.assertEqual(acta.tiempo_inicio_operativo, datetime.time(7, 0))

    def test_el_aviso_de_acta_incompleta_mira_los_tiempos_del_conductor(self):
        acta = Manifiesto.objects.create(recorrido=self.recorrido)
        self.assertFalse(_acta_lista_para_firmar(acta))
        acta.tiempo_inicio_operativo = datetime.time(7, 0)
        acta.save()
        self.assertTrue(_acta_lista_para_firmar(acta))

    def test_el_sondeo_del_estado_del_acta_es_solo_de_quien_la_gestiona(self):
        intruso = self.persona('curioso', 'Conductores')
        self.entrar(intruso)
        respuesta = self.client.get(reverse('gestion:manifiesto_estado',
                                            args=[self.recorrido.pk]))
        self.assertEqual(respuesta.status_code, 403)

        self.entrar(self.conductor)
        respuesta = self.client.get(reverse('gestion:manifiesto_estado',
                                            args=[self.recorrido.pk]))
        self.assertEqual(respuesta.status_code, 200)
        self.assertFalse(respuesta.json()['firmado'])

    def test_el_conductor_no_descarga_el_acta_como_documento(self):
        Manifiesto.objects.create(recorrido=self.recorrido)
        self.entrar(self.conductor)
        self.assertEqual(
            self.client.get(reverse('gestion:acta_formato',
                                    args=[self.recorrido.pk])).status_code, 403)
        self.assertEqual(
            self.client.get(reverse('gestion:acta_pdf',
                                    args=[self.recorrido.pk])).status_code, 403)

    def test_el_acta_en_formato_documento_precarga_lo_del_asesor_sin_guardarla(self):
        self.entrar(self.asesor)
        respuesta = self.client.get(reverse('gestion:acta_formato',
                                            args=[self.recorrido.pk]))
        self.assertEqual(respuesta.status_code, 200)
        self.assertEqual(respuesta.context['estado_acta'], 'PENDIENTE')
        self.assertFalse(Manifiesto.objects.exists(),
                         "previsualizar el acta no debe crearla")


# ============================================================
#  FIRMA DEL CLIENTE (página pública del QR)
# ============================================================
class FirmaDelClienteTests(BaseCRM):
    """El endpoint público: valida la firma, es de un solo uso y no confía en nada."""

    def setUp(self):
        datos = self.servicio_completo()
        self.__dict__.update(datos)
        self.acta = Manifiesto.objects.create(
            recorrido=self.recorrido, tiempo_inicio_operativo=datetime.time(7, 0))
        self.url = reverse('gestion:encuesta_publica', args=[self.acta.token_publico])

    def datos_firma(self, **extra):
        datos = {campo: '4' for campo in (
            'eval_atencion', 'eval_amabilidad', 'eval_solucion_inquietudes',
            'eval_asesoria', 'eval_puntualidad', 'eval_calidad_servicio',
            'eval_oportunidad', 'eval_cumplimiento_condiciones',
            'eval_solucion_problemas', 'eval_volveria_contratar',
            'eval_nos_recomendaria')}
        datos['nombre_responsable_cliente'] = 'María del cliente'
        datos['signature_data'] = firma_data_uri()
        datos.update(extra)
        return datos

    def test_la_pagina_publica_se_abre_sin_iniciar_sesion(self):
        self.assertEqual(self.client.get(self.url).status_code, 200)

    def test_un_token_inventado_no_existe(self):
        import uuid
        self.assertEqual(self.client.get(reverse(
            'gestion:encuesta_publica', args=[uuid.uuid4()])).status_code, 404)

    def test_firmar_marca_el_acta_y_guarda_la_imagen_y_las_calificaciones(self):
        self.client.post(self.url, self.datos_firma())
        self.acta.refresh_from_db()
        self.assertEqual(self.acta.estado_firma, 'FIRMADO')
        self.assertEqual(self.acta.nombre_responsable_cliente, 'María del cliente')
        self.assertTrue(self.acta.firma_cliente.name)
        self.assertEqual(self.acta.eval_atencion, 4)

    def test_el_enlace_es_de_un_solo_uso(self):
        self.client.post(self.url, self.datos_firma())
        respuesta = self.client.post(
            self.url, self.datos_firma(nombre_responsable_cliente='Otro'))
        self.assertContains(respuesta, 'firmad', status_code=200)
        self.acta.refresh_from_db()
        self.assertEqual(self.acta.nombre_responsable_cliente, 'María del cliente',
                         "un acta firmada no se vuelve a firmar")

    def test_una_firma_que_no_es_png_se_rechaza(self):
        basura = 'data:image/svg+xml;base64,' + base64.b64encode(
            b'<svg onload=alert(1)>').decode()
        self.client.post(self.url, self.datos_firma(signature_data=basura))
        self.acta.refresh_from_db()
        self.assertEqual(self.acta.estado_firma, 'PENDIENTE_FIRMA')
        self.assertFalse(self.acta.firma_cliente)

    def test_un_png_falso_con_la_cabecera_equivocada_se_rechaza(self):
        falso = 'data:image/png;base64,' + base64.b64encode(b'no soy un png').decode()
        self.client.post(self.url, self.datos_firma(signature_data=falso))
        self.acta.refresh_from_db()
        self.assertEqual(self.acta.estado_firma, 'PENDIENTE_FIRMA')

    def test_una_firma_enorme_se_rechaza(self):
        gigante = 'data:image/png;base64,' + base64.b64encode(
            b'\x89PNG\r\n\x1a\n' + b'0' * (2 * 1024 * 1024 + 10)).decode()
        self.client.post(self.url, self.datos_firma(signature_data=gigante))
        self.acta.refresh_from_db()
        self.assertEqual(self.acta.estado_firma, 'PENDIENTE_FIRMA')

    def test_sin_nombre_de_quien_recibe_no_se_firma(self):
        self.client.post(self.url, self.datos_firma(nombre_responsable_cliente=''))
        self.acta.refresh_from_db()
        self.assertEqual(self.acta.estado_firma, 'PENDIENTE_FIRMA')

    def test_la_encuesta_de_satisfaccion_se_responde_completa(self):
        datos = self.datos_firma()
        del datos['eval_puntualidad']
        self.client.post(self.url, datos)
        self.acta.refresh_from_db()
        self.assertEqual(self.acta.estado_firma, 'PENDIENTE_FIRMA')

    def test_si_falla_guardar_la_firma_el_acta_no_queda_firmada(self):
        with patch('gestion.views._guardar_firma_cliente',
                   side_effect=OSError('storage caído')):
            with self.assertRaises(OSError):
                self.client.post(self.url, self.datos_firma())
        self.acta.refresh_from_db()
        self.assertEqual(self.acta.estado_firma, 'PENDIENTE_FIRMA',
                         "la firma y el estado van en la misma transacción")


# ============================================================
#  ENCUESTA DE CIERRE DEL CONDUCTOR (PESV)
# ============================================================
class EncuestaDeCierreTests(BaseCRM):
    """Siete preguntas de seguridad vial; cierra el servicio y exige la firma previa."""

    RESPUESTAS_LIMPIAS = {
        'presento_fatiga': 'NO', 'realizo_pausas_activas': 'SI',
        'molestias_fisicas': 'NO', 'tiempos_adecuados': 'SI',
        'cabina_optima': 'SI', 'zonas_seguras_descanso': 'SI',
        'condicion_riesgo': 'NO',
    }

    def setUp(self):
        datos = self.servicio_completo()
        self.__dict__.update(datos)
        self.url = reverse('gestion:encuesta_conductor', args=[self.recorrido.pk])

    def firmar(self):
        return Manifiesto.objects.create(
            recorrido=self.recorrido, estado_firma='FIRMADO')

    def test_sin_acta_firmada_no_se_puede_cerrar_el_servicio(self):
        Manifiesto.objects.create(recorrido=self.recorrido)
        self.entrar(self.conductor)
        respuesta = self.client.post(self.url, self.RESPUESTAS_LIMPIAS)
        self.assertRedirects(respuesta, reverse('gestion:dashboard_redirect'),
                             target_status_code=302)
        self.assertFalse(EncuestaConductor.objects.exists())
        self.recorrido.refresh_from_db()
        self.assertEqual(self.recorrido.estado, 'PROGRAMADO')

    def test_con_el_acta_firmada_la_encuesta_cierra_el_servicio(self):
        self.firmar()
        self.entrar(self.conductor)
        self.client.post(self.url, self.RESPUESTAS_LIMPIAS)
        self.recorrido.refresh_from_db()
        self.orden.refresh_from_db()
        self.assertTrue(EncuestaConductor.objects.exists())
        self.assertEqual(self.recorrido.estado, 'COMPLETADO')
        self.assertEqual(self.orden.estado_orden, 'FINALIZADA')

    def test_reportar_una_condicion_de_riesgo_exige_tipo_y_descripcion(self):
        datos = dict(self.RESPUESTAS_LIMPIAS, condicion_riesgo='SI')
        form = EncuestaConductorForm(datos)
        self.assertFalse(form.is_valid())
        self.assertIn('tipo_incidente', form.errors)
        self.assertIn('descripcion_incidente', form.errors)

        form = EncuestaConductorForm(dict(
            datos, tipo_incidente='FALLA_MECANICA',
            descripcion_incidente='Se varó en la vía'))
        self.assertTrue(form.is_valid(), form.errors)

    def test_sin_condicion_de_riesgo_no_se_guarda_detalle_del_evento(self):
        form = EncuestaConductorForm(dict(
            self.RESPUESTAS_LIMPIAS, tipo_incidente='FALLA_MECANICA',
            descripcion_incidente='algo'))
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data['tipo_incidente'], '')
        self.assertEqual(form.cleaned_data['descripcion_incidente'], '')

    def test_las_siete_preguntas_son_obligatorias(self):
        datos = dict(self.RESPUESTAS_LIMPIAS)
        del datos['cabina_optima']
        form = EncuestaConductorForm(datos)
        self.assertFalse(form.is_valid())
        self.assertIn('cabina_optima', form.errors)

    def test_las_alertas_dependen_de_la_pregunta(self):
        encuesta = EncuestaConductor(recorrido=self.recorrido,
                                     **self.RESPUESTAS_LIMPIAS)
        self.assertFalse(encuesta.tiene_alertas)

        # En fatiga la alerta es responder SÍ...
        encuesta.presento_fatiga = 'SI'
        self.assertTrue(encuesta.tiene_alertas)
        # ...y en las pausas activas, responder NO.
        encuesta.presento_fatiga = 'NO'
        encuesta.realizo_pausas_activas = 'NO'
        self.assertTrue(encuesta.tiene_alertas)

    def test_una_encuesta_vieja_sin_respuestas_muestra_raya(self):
        encuesta = EncuestaConductor(recorrido=self.recorrido)
        respuestas = encuesta.respuestas()
        self.assertEqual(len(respuestas), 7)
        self.assertEqual(respuestas[0]['respuesta'], '—')

    def test_el_conductor_solo_baja_el_pdf_de_sus_recorridos(self):
        self.firmar()
        EncuestaConductor.objects.create(
            recorrido=self.recorrido, **self.RESPUESTAS_LIMPIAS)
        intruso = self.persona('conductor2', 'Conductores')
        self.entrar(intruso)
        self.assertEqual(self.client.get(reverse(
            'gestion:encuesta_conductor_pdf', args=[self.recorrido.pk])).status_code, 404)

    def test_sin_encuesta_no_hay_pdf_que_descargar(self):
        self.entrar(self.asesor)
        self.assertEqual(self.client.get(reverse(
            'gestion:encuesta_conductor_pdf', args=[self.recorrido.pk])).status_code, 404)


# ============================================================
#  ACCESO POR ROL
# ============================================================
class AccesoPorRolTests(BaseCRM):
    """Cada rol ve lo suyo: la autorización va por grupo, no por permisos sueltos."""

    def setUp(self):
        self.admin = self.persona('admin', 'Administradores')
        self.superusuario = self.persona('root', superusuario=True)
        self.asesor = self.persona('asesor', 'Asesores')
        self.conductor = self.persona('conductor', 'Conductores')
        self.talento = self.persona('talento', 'Talento Humano')
        self.planificador = self.persona('plani', 'Planificadores')

    def estado(self, usuario, nombre_url, *args):
        self.entrar(usuario)
        return self.client.get(reverse(nombre_url, args=args)).status_code

    def test_sin_iniciar_sesion_todo_lleva_al_login(self):
        for nombre in ('gestion:lista_ordenes', 'gestion:lista_clientes',
                       'gestion:lista_personal', 'gestion:dashboard',
                       'gestion:centro_correos', 'gestion:lista_vehiculos'):
            with self.subTest(url=nombre):
                respuesta = self.client.get(reverse(nombre))
                self.assertEqual(respuesta.status_code, 302)
                self.assertIn('/login/', respuesta.url)

    def test_las_ordenes_son_de_gestion(self):
        self.assertEqual(self.estado(self.asesor, 'gestion:lista_ordenes'), 200)
        self.assertEqual(self.estado(self.admin, 'gestion:lista_ordenes'), 200)
        self.assertEqual(self.estado(self.superusuario, 'gestion:lista_ordenes'), 200)
        self.assertEqual(self.estado(self.conductor, 'gestion:lista_ordenes'), 403)
        self.assertEqual(self.estado(self.talento, 'gestion:lista_ordenes'), 403)
        self.assertEqual(self.estado(self.planificador, 'gestion:lista_ordenes'), 403)

    def test_clientes_y_vehiculos_son_de_gestion(self):
        self.assertEqual(self.estado(self.asesor, 'gestion:lista_clientes'), 200)
        self.assertEqual(self.estado(self.admin, 'gestion:lista_vehiculos'), 200)
        self.assertEqual(self.estado(self.planificador, 'gestion:lista_clientes'), 403)
        self.assertEqual(self.estado(self.conductor, 'gestion:lista_clientes'), 403)
        self.assertEqual(self.estado(self.talento, 'gestion:lista_vehiculos'), 403)

    def test_el_modulo_de_personal_es_de_gestion_y_de_talento_humano(self):
        self.assertEqual(self.estado(self.talento, 'gestion:lista_personal'), 200)
        self.assertEqual(self.estado(self.asesor, 'gestion:lista_personal'), 200)
        self.assertEqual(self.estado(self.conductor, 'gestion:lista_personal'), 403)
        self.assertEqual(self.estado(self.planificador, 'gestion:lista_personal'), 403)

    def test_talento_humano_tiene_su_casa_en_el_listado_de_personal(self):
        self.entrar(self.talento)
        self.assertRedirects(self.client.get(reverse('gestion:dashboard_redirect')),
                             reverse('gestion:lista_personal'))
        self.assertEqual(self.client.get(reverse('gestion:calendario')).status_code, 403)

    def test_el_conductor_va_a_su_propio_tablero(self):
        self.entrar(self.conductor)
        self.assertRedirects(self.client.get(reverse('gestion:dashboard_redirect')),
                             reverse('gestion:dashboard_conductor'))

    def test_los_reportes_y_los_usuarios_son_solo_de_administradores(self):
        self.assertEqual(self.estado(self.admin, 'gestion:reportes'), 200)
        self.assertEqual(self.estado(self.admin, 'gestion:lista_usuarios'), 200)
        self.assertEqual(self.estado(self.asesor, 'gestion:reportes'), 403)
        self.assertEqual(self.estado(self.asesor, 'gestion:lista_usuarios'), 403)

    def test_el_centro_de_correos_y_los_proveedores_son_de_asesores(self):
        self.assertEqual(self.estado(self.asesor, 'gestion:centro_correos'), 200)
        self.assertEqual(self.estado(self.asesor, 'gestion:lista_dispositores'), 200)
        self.assertEqual(self.estado(self.asesor, 'gestion:lista_proveedores'), 200)
        self.assertEqual(self.estado(self.planificador, 'gestion:centro_correos'), 403)
        self.assertEqual(self.estado(self.conductor, 'gestion:lista_proveedores'), 403)

    def test_mis_recorridos_es_solo_del_conductor(self):
        self.assertEqual(self.estado(self.conductor, 'gestion:mis_recorridos'), 200)
        self.assertEqual(self.estado(self.asesor, 'gestion:mis_recorridos'), 403)

    def test_la_planificacion_es_de_planificadores_y_administradores(self):
        self.assertEqual(self.estado(self.planificador, 'gestion:planificacion'), 200)
        self.assertEqual(self.estado(self.admin, 'gestion:planificacion'), 200)
        self.assertEqual(self.estado(self.asesor, 'gestion:planificacion'), 403)

    def test_las_banderas_del_menu_no_dependen_del_orden_de_los_grupos(self):
        """Un administrador que además es conductor sigue viendo el menú de gestión."""
        self.admin.groups.add(self.grupo('Conductores'))
        self.entrar(self.admin)
        contexto = self.client.get(reverse('gestion:lista_ordenes')).context
        self.assertTrue(contexto['es_administrador'])
        self.assertTrue(contexto['es_asesor'])
        self.assertFalse(contexto['es_conductor'])

    def test_talento_humano_solo_ve_su_modulo_en_el_menu(self):
        self.entrar(self.talento)
        contexto = self.client.get(reverse('gestion:lista_personal')).context
        self.assertTrue(contexto['es_talento_humano'])
        self.assertTrue(contexto['ve_personal'])
        self.assertFalse(contexto['es_asesor'])
        self.assertFalse(contexto['es_administrador'])

    def test_el_calendario_no_le_muestra_al_conductor_recorridos_ajenos(self):
        datos = self.servicio_completo()
        otro = self.persona('conductor9', 'Conductores')
        self.entrar(otro)
        eventos = self.client.get(reverse('gestion:feed_calendario')).json()
        self.assertEqual(eventos, [])

    def test_el_feed_del_calendario_exige_sesion(self):
        respuesta = self.client.get(reverse('gestion:feed_calendario'))
        self.assertEqual(respuesta.status_code, 302)
        self.assertIn('/login/', respuesta.url)


# ============================================================
#  TALENTO HUMANO: LÍMITES DE SU ALCANCE
# ============================================================
class LimitesDeTalentoHumanoTests(BaseCRM):
    """No puede tocar cuentas de gestión ni repartir roles por encima de sí mismo."""

    def setUp(self):
        self.talento = self.persona('talento', 'Talento Humano')
        self.asesor = self.persona('asesor', 'Asesores')
        self.ayudante = self.persona('ayudante', 'Ayudantes')
        self.superusuario = self.persona('root', superusuario=True)
        self.admin = self.persona('admin', 'Administradores')

    def test_no_puede_otorgar_roles_de_gestion(self):
        asignables = set(roles_asignables(self.talento).values_list('name', flat=True))
        self.assertNotIn('Administradores', asignables)
        self.assertNotIn('Asesores', asignables)
        self.assertNotIn('Planificadores', asignables)
        self.assertIn('Conductores', asignables)
        self.assertIn('Ayudantes', asignables)

    def test_gestion_si_puede_otorgar_cualquier_rol(self):
        asignables = set(roles_asignables(self.asesor).values_list('name', flat=True))
        self.assertIn('Administradores', asignables)

    def test_un_post_manipulado_con_rol_de_gestion_no_valida(self):
        from .forms import CrearUsuarioForm
        form = CrearUsuarioForm({
            'username': 'colado', 'first_name': 'Colado', 'last_name': 'Rol',
            'email': 'x@y.co', 'password1': CLAVE, 'password2': CLAVE,
            'grupo': self.grupo('Asesores').pk,
        }, autor=self.talento)
        self.assertFalse(form.is_valid())
        self.assertIn('grupo', form.errors)

    def test_no_edita_la_cuenta_de_un_asesor(self):
        self.entrar(self.talento)
        respuesta = self.client.get(
            reverse('gestion:editar_cuenta_persona', args=[self.asesor.pk]))
        self.assertRedirects(respuesta,
                             reverse('gestion:ficha_persona', args=[self.asesor.pk]))

    def test_si_edita_la_cuenta_de_un_ayudante(self):
        self.entrar(self.talento)
        respuesta = self.client.get(
            reverse('gestion:editar_cuenta_persona', args=[self.ayudante.pk]))
        self.assertEqual(respuesta.status_code, 200)

    def test_no_retira_a_un_asesor(self):
        self.entrar(self.talento)
        self.client.post(reverse('gestion:cambiar_estado_persona', args=[self.asesor.pk]))
        self.asesor.refresh_from_db()
        self.assertTrue(self.asesor.is_active)
        self.assertFalse(PerfilPersona.objects.get(usuario=self.asesor).retirado)

    def test_no_toca_los_documentos_del_expediente_de_gestion(self):
        documento = DocumentoPersonal.objects.create(
            usuario=self.asesor, tipo='CEDULA', archivo=archivo())
        self.entrar(self.talento)
        self.client.post(reverse('gestion:eliminar_documento_personal',
                                 args=[documento.pk]))
        self.assertTrue(DocumentoPersonal.objects.filter(pk=documento.pk).exists())

    def test_no_le_cambia_la_clave_a_un_asesor(self):
        self.entrar(self.talento)
        respuesta = self.client.get(
            reverse('gestion:cambiar_password_persona', args=[self.asesor.pk]))
        self.assertRedirects(respuesta,
                             reverse('gestion:ficha_persona', args=[self.asesor.pk]))

    def test_un_administrador_que_no_es_superusuario_no_toca_al_superusuario(self):
        self.entrar(self.admin)
        respuesta = self.client.get(
            reverse('gestion:editar_cuenta_persona', args=[self.superusuario.pk]))
        self.assertRedirects(
            respuesta, reverse('gestion:ficha_persona', args=[self.superusuario.pk]))


# ============================================================
#  PERSONAL Y EXPEDIENTE DOCUMENTAL
# ============================================================
class PersonalYExpedienteTests(BaseCRM):
    """Seguridad social por vigencia manual, alertas por tipo y estado retirado."""

    def setUp(self):
        self.asesor = self.persona('asesor', 'Asesores')
        self.conductor = self.persona('conductor', 'Conductores', 'Carlos', 'Pérez')

    def test_la_seguridad_social_exige_su_vigencia_al_cargarla(self):
        form = DocumentoPersonalForm(
            {'tipo': 'SEGURIDAD_SOCIAL', 'periodo': '', 'descripcion': '',
             'fecha_vencimiento': ''},
            {'archivo': archivo('ss.pdf')})
        self.assertFalse(form.is_valid())
        self.assertIn('fecha_vencimiento', form.errors)

    def test_otro_documento_no_exige_vigencia_y_pierde_el_periodo(self):
        form = DocumentoPersonalForm(
            {'tipo': 'CEDULA', 'periodo': '2026-08', 'descripcion': '',
             'fecha_vencimiento': ''},
            {'archivo': archivo('cedula.pdf')})
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data['periodo'], '')

    def test_la_alerta_de_la_seguridad_social_es_de_tres_dias(self):
        doc = DocumentoPersonal(tipo='SEGURIDAD_SOCIAL')
        self.assertEqual(doc.dias_alerta, 3)
        self.assertEqual(DocumentoPersonal(tipo='LICENCIA').dias_alerta, 20)

    def test_vigente_vencido_y_por_vencer_se_calculan_con_la_fecha(self):
        hoy = timezone.localdate()
        vigente = DocumentoPersonal(tipo='SEGURIDAD_SOCIAL',
                                    fecha_vencimiento=hoy + datetime.timedelta(days=10))
        por_vencer = DocumentoPersonal(tipo='SEGURIDAD_SOCIAL',
                                       fecha_vencimiento=hoy + datetime.timedelta(days=2))
        vencido = DocumentoPersonal(tipo='SEGURIDAD_SOCIAL',
                                    fecha_vencimiento=hoy - datetime.timedelta(days=1))
        sin_fecha = DocumentoPersonal(tipo='CEDULA')

        self.assertTrue(vigente.vigente)
        self.assertFalse(vigente.por_vencer, "a 10 días la SS todavía no alerta")
        self.assertTrue(por_vencer.por_vencer)
        self.assertTrue(por_vencer.vigente, "por vencer NO es lo mismo que vencida")
        self.assertTrue(vencido.vencido)
        self.assertFalse(vencido.vigente)
        self.assertFalse(sin_fecha.vigente)
        self.assertIsNone(sin_fecha.dias_restantes)

    def test_la_licencia_alerta_a_veinte_dias(self):
        licencia = DocumentoPersonal(
            tipo='LICENCIA',
            fecha_vencimiento=timezone.localdate() + datetime.timedelta(days=15))
        self.assertTrue(licencia.por_vencer)

    def test_la_seguridad_social_vigente_es_la_de_mayor_vencimiento(self):
        hoy = timezone.localdate()
        vieja = DocumentoPersonal.objects.create(
            usuario=self.conductor, tipo='SEGURIDAD_SOCIAL', archivo=archivo(),
            fecha_vencimiento=hoy + datetime.timedelta(days=2))
        nueva = DocumentoPersonal.objects.create(
            usuario=self.conductor, tipo='SEGURIDAD_SOCIAL', archivo=archivo(),
            fecha_vencimiento=hoy + datetime.timedelta(days=40))
        DocumentoPersonal.objects.create(
            usuario=self.conductor, tipo='SEGURIDAD_SOCIAL', archivo=archivo(),
            fecha_vencimiento=hoy - datetime.timedelta(days=5))
        docs = list(self.conductor.documentos_personales.all())
        self.assertEqual(_ss_vigente(docs), nueva)

    def test_sin_ninguna_vigente_no_hay_seguridad_social_al_dia(self):
        DocumentoPersonal.objects.create(
            usuario=self.conductor, tipo='SEGURIDAD_SOCIAL', archivo=archivo(),
            fecha_vencimiento=timezone.localdate() - datetime.timedelta(days=1))
        self.assertIsNone(_ss_vigente(list(self.conductor.documentos_personales.all())))

    def test_un_ayudante_se_registra_sin_acceso_al_sistema(self):
        self.entrar(self.asesor)
        self.client.post(reverse('gestion:crear_persona'), {
            'first_name': 'Luis', 'last_name': 'Gómez', 'email': '',
            'grupo': self.grupo('Ayudantes').pk, 'numero_documento': '1098765432',
        })
        ayudante = User.objects.get(first_name='Luis', last_name='Gómez')
        self.assertFalse(ayudante.is_active)
        self.assertFalse(ayudante.has_usable_password())
        self.assertTrue(ayudante.username, "se le genera un identificador interno")
        self.assertEqual(ayudante.perfil.numero_documento, '1098765432')

    def test_retirar_a_alguien_le_quita_el_acceso_y_lo_saca_de_las_asignaciones(self):
        self.con_ss(self.conductor)
        self.entrar(self.asesor)
        self.client.post(reverse('gestion:cambiar_estado_persona',
                                 args=[self.conductor.pk]))

        self.conductor.refresh_from_db()
        perfil = PerfilPersona.objects.get(usuario=self.conductor)
        self.assertTrue(perfil.retirado)
        self.assertEqual(perfil.fecha_retiro, timezone.localdate())
        self.assertFalse(self.conductor.is_active)

        form = ProgramacionCuadrillaForm(prefix='cuadrilla')
        self.assertNotIn(self.conductor, form.fields['conductor'].queryset)

    def test_reactivar_devuelve_el_acceso_menos_a_los_roles_sin_acceso(self):
        ayudante = self.persona('ayudante', 'Ayudantes')
        self.entrar(self.asesor)
        url_conductor = reverse('gestion:cambiar_estado_persona', args=[self.conductor.pk])
        url_ayudante = reverse('gestion:cambiar_estado_persona', args=[ayudante.pk])

        self.client.post(url_conductor)   # retira
        self.client.post(url_conductor)   # reactiva
        self.client.post(url_ayudante)
        self.client.post(url_ayudante)

        self.conductor.refresh_from_db()
        ayudante.refresh_from_db()
        self.assertTrue(self.conductor.is_active)
        self.assertFalse(ayudante.is_active, "un ayudante reactivado sigue sin acceso")
        self.assertFalse(PerfilPersona.objects.get(usuario=ayudante).retirado)

    def test_el_expediente_avisa_lo_que_le_falta_a_cada_rol(self):
        self.entrar(self.asesor)
        contexto = self.client.get(
            reverse('gestion:ficha_persona', args=[self.conductor.pk])).context
        faltan = contexto['faltan_requeridos']
        self.assertIn('Seguridad social vigente', faltan)
        self.assertIn('Cédula de ciudadanía', faltan)
        self.assertIn('Licencia de conducción', faltan)
        self.assertFalse(contexto['ss_al_dia'])

    def test_con_la_documentacion_al_dia_no_falta_nada(self):
        self.con_ss(self.conductor)
        for tipo in ('CEDULA', 'LICENCIA'):
            DocumentoPersonal.objects.create(
                usuario=self.conductor, tipo=tipo, archivo=archivo())
        self.entrar(self.asesor)
        contexto = self.client.get(
            reverse('gestion:ficha_persona', args=[self.conductor.pk])).context
        self.assertEqual(contexto['faltan_requeridos'], [])
        self.assertTrue(contexto['ss_al_dia'])

    def test_la_vigencia_se_puede_fijar_y_quitar_desde_la_ficha(self):
        documento = DocumentoPersonal.objects.create(
            usuario=self.conductor, tipo='LICENCIA', archivo=archivo())
        self.entrar(self.asesor)
        url = reverse('gestion:vigencia_documento_personal', args=[documento.pk])

        self.client.post(url, {'fecha_vencimiento': '2030-12-31'})
        documento.refresh_from_db()
        self.assertEqual(documento.fecha_vencimiento, datetime.date(2030, 12, 31))

        self.client.post(url, {'fecha_vencimiento': 'no es fecha'})
        documento.refresh_from_db()
        self.assertEqual(documento.fecha_vencimiento, datetime.date(2030, 12, 31))

        self.client.post(url, {'fecha_vencimiento': ''})
        documento.refresh_from_db()
        self.assertIsNone(documento.fecha_vencimiento)

    def test_el_listado_de_personal_filtra_y_deja_los_retirados_al_final(self):
        retirado = self.persona('retirado', 'Conductores', 'Zoe', 'Retirada')
        PerfilPersona.objects.filter(usuario=retirado).update(retirado=True)
        self.persona('root', superusuario=True)
        self.entrar(self.asesor)

        usuarios = list(self.client.get(reverse('gestion:lista_personal')).context['usuarios'])
        self.assertNotIn('root', [u.username for u in usuarios],
                         "los superadministradores no son personal operativo")
        self.assertEqual(usuarios[-1].username, 'retirado')

        solo_retirados = self.client.get(
            reverse('gestion:lista_personal'), {'estado': 'retirado'}).context['usuarios']
        self.assertEqual([u.username for u in solo_retirados], ['retirado'])

        por_rol = self.client.get(
            reverse('gestion:lista_personal'), {'rol': 'Asesores'}).context['usuarios']
        self.assertEqual([u.username for u in por_rol], ['asesor'])

        por_nombre = self.client.get(
            reverse('gestion:lista_personal'), {'q': 'Pérez'}).context['usuarios']
        self.assertEqual([u.username for u in por_nombre], ['conductor'])


# ============================================================
#  FORMULARIO DE PROGRAMACIÓN: LO QUE NO DEJA PASAR
# ============================================================
class ValidacionesDeProgramacionTests(BaseCRM):
    """Sede/tercero, báscula, disposición final y cuadrilla."""

    def setUp(self):
        self.cli = self.cliente()
        self.camion = self.vehiculo()
        self.conductor = self.persona('conductor', 'Conductores')
        self.con_ss(self.conductor)

    def datos(self, **extra):
        datos = {
            'fecha': timezone.localdate().isoformat(),
            'cliente': self.cli.pk,
            'hora_ingreso_bodega': '', 'sitio_inicio': '', 'hora_servicio': '',
            'sede_cliente': '', 'tercero': '', 'direccion': '',
            'observaciones_servicio': '', 'paleada': '', 'bascula': '',
            'bascula_sitio': '', 'registro_fotografico': '', 'responsable_sg': '',
            'requiere_disposicion_final': '', 'dispositor_final': '',
            'destino_sin_disposicion': '', 'trasiego_vehiculo': '',
            'nombre_contacto_recibe': '',
        }
        datos.update(extra)
        return datos

    def test_lo_minimo_es_la_fecha_y_el_cliente(self):
        self.assertTrue(ProgramacionForm(self.datos()).is_valid())
        form = ProgramacionForm(self.datos(cliente=''))
        self.assertFalse(form.is_valid())
        self.assertIn('cliente', form.errors)

    def test_una_sede_de_otro_cliente_no_pasa(self):
        otro = self.cliente('Otro cliente', identificacion='800-1')
        sede = Sede.objects.create(cliente=otro, nombre='Sede ajena')
        form = ProgramacionForm(self.datos(sede_cliente=sede.pk))
        self.assertFalse(form.is_valid())
        self.assertIn('sede_cliente', form.errors)

    def test_si_el_cliente_tiene_sedes_hay_que_elegir_una(self):
        Sede.objects.create(cliente=self.cli, nombre='Sede Norte')
        form = ProgramacionForm(self.datos())
        self.assertFalse(form.is_valid())
        self.assertIn('sede_cliente', form.errors)

    def test_el_tercero_reemplaza_a_la_sede_pero_no_conviven(self):
        sede = Sede.objects.create(cliente=self.cli, nombre='Sede Norte')
        tercero = Tercero.objects.create(cliente=self.cli, nombre='Acopio Sur')

        # Solo el tercero: válido aunque el cliente tenga sedes.
        self.assertTrue(ProgramacionForm(self.datos(tercero=tercero.pk)).is_valid())

        form = ProgramacionForm(self.datos(sede_cliente=sede.pk, tercero=tercero.pk))
        self.assertFalse(form.is_valid())
        self.assertIn('tercero', form.errors)

    def test_los_desplegables_dependientes_siguen_al_cliente_del_post(self):
        """
        Regresión: al editar una programación y CAMBIAR de cliente, la sede del
        cliente nuevo se rechazaba como si no se hubiera elegido.
        """
        otro = self.cliente('Cliente nuevo', identificacion='800-2')
        sede_nueva = Sede.objects.create(cliente=otro, nombre='Sede del nuevo')
        programacion = Programacion.objects.create(
            cliente=self.cli, fecha=timezone.localdate())

        form = ProgramacionForm(
            self.datos(cliente=otro.pk, sede_cliente=sede_nueva.pk),
            instance=programacion)
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data['sede_cliente'], sede_nueva)

    def test_pesar_en_bascula_obliga_a_decir_en_cual(self):
        form = ProgramacionForm(self.datos(bascula='PESAN'))
        self.assertFalse(form.is_valid())
        self.assertIn('bascula_sitio', form.errors)

        bascula = Bascula.objects.create(nombre='Báscula Centro')
        form = ProgramacionForm(self.datos(bascula='PESAN', bascula_sitio=bascula.pk))
        self.assertTrue(form.is_valid(), form.errors)

    def test_la_bascula_del_cliente_no_pide_sitio_y_lo_limpia(self):
        bascula = Bascula.objects.create(nombre='Báscula Centro')
        form = ProgramacionForm(
            self.datos(bascula='PESO_CLIENTE', bascula_sitio=bascula.pk))
        self.assertTrue(form.is_valid(), form.errors)
        self.assertIsNone(form.cleaned_data['bascula_sitio'])

    def test_la_disposicion_si_exige_proveedor_externo(self):
        form = ProgramacionForm(self.datos(requiere_disposicion_final='SI'))
        self.assertFalse(form.is_valid())
        self.assertIn('dispositor_final', form.errors)

        proveedor = Dispositor.objects.create(nombre='Gestor Ambiental S.A.')
        form = ProgramacionForm(self.datos(
            requiere_disposicion_final='SI', dispositor_final=proveedor.pk))
        self.assertTrue(form.is_valid(), form.errors)

    def test_un_destino_interno_no_sirve_como_proveedor_de_disposicion(self):
        interno = Dispositor.objects.create(
            nombre=Dispositor.DEJAR_CARRO_CARGADO, tipo='INTERNO')
        form = ProgramacionForm(self.datos(
            requiere_disposicion_final='SI', dispositor_final=interno.pk))
        self.assertFalse(form.is_valid())
        self.assertIn('dispositor_final', form.errors)

    def test_la_disposicion_no_exige_decir_donde_queda_el_contenido(self):
        form = ProgramacionForm(self.datos(requiere_disposicion_final='NO'))
        self.assertFalse(form.is_valid())
        self.assertIn('destino_sin_disposicion', form.errors)

        interno = Dispositor.objects.create(
            nombre=Dispositor.DEJAR_CARRO_CARGADO, tipo='INTERNO')
        form = ProgramacionForm(self.datos(
            requiere_disposicion_final='NO', destino_sin_disposicion=interno.pk))
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data['dispositor_final'], interno)

    def test_el_trasiego_a_placa_exige_la_placa_destino(self):
        interno = Dispositor.objects.create(
            nombre=Dispositor.TRASIEGO_PLACA, tipo='INTERNO')
        form = ProgramacionForm(self.datos(
            requiere_disposicion_final='NO', destino_sin_disposicion=interno.pk))
        self.assertFalse(form.is_valid())
        self.assertIn('trasiego_vehiculo', form.errors)

        receptor = self.vehiculo('ABC987')
        form = ProgramacionForm(self.datos(
            requiere_disposicion_final='NO', destino_sin_disposicion=interno.pk,
            trasiego_vehiculo=receptor.pk))
        self.assertTrue(form.is_valid(), form.errors)

    def test_los_interruptores_de_cursos_se_guardan_como_si_o_no(self):
        form = ProgramacionForm(self.datos(exige_curso_alturas='on'))
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data['exige_curso_alturas'], 'SI')
        self.assertEqual(form.cleaned_data['exige_curso_confinados'], 'NO')

    def test_la_cuadrilla_exige_conductor_y_placa(self):
        form = ProgramacionCuadrillaForm({}, prefix='cuadrilla')
        self.assertFalse(form.is_valid())
        self.assertIn('conductor', form.errors)
        self.assertIn('vehiculo', form.errors)

    def test_el_mismo_ayudante_no_va_dos_veces_en_la_cuadrilla(self):
        ayudante = self.persona('ayudante', 'Ayudantes')
        form = ProgramacionCuadrillaForm({
            'cuadrilla-conductor': self.conductor.pk,
            'cuadrilla-vehiculo': self.camion.pk,
            'cuadrilla-ayudante': ayudante.pk,
            'cuadrilla-ayudante2': ayudante.pk,
        }, prefix='cuadrilla')
        self.assertFalse(form.is_valid())
        self.assertIn('ayudante2', form.errors)

    def test_apoyar_una_disposicion_exige_decir_de_cual_placa(self):
        ayudante = self.persona('ayudante', 'Ayudantes')
        base = {
            'cuadrilla-conductor': self.conductor.pk,
            'cuadrilla-vehiculo': self.camion.pk,
            'cuadrilla-ayudante': ayudante.pk,
            'cuadrilla-ayudante_novedad': [ProgramacionCuadrilla.APOYA_DISPOSICION],
        }
        form = ProgramacionCuadrillaForm(base, prefix='cuadrilla')
        self.assertFalse(form.is_valid())
        self.assertIn('apoya_disposicion_vehiculo', form.errors)

    def test_las_novedades_se_guardan_como_lista_separada_por_comas(self):
        ayudante = self.persona('ayudante', 'Ayudantes')
        programacion = Programacion.objects.create(
            cliente=self.cli, fecha=timezone.localdate())
        form = ProgramacionCuadrillaForm({
            'cuadrilla-conductor': self.conductor.pk,
            'cuadrilla-vehiculo': self.camion.pk,
            'cuadrilla-ayudante': ayudante.pk,
            'cuadrilla-ayudante_novedad': ['INICIA_CLIENTE', 'RETORNA_BODEGA'],
        }, prefix='cuadrilla')
        self.assertTrue(form.is_valid(), form.errors)
        cuadrilla = form.save(commit=False)
        cuadrilla.programacion = programacion
        cuadrilla.save()
        self.assertEqual(cuadrilla.ayudante_novedad, 'INICIA_CLIENTE,RETORNA_BODEGA')
        self.assertEqual(cuadrilla.novedades_de(1), ['INICIA_CLIENTE', 'RETORNA_BODEGA'])
        self.assertEqual([f['codigo'] for f in cuadrilla.fotos_pedidas(1)],
                         ['INICIA_CLIENTE'], "solo esa novedad exige foto")

    def test_sin_ayudante_no_quedan_novedades_colgando(self):
        form = ProgramacionCuadrillaForm({
            'cuadrilla-conductor': self.conductor.pk,
            'cuadrilla-vehiculo': self.camion.pk,
            'cuadrilla-ayudante_novedad': ['INICIA_CLIENTE'],
        }, prefix='cuadrilla')
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data['ayudante_novedad'], [])

    def test_los_vehiculos_fuera_de_servicio_no_se_pueden_asignar(self):
        taller = self.vehiculo('TAL999', estado='MANTENIMIENTO')
        form = ProgramacionCuadrillaForm(prefix='cuadrilla')
        self.assertNotIn(taller, form.fields['vehiculo'].queryset)


# ============================================================
#  NOVEDADES DEL AYUDANTE Y SERVICIO SIN AYUDANTE (pedido de la clienta)
# ============================================================
class SinAyudanteYNovedadesTests(BaseCRM):
    """
    Dos cosas que faltaban en el formato: dejar constancia de que el conductor
    va solo, y la evidencia del ingreso tarde a bodega cuando la demora fue del
    conductor.
    """

    def setUp(self):
        self.cli = self.cliente()
        self.camion = self.vehiculo()
        self.conductor = self.persona('conductor', 'Conductores', 'Carlos', 'Pérez')
        self.con_ss(self.conductor)
        self.ayudante = self.persona('ayudante', 'Ayudantes', 'Luis', 'Gómez')
        self.asesor = self.persona('asesor', 'Asesores')

    def cuadrilla(self, **extra):
        datos = {'cuadrilla-conductor': self.conductor.pk,
                 'cuadrilla-vehiculo': self.camion.pk}
        datos.update(extra)
        return ProgramacionCuadrillaForm(datos, prefix='cuadrilla')

    # ---------- El conductor va solo ----------

    def test_se_puede_dejar_constancia_de_que_el_conductor_va_solo(self):
        form = self.cuadrilla(**{'cuadrilla-conductor_solo': 'on'})
        self.assertTrue(form.is_valid(), form.errors)
        self.assertTrue(form.cleaned_data['conductor_solo'])

    def test_va_solo_y_con_ayudante_se_contradicen(self):
        form = self.cuadrilla(**{'cuadrilla-conductor_solo': 'on',
                                 'cuadrilla-ayudante': self.ayudante.pk})
        self.assertFalse(form.is_valid())
        self.assertIn('conductor_solo', form.errors)

    def test_dejar_el_ayudante_vacio_sin_marcar_nada_sigue_valiendo(self):
        """No se obliga a marcarlo: la casilla informa, no estorba."""
        form = self.cuadrilla()
        self.assertTrue(form.is_valid(), form.errors)
        self.assertFalse(form.cleaned_data['conductor_solo'])

    def test_el_expediente_de_la_orden_dice_que_va_solo(self):
        programacion = Programacion.objects.create(
            cliente=self.cli, fecha=timezone.localdate())
        ProgramacionCuadrilla.objects.create(
            programacion=programacion, conductor=self.conductor,
            vehiculo=self.camion, conductor_solo=True)
        orden = programacion.convertir_en_orden(self.asesor)
        recorrido = orden.recorridos.get()

        self.assertTrue(recorrido.va_sin_ayudante)
        self.entrar(self.asesor)
        self.assertContains(
            self.client.get(reverse('gestion:detalle_orden', args=[orden.pk])),
            'El conductor va solo')

    def test_un_servicio_con_ayudante_no_dice_que_va_solo(self):
        programacion = Programacion.objects.create(
            cliente=self.cli, fecha=timezone.localdate())
        ProgramacionCuadrilla.objects.create(
            programacion=programacion, conductor=self.conductor,
            vehiculo=self.camion, ayudante=self.ayudante)
        recorrido = programacion.convertir_en_orden(self.asesor).recorridos.get()
        self.assertFalse(recorrido.va_sin_ayudante)

    def test_sin_ayudante_y_sin_marcar_no_afirma_nada(self):
        programacion = Programacion.objects.create(
            cliente=self.cli, fecha=timezone.localdate())
        ProgramacionCuadrilla.objects.create(
            programacion=programacion, conductor=self.conductor,
            vehiculo=self.camion)
        recorrido = programacion.convertir_en_orden(self.asesor).recorridos.get()
        self.assertFalse(recorrido.va_sin_ayudante,
                         "vacío no es lo mismo que «va solo»")

    # ---------- Ingreso tarde a bodega ----------

    def test_el_ingreso_tarde_a_bodega_es_una_novedad_que_pide_foto(self):
        self.assertIn('INICIA_BODEGA_TARDE',
                      dict(ProgramacionCuadrilla.NOVEDAD_CHOICES))
        self.assertIn('INICIA_BODEGA_TARDE',
                      ProgramacionCuadrilla.NOVEDADES_CON_FOTO)

    def test_iniciar_en_bodega_normal_sigue_sin_pedir_foto(self):
        self.assertNotIn('INICIA_BODEGA', ProgramacionCuadrilla.NOVEDADES_CON_FOTO)

    def test_al_marcarla_se_le_pide_la_foto_al_ayudante(self):
        programacion = Programacion.objects.create(
            cliente=self.cli, fecha=timezone.localdate())
        cuadrilla = ProgramacionCuadrilla.objects.create(
            programacion=programacion, conductor=self.conductor,
            vehiculo=self.camion, ayudante=self.ayudante,
            ayudante_novedad='INICIA_BODEGA,INICIA_BODEGA_TARDE')
        pedidas = {f['codigo'] for f in cuadrilla.fotos_pedidas(1)}
        self.assertEqual(pedidas, {'INICIA_BODEGA_TARDE'},
                         "solo el ingreso tarde exige evidencia")

    def test_el_ayudante_la_ve_y_sube_su_evidencia_desde_su_enlace(self):
        programacion = Programacion.objects.create(
            cliente=self.cli, fecha=timezone.localdate())
        cuadrilla = ProgramacionCuadrilla.objects.create(
            programacion=programacion, conductor=self.conductor,
            vehiculo=self.camion, ayudante=self.ayudante,
            ayudante_novedad='INICIA_BODEGA_TARDE')
        url = reverse('gestion:acceso_ayudante', args=[cuadrilla.token_ayudante])

        respuesta = self.client.get(url)
        self.assertContains(respuesta, 'Ingresa tarde a bodega')

        self.client.post(url, {'novedad': 'INICIA_BODEGA_TARDE',
                               'fotos': [imagen('llegada.png')]})
        foto = FotoAyudante.objects.get()
        self.assertEqual(foto.novedad, 'INICIA_BODEGA_TARDE')
        self.assertEqual(foto.persona, self.ayudante)


# ============================================================
#  CREAR LA PROGRAMACIÓN (crear = generar la orden)
# ============================================================
class CrearProgramacionTests(BaseCRM):
    """La vista: todo o nada, exige documentación al día y avisa por correo."""

    def setUp(self):
        self.asesor = self.persona('asesor', 'Asesores')
        self.cli = self.cliente()
        self.camion = self.vehiculo()
        self.conductor = self.persona('conductor', 'Conductores', 'Carlos', 'Pérez')
        self.con_ss(self.conductor)
        self.entrar(self.asesor)

    def datos(self, **extra):
        datos = {
            'fecha': timezone.localdate().isoformat(), 'cliente': self.cli.pk,
            'hora_ingreso_bodega': '06:00', 'sitio_inicio': '', 'hora_servicio': '08:00',
            'sede_cliente': '', 'tercero': '', 'direccion': 'Calle 100 # 20-30',
            'observaciones_servicio': 'Succión de pozo', 'paleada': '',
            'bascula': '', 'bascula_sitio': '', 'registro_fotografico': '',
            'responsable_sg': '', 'requiere_disposicion_final': '',
            'dispositor_final': '', 'destino_sin_disposicion': '',
            'trasiego_vehiculo': '', 'nombre_contacto_recibe': 'Quien recibe',
            'cuadrilla-conductor': self.conductor.pk,
            'cuadrilla-vehiculo': self.camion.pk,
            'cuadrilla-ayudante': '', 'cuadrilla-ayudante2': '',
        }
        datos.update(extra)
        return datos

    def test_crear_la_programacion_genera_la_orden_y_su_recorrido(self):
        respuesta = self.client.post(reverse('gestion:crear_programacion'), self.datos())
        orden = OrdenServicio.objects.get()
        self.assertRedirects(respuesta, reverse('gestion:detalle_orden', args=[orden.pk]))
        self.assertEqual(orden.numero_orden, OrdenServicio.NUMERO_INICIAL)
        self.assertEqual(orden.recorridos.count(), 1)
        self.assertEqual(orden.direccion_servicio, 'Calle 100 # 20-30')
        self.assertEqual(Programacion.objects.get().estado, 'CONVERTIDA')

    def test_avisa_por_correo_al_conductor_sin_contarle_quien_es_el_cliente(self):
        mail.outbox.clear()
        self.client.post(reverse('gestion:crear_programacion'), self.datos())
        self.assertEqual(len(mail.outbox), 1)
        correo = mail.outbox[0]
        self.assertEqual(correo.to, [self.conductor.email])
        cuerpo = correo.body + ' '.join(str(a) for a, _ in correo.alternatives)
        self.assertNotIn(self.cli.nombre, cuerpo)
        self.assertNotIn(self.cli.nombre, correo.subject)
        self.assertIn('Calle 100 # 20-30', cuerpo)

    def test_el_interruptor_sin_correos_crea_todo_pero_no_avisa(self):
        mail.outbox.clear()
        self.client.post(reverse('gestion:crear_programacion'),
                         self.datos(sin_correos='on'))
        self.assertTrue(OrdenServicio.objects.exists())
        self.assertEqual(len(mail.outbox), 0)

    def test_un_conductor_sin_seguridad_social_vigente_no_se_puede_programar(self):
        self.conductor.documentos_personales.all().delete()
        respuesta = self.client.post(reverse('gestion:crear_programacion'), self.datos())
        self.assertEqual(respuesta.status_code, 200)
        self.assertFalse(Programacion.objects.exists())
        self.assertFalse(OrdenServicio.objects.exists())
        self.assertIn('seguridad social',
                      str(respuesta.context['cuadrilla_form'].errors).lower())

    def test_un_ayudante_sin_el_curso_exigido_no_se_puede_programar(self):
        ayudante = self.persona('ayudante', 'Ayudantes', 'Luis', 'Gómez')
        self.con_ss(ayudante)
        respuesta = self.client.post(reverse('gestion:crear_programacion'), self.datos(
            **{'cuadrilla-ayudante': ayudante.pk, 'exige_curso_alturas': 'on'}))
        self.assertEqual(respuesta.status_code, 200)
        self.assertFalse(OrdenServicio.objects.exists())
        self.assertIn('curso de alturas',
                      str(respuesta.context['cuadrilla_form'].errors))

    def test_si_falla_la_generacion_de_la_orden_no_queda_nada_a_medias(self):
        from django.db import IntegrityError
        with patch.object(Programacion, 'convertir_en_orden',
                          side_effect=IntegrityError('choque de número')):
            respuesta = self.client.post(reverse('gestion:crear_programacion'),
                                         self.datos())
        self.assertEqual(respuesta.status_code, 200)
        self.assertFalse(Programacion.objects.exists(),
                         "no puede quedar una programación en borrador sin orden")
        self.assertFalse(ProgramacionCuadrilla.objects.exists())
        self.assertFalse(OrdenServicio.objects.exists())

    def test_una_programacion_ya_convertida_no_se_edita_directamente(self):
        self.client.post(reverse('gestion:crear_programacion'), self.datos())
        programacion = Programacion.objects.get()
        respuesta = self.client.get(
            reverse('gestion:actualizar_programacion', args=[programacion.pk]))
        self.assertRedirects(respuesta, reverse('gestion:detalle_orden',
                                                args=[programacion.orden_id]))

    def test_una_programacion_con_orden_no_se_cancela(self):
        self.client.post(reverse('gestion:crear_programacion'), self.datos())
        programacion = Programacion.objects.get()
        self.client.post(reverse('gestion:cancelar_programacion', args=[programacion.pk]))
        programacion.refresh_from_db()
        self.assertEqual(programacion.estado, 'CONVERTIDA')

    def test_el_conductor_no_programa(self):
        self.entrar(self.conductor)
        respuesta = self.client.post(reverse('gestion:crear_programacion'), self.datos())
        self.assertEqual(respuesta.status_code, 403)
        self.assertFalse(Programacion.objects.exists())


# ============================================================
#  CORREGIR LA ORDEN Y SUS RECORRIDOS
# ============================================================
class EdicionDeOrdenesTests(BaseCRM):
    """En la app se EDITA, no se borra; y no se añaden recorridos."""

    def setUp(self):
        datos = self.servicio_completo()
        self.__dict__.update(datos)
        self.entrar(self.asesor)

    def test_editar_la_orden_abre_el_formulario_completo_de_la_programacion(self):
        respuesta = self.client.get(reverse('gestion:actualizar_orden',
                                            args=[self.orden.pk]))
        self.assertEqual(respuesta.status_code, 200)
        self.assertEqual(respuesta.context['object'], self.programacion)
        self.assertEqual(respuesta.context['desde_orden'], self.orden)

    def test_lo_corregido_en_la_programacion_baja_a_la_orden_y_al_recorrido(self):
        otro_cliente = self.cliente('Cliente corregido', identificacion='800-9')
        otro_camion = self.vehiculo('NUE111')
        otro_conductor = self.persona('conductor2', 'Conductores', 'Diana', 'Lopez')
        self.con_ss(otro_conductor)
        nueva_fecha = timezone.localdate() + datetime.timedelta(days=3)

        self.client.post(reverse('gestion:actualizar_orden', args=[self.orden.pk]), {
            'fecha': nueva_fecha.isoformat(), 'cliente': otro_cliente.pk,
            'hora_ingreso_bodega': '', 'sitio_inicio': '', 'hora_servicio': '',
            'sede_cliente': '', 'tercero': '', 'direccion': 'Nueva dirección 45',
            'observaciones_servicio': '', 'paleada': '', 'bascula': 'PESO_CLIENTE',
            'bascula_sitio': '', 'registro_fotografico': 'SI', 'responsable_sg': '',
            'requiere_disposicion_final': '', 'dispositor_final': '',
            'destino_sin_disposicion': '', 'trasiego_vehiculo': '',
            'nombre_contacto_recibe': '',
            'cuadrilla-conductor': otro_conductor.pk,
            'cuadrilla-vehiculo': otro_camion.pk,
            'cuadrilla-ayudante': '', 'cuadrilla-ayudante2': '',
        })

        self.orden.refresh_from_db()
        recorrido = self.orden.recorridos.get()
        self.assertEqual(self.orden.cliente, otro_cliente)
        self.assertEqual(self.orden.direccion_servicio, 'Nueva dirección 45')
        self.assertEqual(self.orden.bascula, 'PESO_CLIENTE')
        self.assertEqual(self.orden.registro_fotografico, 'SI')
        self.assertEqual(recorrido.vehiculo, otro_camion)
        self.assertEqual(recorrido.conductor, otro_conductor)
        self.assertEqual(recorrido.fecha_recorrido, nueva_fecha)

    def test_no_se_puede_quitar_el_unico_recorrido_de_la_orden(self):
        self.client.post(reverse('gestion:eliminar_recorrido', args=[self.recorrido.pk]))
        self.assertTrue(Recorrido.objects.filter(pk=self.recorrido.pk).exists())

    def test_un_recorrido_con_acta_firmada_no_se_puede_quitar(self):
        otro = Recorrido.objects.create(
            orden=self.orden, vehiculo=self.vehiculo('OTR456'),
            conductor=self.conductor, fecha_recorrido=timezone.localdate())
        Manifiesto.objects.create(recorrido=self.recorrido, estado_firma='FIRMADO')

        self.client.post(reverse('gestion:eliminar_recorrido', args=[self.recorrido.pk]))
        self.assertTrue(Recorrido.objects.filter(pk=self.recorrido.pk).exists())

        # El que no tiene firma sí se puede quitar.
        self.client.post(reverse('gestion:eliminar_recorrido', args=[otro.pk]))
        self.assertFalse(Recorrido.objects.filter(pk=otro.pk).exists())

    def test_quitar_un_recorrido_recalcula_el_estado_de_la_orden(self):
        otro = Recorrido.objects.create(
            orden=self.orden, vehiculo=self.vehiculo('OTR456'),
            conductor=self.conductor, fecha_recorrido=timezone.localdate())
        self.recorrido.estado = 'COMPLETADO'
        self.recorrido.save()
        self.orden.refresh_from_db()
        self.assertEqual(self.orden.estado_orden, 'EN_EJECUCION')

        self.client.post(reverse('gestion:eliminar_recorrido', args=[otro.pk]))
        self.orden.refresh_from_db()
        self.assertEqual(self.orden.estado_orden, 'FINALIZADA')

    def test_editar_un_recorrido_cambia_la_placa_y_el_conductor(self):
        nuevo_camion = self.vehiculo('NUE111')
        otro_conductor = self.persona('conductor2', 'Conductores')
        self.client.post(reverse('gestion:editar_recorrido', args=[self.recorrido.pk]), {
            'vehiculo': nuevo_camion.pk, 'conductor': otro_conductor.pk,
            'ayudante': '', 'ayudante2': '',
            'fecha_recorrido': timezone.localdate().isoformat(),
            'estado': 'PROGRAMADO', 'descripcion': '',
        })
        self.recorrido.refresh_from_db()
        self.assertEqual(self.recorrido.vehiculo, nuevo_camion)
        self.assertEqual(self.recorrido.conductor, otro_conductor)

    def test_borrar_la_orden_desde_el_admin_arrastra_todo_lo_que_cuelga(self):
        Manifiesto.objects.create(recorrido=self.recorrido)
        Pago.objects.create(orden=self.orden, monto=Decimal('100.00'))
        DocumentoOrden.objects.create(orden=self.orden, archivo=archivo())

        self.orden.delete()

        self.assertFalse(Recorrido.objects.exists())
        self.assertFalse(Manifiesto.objects.exists())
        self.assertFalse(Pago.objects.exists())
        self.assertFalse(DocumentoOrden.objects.exists())
        self.assertFalse(Programacion.objects.exists(),
                         "la programación que la originó también cae (CASCADE)")


# ============================================================
#  RENUMERAR ÓRDENES (el consecutivo no admite huecos ni repetidos)
# ============================================================
class RenumeracionTests(BaseCRM):

    def setUp(self):
        self.asesor = self.persona('asesor', 'Asesores')
        self.admin = self.persona('admin', 'Administradores')
        self.cli = self.cliente()
        self.ordenes = [self._orden() for _ in range(3)]   # 22207, 22208, 22209

    def _orden(self):
        return OrdenServicio.objects.create(
            cliente=self.cli, asesor=self.asesor,
            direccion_servicio='x', descripcion='y')

    def numeros(self):
        return list(OrdenServicio.objects.order_by('pk').values_list('pk', flat=True))

    def test_si_el_numero_destino_esta_libre_es_un_solo_movimiento(self):
        self.assertEqual(plan_reubicacion(22207, 30000), [(22207, 30000)])

    def test_bajar_una_orden_empuja_a_las_de_abajo_hacia_arriba(self):
        reubicar_orden(22209, 22207)
        self.assertEqual(self.numeros(), [22207, 22208, 22209])
        self.assertEqual(OrdenServicio.objects.get(pk=22207).pk, 22207)
        # La que estaba en 22207 quedó en 22208 y la de 22208 en 22209.
        self.ordenes[0].refresh_from_db()
        self.assertEqual(
            OrdenServicio.objects.get(pk=22209).fecha_creacion.date(),
            self.ordenes[1].fecha_creacion.date())

    def test_subir_una_orden_empuja_a_las_de_arriba_hacia_abajo(self):
        primera = self.ordenes[0]
        Recorrido.objects.create(orden=primera, vehiculo=self.vehiculo(),
                                 fecha_recorrido=timezone.localdate())
        reubicar_orden(22207, 22209)
        self.assertEqual(self.numeros(), [22207, 22208, 22209])
        # Los hijos viajan con su orden.
        self.assertEqual(Recorrido.objects.get().orden_id, 22209)

    def test_renumerar_arrastra_recorridos_pagos_documentos_y_programacion(self):
        conductor = self.persona('conductor', 'Conductores')
        self.con_ss(conductor)
        programacion = self.programacion(cliente=self.cli, conductor=conductor,
                                         vehiculo=self.vehiculo('MUD001'))
        orden = programacion.convertir_en_orden(self.asesor)
        Pago.objects.create(orden=orden, monto=Decimal('50.00'))
        DocumentoOrden.objects.create(orden=orden, archivo=archivo())
        creada = orden.fecha_creacion

        reubicar_orden(orden.pk, 40000)

        movida = OrdenServicio.objects.get(pk=40000)
        self.assertEqual(movida.recorridos.count(), 1)
        self.assertEqual(movida.pagos.count(), 1)
        self.assertEqual(movida.documentos.count(), 1)
        self.assertEqual(movida.programacion_origen.pk, programacion.pk)
        self.assertEqual(movida.fecha_creacion, creada,
                         "la fecha de creación no se puede reescribir al mover")
        self.assertFalse(OrdenServicio.objects.filter(pk=orden.pk).exists())

    def test_cambiar_el_numero_desde_la_app_es_solo_de_administradores(self):
        self.entrar(self.asesor)
        respuesta = self.client.post(
            reverse('gestion:cambiar_numero_orden', args=[22207]),
            {'numero_orden': '22209'})
        self.assertEqual(respuesta.status_code, 403)

        self.entrar(self.admin)
        self.client.post(reverse('gestion:cambiar_numero_orden', args=[22207]),
                         {'numero_orden': '22209'})
        self.assertEqual(self.numeros(), [22207, 22208, 22209])

    def test_un_numero_invalido_no_mueve_nada(self):
        self.entrar(self.admin)
        for valor in ('', 'abc', '-3', '0'):
            with self.subTest(valor=valor):
                self.client.post(reverse('gestion:cambiar_numero_orden', args=[22207]),
                                 {'numero_orden': valor})
                self.assertEqual(self.numeros(), [22207, 22208, 22209])


# ============================================================
#  ÓRDENES HISTÓRICAS (actas llenadas en papel)
# ============================================================
class OrdenHistoricaTests(BaseCRM):

    def setUp(self):
        self.asesor = self.persona('asesor', 'Asesores')
        self.cli = self.cliente()
        self.camion = self.vehiculo()
        self.entrar(self.asesor)

    def datos(self, **extra):
        datos = {'numero_orden': 21000, 'cliente': self.cli.pk,
                 'vehiculo': self.camion.pk,
                 'fecha_servicio': '2024-05-10', 'descripcion': ''}
        datos.update(extra)
        return datos

    def test_solo_admite_numeros_anteriores_al_arranque_del_sistema(self):
        form = OrdenHistoricaForm(self.datos(numero_orden=OrdenServicio.NUMERO_INICIAL),
                                  {'acta': archivo('acta.pdf')})
        self.assertFalse(form.is_valid())
        self.assertIn('numero_orden', form.errors)

    def test_no_admite_un_numero_ya_ocupado(self):
        OrdenServicio.objects.create(
            numero_orden=21000, cliente=self.cli, asesor=self.asesor,
            direccion_servicio='', descripcion='')
        form = OrdenHistoricaForm(self.datos(), {'acta': archivo('acta.pdf')})
        self.assertFalse(form.is_valid())
        self.assertIn('numero_orden', form.errors)

    def test_queda_archivada_finalizada_con_su_acta_escaneada(self):
        self.client.post(reverse('gestion:orden_historica'),
                         dict(self.datos(), acta=archivo('acta.pdf')))
        orden = OrdenServicio.objects.get(pk=21000)
        self.assertEqual(orden.estado_orden, 'FINALIZADA')
        self.assertEqual(orden.estado_pago, 'PAGADO')
        self.assertEqual(orden.estado_conciliacion, 'NO_APLICA')
        recorrido = orden.recorridos.get()
        self.assertEqual(recorrido.estado, 'COMPLETADO')
        self.assertIsNone(recorrido.conductor)
        self.assertEqual(orden.documentos.count(), 1)

    def test_no_dispara_correos(self):
        mail.outbox.clear()
        self.client.post(reverse('gestion:orden_historica'),
                         dict(self.datos(), acta=archivo('acta.pdf')))
        self.assertEqual(len(mail.outbox), 0)


# ============================================================
#  CONCILIACIÓN DE "TRANSPORTE - CANTIDAD"
# ============================================================
class ConciliacionTests(BaseCRM):

    def setUp(self):
        datos = self.servicio_completo()
        self.__dict__.update(datos)
        self.url = reverse('gestion:conciliar_orden', args=[self.orden.pk])
        self.entrar(self.asesor)

    def test_conciliar_guarda_la_cantidad_en_la_programacion_y_cierra_el_pendiente(self):
        self.assertEqual(self.orden.estado_conciliacion, 'PENDIENTE')
        self.client.post(self.url, {'transporte_cantidad': '12 m³'})

        self.orden.refresh_from_db()
        self.programacion.refresh_from_db()
        self.assertEqual(self.orden.estado_conciliacion, 'CONCILIADA')
        self.assertIsNotNone(self.orden.fecha_conciliacion)
        self.assertEqual(self.programacion.transporte_cantidad, '12 m³')
        self.assertFalse(self.orden.pendiente_conciliacion)

    def test_conciliar_tambien_actualiza_el_acta_ya_firmada(self):
        """DECISIÓN PROVISIONAL del negocio: si cambia, hay que cambiar esta prueba."""
        acta = Manifiesto.objects.create(recorrido=self.recorrido,
                                         estado_firma='FIRMADO')
        self.client.post(self.url, {'transporte_cantidad': '9 m³'})
        acta.refresh_from_db()
        self.assertEqual(acta.transporte_cantidad, '9 m³')

    def test_sin_cantidad_no_se_concilia(self):
        self.client.post(self.url, {'transporte_cantidad': '   '})
        self.orden.refresh_from_db()
        self.assertEqual(self.orden.estado_conciliacion, 'PENDIENTE')

    def test_una_orden_que_no_maneja_conciliacion_no_cambia(self):
        self.orden.estado_conciliacion = 'NO_APLICA'
        self.orden.save()
        self.client.post(self.url, {'transporte_cantidad': '5 m³'})
        self.orden.refresh_from_db()
        self.assertEqual(self.orden.estado_conciliacion, 'NO_APLICA')

    def test_el_conductor_no_concilia(self):
        self.entrar(self.conductor)
        self.assertEqual(self.client.post(
            self.url, {'transporte_cantidad': '5 m³'}).status_code, 403)


# ============================================================
#  PAGOS
# ============================================================
class PagosTests(BaseCRM):

    def setUp(self):
        self.asesor = self.persona('asesor', 'Asesores')
        self.orden = OrdenServicio.objects.create(
            cliente=self.cliente(), asesor=self.asesor, direccion_servicio='x',
            descripcion='y', valor_servicio=Decimal('1000.00'))

    def test_un_pago_de_cero_o_negativo_no_se_registra(self):
        for monto in ('0', '-50'):
            with self.subTest(monto=monto):
                form = PagoForm({'fecha_pago': timezone.now().strftime('%Y-%m-%d %H:%M'),
                                 'monto': monto, 'metodo_pago': 'EFECTIVO', 'notas': ''})
                self.assertFalse(form.is_valid())
                self.assertIn('monto', form.errors)

    def test_un_abono_deja_la_orden_abonada_y_el_total_la_marca_pagada(self):
        Pago.objects.create(orden=self.orden, monto=Decimal('400.00'))
        self.orden.refresh_from_db()
        self.assertEqual(self.orden.estado_pago, 'ABONADO')

        Pago.objects.create(orden=self.orden, monto=Decimal('600.00'))
        self.orden.refresh_from_db()
        self.assertEqual(self.orden.estado_pago, 'PAGADO')

    def test_borrar_el_pago_devuelve_la_orden_a_pendiente(self):
        pago = Pago.objects.create(orden=self.orden, monto=Decimal('400.00'))
        pago.delete()
        self.orden.refresh_from_db()
        self.assertEqual(self.orden.estado_pago, 'PENDIENTE')


# ============================================================
#  "QUÉ FALTA" DE CADA ORDEN (guía de seguimiento)
# ============================================================
class PendientesDeLaOrdenTests(BaseCRM):

    def setUp(self):
        datos = self.servicio_completo()
        self.__dict__.update(datos)

    def etiquetas(self, orden=None):
        orden = orden or OrdenServicio.objects.get(pk=self.orden.pk)
        return [p['etiqueta'] for p in _pendientes_orden(orden)]

    def test_una_orden_recien_creada_lo_pide_todo_en_orden_natural(self):
        self.assertEqual(self.etiquetas(), [
            'Datos del acta', 'Firma del cliente', 'Encuesta de cierre',
            'Conciliar cantidad'])

    def test_los_soportes_solo_se_piden_si_el_servicio_los_exige(self):
        self.orden.bascula = 'PESAN'
        self.orden.registro_fotografico = 'SI'
        self.orden.save()
        etiquetas = self.etiquetas()
        self.assertIn('Tiquete de báscula', etiquetas)
        self.assertIn('Fotos del servicio', etiquetas)

        self.orden.bascula = 'NO_PESAN'
        self.orden.registro_fotografico = 'NO'
        self.orden.save()
        etiquetas = self.etiquetas()
        self.assertNotIn('Tiquete de báscula', etiquetas)
        self.assertNotIn('Fotos del servicio', etiquetas)

    def test_cuenta_las_fotos_que_le_faltan_al_ayudante(self):
        ayudante = self.persona('ayu', 'Ayudantes')
        cuadrilla = self.programacion.cuadrillas.get()
        cuadrilla.ayudante = ayudante
        cuadrilla.ayudante_novedad = 'INICIA_CLIENTE,TERMINA_CLIENTE'
        cuadrilla.save()
        self.assertIn('Fotos del ayudante (2)', self.etiquetas())

        FotoAyudante.objects.create(cuadrilla=cuadrilla, slot=1,
                                    novedad='INICIA_CLIENTE', archivo=imagen())
        self.assertIn('Fotos del ayudante (1)', self.etiquetas())

    def test_cuando_no_falta_nada_la_lista_queda_vacia(self):
        Manifiesto.objects.create(
            recorrido=self.recorrido, estado_firma='FIRMADO',
            tiempo_inicio_operativo=datetime.time(7, 0))
        EncuestaConductor.objects.create(
            recorrido=self.recorrido, presento_fatiga='NO',
            realizo_pausas_activas='SI', molestias_fisicas='NO',
            tiempos_adecuados='SI', cabina_optima='SI',
            zonas_seguras_descanso='SI', condicion_riesgo='NO')
        self.orden.conciliar_transporte('10 m³')
        self.assertEqual(self.etiquetas(), [])


# ============================================================
#  EXPERIENCIA DEL CONDUCTOR
# ============================================================
class ExperienciaDelConductorTests(BaseCRM):
    """Ve lo mínimo para prestar el servicio, y solo lo suyo."""

    def setUp(self):
        datos = self.servicio_completo()
        self.__dict__.update(datos)
        self.entrar(self.conductor)

    def test_su_orden_no_le_muestra_quien_es_el_cliente(self):
        respuesta = self.client.get(
            reverse('gestion:detalle_orden_conductor', args=[self.orden.pk]))
        contenido = respuesta.content.decode()
        self.assertEqual(respuesta.status_code, 200)
        self.assertNotIn(self.cli.nombre, contenido)
        self.assertNotIn(self.cli.identificacion, contenido)

    def test_no_puede_abrir_la_orden_de_otro_conductor(self):
        otro = self.persona('conductor2', 'Conductores')
        self.entrar(otro)
        self.assertEqual(self.client.get(reverse(
            'gestion:detalle_orden_conductor', args=[self.orden.pk])).status_code, 404)

    def test_su_orden_es_una_lista_de_chequeo_con_avance(self):
        respuesta = self.client.get(
            reverse('gestion:detalle_orden_conductor', args=[self.orden.pk]))
        tareas = respuesta.context['tareas']
        progreso = respuesta.context['progreso']
        titulos = ' '.join(t['titulo'] for t in tareas)
        self.assertIn('Llena los datos del servicio', titulos)
        self.assertEqual(progreso['hechas'], 0)
        self.assertGreaterEqual(progreso['total'], 3)
        self.assertIn('los datos del servicio', progreso['faltan'])

    def test_la_encuesta_de_cierre_espera_la_firma_del_cliente(self):
        respuesta = self.client.get(
            reverse('gestion:detalle_orden_conductor', args=[self.orden.pk]))
        encuesta = [t for t in respuesta.context['tareas']
                    if 'encuesta' in t['titulo'].lower()][0]
        self.assertFalse(encuesta['habilitada'], "va con candado hasta que firmen")

        Manifiesto.objects.create(recorrido=self.recorrido, estado_firma='FIRMADO')
        respuesta = self.client.get(
            reverse('gestion:detalle_orden_conductor', args=[self.orden.pk]))
        encuesta = [t for t in respuesta.context['tareas']
                    if 'encuesta' in t['titulo'].lower()][0]
        self.assertTrue(encuesta['habilitada'])

    def test_mis_recorridos_solo_trae_los_suyos_y_los_pendientes(self):
        otro_conductor = self.persona('conductor2', 'Conductores')
        Recorrido.objects.create(
            orden=self.orden, vehiculo=self.vehiculo('AJE111'),
            conductor=otro_conductor, fecha_recorrido=timezone.localdate())
        viejo = Recorrido.objects.create(
            orden=self.orden, vehiculo=self.vehiculo('OLD111'),
            conductor=self.conductor,
            fecha_recorrido=timezone.localdate() - datetime.timedelta(days=3))

        recorridos = self.client.get(reverse('gestion:mis_recorridos')).context['recorridos']
        self.assertEqual([r.pk for r in recorridos], [self.recorrido.pk])

    def test_el_historial_si_trae_todos_sus_recorridos(self):
        Recorrido.objects.create(
            orden=self.orden, vehiculo=self.vehiculo('OLD111'),
            conductor=self.conductor,
            fecha_recorrido=timezone.localdate() - datetime.timedelta(days=3))
        recorridos = self.client.get(reverse('gestion:historial_conductor')).context['recorridos']
        self.assertEqual(len(recorridos), 2)

    def test_puede_subir_el_tiquete_de_bascula_de_su_orden(self):
        self.orden.bascula = 'PESAN'
        self.orden.save()
        self.client.post(
            reverse('gestion:detalle_orden_conductor', args=[self.orden.pk]),
            {'submit_bascula': '1', 'bascula_adjunto': imagen('tiquete.png')})
        self.orden.refresh_from_db()
        self.assertTrue(self.orden.bascula_adjunto.name)

    def test_las_fotos_de_mas_quedan_como_documentos_de_la_orden(self):
        self.orden.registro_fotografico = 'SI'
        self.orden.save()
        self.client.post(
            reverse('gestion:detalle_orden_conductor', args=[self.orden.pk]),
            {'submit_fotos': '1', 'fotos': [imagen('f1.png'), imagen('f2.png')]})
        self.orden.refresh_from_db()
        self.assertTrue(self.orden.registro_fotografico_adjunto.name)
        self.assertEqual(self.orden.documentos.count(), 1)

    def test_no_se_cargan_soportes_que_el_servicio_no_pidio(self):
        self.client.post(
            reverse('gestion:detalle_orden_conductor', args=[self.orden.pk]),
            {'submit_bascula': '1', 'bascula_adjunto': imagen('tiquete.png')})
        self.orden.refresh_from_db()
        self.assertFalse(self.orden.bascula_adjunto)


# ============================================================
#  ACCESO DEL AYUDANTE POR TOKEN (sin usuario ni contraseña)
# ============================================================
class AccesoDelAyudanteTests(BaseCRM):

    def setUp(self):
        self.asesor = self.persona('asesor', 'Asesores')
        self.conductor = self.persona('conductor', 'Conductores', 'Carlos', 'Pérez')
        self.ayudante = self.persona('ayudante', 'Ayudantes', 'Luis', 'Gómez')
        self.ayudante2 = self.persona('ayudante2', 'Ayudantes', 'Iván', 'Mora')
        self.cli = self.cliente()
        sitio, _ = SitioInicio.objects.get_or_create(nombre='Bodega')
        self.programacion = Programacion.objects.create(
            cliente=self.cli, fecha=timezone.localdate(), sitio_inicio=sitio,
            hora_ingreso_bodega=datetime.time(5, 30),
            nombre_contacto_recibe='Contacto secreto')
        self.cuadrilla = ProgramacionCuadrilla.objects.create(
            programacion=self.programacion, conductor=self.conductor,
            vehiculo=self.vehiculo(), ayudante=self.ayudante,
            ayudante2=self.ayudante2,
            ayudante_novedad='INICIA_CLIENTE,RETORNA_BODEGA',
            ayudante2_novedad='TERMINA_CLIENTE')
        self.url = reverse('gestion:acceso_ayudante',
                           args=[self.cuadrilla.token_ayudante])

    def test_entra_sin_iniciar_sesion_y_solo_ve_su_hora_y_su_lugar(self):
        respuesta = self.client.get(self.url)
        contenido = respuesta.content.decode()
        self.assertEqual(respuesta.status_code, 200)
        self.assertIn('Bodega', contenido)
        self.assertNotIn(self.cli.nombre, contenido)
        self.assertNotIn('Contacto secreto', contenido)
        self.assertNotIn('Carlos Pérez', contenido, "no ve al conductor")

    def test_cada_ayudante_entra_con_su_propio_enlace(self):
        respuesta = self.client.get(self.url)
        self.assertEqual(respuesta.context['ayudante'], self.ayudante)
        self.assertEqual(respuesta.context['slot'], 1)

        respuesta = self.client.get(reverse(
            'gestion:acceso_ayudante', args=[self.cuadrilla.token_ayudante2]))
        self.assertEqual(respuesta.context['ayudante'], self.ayudante2)
        self.assertEqual(respuesta.context['slot'], 2)

    def test_solo_le_piden_las_fotos_de_sus_novedades(self):
        contexto = self.client.get(self.url).context
        self.assertEqual([f['codigo'] for f in contexto['fotos_pedidas']],
                         ['INICIA_CLIENTE'])

    def test_sube_la_foto_de_una_novedad_que_le_pidieron(self):
        self.client.post(self.url, {'novedad': 'INICIA_CLIENTE',
                                    'fotos': [imagen('llegada.png')]})
        foto = FotoAyudante.objects.get()
        self.assertEqual(foto.slot, 1)
        self.assertEqual(foto.novedad, 'INICIA_CLIENTE')
        self.assertEqual(foto.persona, self.ayudante)

    def test_no_puede_subir_fotos_de_novedades_que_no_son_suyas(self):
        self.client.post(self.url, {'novedad': 'TERMINA_CLIENTE',
                                    'fotos': [imagen('otra.png')]})
        self.assertFalse(FotoAyudante.objects.exists())

    def test_sin_archivo_no_se_registra_nada(self):
        self.client.post(self.url, {'novedad': 'INICIA_CLIENTE'})
        self.assertFalse(FotoAyudante.objects.exists())

    def test_el_enlace_vence_pasados_los_dias_de_vigencia(self):
        vencida = ProgramacionCuadrilla.DIAS_VIGENCIA_ACCESO + 1
        self.programacion.fecha = timezone.localdate() - datetime.timedelta(days=vencida)
        self.programacion.save()
        self.cuadrilla.refresh_from_db()
        self.assertFalse(self.cuadrilla.acceso_vigente)

        self.client.post(self.url, {'novedad': 'INICIA_CLIENTE',
                                    'fotos': [imagen('tarde.png')]})
        self.assertFalse(FotoAyudante.objects.exists())
        # Consultar sí puede, aunque haya vencido.
        self.assertEqual(self.client.get(self.url).status_code, 200)

    def test_si_le_quitan_el_ayudante_el_enlace_deja_de_servir(self):
        self.cuadrilla.ayudante = None
        self.cuadrilla.save()
        self.assertEqual(self.client.get(self.url).status_code, 404)


# ============================================================
#  CENTRO DE CORREOS
# ============================================================
class CentroDeCorreosTests(BaseCRM):
    """Resolución de adjuntos, envío, historial y fallos del servidor."""

    def setUp(self):
        self.asesor = self.persona('asesor', 'Asesores')
        self.cli = self.cliente(email='cliente@correo.co')
        self.entrar(self.asesor)

    def test_resuelve_los_documentos_de_cada_familia(self):
        conductor = self.persona('conductor', 'Conductores', 'Carlos', 'Pérez')
        ss = self.con_ss(conductor)
        camion = self.vehiculo(archivo_soat=archivo('soat.pdf'))
        dispositor = Dispositor.objects.create(nombre='Gestor Ambiental S.A.')
        doc_dispositor = DocumentoDispositor.objects.create(
            dispositor=dispositor, tipo='RUT', archivo=archivo())
        interno = DocumentoInterno.objects.create(
            tipo='OTRO', descripcion='Política de calidad', archivo=archivo())
        self.cli.doc_rut = archivo('rut.pdf')
        self.cli.save()
        ambiental = DocumentoAmbientalCliente.objects.create(
            cliente=self.cli, archivo=archivo(), descripcion='Caracterización')
        del_cliente = DocumentoCorreoCliente.objects.create(
            cliente=self.cli, archivo=archivo(), descripcion='Anexo del contrato')

        casos = {
            f'personal:{ss.pk}': 'Carlos Pérez',
            f'vehiculo:{camion.pk}:soat': 'SOAT',
            f'proveedor:{doc_dispositor.pk}': 'Gestor Ambiental S.A.',
            f'solmed:{interno.pk}': 'Política de calidad',
            f'cliente_fijo:{self.cli.pk}:rut': 'RUT',
            f'cliente_amb:{ambiental.pk}': 'Caracterización',
            f'cliente_correo:{del_cliente.pk}': 'Anexo del contrato',
        }
        for token, esperado in casos.items():
            with self.subTest(token=token):
                resuelto = _resolver_adjunto_correo(token)
                self.assertIsNotNone(resuelto, f"{token} debería resolver")
                self.assertIn(esperado, resuelto['linea'])

    def test_la_seguridad_social_se_adjunta_diciendo_hasta_cuando_vale(self):
        conductor = self.persona('conductor', 'Conductores', 'Carlos', 'Pérez')
        ss = self.con_ss(conductor, dias=10)
        resuelto = _resolver_adjunto_correo(f'personal:{ss.pk}')
        self.assertIn('vigente hasta', resuelto['linea'])

    def test_los_tokens_inventados_o_de_documentos_borrados_no_resuelven(self):
        for token in ('', 'basura', 'personal:999999', 'personal:abc',
                      'vehiculo:1:pasaporte', 'solmed:0'):
            with self.subTest(token=token):
                self.assertIsNone(_resolver_adjunto_correo(token))

    def test_el_envio_manda_el_correo_con_sus_adjuntos_y_lo_registra(self):
        conductor = self.persona('conductor', 'Conductores', 'Carlos', 'Pérez')
        ss = self.con_ss(conductor)
        mail.outbox.clear()

        respuesta = self.client.post(reverse('gestion:crear_envio_correo'), {
            'cliente': self.cli.pk, 'destinatarios': ['cliente@correo.co'],
            'asunto': 'Documentación del servicio', 'mensaje': 'Buen día',
            'responder_a': 'respuestas@solmed.co',
            'adjuntos': [f'personal:{ss.pk}'],
        })

        registro = EnvioCorreo.objects.get()
        self.assertRedirects(respuesta, reverse('gestion:detalle_envio_correo',
                                                args=[registro.pk]))
        self.assertEqual(registro.estado, 'ENVIADO')
        self.assertEqual(registro.cliente, self.cli)
        self.assertEqual(registro.enviado_por, self.asesor)
        self.assertEqual(registro.adjuntos, [f'personal:{ss.pk}'])
        self.assertEqual(len(registro.adjuntos_detalle), 1)

        self.assertEqual(len(mail.outbox), 1)
        correo = mail.outbox[0]
        self.assertEqual(correo.to, ['cliente@correo.co'])
        self.assertEqual(correo.reply_to, ['respuestas@solmed.co'])
        self.assertEqual(len(correo.attachments), 1)

    def test_el_historial_conserva_lo_enviado_aunque_el_documento_cambie(self):
        conductor = self.persona('conductor', 'Conductores', 'Carlos', 'Pérez')
        ss = self.con_ss(conductor)
        self.client.post(reverse('gestion:crear_envio_correo'), {
            'destinatarios': ['cliente@correo.co'], 'asunto': 'Docs',
            'mensaje': '', 'responder_a': '', 'adjuntos': [f'personal:{ss.pk}'],
        })
        detalle = EnvioCorreo.objects.get().adjuntos_detalle
        ss.delete()
        self.assertEqual(EnvioCorreo.objects.get().adjuntos_detalle, detalle)

    def test_un_destinatario_invalido_frena_el_envio(self):
        mail.outbox.clear()
        respuesta = self.client.post(reverse('gestion:crear_envio_correo'), {
            'destinatarios': ['esto no es un correo'], 'asunto': 'Docs',
            'mensaje': '', 'responder_a': '', 'adjuntos': [],
        })
        self.assertEqual(respuesta.status_code, 200)
        self.assertTrue(respuesta.context['errores'])
        self.assertFalse(EnvioCorreo.objects.exists())
        self.assertEqual(len(mail.outbox), 0)

    def test_sin_asunto_no_se_envia(self):
        self.client.post(reverse('gestion:crear_envio_correo'), {
            'destinatarios': ['cliente@correo.co'], 'asunto': '  ',
            'mensaje': '', 'responder_a': '', 'adjuntos': [],
        })
        self.assertFalse(EnvioCorreo.objects.exists())

    def test_un_adjunto_que_ya_no_existe_frena_el_envio(self):
        self.client.post(reverse('gestion:crear_envio_correo'), {
            'destinatarios': ['cliente@correo.co'], 'asunto': 'Docs',
            'mensaje': '', 'responder_a': '', 'adjuntos': ['personal:999999'],
        })
        self.assertFalse(EnvioCorreo.objects.exists())

    def test_si_el_servidor_de_correo_rechaza_el_envio_queda_como_fallido(self):
        from unittest.mock import MagicMock
        mensaje = MagicMock()
        mensaje.send.side_effect = Exception('SMTP caído')
        with patch('gestion.views._armar_correo_envio', return_value=mensaje):
            self.client.post(reverse('gestion:crear_envio_correo'), {
                'destinatarios': ['cliente@correo.co'], 'asunto': 'Docs',
                'mensaje': '', 'responder_a': '', 'adjuntos': [],
            })
        registro = EnvioCorreo.objects.get()
        self.assertEqual(registro.estado, 'FALLIDO')
        self.assertIn('SMTP caído', registro.error)

    def test_reenviar_un_envio_precarga_sus_datos(self):
        registro = EnvioCorreo.objects.create(
            cliente=self.cli, destinatarios='cliente@correo.co', asunto='Original',
            mensaje='Texto', adjuntos=[], enviado_por=self.asesor)
        respuesta = self.client.get(reverse('gestion:crear_envio_correo'),
                                    {'copiar': registro.pk})
        self.assertEqual(respuesta.context['datos']['asunto'], 'Original')
        self.assertEqual(respuesta.context['datos']['destinatarios'],
                         'cliente@correo.co')

    def test_el_buscador_no_lista_el_catalogo_entero(self):
        """Regla del rediseño: los documentos salen bajo demanda, no de una."""
        for i in range(12):
            self.con_ss(self.persona(f'p{i}', 'Conductores'))
        respuesta = self.client.get(reverse('gestion:buscar_docs_correo'), {'q': 'p'})
        datos = respuesta.json()
        for fuente in datos.get('fuentes', datos if isinstance(datos, list) else []):
            if isinstance(fuente, dict) and 'items' in fuente:
                self.assertLessEqual(len(fuente['items']), 6)


# ============================================================
#  DOCUMENTACIÓN INTERNA DE SOLMED
# ============================================================
class DocumentacionSolmedTests(BaseCRM):
    """Una sola versión vigente por documento: cargar otro REEMPLAZA al anterior."""

    def setUp(self):
        self.asesor = self.persona('asesor', 'Asesores')
        self.entrar(self.asesor)
        self.url = reverse('gestion:documentacion')

    def test_cargar_el_mismo_tipo_reemplaza_al_anterior(self):
        viejo = DocumentoInterno.objects.create(tipo='RIT', archivo=archivo('viejo.pdf'))
        self.client.post(self.url, {'tipo': 'RIT', 'archivo': archivo('nuevo.pdf'),
                                    'fecha': '', 'entidad': '', 'descripcion': ''})
        self.assertEqual(DocumentoInterno.objects.filter(tipo='RIT').count(), 1)
        self.assertFalse(DocumentoInterno.objects.filter(pk=viejo.pk).exists())

    def test_la_certificacion_bancaria_se_reemplaza_por_banco_no_entre_cuentas(self):
        self.client.post(self.url, {
            'tipo': 'CERTIFICACION_BANCARIA', 'archivo': archivo('banco1.pdf'),
            'fecha': '', 'entidad': 'Bancolombia', 'descripcion': ''})
        self.client.post(self.url, {
            'tipo': 'CERTIFICACION_BANCARIA', 'archivo': archivo('banco2.pdf'),
            'fecha': '', 'entidad': 'Occidente', 'descripcion': ''})
        self.assertEqual(DocumentoInterno.objects.count(), 2,
                         "una cuenta no pisa a la otra")

        self.client.post(self.url, {
            'tipo': 'CERTIFICACION_BANCARIA', 'archivo': archivo('banco3.pdf'),
            'fecha': '', 'entidad': 'bancolombia', 'descripcion': ''})
        self.assertEqual(DocumentoInterno.objects.count(), 2,
                         "el mismo banco (sin importar mayúsculas) sí reemplaza")

    def test_la_documentacion_adicional_se_reemplaza_por_su_nombre(self):
        self.client.post(self.url, {
            'tipo': 'OTRO', 'archivo': archivo('a.pdf'), 'fecha': '',
            'entidad': '', 'descripcion': 'Política de calidad'})
        self.client.post(self.url, {
            'tipo': 'OTRO', 'archivo': archivo('b.pdf'), 'fecha': '',
            'entidad': '', 'descripcion': 'Matriz de riesgos'})
        self.assertEqual(DocumentoInterno.objects.count(), 2)

        self.client.post(self.url, {
            'tipo': 'OTRO', 'archivo': archivo('c.pdf'), 'fecha': '',
            'entidad': '', 'descripcion': 'política de calidad'})
        self.assertEqual(DocumentoInterno.objects.count(), 2)

    def test_la_documentacion_adicional_exige_nombre(self):
        self.client.post(self.url, {
            'tipo': 'OTRO', 'archivo': archivo('a.pdf'), 'fecha': '',
            'entidad': '', 'descripcion': '   '})
        self.assertFalse(DocumentoInterno.objects.exists())

    def test_el_rut_y_la_camara_exigen_fecha(self):
        for tipo in ('RUT', 'CAMARA_COMERCIO'):
            with self.subTest(tipo=tipo):
                self.client.post(self.url, {
                    'tipo': tipo, 'archivo': archivo('x.pdf'), 'fecha': '',
                    'entidad': '', 'descripcion': ''})
                self.assertFalse(DocumentoInterno.objects.filter(tipo=tipo).exists())

    def test_la_certificacion_bancaria_exige_el_banco(self):
        self.client.post(self.url, {
            'tipo': 'CERTIFICACION_BANCARIA', 'archivo': archivo('x.pdf'),
            'fecha': '', 'entidad': '', 'descripcion': ''})
        self.assertFalse(DocumentoInterno.objects.exists())


# ============================================================
#  PROVEEDORES (dispositores y proveedores generales)
# ============================================================
class ProveedoresTests(BaseCRM):

    def setUp(self):
        self.asesor = self.persona('asesor', 'Asesores')
        self.admin = self.persona('admin', 'Administradores')
        self.entrar(self.asesor)

    def test_el_panel_solo_maneja_los_proveedores_externos(self):
        externo = Dispositor.objects.create(nombre='Gestor Ambiental S.A.')
        interno = Dispositor.objects.create(
            nombre=Dispositor.DEJAR_CARRO_CARGADO, tipo='INTERNO')

        self.assertEqual(self.client.get(reverse(
            'gestion:ficha_dispositor', args=[externo.pk])).status_code, 200)
        self.assertEqual(self.client.get(reverse(
            'gestion:ficha_dispositor', args=[interno.pk])).status_code, 404,
            "los destinos internos son cosa del admin de Django")

        listado = self.client.get(reverse('gestion:lista_dispositores')).context
        self.assertNotIn(interno, listado['dispositores'])

    def test_el_expediente_del_dispositor_admite_varios_ambientales(self):
        dispositor = Dispositor.objects.create(nombre='Gestor Ambiental S.A.')
        for i in range(2):
            DocumentoDispositor.objects.create(
                dispositor=dispositor, tipo='DOC_AMBIENTAL', archivo=archivo())
        respuesta = self.client.get(reverse('gestion:ficha_dispositor',
                                            args=[dispositor.pk]))
        ambientales = [s for s in respuesta.context['secciones']
                       if s['tipo'] == 'DOC_AMBIENTAL'][0]
        self.assertEqual(len(ambientales['docs']), 2)

    def test_un_proveedor_general_se_crea_con_sus_contactos(self):
        self.client.post(reverse('gestion:crear_proveedor'), {
            'nit': '900123456-7', 'razon_social': 'Repuestos del Sur S.A.S.',
            'nombre_comercial': 'Repuestos Sur', 'direccion': 'Cra 1',
            'banco': '', 'tipo_cuenta': 'AHORROS', 'numero_cuenta': '123456',
            'activo': 'on',
            'contactos-TOTAL_FORMS': '3', 'contactos-INITIAL_FORMS': '0',
            'contactos-MIN_NUM_FORMS': '0', 'contactos-MAX_NUM_FORMS': '3',
            'contactos-0-nombre': 'Sandra', 'contactos-0-area': 'Cartera',
            'contactos-0-correo': 'sandra@sur.co', 'contactos-0-celular': '3001234567',
            'contactos-1-nombre': '', 'contactos-1-area': '',
            'contactos-1-correo': '', 'contactos-1-celular': '',
            'contactos-2-nombre': '', 'contactos-2-area': '',
            'contactos-2-correo': '', 'contactos-2-celular': '',
        })
        proveedor = Proveedor.objects.get()
        self.assertEqual(str(proveedor), 'Repuestos Sur')
        self.assertEqual([c.nombre for c in proveedor.contactos.all()], ['Sandra'])

    def test_una_fila_de_contacto_con_datos_pero_sin_nombre_no_pasa(self):
        from .forms import ContactoProveedorForm
        form = ContactoProveedorForm({'nombre': '', 'area': 'Cartera',
                                      'correo': 'x@y.co', 'celular': ''})
        self.assertFalse(form.is_valid())
        self.assertIn('nombre', form.errors)

    def test_vaciar_la_fila_de_un_contacto_lo_quita(self):
        proveedor = Proveedor.objects.create(nit='900', razon_social='Sur S.A.S.')
        contacto = proveedor.contactos.create(nombre='Sandra', area='Cartera')
        self.client.post(reverse('gestion:actualizar_proveedor', args=[proveedor.pk]), {
            'nit': '900', 'razon_social': 'Sur S.A.S.', 'nombre_comercial': '',
            'direccion': '', 'banco': '', 'tipo_cuenta': '', 'numero_cuenta': '',
            'activo': 'on',
            'contactos-TOTAL_FORMS': '3', 'contactos-INITIAL_FORMS': '1',
            'contactos-MIN_NUM_FORMS': '0', 'contactos-MAX_NUM_FORMS': '3',
            'contactos-0-id': contacto.pk, 'contactos-0-proveedor': proveedor.pk,
            'contactos-0-nombre': '', 'contactos-0-area': '',
            'contactos-0-correo': '', 'contactos-0-celular': '',
            'contactos-1-nombre': '', 'contactos-1-area': '',
            'contactos-1-correo': '', 'contactos-1-celular': '',
            'contactos-2-nombre': '', 'contactos-2-area': '',
            'contactos-2-correo': '', 'contactos-2-celular': '',
        })
        self.assertFalse(proveedor.contactos.exists())

    def test_eliminar_un_proveedor_es_de_administradores_y_borra_su_expediente(self):
        proveedor = Proveedor.objects.create(nit='900', razon_social='Sur S.A.S.')
        proveedor.contactos.create(nombre='Sandra')
        proveedor.documentos.create(nombre='RUT', archivo=archivo())

        self.assertEqual(self.client.post(reverse(
            'gestion:eliminar_proveedor', args=[proveedor.pk])).status_code, 403)

        self.entrar(self.admin)
        self.client.post(reverse('gestion:eliminar_proveedor', args=[proveedor.pk]))
        self.assertFalse(Proveedor.objects.exists())
        self.assertEqual(proveedor.contactos.model.objects.count(), 0)
        self.assertEqual(proveedor.documentos.model.objects.count(), 0)


# ============================================================
#  VEHÍCULOS: PAPELES, VEREDICTO Y MANTENIMIENTO
# ============================================================
class VehiculosTests(BaseCRM):

    def setUp(self):
        self.asesor = self.persona('asesor', 'Asesores')
        self.camion = self.vehiculo()
        self.entrar(self.asesor)

    def test_los_documentos_avisan_veinte_dias_antes_y_marcan_los_vencidos(self):
        hoy = timezone.localdate()
        self.camion.fecha_vencimiento_soat = hoy + datetime.timedelta(days=10)
        self.camion.fecha_vencimiento_tecnomecanica = hoy - datetime.timedelta(days=2)
        self.camion.save()

        alertas = {a['documento']: a for a in self.camion.documentos_por_vencer()}
        self.assertFalse(alertas['SOAT']['vencido'])
        self.assertTrue(alertas['Tecnomecánica']['vencido'])
        self.assertTrue(self.camion.tiene_alerta_documentos)

    def test_un_documento_lejano_no_alerta(self):
        self.camion.fecha_vencimiento_soat = (
            timezone.localdate() + datetime.timedelta(days=90))
        self.camion.save()
        self.assertFalse(self.camion.tiene_alerta_documentos)

    def test_el_veredicto_frena_por_documento_vencido_o_fuera_de_servicio(self):
        self.camion.fecha_vencimiento_soat = (
            timezone.localdate() - datetime.timedelta(days=1))
        self.camion.save()
        self.assertEqual(_puede_programarse(self.camion)['nivel'], 'alto')

        otro = self.vehiculo('TAL999', estado='MANTENIMIENTO')
        self.assertEqual(_puede_programarse(otro)['nivel'], 'alto')

    def test_el_veredicto_solo_advierte_por_carga_pendiente_o_vencimiento_cercano(self):
        self.camion.cargado = True
        self.camion.cargado_detalle = 'Orden #22207'
        self.camion.save()
        veredicto = _puede_programarse(self.camion)
        self.assertEqual(veredicto['nivel'], 'aviso')
        self.assertIn('residuo pendiente', ' '.join(veredicto['motivos']))

    def test_un_camion_al_dia_esta_listo_para_programar(self):
        hoy = timezone.localdate()
        self.camion.fecha_vencimiento_soat = hoy + datetime.timedelta(days=200)
        self.camion.fecha_vencimiento_tecnomecanica = hoy + datetime.timedelta(days=200)
        self.camion.save()
        self.assertEqual(_puede_programarse(self.camion)['nivel'], 'ok')

    def test_se_registra_el_cambio_de_filtros_y_aceites(self):
        self.client.post(reverse('gestion:registrar_filtro_aceite', args=[self.camion.pk]), {
            'tipo': 'ACEITE_MOTOR', 'fecha_cambio': timezone.localdate().isoformat(),
            'cantidad': '5', 'unidad': 'GALONES', 'kilometraje': '120000',
            'referencia': 'Mobil Delvac 15W-40', 'observaciones': '',
        })
        registro = self.camion.filtros_aceites.get()
        self.assertTrue(registro.es_aceite)
        self.assertEqual(registro.dias_desde_cambio, 0)

    def test_una_cantidad_de_cero_no_es_un_cambio(self):
        from .forms import FiltroAceiteForm
        form = FiltroAceiteForm({
            'tipo': 'FILTRO_AIRE', 'fecha_cambio': timezone.localdate().isoformat(),
            'cantidad': '0', 'unidad': 'UNIDADES', 'kilometraje': '',
            'referencia': '', 'observaciones': ''})
        self.assertFalse(form.is_valid())
        self.assertIn('cantidad', form.errors)

    def test_un_vehiculo_con_recorridos_no_se_puede_borrar_desde_la_app(self):
        admin = self.persona('admin', 'Administradores')
        orden = OrdenServicio.objects.create(
            cliente=self.cliente(), asesor=self.asesor,
            direccion_servicio='x', descripcion='y')
        Recorrido.objects.create(orden=orden, vehiculo=self.camion,
                                 fecha_recorrido=timezone.localdate())
        self.entrar(admin)
        self.client.post(reverse('gestion:eliminar_vehiculo', args=[self.camion.pk]))
        self.assertTrue(Vehiculo.objects.filter(pk=self.camion.pk).exists())


# ============================================================
#  EXPEDIENTE DEL CLIENTE
# ============================================================
class FichaClienteTests(BaseCRM):

    def setUp(self):
        datos = self.servicio_completo()
        self.__dict__.update(datos)
        self.url = reverse('gestion:ficha_cliente', args=[self.cli.pk])
        self.entrar(self.asesor)

    def test_reune_los_indicadores_del_historico(self):
        Manifiesto.objects.create(
            recorrido=self.recorrido, estado_firma='FIRMADO',
            eval_atencion=4, eval_amabilidad=4, eval_puntualidad=3)
        contexto = self.client.get(self.url).context
        indicadores = contexto['indicadores']
        self.assertEqual(indicadores['total_ordenes'], 1)
        self.assertEqual(indicadores['actas_firmadas'], 1)
        self.assertEqual(indicadores['por_conciliar'], 1)
        self.assertIsNotNone(indicadores['satisfaccion'])
        etiquetas = [a['etiqueta'] for a in contexto['aspectos']]
        self.assertIn('Atención', etiquetas)

    def test_las_graficas_traen_doce_meses_aunque_esten_en_cero(self):
        graficas = self.client.get(self.url).context['graficas']
        self.assertEqual(len(graficas['meses']['etiquetas']), 12)
        self.assertEqual(len(graficas['meses']['datos']), 12)

    def test_lista_y_filtra_las_ordenes_del_cliente(self):
        otro = self.cliente('Cliente ajeno', identificacion='800-77')
        OrdenServicio.objects.create(
            cliente=otro, asesor=self.asesor, direccion_servicio='x', descripcion='y')

        ordenes = self.client.get(self.url).context['ordenes']
        self.assertEqual([o.pk for o in ordenes], [self.orden.pk])

        vacio = self.client.get(self.url, {'conciliacion': 'CONCILIADA'}).context['ordenes']
        self.assertEqual(list(vacio), [])

    def test_el_expediente_del_cliente_es_de_gestion(self):
        self.entrar(self.conductor)
        self.assertEqual(self.client.get(self.url).status_code, 403)


# ============================================================
#  CATÁLOGOS ADMINISTRABLES (báscula, sitio de inicio, residuo)
# ============================================================
class CatalogosTests(BaseCRM):

    def setUp(self):
        self.asesor = self.persona('asesor', 'Asesores')
        self.entrar(self.asesor)

    def test_se_crean_desde_el_popup_y_no_se_duplican(self):
        respuesta = self.client.post(reverse('gestion:crear_bascula'),
                                     {'nombre': 'Báscula Centro', 'direccion': 'Cra 1'})
        self.assertTrue(respuesta.json()['ok'])

        # El mismo nombre (con otras mayúsculas) reutiliza el registro.
        self.client.post(reverse('gestion:crear_bascula'),
                         {'nombre': 'báscula centro', 'direccion': ''})
        self.assertEqual(Bascula.objects.filter(nombre__iexact='báscula centro').count(), 1)

    def test_sin_nombre_no_se_crea(self):
        respuesta = self.client.post(reverse('gestion:crear_tipo_residuo'), {'nombre': '  '})
        self.assertEqual(respuesta.status_code, 400)
        self.assertFalse(TipoResiduo.objects.filter(nombre='  ').exists())

    def test_un_catalogo_sin_uso_se_borra_de_verdad(self):
        sitio = SitioInicio.objects.create(nombre='Taller de pruebas')
        respuesta = self.client.post(
            reverse('gestion:eliminar_sitio_inicio', args=[sitio.pk]))
        self.assertTrue(respuesta.json()['eliminada'])
        self.assertFalse(SitioInicio.objects.filter(pk=sitio.pk).exists())

    def test_uno_ya_usado_se_oculta_en_vez_de_borrarse(self):
        sitio = SitioInicio.objects.create(nombre='Bodega usada')
        Programacion.objects.create(cliente=self.cliente(),
                                    fecha=timezone.localdate(), sitio_inicio=sitio)
        respuesta = self.client.post(
            reverse('gestion:eliminar_sitio_inicio', args=[sitio.pk]))
        sitio.refresh_from_db()
        self.assertFalse(respuesta.json()['eliminada'])
        self.assertFalse(sitio.activo, "se oculta, el histórico queda intacto")

    def test_un_residuo_ya_usado_tambien_se_oculta(self):
        residuo = TipoResiduo.objects.create(nombre='Lodos de prueba')
        Programacion.objects.create(cliente=self.cliente(),
                                    fecha=timezone.localdate(),
                                    transporte_tipo='Lodos de prueba')
        self.client.post(reverse('gestion:eliminar_tipo_residuo', args=[residuo.pk]))
        residuo.refresh_from_db()
        self.assertFalse(residuo.activo)

    def test_los_catalogos_son_de_gestion(self):
        conductor = self.persona('conductor', 'Conductores')
        self.entrar(conductor)
        self.assertEqual(self.client.post(
            reverse('gestion:crear_bascula'), {'nombre': 'X'}).status_code, 403)


# ============================================================
#  DOCUMENTOS PDF (se generan al descargar, no se guardan)
# ============================================================
class DocumentosPDFTests(BaseCRM):

    def setUp(self):
        datos = self.servicio_completo()
        self.__dict__.update(datos)
        self.entrar(self.asesor)

    def test_el_acta_no_guarda_su_pdf_en_la_base(self):
        campos = {f.name for f in Manifiesto._meta.get_fields()}
        self.assertNotIn('pdf_generado', campos)
        self.assertNotIn('pdf_generado',
                         {f.name for f in EncuestaConductor._meta.get_fields()})

    def test_el_acta_se_descarga_en_pdf_con_los_datos_vigentes(self):
        Manifiesto.objects.create(
            recorrido=self.recorrido, estado_firma='FIRMADO',
            tiempo_inicio_operativo=datetime.time(7, 0),
            nombre_responsable_cliente='María del cliente')
        respuesta = self.client.get(reverse('gestion:acta_pdf', args=[self.recorrido.pk]))
        self.assertEqual(respuesta.status_code, 200)
        self.assertEqual(respuesta['Content-Type'], 'application/pdf')
        self.assertIn('attachment', respuesta['Content-Disposition'])
        self.assertTrue(respuesta.content.startswith(b'%PDF'))

    def test_sin_acta_no_hay_pdf(self):
        self.assertEqual(self.client.get(reverse(
            'gestion:acta_pdf', args=[self.recorrido.pk])).status_code, 404)

    def test_la_encuesta_de_cierre_se_descarga_en_pdf(self):
        Manifiesto.objects.create(recorrido=self.recorrido, estado_firma='FIRMADO')
        EncuestaConductor.objects.create(
            recorrido=self.recorrido, presento_fatiga='SI',
            realizo_pausas_activas='NO', molestias_fisicas='NO',
            tiempos_adecuados='SI', cabina_optima='SI',
            zonas_seguras_descanso='SI', condicion_riesgo='NO')
        respuesta = self.client.get(reverse('gestion:encuesta_conductor_pdf',
                                            args=[self.recorrido.pk]))
        self.assertEqual(respuesta.status_code, 200)
        self.assertTrue(respuesta.content.startswith(b'%PDF'))


# ============================================================
#  LISTADOS: FILTROS Y PAGINACIÓN
# ============================================================
class ListadosTests(BaseCRM):

    def setUp(self):
        self.asesor = self.persona('asesor', 'Asesores')
        self.conductor = self.persona('conductor', 'Conductores')
        self.con_ss(self.conductor)
        self.cli = self.cliente()
        self.otro = self.cliente('Aseo Total S.A.', identificacion='800-55')
        self.entrar(self.asesor)

    def _orden(self, cliente):
        return OrdenServicio.objects.create(
            cliente=cliente, asesor=self.asesor, direccion_servicio='x', descripcion='y')

    def test_la_lista_de_ordenes_busca_por_cliente_y_por_numero(self):
        mia = self._orden(self.cli)
        ajena = self._orden(self.otro)

        ordenes = self.client.get(reverse('gestion:lista_ordenes'),
                                  {'q': 'Aseo'}).context['ordenes']
        self.assertEqual([o.pk for o in ordenes], [ajena.pk])

        ordenes = self.client.get(reverse('gestion:lista_ordenes'),
                                  {'q': str(mia.pk)}).context['ordenes']
        self.assertEqual([o.pk for o in ordenes], [mia.pk])

    def test_la_lista_de_ordenes_filtra_por_estado_pago_y_conciliacion(self):
        pendiente = self._orden(self.cli)
        conciliada = self._orden(self.cli)
        conciliada.estado_conciliacion = 'CONCILIADA'
        conciliada.save()

        ordenes = self.client.get(reverse('gestion:lista_ordenes'),
                                  {'conciliacion': 'CONCILIADA'}).context['ordenes']
        self.assertEqual([o.pk for o in ordenes], [conciliada.pk])

        ordenes = self.client.get(reverse('gestion:lista_ordenes'),
                                  {'pago': 'PAGADO'}).context['ordenes']
        self.assertEqual(list(ordenes), [])

    def test_la_lista_muestra_la_fecha_del_servicio_no_la_de_creacion(self):
        programacion = self.programacion(
            cliente=self.cli, conductor=self.conductor,
            fecha=timezone.localdate() + datetime.timedelta(days=5))
        orden = programacion.convertir_en_orden(self.asesor)
        listada = self.client.get(reverse('gestion:lista_ordenes')).context['ordenes'][0]
        self.assertEqual(listada.fecha_servicio,
                         timezone.localdate() + datetime.timedelta(days=5))

    def test_los_listados_paginan_de_a_veinte(self):
        for _ in range(21):
            self._orden(self.cli)
        contexto = self.client.get(reverse('gestion:lista_ordenes')).context
        self.assertTrue(contexto['is_paginated'])
        self.assertEqual(len(contexto['ordenes']), 20)
        self.assertTrue(contexto['pagina_rango'])

    def test_los_listados_conservan_el_filtro_al_cambiar_de_pagina(self):
        for _ in range(21):
            self._orden(self.otro)
        contexto = self.client.get(reverse('gestion:lista_ordenes'),
                                   {'q': 'Aseo', 'page': 2}).context
        self.assertEqual(contexto['current_estado'], '')
        self.assertEqual(len(contexto['ordenes']), 1)


# ============================================================
#  PANTALLAS QUE NO PUEDEN ROMPERSE (humo)
# ============================================================
class PantallasPrincipalesTests(BaseCRM):
    """Las vistas con más consultas: que rendericen con y sin datos."""

    def setUp(self):
        self.admin = self.persona('admin', 'Administradores')

    def test_el_tablero_carga_con_la_base_vacia(self):
        self.entrar(self.admin)
        self.assertEqual(self.client.get(reverse('gestion:dashboard')).status_code, 200)

    def test_el_tablero_carga_con_un_servicio_completo(self):
        datos = self.servicio_completo()
        Manifiesto.objects.create(recorrido=datos['recorrido'], estado_firma='FIRMADO')
        EncuestaConductor.objects.create(
            recorrido=datos['recorrido'], presento_fatiga='SI',
            realizo_pausas_activas='NO', molestias_fisicas='NO',
            tiempos_adecuados='SI', cabina_optima='SI',
            zonas_seguras_descanso='SI', condicion_riesgo='SI',
            tipo_incidente='FALLA_MECANICA', descripcion_incidente='Varada')
        self.entrar(self.admin)
        self.assertEqual(self.client.get(reverse('gestion:dashboard')).status_code, 200)

    def test_las_pantallas_de_gestion_abren(self):
        datos = self.servicio_completo()
        self.entrar(self.admin)
        pantallas = [
            ('gestion:lista_ordenes', []),
            ('gestion:detalle_orden', [datos['orden'].pk]),
            ('gestion:lista_programaciones', []),
            ('gestion:crear_programacion', []),
            ('gestion:lista_clientes', []),
            ('gestion:crear_cliente', []),
            ('gestion:lista_vehiculos', []),
            ('gestion:detalle_vehiculo', [datos['camion'].pk]),
            ('gestion:lista_personal', []),
            ('gestion:ficha_persona', [datos['conductor'].pk]),
            ('gestion:historial_seguridad_social', [datos['conductor'].pk]),
            ('gestion:documentacion', []),
            ('gestion:lista_dispositores', []),
            ('gestion:lista_proveedores', []),
            ('gestion:centro_correos', []),
            ('gestion:crear_envio_correo', []),
            ('gestion:calendario', []),
            ('gestion:reportes', []),
            ('gestion:orden_historica', []),
            ('gestion:actualizar_orden', [datos['orden'].pk]),
        ]
        for nombre, args in pantallas:
            with self.subTest(pantalla=nombre):
                self.assertEqual(
                    self.client.get(reverse(nombre, args=args)).status_code, 200)

    def test_los_reportes_responden_a_cada_tipo(self):
        self.servicio_completo()
        self.entrar(self.admin)
        for reporte in ('facturacion_cliente', 'servicios_vehiculo'):
            with self.subTest(reporte=reporte):
                respuesta = self.client.get(reverse('gestion:reportes'),
                                            {'report_type': reporte})
                self.assertEqual(respuesta.status_code, 200)


# ============================================================
#  PLANTILLAS: ERRORES QUE DJANGO NO AVISA
# ============================================================
class PlantillasTests(TestCase):
    """
    Dos trampas que ya se colaron en producción: los comentarios `{# #}` de
    varias líneas (se imprimen tal cual en la página) y el CSS/JS que asume
    que los widgets múltiples de Django son `ul/li` (desde Django 4 son
    `div > label > input`, así que falla en silencio).
    """

    @staticmethod
    def plantillas():
        from django.conf import settings
        rutas = []
        for app in ('gestion', 'planes'):
            patron = os.path.join(settings.BASE_DIR, app, 'templates', '**', '*.html')
            rutas.extend(glob.glob(patron, recursive=True))
        return rutas

    def test_hay_plantillas_que_revisar(self):
        self.assertGreater(len(self.plantillas()), 20)

    def test_ningun_comentario_de_plantilla_queda_abierto_en_su_linea(self):
        rotos = []
        for ruta in self.plantillas():
            with open(ruta, encoding='utf-8') as f:
                for numero, linea in enumerate(f, 1):
                    if '{#' in linea and '#}' not in linea.split('{#', 1)[1]:
                        rotos.append(f"{os.path.basename(ruta)}:{numero}")
        self.assertEqual(rotos, [], "esos comentarios se verán como texto en la página")

    def test_ningun_javascript_asume_que_los_widgets_son_listas(self):
        sospechosos = []
        patrones = (re.compile(r"closest\(\s*['\"]li['\"]"),
                    re.compile(r"querySelectorAll\(\s*['\"][^'\"]*\bli\b"))
        for ruta in self.plantillas():
            contenido = open(ruta, encoding='utf-8').read()
            if any(p.search(contenido) for p in patrones):
                sospechosos.append(os.path.basename(ruta))
        self.assertEqual(sospechosos, [],
                         "los RadioSelect/CheckboxSelectMultiple son div>label>input")


# ============================================================
#  CONFIGURACIÓN Y PUERTAS DE ENTRADA
# ============================================================
class ConfiguracionYAccesoTests(BaseCRM):

    # Páginas que a propósito se abren SIN iniciar sesión.
    PUBLICAS = {
        'gestion:encuesta_publica',       # el cliente firma con su token
        'gestion:acceso_ayudante',        # el ayudante entra con su token
    }

    def test_ninguna_pantalla_nueva_queda_abierta_sin_querer(self):
        """
        Barrido: toda URL de la app sin parámetros debe exigir sesión, salvo la
        lista blanca de arriba. Si alguien agrega una vista sin su mixin, esta
        prueba lo detecta.
        """
        from gestion.urls import urlpatterns
        abiertas = []
        for patron in urlpatterns:
            nombre = f"gestion:{patron.name}"
            if patron.pattern.regex.groups:      # necesita argumentos: se omite
                continue
            if nombre in self.PUBLICAS:
                continue
            respuesta = self.client.get(reverse(nombre))
            if respuesta.status_code == 200:
                abiertas.append(nombre)
        self.assertEqual(abiertas, [])

    def test_el_modulo_de_demostracion_ya_no_existe(self):
        """Se eliminó (ago-2026): abría pantallas del sistema sin iniciar sesión."""
        from django.urls import NoReverseMatch
        for nombre in ('gestion:demo_orden_conductor', 'gestion:demo_conductor_datos',
                       'gestion:demo_conductor_cierre', 'gestion:demo_conductor_qr',
                       'gestion:demo_conductor_encuesta', 'gestion:demo_encuesta_cliente',
                       'gestion:demo_conductor_reiniciar'):
            with self.subTest(url=nombre):
                with self.assertRaises(NoReverseMatch):
                    reverse(nombre)
        for ruta in ('/app/demo/orden-conductor/', '/app/demo/encuesta-cliente/'):
            with self.subTest(ruta=ruta):
                self.assertEqual(self.client.get(ruta).status_code, 404)

    def test_los_roles_del_sistema_se_crean_solos(self):
        esperados = {'Administradores', 'Asesores', 'Conductores', 'Ayudantes',
                     'Planificadores', 'Talento Humano', 'Director Técnico',
                     'SISO', 'Soldador - Armador', 'Auxiliares Administrativas',
                     'Administrativo'}
        existentes = set(Group.objects.values_list('name', flat=True))
        self.assertTrue(esperados.issubset(existentes))

    def test_los_numeros_de_orden_no_llevan_separador_de_miles(self):
        from django.conf import settings
        self.assertFalse(settings.USE_THOUSAND_SEPARATOR,
                         "con separador el número de orden se pinta '#22.207'")

    def test_la_zona_horaria_es_la_de_bogota(self):
        from django.conf import settings
        self.assertEqual(settings.TIME_ZONE, 'America/Bogota')
        self.assertEqual(settings.LANGUAGE_CODE, 'es-co')

    def test_las_fechas_del_dia_se_calculan_en_hora_local(self):
        """
        `timezone.now().date()` daba el día en UTC: de noche adelantaba la fecha
        en Bogotá y le escondía al conductor los recorridos de hoy.
        """
        fuente = open(os.path.join('gestion', 'views.py'), encoding='utf-8').read()
        self.assertNotIn('timezone.now().date()', fuente)

    def test_una_cuenta_inactiva_no_puede_entrar(self):
        ayudante = self.persona('ayudante', 'Ayudantes')
        ayudante.is_active = False
        ayudante.save()
        self.assertFalse(self.client.login(username=ayudante.username, password=CLAVE))


# ============================================================
#  EXPEDIENTE DE LA ORDEN: GESTIÓN COMPLETA LO QUE FALTA
# ============================================================
class ExpedienteDeLaOrdenTests(BaseCRM):
    """El asesor puede cerrar el servicio aunque el conductor o el ayudante no puedan."""

    def setUp(self):
        datos = self.servicio_completo()
        self.__dict__.update(datos)
        self.ayudante = self.persona('ayudante', 'Ayudantes', 'Luis', 'Gómez')
        self.cuadrilla = self.programacion.cuadrillas.get()
        self.cuadrilla.ayudante = self.ayudante
        self.cuadrilla.ayudante_novedad = 'INICIA_CLIENTE'
        self.cuadrilla.save()
        self.recorrido.ayudante = self.ayudante
        self.recorrido.save()
        self.url = reverse('gestion:detalle_orden', args=[self.orden.pk])
        self.entrar(self.asesor)

    def test_el_asesor_sube_el_tiquete_de_bascula_que_falta(self):
        self.orden.bascula = 'PESAN'
        self.orden.save()
        self.client.post(self.url, {'submit_bascula': '1',
                                    'bascula_adjunto': imagen('tiquete.png')})
        self.orden.refresh_from_db()
        self.assertTrue(self.orden.bascula_adjunto.name)

    def test_el_asesor_sube_las_fotos_pendientes_del_ayudante(self):
        self.client.post(self.url, {
            'submit_foto_ayudante': '1', 'cuadrilla': self.cuadrilla.pk,
            'slot': '1', 'novedad': 'INICIA_CLIENTE',
            'fotos_ayudante': [imagen('llegada.png')]})
        foto = FotoAyudante.objects.get()
        self.assertEqual(foto.persona, self.ayudante)

    def test_no_se_cargan_fotos_de_novedades_que_nadie_pidio(self):
        self.client.post(self.url, {
            'submit_foto_ayudante': '1', 'cuadrilla': self.cuadrilla.pk,
            'slot': '1', 'novedad': 'TERMINA_CLIENTE',
            'fotos_ayudante': [imagen('otra.png')]})
        self.assertFalse(FotoAyudante.objects.exists())

    def test_el_asesor_sube_las_fotos_aunque_el_enlace_del_ayudante_ya_vencio(self):
        vencida = ProgramacionCuadrilla.DIAS_VIGENCIA_ACCESO + 5
        self.programacion.fecha = timezone.localdate() - datetime.timedelta(days=vencida)
        self.programacion.save()
        self.client.post(self.url, {
            'submit_foto_ayudante': '1', 'cuadrilla': self.cuadrilla.pk,
            'slot': '1', 'novedad': 'INICIA_CLIENTE',
            'fotos_ayudante': [imagen('tarde.png')]})
        self.assertTrue(FotoAyudante.objects.exists())

    def test_reenviar_el_correo_al_conductor_del_recorrido(self):
        mail.outbox.clear()
        self.client.post(self.url, {'submit_reenviar_conductor': '1',
                                    'recorrido': self.recorrido.pk})
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, [self.conductor.email])

    def test_el_correo_se_le_manda_al_conductor_nuevo_si_lo_cambiaron(self):
        nuevo = self.persona('conductor2', 'Conductores', 'Diana', 'Lopez')
        self.recorrido.conductor = nuevo
        self.recorrido.save()
        mail.outbox.clear()
        self.client.post(self.url, {'submit_reenviar_conductor': '1',
                                    'recorrido': self.recorrido.pk})
        self.assertEqual(mail.outbox[0].to, [nuevo.email])

    def test_sin_correo_registrado_no_se_reenvia_nada(self):
        self.conductor.email = ''
        self.conductor.save()
        mail.outbox.clear()
        self.client.post(self.url, {'submit_reenviar_conductor': '1',
                                    'recorrido': self.recorrido.pk})
        self.assertEqual(len(mail.outbox), 0)

    def test_reenviar_al_ayudante_le_manda_su_enlace_con_token(self):
        mail.outbox.clear()
        self.client.post(self.url, {'submit_reenviar_ayudante': '1',
                                    'cuadrilla': self.cuadrilla.pk, 'slot': '1'})
        self.assertEqual(len(mail.outbox), 1)
        correo = mail.outbox[0]
        cuerpo = correo.body + ' '.join(str(a) for a, _ in correo.alternatives)
        self.assertEqual(correo.to, [self.ayudante.email])
        self.assertIn(str(self.cuadrilla.token_ayudante), cuerpo)
        self.assertNotIn(self.cli.nombre, cuerpo, "al ayudante no le llega el cliente")

    def test_se_adjuntan_documentos_a_la_orden(self):
        self.client.post(self.url, {'submit_documento': '1',
                                    'archivo': archivo('anexo.pdf'),
                                    'descripcion': 'Anexo del servicio'})
        self.assertEqual(self.orden.documentos.count(), 1)

    def test_el_expediente_muestra_el_acta_y_sus_pendientes(self):
        respuesta = self.client.get(self.url)
        self.assertEqual(respuesta.status_code, 200)
        self.assertEqual(respuesta.context['orden'], self.orden)


# ============================================================
#  PUERTAS QUE DEBEN SEGUIR CERRADAS
# ============================================================
class PuertasCerradasTests(BaseCRM):
    """Decisiones del negocio que se pierden fácil al tocar el código."""

    def setUp(self):
        datos = self.servicio_completo()
        self.__dict__.update(datos)

    def test_no_existe_una_via_para_crear_ordenes_a_mano(self):
        from django.urls import NoReverseMatch
        for nombre in ('gestion:crear_orden', 'gestion:nueva_orden',
                       'gestion:agregar_recorrido'):
            with self.subTest(url=nombre):
                with self.assertRaises(NoReverseMatch):
                    reverse(nombre)

    def test_el_expediente_de_la_orden_no_agrega_recorridos(self):
        self.entrar(self.asesor)
        antes = Recorrido.objects.count()
        self.client.post(reverse('gestion:detalle_orden', args=[self.orden.pk]), {
            'submit_recorrido': '1', 'vehiculo': self.camion.pk,
            'conductor': self.conductor.pk,
            'fecha_recorrido': timezone.localdate().isoformat(),
        })
        self.assertEqual(Recorrido.objects.count(), antes)

    def test_un_doble_envio_del_asistente_no_duplica_el_acta(self):
        self.entrar(self.conductor)
        url = reverse('gestion:firmar_manifiesto_step',
                      args=[self.recorrido.pk, 'paso3'])
        datos = {'tiempo_inicio_operativo': '07:00', 'tiempo_final_operativo': '11:00',
                 'hora_salida_solmed': '', 'hora_llegada_empresa': '',
                 'hora_llegada_disposicion': '', 'hora_llegada_solmed': '',
                 'tiempo_llegada_disposicion': '', 'tiempo_salida_disposicion': ''}
        self.client.post(url, datos)
        self.client.post(url, datos)
        self.assertEqual(Manifiesto.objects.filter(recorrido=self.recorrido).count(), 1)

    def test_un_paso_inventado_del_asistente_no_hace_nada(self):
        self.entrar(self.conductor)
        respuesta = self.client.get(reverse('gestion:firmar_manifiesto_step',
                                            args=[self.recorrido.pk, 'paso9']))
        self.assertEqual(respuesta.status_code, 302)
        self.assertFalse(Manifiesto.objects.exists())

    def test_un_cliente_con_ordenes_no_se_puede_eliminar(self):
        admin = self.persona('admin', 'Administradores')
        self.entrar(admin)
        self.client.post(reverse('gestion:eliminar_cliente', args=[self.cli.pk]))
        self.assertTrue(Cliente.objects.filter(pk=self.cli.pk).exists())

    def test_un_cliente_sin_movimientos_si_se_elimina(self):
        admin = self.persona('admin', 'Administradores')
        nuevo = self.cliente('Cliente sin uso', identificacion='800-31')
        self.entrar(admin)
        self.client.post(reverse('gestion:eliminar_cliente', args=[nuevo.pk]))
        self.assertFalse(Cliente.objects.filter(pk=nuevo.pk).exists())

    def test_una_persona_que_ya_prestó_servicios_no_se_elimina(self):
        admin = self.persona('admin', 'Administradores')
        self.entrar(admin)
        self.client.post(reverse('gestion:eliminar_persona', args=[self.conductor.pk]))
        self.assertTrue(User.objects.filter(pk=self.conductor.pk).exists())

    def test_nadie_elimina_su_propia_cuenta_ni_la_de_un_superadministrador(self):
        admin = self.persona('admin', 'Administradores')
        root = self.persona('root', superusuario=True)
        self.entrar(admin)
        self.client.post(reverse('gestion:eliminar_persona', args=[admin.pk]))
        self.client.post(reverse('gestion:eliminar_persona', args=[root.pk]))
        self.assertTrue(User.objects.filter(pk=admin.pk).exists())
        self.assertTrue(User.objects.filter(pk=root.pk).exists())


# ============================================================
#  HISTORIAL DE SEGURIDAD SOCIAL
# ============================================================
class HistorialSeguridadSocialTests(BaseCRM):

    def setUp(self):
        self.asesor = self.persona('asesor', 'Asesores')
        self.conductor = self.persona('conductor', 'Conductores', 'Carlos', 'Pérez')
        self.entrar(self.asesor)
        self.url = reverse('gestion:historial_seguridad_social',
                           args=[self.conductor.pk])

    def test_lista_todas_las_cargas_con_su_estado(self):
        hoy = timezone.localdate()
        DocumentoPersonal.objects.create(
            usuario=self.conductor, tipo='SEGURIDAD_SOCIAL', archivo=archivo(),
            fecha_vencimiento=hoy - datetime.timedelta(days=40))
        DocumentoPersonal.objects.create(
            usuario=self.conductor, tipo='SEGURIDAD_SOCIAL', archivo=archivo(),
            fecha_vencimiento=hoy + datetime.timedelta(days=20))
        DocumentoPersonal.objects.create(
            usuario=self.conductor, tipo='CEDULA', archivo=archivo())

        contexto = self.client.get(self.url).context
        self.assertEqual(contexto['total'], 2, "solo la seguridad social")
        self.assertTrue(contexto['al_dia'])
        self.assertEqual(sum(1 for r in contexto['registros'] if r['vigente']), 1)

    def test_sin_ninguna_vigente_avisa_que_no_esta_al_dia(self):
        DocumentoPersonal.objects.create(
            usuario=self.conductor, tipo='SEGURIDAD_SOCIAL', archivo=archivo(),
            fecha_vencimiento=timezone.localdate() - datetime.timedelta(days=1))
        self.assertFalse(self.client.get(self.url).context['al_dia'])

    def test_borrar_una_carga_devuelve_al_historial(self):
        documento = DocumentoPersonal.objects.create(
            usuario=self.conductor, tipo='SEGURIDAD_SOCIAL', archivo=archivo(),
            fecha_vencimiento=timezone.localdate() + datetime.timedelta(days=10))
        respuesta = self.client.post(
            reverse('gestion:eliminar_documento_personal', args=[documento.pk]),
            {'origen': 'seguridad_social'})
        self.assertRedirects(respuesta, self.url)
        self.assertFalse(DocumentoPersonal.objects.filter(pk=documento.pk).exists())


# ============================================================
#  EL TABLERO: SOLO ADMINISTRADORES (decisión del usuario, ago-2026)
# ============================================================
class TableroSoloAdministradoresTests(BaseCRM):
    """
    El tablero resume TODO el negocio (cobranza, top de clientes, agenda con
    clientes y placas). Lo ven el superusuario y el rol 'Administradores', y
    NADIE más: da igual el método, la URL escrita a mano o el rol que se tenga.
    """

    # Todos los roles del sistema que NO deben ver el tablero.
    ROLES_SIN_ACCESO = [
        'Asesores', 'Planificadores', 'Conductores', 'Talento Humano',
        'Director Técnico', 'SISO', 'Soldador - Armador',
        'Auxiliares Administrativas', 'Administrativo', 'Ayudantes',
    ]

    def setUp(self):
        self.url = reverse('gestion:dashboard')

    def test_el_superusuario_y_el_administrador_si_entran(self):
        for username, rol, superusuario in (('root', None, True),
                                            ('admin', 'Administradores', False)):
            with self.subTest(usuario=username):
                self.entrar(self.persona(username, rol, superusuario=superusuario))
                self.assertEqual(self.client.get(self.url).status_code, 200)

    def test_ningun_otro_rol_entra_ni_escribiendo_la_url(self):
        for i, rol in enumerate(self.ROLES_SIN_ACCESO):
            with self.subTest(rol=rol):
                self.entrar(self.persona(f'usuario{i}', rol))
                self.assertEqual(self.client.get(self.url).status_code, 403)
                self.assertEqual(self.client.get('/app/').status_code, 403)

    def test_un_usuario_sin_rol_tampoco_entra(self):
        self.entrar(self.persona('suelto'))
        self.assertEqual(self.client.get(self.url).status_code, 403)

    def test_tener_varios_roles_no_abre_la_puerta(self):
        persona = self.persona('asesor_plani', 'Asesores')
        persona.groups.add(self.grupo('Planificadores'), self.grupo('Talento Humano'))
        self.entrar(persona)
        self.assertEqual(self.client.get(self.url).status_code, 403)

    def test_sin_iniciar_sesion_va_al_login_y_no_ve_nada(self):
        respuesta = self.client.get(self.url)
        self.assertEqual(respuesta.status_code, 302)
        self.assertIn('/login/', respuesta.url)
        self.assertNotContains(self.client.get(self.url, follow=True),
                               'Cobranza', status_code=200)

    def test_el_bloqueo_no_depende_del_metodo(self):
        self.entrar(self.persona('asesor', 'Asesores'))
        self.assertEqual(self.client.get(self.url).status_code, 403)
        self.assertEqual(self.client.post(self.url, {}).status_code, 403)
        self.assertEqual(self.client.head(self.url).status_code, 403)
        self.assertEqual(self.client.options(self.url).status_code, 403)

    def test_al_iniciar_sesion_nadie_mas_aterriza_en_el_tablero(self):
        destinos = {
            'Asesores': reverse('gestion:lista_ordenes'),
            'Planificadores': reverse('gestion:planificacion'),
            'Conductores': reverse('gestion:dashboard_conductor'),
            'Talento Humano': reverse('gestion:lista_personal'),
            'SISO': reverse('gestion:sin_acceso'),
            'Director Técnico': reverse('gestion:sin_acceso'),
        }
        for i, (rol, destino) in enumerate(destinos.items()):
            with self.subTest(rol=rol):
                self.entrar(self.persona(f'aterriza{i}', rol))
                # Ni por la raíz del sitio ni por el redirector del login.
                for entrada in ('/', reverse('gestion:dashboard_redirect')):
                    respuesta = self.client.get(entrada, follow=True)
                    recorrido = [url for url, _codigo in respuesta.redirect_chain]
                    self.assertEqual(recorrido[-1], destino)
                    self.assertNotIn(self.url, recorrido)

    def test_el_administrador_si_aterriza_en_el_tablero(self):
        self.entrar(self.persona('admin', 'Administradores'))
        respuesta = self.client.get('/', follow=True)
        self.assertEqual(respuesta.redirect_chain[-1][0], self.url)
        self.assertEqual(respuesta.status_code, 200)

    def test_el_menu_solo_le_ofrece_el_tablero_al_administrador(self):
        self.entrar(self.persona('admin', 'Administradores'))
        self.assertContains(self.client.get(self.url), 'Tablero')

        self.entrar(self.persona('asesor', 'Asesores'))
        self.assertNotContains(self.client.get(reverse('gestion:lista_ordenes')),
                               'Tablero')

    def test_las_cifras_del_tablero_no_se_filtran_por_otra_pantalla(self):
        """Ninguna otra vista publica la plantilla del tablero."""
        fuente = open(os.path.join('gestion', 'views.py'), encoding='utf-8').read()
        self.assertEqual(fuente.count("'gestion/dashboard.html'"), 1)


# ============================================================
#  CLIENTES, ÓRDENES, PROGRAMACIÓN Y VEHÍCULOS: SOLO GESTIÓN
#  (decisión del usuario, ago-2026)
# ============================================================
class SoloGestionVeLaOperacionTests(BaseCRM):
    """
    La información del negocio —quién es el cliente, qué se le prestó, con qué
    camión y cuándo— es de superusuario, Administradores y Asesores. Ningún
    otro rol la ve, ni escribiendo la URL. Excepciones deliberadas: el
    CONDUCTOR ve SU servicio (sin datos del cliente) y el PLANIFICADOR conserva
    su tablero de planificación.
    """

    def setUp(self):
        datos = self.servicio_completo()
        self.__dict__.update(datos)
        self.admin = self.persona('admin', 'Administradores')
        self.root = self.persona('root', superusuario=True)
        self.planificador = self.persona('plani', 'Planificadores')
        self.talento = self.persona('talento', 'Talento Humano')
        self.siso = self.persona('siso', 'SISO')
        Manifiesto.objects.create(recorrido=self.recorrido,
                                  tiempo_inicio_operativo=datetime.time(7, 0))

    def pantallas(self):
        """Todo lo que expone clientes, órdenes, programación o vehículos."""
        return {
            'clientes': reverse('gestion:lista_clientes'),
            'cliente nuevo': reverse('gestion:crear_cliente'),
            'expediente del cliente': reverse('gestion:ficha_cliente', args=[self.cli.pk]),
            'órdenes': reverse('gestion:lista_ordenes'),
            'expediente de la orden': reverse('gestion:detalle_orden', args=[self.orden.pk]),
            'editar la orden': reverse('gestion:actualizar_orden', args=[self.orden.pk]),
            'editar el recorrido': reverse('gestion:editar_recorrido', args=[self.recorrido.pk]),
            'acta en formato': reverse('gestion:acta_formato', args=[self.recorrido.pk]),
            'acta en PDF': reverse('gestion:acta_pdf', args=[self.recorrido.pk]),
            'programaciones': reverse('gestion:lista_programaciones'),
            'programación nueva': reverse('gestion:crear_programacion'),
            'vehículos': reverse('gestion:lista_vehiculos'),
            'expediente del vehículo': reverse('gestion:detalle_vehiculo', args=[self.camion.pk]),
            'vehículo nuevo': reverse('gestion:crear_vehiculo'),
            'calendario': reverse('gestion:calendario'),
        }

    def test_gestion_si_ve_todo(self):
        for usuario in (self.root, self.admin, self.asesor):
            self.entrar(usuario)
            for nombre, url in self.pantallas().items():
                with self.subTest(usuario=usuario.username, pantalla=nombre):
                    self.assertEqual(self.client.get(url).status_code, 200)

    def test_ningun_otro_rol_la_ve_ni_escribiendo_la_url(self):
        for usuario in (self.planificador, self.talento, self.siso, self.conductor):
            self.entrar(usuario)
            for nombre, url in self.pantallas().items():
                if usuario is self.conductor and nombre == 'calendario':
                    continue      # el conductor conserva SU calendario
                with self.subTest(usuario=usuario.username, pantalla=nombre):
                    self.assertEqual(self.client.get(url).status_code, 403)

    def test_sin_iniciar_sesion_nada_de_esto_se_abre(self):
        for nombre, url in self.pantallas().items():
            with self.subTest(pantalla=nombre):
                respuesta = self.client.get(url)
                self.assertEqual(respuesta.status_code, 302)
                self.assertIn('/login/', respuesta.url)

    def test_tampoco_pueden_modificar_nada_por_post(self):
        acciones = {
            reverse('gestion:eliminar_recorrido', args=[self.recorrido.pk]): {},
            reverse('gestion:actualizar_orden', args=[self.orden.pk]): {},
            reverse('gestion:crear_programacion'): {},
            reverse('gestion:crear_vehiculo'): {'placa': 'COL999', 'marca': 'X',
                                                'modelo': '2020', 'capacidad': '1',
                                                'estado': 'OPERATIVO'},
        }
        for usuario in (self.planificador, self.siso, self.conductor, self.talento):
            self.entrar(usuario)
            for url, datos in acciones.items():
                with self.subTest(usuario=usuario.username, url=url):
                    self.assertEqual(self.client.post(url, datos).status_code, 403)
        self.assertFalse(Vehiculo.objects.filter(placa='COL999').exists())
        self.assertTrue(Recorrido.objects.filter(pk=self.recorrido.pk).exists())

    def test_el_pdf_de_la_encuesta_de_cierre_tampoco_se_reparte(self):
        """Lleva el número de orden y el nombre del cliente."""
        EncuestaConductor.objects.create(
            recorrido=self.recorrido, presento_fatiga='NO',
            realizo_pausas_activas='SI', molestias_fisicas='NO',
            tiempos_adecuados='SI', cabina_optima='SI',
            zonas_seguras_descanso='SI', condicion_riesgo='NO')
        url = reverse('gestion:encuesta_conductor_pdf', args=[self.recorrido.pk])

        for usuario in (self.root, self.admin, self.asesor, self.conductor):
            with self.subTest(usuario=usuario.username):
                self.entrar(usuario)
                self.assertEqual(self.client.get(url).status_code, 200)

        for usuario in (self.planificador, self.siso, self.talento):
            with self.subTest(usuario=usuario.username):
                self.entrar(usuario)
                self.assertEqual(self.client.get(url).status_code, 403)

        self.entrar(self.persona('conductor9', 'Conductores'))
        self.assertEqual(self.client.get(url).status_code, 404)

    def test_el_planificador_conserva_su_tablero_de_planificacion(self):
        """Excepción acordada: el rol existe para repartir camiones y conductores."""
        self.entrar(self.planificador)
        respuesta = self.client.get(reverse('gestion:planificacion'))
        self.assertEqual(respuesta.status_code, 200)
        self.assertIn(self.recorrido, respuesta.context['recorridos_del_dia'])

    def test_el_conductor_conserva_su_propio_servicio(self):
        self.entrar(self.conductor)
        for url in (reverse('gestion:detalle_orden_conductor', args=[self.orden.pk]),
                    reverse('gestion:mis_recorridos'),
                    reverse('gestion:firmar_manifiesto_step',
                            args=[self.recorrido.pk, 'paso3']),
                    reverse('gestion:manifiesto_qr', args=[self.recorrido.pk])):
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 200)

    def test_el_calendario_solo_reparte_eventos_a_quien_debe(self):
        url = reverse('gestion:feed_calendario')

        self.entrar(self.asesor)
        self.assertEqual(len(self.client.get(url).json()), 1)

        self.entrar(self.conductor)
        self.assertEqual(len(self.client.get(url).json()), 1, "los suyos sí")

        otro_conductor = self.persona('conductor9', 'Conductores')
        self.entrar(otro_conductor)
        self.assertEqual(self.client.get(url).json(), [])

        for usuario in (self.planificador, self.siso, self.talento):
            with self.subTest(usuario=usuario.username):
                self.entrar(usuario)
                self.assertEqual(self.client.get(url).status_code, 403)

    def test_el_menu_no_le_ofrece_al_planificador_lo_que_no_puede_abrir(self):
        self.entrar(self.planificador)
        contenido = self.client.get(reverse('gestion:planificacion')).content.decode()
        # Se comprueban los ENLACES del menú (las palabras sueltas también
        # aparecen en el contenido de la propia página de planificación).
        for seccion in ('lista_ordenes', 'lista_clientes', 'lista_vehiculos',
                        'lista_programaciones', 'centro_correos', 'calendario',
                        'dashboard'):
            with self.subTest(seccion=seccion):
                self.assertNotIn(f'href="{reverse("gestion:" + seccion)}"', contenido)
        self.assertIn(f'href="{reverse("gestion:planificacion")}"', contenido)


# ============================================================
#  CUENTAS SIN MÓDULOS ASIGNADOS
# ============================================================
class CuentasSinModulosTests(BaseCRM):
    """
    Director Técnico, SISO, Soldador, Auxiliares Administrativas y
    Administrativo existen por su expediente: entran y no ven nada más.
    """

    CARGOS = ['Director Técnico', 'SISO', 'Soldador - Armador',
              'Auxiliares Administrativas', 'Administrativo']

    def test_al_entrar_aterrizan_en_su_pantalla_y_no_en_un_error(self):
        for i, cargo in enumerate(self.CARGOS):
            with self.subTest(cargo=cargo):
                self.entrar(self.persona(f'cargo{i}', cargo, nombre='Pedro'))
                respuesta = self.client.get('/', follow=True)
                self.assertEqual(respuesta.redirect_chain[-1][0],
                                 reverse('gestion:sin_acceso'))
                self.assertEqual(respuesta.status_code, 200)
                self.assertContains(respuesta, 'expediente')

    def test_su_pantalla_no_muestra_ni_un_dato_de_la_operacion(self):
        datos = self.servicio_completo()
        self.entrar(self.persona('siso', 'SISO'))
        contenido = self.client.get(reverse('gestion:sin_acceso')).content.decode()
        self.assertNotIn(datos['cli'].nombre, contenido)
        self.assertNotIn(str(datos['orden'].numero_orden), contenido)
        self.assertNotIn(datos['camion'].placa, contenido)
        # Tampoco el menú lateral con secciones que no puede abrir.
        self.assertNotIn('Órdenes de servicio', contenido)

    def test_la_pantalla_exige_haber_iniciado_sesion(self):
        respuesta = self.client.get(reverse('gestion:sin_acceso'))
        self.assertEqual(respuesta.status_code, 302)
        self.assertIn('/login/', respuesta.url)
