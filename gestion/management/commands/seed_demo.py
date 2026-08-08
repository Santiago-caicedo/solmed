"""
Siembra datos de demostración para VER cómo queda el PDF del acta de servicio:
clientes de prueba y programaciones ya convertidas en órdenes, con el acta
(manifiesto) llena y firmada y su PDF generado.

Uso:
    python manage.py seed_demo            # crea la demo si aún no existe
    python manage.py seed_demo --recrear  # borra la demo anterior y la vuelve a crear

Marca las órdenes demo con "[DEMO]" en la descripción para poder limpiarlas.
Para verlas: entra a Órdenes y abre el "Ver PDF" del acta de servicio.
"""
import base64
import datetime
import math
import os
from io import BytesIO

from django.contrib.auth.models import Group, User
from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand
from django.template.loader import get_template
from django.utils import timezone
from weasyprint import HTML

from gestion.forms import generar_username
from gestion.models import (
    Cliente, DocumentoPersonal, Manifiesto, OrdenServicio, PerfilPersona,
    Programacion, ProgramacionCuadrilla, Sede, Vehiculo,
)

MARCA_DEMO = '[DEMO]'


def _firma_png(texto_semilla):
    """Genera una firma manuscrita simulada (PNG) para el acta."""
    from PIL import Image, ImageDraw
    img = Image.new('RGBA', (260, 80), (255, 255, 255, 0))
    d = ImageDraw.Draw(img)
    fase = sum(ord(c) for c in texto_semilla) % 7
    pts = []
    for x in range(12, 248, 4):
        y = 45 + int(20 * math.sin((x + fase * 10) / 13.0)) - (x // 60) * 3
        pts.append((x, y))
    d.line(pts, fill=(20, 40, 120, 255), width=2, joint='curve')
    # un trazo final
    d.line([(180, 60), (240, 30)], fill=(20, 40, 120, 255), width=2)
    buf = BytesIO()
    img.save(buf, format='PNG')
    return buf.getvalue()


class Command(BaseCommand):
    help = "Siembra clientes y órdenes demo con actas de servicio llenas y su PDF, para ver el formato."

    def add_arguments(self, parser):
        parser.add_argument('--recrear', action='store_true',
                            help='Borra la demo anterior y la crea de nuevo.')

    def handle(self, *args, **options):
        self.hoy = timezone.localdate()
        for nombre in ('Conductores', 'Ayudantes', 'Asesores'):
            Group.objects.get_or_create(name=nombre)

        if options['recrear']:
            self._wipe()

        if OrdenServicio.objects.filter(descripcion__startswith=MARCA_DEMO).exists():
            self.stdout.write(self.style.WARNING(
                "Ya hay órdenes demo. Usa --recrear para regenerarlas."))
            return

        asesor = User.objects.filter(is_superuser=True).first() \
            or User.objects.create_superuser('demo_admin', 'demo@solmed.com', 'Demo.2026')

        conductores = self._personal()
        vehiculos = self._vehiculos()
        clientes = self._clientes()

        servicios = self._servicios_demo()
        creadas = 0
        for i, serv in enumerate(servicios):
            cliente = clientes[i % len(clientes)]
            veh = vehiculos[i % len(vehiculos)]
            cond = conductores[i % len(conductores)]
            orden = self._crear_orden_demo(asesor, cliente, veh, cond, serv, i)
            creadas += 1
            self.stdout.write(self.style.SUCCESS(
                f"  Orden #{orden.numero_orden} — {cliente.nombre} — acta firmada y PDF generado."))

        self.stdout.write(self.style.SUCCESS(
            f"\nListo: {creadas} orden(es) demo con su acta de servicio en PDF.\n"
            "Entra a Órdenes y abre 'Ver PDF' del acta. Para regenerar: seed_demo --recrear"))

    # ---------------------------------------------------------------
    def _wipe(self):
        ordenes = OrdenServicio.objects.filter(descripcion__startswith=MARCA_DEMO)
        n = ordenes.count()
        # Borrar la orden arrastra recorridos, manifiestos y la programación (CASCADE).
        ordenes.delete()
        self.stdout.write(self.style.WARNING(f"  Borradas {n} orden(es) demo."))

    def _personal(self):
        datos = [
            ('Fredy Alonso', 'Peñaranda Bayona', '13924567'),
            ('Willian', 'Martínez Castañeda', '80234111'),
            ('Óscar Darío', 'Baldovino Fernández', '1098765001'),
        ]
        conductores = []
        for nombre, apellido, cedula in datos:
            u, creado = User.objects.get_or_create(
                username=f'c_{cedula}',
                defaults={'first_name': nombre, 'last_name': apellido, 'is_active': True})
            if creado:
                u.set_password('Solmed.2026'); u.save()
            u.groups.set([Group.objects.get(name='Conductores')])
            PerfilPersona.objects.update_or_create(
                usuario=u, defaults={'numero_documento': cedula, 'cargo': 'Conductor'})
            DocumentoPersonal.objects.get_or_create(
                usuario=u, tipo='SEGURIDAD_SOCIAL', descripcion=f'{MARCA_DEMO}SS',
                defaults={'archivo': ContentFile(b'%PDF-1.4 demo', name=f'ss_{cedula}.pdf'),
                          'fecha_vencimiento': self.hoy + datetime.timedelta(days=60)})
            conductores.append(u)
        return conductores

    def _vehiculos(self):
        datos = [
            ('WGY347', 'International', 'Vactor 2100'),
            ('OBC727', 'Kenworth', 'T800'),
            ('VCP886', 'Chevrolet', 'Kodiak'),
        ]
        vehiculos = []
        for placa, marca, modelo in datos:
            v, _ = Vehiculo.objects.get_or_create(
                placa=placa, defaults={'marca': marca, 'modelo': modelo, 'capacidad': '20 m³'})
            vehiculos.append(v)
        return vehiculos

    def _clientes(self):
        datos = [
            ('Crepes and Waffles Toberín', 'CW', '860518299', 'Kr 21 # 164-40', 'Bogotá', '6013001122'),
            ('D1 Ibagué Centro', 'D1', '900123456', 'Cra 5 # 10-20', 'Ibagué', '6082701020'),
            ('Ara Fusagasugá', 'ARA', '901234567', 'Cll 8 # 12-30', 'Fusagasugá', '6018901234'),
        ]
        clientes = []
        for nombre, sigla, nit, direccion, ciudad, tel in datos:
            c, _ = Cliente.objects.get_or_create(
                nombre=nombre,
                defaults={'sigla': sigla, 'identificacion': nit, 'direccion': direccion,
                          'ciudad': ciudad, 'telefono': tel, 'telefono_celular': tel})
            Sede.objects.get_or_create(
                cliente=c, nombre='Sede principal',
                defaults={'direccion': direccion, 'ciudad': ciudad})
            clientes.append(c)
        return clientes

    def _servicios_demo(self):
        """Datos de cada acta (variados) para que los PDFs se vean distintos."""
        return [
            dict(
                auxiliar1='Antonio Garzón',
                succ_pozos_inspeccion=True, succ_pozos_inspeccion_cant='2',
                sond_preventivo=True,
                lavado_concepto='Lavado', lavado_cantidad='Trampas', lavado_correctivo='Grasas',
                transporte_tipo='Lodos orgánicos', transporte_cantidad='8 m³',
                tiempo_inicio_operativo=datetime.time(4, 15), tiempo_final_operativo=datetime.time(7, 20),
                tiempo_llegada_disposicion=datetime.time(10, 46),
                km_salida_solmed=300, km_llegada_empresa=415, km_llegada_disposicion=1046, km_llegada_solmed=1135,
                evals=[4, 4, 4, 4, 4, 4, 4, 4, 4, 4, 4],
                observaciones='Mantenimiento general + tanques sótano. Descarga #1 - descarga #3 - '
                              'mantenimiento tanques PTAR. Carro sin mal olor.',
                nombre_responsable_empresa='Nicol Amaya', nombre_responsable_cliente='Fernando Torán',
            ),
            dict(
                auxiliar1='Camilo Rueda', auxiliar2='Jorge Niño',
                succ_pozos_septicos=True, succ_pozos_septicos_cant='5',
                sond_red_aguas_negras=True, sond_red_aguas_negras_cant='40',
                lavado_concepto='Preventivo', lavado_cantidad='3',
                transporte_tipo='Aguas residuales', transporte_cantidad='10 m³',
                tiempo_inicio_operativo=datetime.time(6, 0), tiempo_final_operativo=datetime.time(9, 30),
                tiempo_llegada_disposicion=datetime.time(11, 15),
                km_salida_solmed=120, km_llegada_empresa=180, km_llegada_disposicion=430, km_llegada_solmed=560,
                evals=[4, 4, 3, 4, 3, 4, 4, 3, 4, 4, 4],
                observaciones='Succión de pozo séptico y sondeo de red de aguas negras. '
                              'Se recomienda mantenimiento trimestral.',
                nombre_responsable_empresa='Nicol Amaya', nombre_responsable_cliente='Marcela Ríos',
            ),
            dict(
                auxiliar1='Luis Ortega',
                succ_tanques=True, succ_tanques_cant='3',
                succ_trampas_grasa=True, succ_trampas_grasa_cant='1',
                sond_red_acueducto=True, sond_red_acueducto_cant='25',
                lavado_concepto='Correctivo', lavado_correctivo='Tubería obstruida',
                transporte_tipo='RESPEL', transporte_cantidad='4 m³',
                tiempo_inicio_operativo=datetime.time(5, 30), tiempo_final_operativo=datetime.time(8, 45),
                tiempo_llegada_disposicion=datetime.time(10, 0),
                km_salida_solmed=210, km_llegada_empresa=260, km_llegada_disposicion=520, km_llegada_solmed=640,
                evals=[3, 4, 4, 4, 4, 4, 3, 4, 4, 4, 3],
                observaciones='Lavado correctivo de tubería y succión de trampa de grasa. '
                              'Cliente satisfecho con el servicio.',
                nombre_responsable_empresa='Diana Castaño', nombre_responsable_cliente='Andrés Muñoz',
            ),
        ]

    def _crear_orden_demo(self, asesor, cliente, veh, cond, serv, idx):
        fecha = self.hoy - datetime.timedelta(days=idx)
        prog = Programacion.objects.create(
            cliente=cliente, fecha=fecha, direccion=cliente.direccion, creado_por=asesor,
            correo_seguridad_social='cliente@ejemplo.com',
            observaciones_servicio=f'{MARCA_DEMO} Servicio de demostración',
            sede_cliente=cliente.sedes.first(),
        )
        ProgramacionCuadrilla.objects.create(programacion=prog, conductor=cond, vehiculo=veh)
        orden = prog.convertir_en_orden(asesor)
        # La descripción de la orden lleva la marca DEMO (para poder limpiarla).
        orden.descripcion = f'{MARCA_DEMO} Orden de demostración — {cliente.nombre}'
        orden.valor_servicio = 850000
        orden.save(update_fields=['descripcion', 'valor_servicio'])

        # Acta (manifiesto) llena y firmada para cada recorrido.
        campos_eval = [
            'eval_atencion', 'eval_amabilidad', 'eval_solucion_inquietudes', 'eval_asesoria',
            'eval_puntualidad', 'eval_calidad_servicio', 'eval_oportunidad',
            'eval_cumplimiento_condiciones', 'eval_solucion_problemas',
            'eval_volveria_contratar', 'eval_nos_recomendaria',
        ]
        for recorrido in orden.recorridos.all():
            datos = {k: v for k, v in serv.items() if k not in ('evals',)}
            datos.update({campos_eval[j]: serv['evals'][j] for j in range(len(campos_eval))})
            manifiesto = Manifiesto.objects.create(
                recorrido=recorrido, estado_firma='FIRMADO', **datos)
            firma = _firma_png(serv['nombre_responsable_cliente'])
            manifiesto.firma_cliente.save(
                f'firma_demo_{recorrido.pk}.png', ContentFile(firma), save=True)
            self._generar_pdf(manifiesto)
            recorrido.estado = 'COMPLETADO'
            recorrido.save()
        return orden

    def _generar_pdf(self, manifiesto):
        from django.conf import settings
        template = get_template('gestion/manifiesto_pdf.html')
        logo_path = os.path.join(settings.BASE_DIR, 'static', 'images', 'logo-solmed.png')
        with open(logo_path, 'rb') as f:
            logo_b64 = 'data:image/png;base64,' + base64.b64encode(f.read()).decode()
        firma_b64 = None
        if manifiesto.firma_cliente:
            with manifiesto.firma_cliente.open('rb') as f:
                firma_b64 = 'data:image/png;base64,' + base64.b64encode(f.read()).decode()
        recorrido = manifiesto.recorrido
        html = template.render({
            'manifiesto': manifiesto, 'recorrido': recorrido, 'orden': recorrido.orden,
            'logo_b64': logo_b64, 'firma_cliente_b64': firma_b64,
        })
        pdf = HTML(string=html).write_pdf()
        manifiesto.pdf_generado.save(
            f'acta_demo_recorrido_{recorrido.pk}.pdf', ContentFile(pdf), save=True)
