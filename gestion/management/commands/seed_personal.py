"""
Siembra personal de prueba (conductores, ayudantes y asesores) con su perfil y
su expediente documental: cédula, seguridad social con vigencia, licencia y
cursos. Pensado para probar el módulo de personal y el envío de seguridad social.

Uso:
    python manage.py seed_personal          # crea/actualiza el personal de prueba
    python manage.py seed_personal --wipe    # borra antes el personal de prueba y lo recrea

Es idempotente: correrlo dos veces no duplica (identifica por número de documento).
Los archivos se guardan por el storage configurado (disco local o S3).
"""
import datetime

from django.contrib.auth.models import Group, User
from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from gestion.forms import generar_username
from gestion.models import DocumentoPersonal, PerfilPersona

# Marca para reconocer (y poder borrar) el personal de prueba.
PREFIJO_DOC = 'TEST-'

PDF_FALSO = b'%PDF-1.4\n1 0 obj<</Type/Catalog>>endobj\n%%EOF\n'


def _pdf(nombre):
    return ContentFile(PDF_FALSO, name=nombre)


# (nombre, apellido, cédula, rol, teléfono, cargo)
CONDUCTORES = [
    ('Carlos', 'Ramírez Gómez', '79123456', '3001112233', 'Conductor'),
    ('Andrés', 'Muñoz Torres', '80234567', '3002223344', 'Conductor'),
    ('Jorge', 'Pérez Cardona', '16345678', '3003334455', 'Conductor'),
]
AYUDANTES = [
    ('Pedro', 'Ramírez Salazar', '1098765432', '3101112233'),
    ('Luis', 'Ortega Vargas', '1091234567', '3102223344'),
    ('Miguel', 'Cortés Díaz', '1093456789', '3103334455'),
    ('Fabián', 'Rojas Mora', '1095678901', '3104445566'),
]
ASESORES = [
    ('Diana', 'Castaño López', '52123456', '3201112233', 'Asesora comercial'),
    ('Marcela', 'Ríos Peña', '43234567', '3202223344', 'Asesora'),
]


