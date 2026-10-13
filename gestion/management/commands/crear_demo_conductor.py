"""
Crea un conductor de prueba con una orden de hoy asignada, para mostrarle al
equipo cómo es el proceso en la plataforma (oct-2026, capacitación).

Uso:
    python manage.py crear_demo_conductor                 # crea (o reutiliza) el conductor y una orden de hoy
    python manage.py crear_demo_conductor --nueva         # otra orden más para hoy
    python manage.py crear_demo_conductor --clave Otra.1  # con otra contraseña
    python manage.py crear_demo_conductor --borrar        # quita TODO lo de la demo

Es idempotente: correrlo dos veces no duplica el conductor, el camión ni el
cliente; la orden se reutiliza si ya hay una de hoy sin cerrar. Todo lo que
crea lleva la marca «DEMO CONDUCTOR», que es lo que --borrar busca.

La orden pide registro fotográfico en dos sedes, para que se vea la tarea
de fotos por sede; no pide báscula (eso lo sube la oficina).
"""
import datetime

from django.contrib.auth.models import Group, User
from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from gestion.models import (
    Cliente, DocumentoPersonal, OrdenServicio, PerfilPersona, Programacion,
    ProgramacionCuadrilla, Sede, Vehiculo,
)

MARCA = 'DEMO CONDUCTOR'
USUARIO = 'demo_conductor'
CLAVE = 'Demo.2026'
PLACA = 'DEMO001'
CLIENTE = 'Cliente de prueba (demo)'
SEDES = (('Sede Norte', 'Cl 170 # 8-20, Bogotá'), ('Sede Sur', 'Cra 10 # 20-30, Bogotá'))


