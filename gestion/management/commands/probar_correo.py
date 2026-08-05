"""
Envía un correo de prueba para verificar la configuración SMTP sin pasar por
toda la aplicación. Útil para comprobar credenciales, puerto y conexión.

Uso:
    python manage.py probar_correo tu@correo.com
    python manage.py probar_correo tu@correo.com --adjunto ruta/archivo.pdf

Muestra la configuración usada y el resultado (enviado o el error exacto).
"""
import os

from django.conf import settings
from django.core.mail import EmailMessage, get_connection
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone


class Command(BaseCommand):
    help = "Envía un correo de prueba al destinatario indicado para validar el SMTP."

    def add_arguments(self, parser):
        parser.add_argument('destinatario', help='Correo a donde enviar la prueba.')
        parser.add_argument(
            '--adjunto', default=None,
            help='Ruta opcional de un archivo para adjuntar (prueba de adjuntos).',
        )

    def handle(self, *args, **options):
        destinatario = options['destinatario']
        adjunto = options['adjunto']

        # 1. Mostrar la configuración que se va a usar (sin revelar la contraseña).
        backend = settings.EMAIL_BACKEND.split('.')[-1]
        self.stdout.write("Configuración de correo:")
        self.stdout.write(f"  Backend      : {backend}")
        self.stdout.write(f"  Host / Puerto: {settings.EMAIL_HOST}:{settings.EMAIL_PORT}")
        self.stdout.write(f"  Usuario      : {settings.EMAIL_HOST_USER}")
        self.stdout.write(f"  SSL / TLS    : {settings.EMAIL_USE_SSL} / {settings.EMAIL_USE_TLS}")
        self.stdout.write(f"  Remitente    : {settings.DEFAULT_FROM_EMAIL}")
        self.stdout.write(f"  Destinatario : {destinatario}\n")

        if not settings.EMAIL_HOST:
            self.stdout.write(self.style.WARNING(
                "EMAIL_HOST está vacío: se usará el backend de consola (no se envía nada "
                "real). Define las credenciales SMTP en el .env para enviar de verdad."
            ))

        # 2. Armar el correo.
        ahora = timezone.localtime().strftime('%d/%m/%Y %H:%M')
        correo = EmailMessage(
            subject=f"SOLMED - Correo de prueba ({ahora})",
            body=(
                "Este es un correo de prueba enviado desde el CRM de SOLMED.\n\n"
                "Si lo recibiste, la configuración SMTP funciona correctamente.\n\n"
                "Cordialmente,\nSOLMED SAS"
            ),
            from_email=settings.DEFAULT_FROM_EMAIL,
            to=[destinatario],
            # Mismo Reply-To que los correos reales: sirve para comprobarlo.
            reply_to=list(getattr(settings, 'EMAIL_REPLY_TO', []) or []),
        )

        if adjunto:
            if not os.path.exists(adjunto):
                raise CommandError(f"No existe el archivo a adjuntar: {adjunto}")
            correo.attach_file(adjunto)
            self.stdout.write(f"  Adjunto      : {adjunto}\n")

        # 3. Enviar, informando el resultado o el error exacto.
        try:
            # fail_silently=False para que cualquier problema (credenciales, puerto,
            # conexión) suba como excepción y se muestre.
            enviados = correo.send(fail_silently=False)
        except Exception as e:
            raise CommandError(
                f"No se pudo enviar el correo: {e.__class__.__name__}: {e}\n"
                "Revisa el host/puerto, la contraseña y que la red no bloquee el puerto SMTP."
            )

        if enviados:
            self.stdout.write(self.style.SUCCESS(
                f"\n✓ Correo enviado a {destinatario}. Revisa la bandeja (y el spam)."
            ))
        else:
            self.stdout.write(self.style.WARNING(
                "\nEl servidor no reportó ningún correo enviado. Revisa la configuración."
            ))