class Command(BaseCommand):
    help = "Siembra personal de prueba con seguridad social, licencias y cursos."

    def add_arguments(self, parser):
        parser.add_argument(
            '--wipe', action='store_true',
            help='Borra el personal de prueba existente antes de recrearlo.',
        )

    def handle(self, *args, **options):
        self.hoy = timezone.localdate()

        for nombre in ('Conductores', 'Ayudantes', 'Asesores'):
            Group.objects.get_or_create(name=nombre)

        if options['wipe']:
            self._wipe()

        with transaction.atomic():
            conductores = [self._crear_conductor(*c) for c in CONDUCTORES]
            ayudantes = [self._crear_ayudante(*a) for a in AYUDANTES]
            asesores = [self._crear_asesor(*a) for a in ASESORES]

        self._resumen(conductores, ayudantes, asesores)

    # ---- vigencias variadas para ver los distintos estados en la UI ----
    def _vence_en(self, dias):
        return self.hoy + datetime.timedelta(days=dias)

    def _wipe(self):
        usuarios = User.objects.filter(
            documentos_personales__descripcion__startswith=PREFIJO_DOC
        ).distinct()
        borrados = usuarios.exclude(is_superuser=True).count()
        for u in usuarios:
            if not u.is_superuser:
                u.delete()   # arrastra perfil y documentos (CASCADE)
        self.stdout.write(self.style.WARNING(f"  Borrados {borrados} usuario(s) de prueba."))

    def _perfil(self, usuario, cedula, telefono, cargo, direccion='Cra 10 # 20-30, Ibagué'):
        PerfilPersona.objects.update_or_create(
            usuario=usuario,
            defaults={'numero_documento': cedula, 'telefono': telefono,
                      'cargo': cargo, 'direccion': direccion},
        )

    @staticmethod
    def _correo(nombre, apellido):
        """Correo de ejemplo: el sistema lo exige a todo el personal."""
        from django.utils.text import slugify
        return f"{slugify(nombre)}.{slugify(apellido)}@solmed.com"

    def _persona_por_cedula(self, cedula):
        """Persona ya sembrada con esa cédula (para no duplicarla al re-correr)."""
        perfil = PerfilPersona.objects.filter(
            numero_documento=cedula
        ).select_related('usuario').first()
        return perfil.usuario if perfil else None

    def _doc(self, usuario, tipo, archivo, vence=None, periodo=''):
        """
        Crea el documento si no existe; si ya existe, solo refresca la vigencia
        (no re-guarda el archivo, para no acumular copias en cada corrida).
        """
        doc, creado = DocumentoPersonal.objects.get_or_create(
            usuario=usuario, tipo=tipo, descripcion=f'{PREFIJO_DOC}{tipo}',
            defaults={'archivo': _pdf(archivo), 'fecha_vencimiento': vence, 'periodo': periodo},
        )
        if not creado:
            doc.fecha_vencimiento = vence
            doc.periodo = periodo
            doc.save(update_fields=['fecha_vencimiento', 'periodo'])

    def _crear_conductor(self, nombre, apellido, cedula, telefono, cargo):
        usuario, creado = User.objects.get_or_create(
            username=f'c_{cedula}',
            defaults={'first_name': nombre, 'last_name': apellido, 'is_active': True},
        )
        usuario.email = self._correo(nombre, apellido)
        if creado:
            usuario.set_password('Solmed.2026')
        usuario.first_name, usuario.last_name = nombre, apellido
        usuario.save()
        usuario.groups.set([Group.objects.get(name='Conductores')])
        self._perfil(usuario, cedula, telefono, cargo)

        self._doc(usuario, 'CEDULA', f'cedula_{cedula}.pdf')
        # Seguridad social: uno por vencer, otros vigentes (según la cédula).
        dias = 12 if cedula.endswith('6') else 60
        self._doc(usuario, 'SEGURIDAD_SOCIAL', f'ss_{cedula}.pdf', vence=self._vence_en(dias))
        self._doc(usuario, 'LICENCIA', f'licencia_{cedula}.pdf', vence=self._vence_en(300))
        return usuario

    def _crear_ayudante(self, nombre, apellido, cedula, telefono):
        # Ayudantes: SIN acceso (username autogenerado de la cédula, inactivo).
        # Se busca por cédula para no duplicar: generar_username NO es idempotente
        # (al re-correr evitaría la colisión creando otro username).
        usuario = self._persona_por_cedula(cedula)
        if usuario is None:
            usuario = User(username=generar_username(nombre, apellido, cedula))
            usuario.set_unusable_password()
        usuario.first_name, usuario.last_name = nombre, apellido
        usuario.email = self._correo(nombre, apellido)
        usuario.is_active = False
        usuario.save()
        usuario.groups.set([Group.objects.get(name='Ayudantes')])
        self._perfil(usuario, cedula, telefono, 'Ayudante')

        self._doc(usuario, 'CEDULA', f'cedula_{cedula}.pdf')
        # Variamos la seguridad social: vigente, por vencer y una vencida.
        ultimo = cedula[-1]
        if ultimo in '01':
            venc_ss = self._vence_en(90)      # vigente
        elif ultimo in '23':
            venc_ss = self._vence_en(8)       # por vencer (avisa)
        else:
            venc_ss = self._vence_en(-4)      # vencida
        self._doc(usuario, 'SEGURIDAD_SOCIAL', f'ss_{cedula}.pdf', vence=venc_ss)

        # Cursos (opcionales en el expediente, exigibles desde la programación):
        # los dos primeros ayudantes tienen ambos; los demás, solo alturas.
        self._doc(usuario, 'CURSO_ALTURAS', f'alturas_{cedula}.pdf', vence=self._vence_en(200))
        if ultimo in '012':
            self._doc(usuario, 'CURSO_CONFINADOS', f'confinados_{cedula}.pdf', vence=self._vence_en(200))
        return usuario

    def _crear_asesor(self, nombre, apellido, cedula, telefono, cargo):
        usuario, creado = User.objects.get_or_create(
            username=f'a_{cedula}',
            defaults={'first_name': nombre, 'last_name': apellido,
                      'is_active': True, 'email': f'{nombre.lower()}@solmed.com'},
        )
        if creado:
            usuario.set_password('Solmed.2026')
        usuario.first_name, usuario.last_name = nombre, apellido
        usuario.save()
        usuario.groups.set([Group.objects.get(name='Asesores')])
        self._perfil(usuario, cedula, telefono, cargo)
        self._doc(usuario, 'SEGURIDAD_SOCIAL', f'ss_{cedula}.pdf', vence=self._vence_en(45))
        return usuario

    def _resumen(self, conductores, ayudantes, asesores):
        ok = self.style.SUCCESS
        self.stdout.write(ok("\nPersonal de prueba creado/actualizado:"))
        self.stdout.write(f"  Conductores: {len(conductores)}  (usuario c_<cédula>, clave Solmed.2026)")
        self.stdout.write(f"  Ayudantes:   {len(ayudantes)}  (sin acceso; solo expediente)")
        self.stdout.write(f"  Asesores:    {len(asesores)}  (usuario a_<cédula>, clave Solmed.2026)")
        self.stdout.write(
            "\nSeguridad social sembrada con vigencias variadas: vigentes, por vencer y vencidas, "
            "para ver todos los estados. Los archivos son PDF de relleno.\n"
            "Para reiniciar: python manage.py seed_personal --wipe"
        )