class Command(BaseCommand):
    help = "Crea un conductor de prueba con una orden de hoy, para capacitar (--borrar la quita)."

    def add_arguments(self, parser):
        parser.add_argument('--usuario', default=USUARIO, help=f"Usuario del conductor (por defecto {USUARIO})")
        parser.add_argument('--clave', default=CLAVE, help=f"Contraseña del conductor (por defecto {CLAVE})")
        parser.add_argument('--nueva', action='store_true', help="Crea otra orden de hoy aunque ya haya una")
        parser.add_argument('--borrar', action='store_true', help="Borra el conductor, sus órdenes, el camión y el cliente de la demo")

    def handle(self, *args, **opciones):
        if opciones['borrar']:
            return self._borrar(opciones['usuario'])
        with transaction.atomic():
            conductor = self._conductor(opciones['usuario'], opciones['clave'])
            asesor = self._asesor()
            camion = self._camion()
            cliente, sedes = self._cliente()
            orden, reutilizada = self._orden(conductor, asesor, camion, cliente, sedes, opciones['nueva'])
        self.stdout.write(self.style.SUCCESS(
            f"{'Orden de hoy ya existente' if reutilizada else 'Orden creada'}: #{orden.numero_orden} "
            f"({cliente.nombre}, {camion.placa}, registro fotográfico en {' y '.join(s.nombre for s in sedes)})."))
        self.stdout.write(f"Conductor: usuario «{conductor.username}», contraseña «{opciones['clave']}».")
        self.stdout.write("Entra en /login/ con ese usuario: verá la orden en «Mi jornada» y podrá "
                          "llenar los datos, subir las fotos de cada sede, pedir la firma y cerrar.")
        self.stdout.write("Cuando termine la capacitación: python manage.py crear_demo_conductor --borrar")

    # ---- piezas ----
    def _conductor(self, usuario, clave):
        grupo, _ = Group.objects.get_or_create(name='Conductores')
        u, creado = User.objects.get_or_create(
            username=usuario, defaults={'first_name': 'Carlos', 'last_name': 'Demo', 'is_active': True})
        u.set_password(clave)
        u.is_active = True
        u.save()
        u.groups.add(grupo)
        PerfilPersona.objects.update_or_create(
            usuario=u, defaults={'numero_documento': 'DEMO-0001', 'cargo': 'Conductor (demo)',
                                 'telefono': '3000000000'})
        # Seguridad social vigente: así la oficina puede editar la programación sin trabas.
        DocumentoPersonal.objects.get_or_create(
            usuario=u, tipo='SEGURIDAD_SOCIAL', descripcion=f'{MARCA} SS',
            defaults={'archivo': ContentFile(b'%PDF-1.4 demo', name='ss_demo_conductor.pdf'),
                      'fecha_vencimiento': timezone.localdate() + datetime.timedelta(days=60)})
        self.stdout.write(f"Conductor {'creado' if creado else 'ya existía (contraseña actualizada)'}: {u.username}")
        return u

    def _asesor(self):
        """Quien figura como asesor de la orden: un administrador o asesor real; si no hay, uno de demo sin acceso."""
        asesor = (User.objects.filter(is_superuser=True, is_active=True).order_by('pk').first()
                  or User.objects.filter(groups__name__in=('Administradores', 'Asesores'), is_active=True).order_by('pk').first())
        if asesor is None:
            asesor, _ = User.objects.get_or_create(
                username='demo_asesor', defaults={'first_name': 'Asesor', 'last_name': 'Demo', 'is_active': False})
        return asesor

    def _camion(self):
        v, creado = Vehiculo.objects.get_or_create(
            placa=PLACA, defaults={'marca': 'Kenworth', 'modelo': 'T800', 'capacidad': '20 m³'})
        if creado:
            self.stdout.write(f"Camión de demo creado: {v.placa}")
        return v

    def _cliente(self):
        c, creado = Cliente.objects.get_or_create(
            nombre=CLIENTE,
            defaults={'identificacion': '900000000-0', 'direccion': SEDES[0][1], 'ciudad': 'Bogotá',
                      'email': 'demo@ejemplo.com', 'persona_contacto': 'María Rodríguez'})
        sedes = [Sede.objects.get_or_create(cliente=c, nombre=nombre, defaults={'direccion': direccion, 'ciudad': 'Bogotá'})[0]
                 for nombre, direccion in SEDES]
        if creado:
            self.stdout.write(f"Cliente de demo creado: {c.nombre} ({', '.join(s.nombre for s in sedes)})")
        return c, sedes

    def _orden(self, conductor, asesor, camion, cliente, sedes, nueva):
        hoy = timezone.localdate()
        if not nueva:
            abierta = (OrdenServicio.objects
                       .filter(descripcion__contains=MARCA, recorridos__conductor=conductor,
                               recorridos__fecha_recorrido=hoy)
                       .exclude(estado_orden__in=('FINALIZADA', 'CANCELADA')).order_by('-pk').first())
            if abierta is not None:
                return abierta, True
        prog = Programacion.objects.create(
            cliente=cliente, fecha=hoy, hora_servicio=datetime.time(8, 0), sede_cliente=sedes[0],
            direccion=sedes[0].direccion, creado_por=asesor,
            observaciones_servicio=f'{MARCA}: succión de trampa de grasas y canecas',
            registro_fotografico='SI', bascula='NO', paleada='NO_REQUIERE',
            succ_canecas=True, succ_canecas_cant='4', succ_trampas_grasa=True, succ_trampas_grasa_cant='1',
            nombre_contacto_recibe='María Rodríguez',
        )
        prog.sedes_registro.set(sedes)
        ProgramacionCuadrilla.objects.create(programacion=prog, conductor=conductor, vehiculo=camion)
        orden = prog.convertir_en_orden(asesor)
        orden.descripcion = f'{MARCA}: orden de demostración para capacitar'
        orden.save(update_fields=['descripcion'])
        return orden, False

    def _borrar(self, usuario):
        with transaction.atomic():
            ordenes = OrdenServicio.objects.filter(descripcion__contains=MARCA)
            n = ordenes.count()
            ordenes.delete()   # arrastra recorridos, actas, fotos y la programación
            Programacion.objects.filter(observaciones_servicio__contains=MARCA).delete()
            User.objects.filter(username=usuario).delete()
            User.objects.filter(username='demo_asesor').delete()
            Vehiculo.objects.filter(placa=PLACA, recorridos__isnull=True).delete()
            Cliente.objects.filter(nombre=CLIENTE, ordenes__isnull=True).delete()
        self.stdout.write(self.style.SUCCESS(
            f"Demo borrada: {n} orden(es), el conductor «{usuario}», el camión {PLACA} y el cliente de prueba."))
