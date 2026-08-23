"""
Averigua por qué no salen los correos, paso a paso y sin adivinar.

Revisa en orden lo que puede fallar —la configuración que la app está usando,
el DNS, el puerto, el saludo del servidor SMTP y las credenciales— y al final
dice qué hacer con lo que encontró.

    python manage.py diagnosticar_correo
    python manage.py diagnosticar_correo --enviar tucorreo@ejemplo.com

No imprime la contraseña: solo si está puesta y cuántos caracteres tiene.
"""
import smtplib
import socket
import ssl

from django.conf import settings
from django.core.mail import EmailMessage
from django.core.management.base import BaseCommand
from django.utils import timezone

ESPERA = 8          # segundos por intento: lo suficiente sin dejar colgado a nadie
PUERTOS_ALTERNOS = (587, 465, 25)


class Command(BaseCommand):
    help = "Diagnostica el envío de correo: configuración, DNS, puerto, SMTP y credenciales."

    def add_arguments(self, parser):
        parser.add_argument('--enviar', default=None, metavar='CORREO',
                            help='Si todo lo demás pasa, manda un correo de prueba ahí.')

    # ---------- utilidades de salida ----------

    def _titulo(self, texto):
        self.stdout.write(self.style.MIGRATE_HEADING(f"\n{texto}"))

    def _ok(self, texto):
        self.stdout.write(self.style.SUCCESS(f"  ✓ {texto}"))

    def _mal(self, texto):
        self.stdout.write(self.style.ERROR(f"  ✗ {texto}"))
        return False

    def _nota(self, texto):
        self.stdout.write(f"    {texto}")

    # ---------- los pasos ----------

    def _configuracion(self):
        self._titulo("1. La configuración que está usando la aplicación")
        clave = settings.EMAIL_HOST_PASSWORD or ''
        self._nota(f"backend  {settings.EMAIL_BACKEND}")
        self._nota(f"servidor {settings.EMAIL_HOST or '(vacío)'}  puerto {settings.EMAIL_PORT}")
        self._nota(f"cifrado  {'SSL' if settings.EMAIL_USE_SSL else ''}"
                   f"{'TLS' if settings.EMAIL_USE_TLS else ''}"
                   f"{'ninguno' if not (settings.EMAIL_USE_SSL or settings.EMAIL_USE_TLS) else ''}")
        self._nota(f"usuario  {settings.EMAIL_HOST_USER or '(vacío)'}")
        self._nota(f"clave    {'puesta (' + str(len(clave)) + ' caracteres)' if clave else 'VACÍA'}")
        self._nota(f"remite   {settings.DEFAULT_FROM_EMAIL}")
        self._nota(f"espera   {getattr(settings, 'EMAIL_TIMEOUT', None)} s")

        if 'smtp' not in settings.EMAIL_BACKEND:
            self._mal("La app NO está configurada para enviar por SMTP: los correos "
                      "no salen a internet, se imprimen o se guardan en memoria.")
            self._nota("Pasa cuando EMAIL_HOST está vacío en el .env que lee el servidor.")
            return False
        if not settings.EMAIL_HOST:
            return self._mal("Falta EMAIL_HOST en el .env.")
        if not clave:
            self._mal("La contraseña del correo está VACÍA en el .env que lee la app.")
            self._nota("Suele pasar tras redesplegar: el .env.prod no se copió o "
                       "Apache no se recargó después de cambiarlo.")
            return False
        self._ok("Configuración completa para enviar por SMTP.")
        return True

    def _dns(self):
        self._titulo("2. ¿El servidor resuelve el nombre del correo?")
        try:
            info = socket.getaddrinfo(settings.EMAIL_HOST, None)
            direcciones = sorted({d[4][0] for d in info})
            self._ok(f"{settings.EMAIL_HOST} → {', '.join(direcciones)}")
            return True
        except socket.gaierror as e:
            self._mal(f"No resuelve «{settings.EMAIL_HOST}» ({e}).")
            self._nota("Revisa que el nombre esté bien escrito y que el servidor "
                       "tenga DNS (cat /etc/resolv.conf).")
            return False

    def _puerto(self):
        self._titulo("3. ¿Se puede abrir el puerto? (aquí es donde da «time out»)")
        abierto = self._probar_puerto(settings.EMAIL_HOST, settings.EMAIL_PORT)
        if abierto:
            self._ok(f"El puerto {settings.EMAIL_PORT} responde.")
            return True

        self._mal(f"El puerto {settings.EMAIL_PORT} no responde: por esto sale el «time out».")
        otros = [p for p in PUERTOS_ALTERNOS if p != settings.EMAIL_PORT]
        self._nota("Probando los otros puertos de correo, por si cambió:")
        disponibles = []
        for puerto in otros:
            if self._probar_puerto(settings.EMAIL_HOST, puerto):
                disponibles.append(puerto)
                self._nota(f"  · {puerto}: SÍ responde")
            else:
                self._nota(f"  · {puerto}: tampoco")
        if disponibles:
            self._nota(f"El servidor de correo atiende en {disponibles}: es cambio de "
                       f"puerto, se corrige en el .env (ver el resumen del final).")
        else:
            self._nota("Ningún puerto de correo responde: o el servidor de correo "
                       "está caído, o la salida está bloqueada (grupo de seguridad "
                       "de la EC2 → reglas de SALIDA).")
        return False

    @staticmethod
    def _probar_puerto(host, puerto):
        try:
            with socket.create_connection((host, puerto), timeout=ESPERA):
                return True
        except (OSError, socket.timeout):
            return False

    def _smtp(self):
        self._titulo("4. ¿El servidor de correo saluda y acepta las credenciales?")
        try:
            if settings.EMAIL_USE_SSL:
                conexion = smtplib.SMTP_SSL(
                    settings.EMAIL_HOST, settings.EMAIL_PORT, timeout=ESPERA,
                    context=ssl.create_default_context())
            else:
                conexion = smtplib.SMTP(
                    settings.EMAIL_HOST, settings.EMAIL_PORT, timeout=ESPERA)
                if settings.EMAIL_USE_TLS:
                    conexion.starttls(context=ssl.create_default_context())
        except ssl.SSLError as e:
            self._mal(f"Falla el cifrado: {e}")
            self._nota("Suele ser SSL/TLS al revés: el 465 usa SSL y el 587 usa TLS.")
            return False
        except (OSError, smtplib.SMTPException) as e:
            return self._mal(f"No se pudo conectar: {e}")

        with conexion:
            self._ok("El servidor de correo contesta.")
            try:
                conexion.login(settings.EMAIL_HOST_USER, settings.EMAIL_HOST_PASSWORD)
            except smtplib.SMTPAuthenticationError as e:
                self._mal(f"Rechazó el usuario o la contraseña: {e.smtp_code} "
                          f"{e.smtp_error.decode(errors='ignore') if isinstance(e.smtp_error, bytes) else e.smtp_error}")
                self._nota("La conexión sirve; lo que está mal son las credenciales "
                           "del .env (o la cuenta cambió de clave).")
                return False
            except smtplib.SMTPException as e:
                return self._mal(f"Falló el ingreso: {e}")
            self._ok(f"Entró como {settings.EMAIL_HOST_USER}.")
        return True

    def _enviar(self, destinatario):
        self._titulo("5. Envío de prueba")
        mensaje = EmailMessage(
            subject="Prueba de correo · Solmed",
            body=(f"Si estás leyendo esto, el correo del CRM funciona.\n"
                  f"Enviado el {timezone.localtime():%d/%m/%Y a las %H:%M}."),
            to=[destinatario],
        )
        try:
            mensaje.send(fail_silently=False)
        except Exception as e:
            return self._mal(f"No salió: {type(e).__name__}: {e}")
        self._ok(f"Enviado a {destinatario}. Revisa la bandeja (y el correo no deseado).")
        return True

    # ---------- el comando ----------

    def handle(self, *args, **opciones):
        self.stdout.write(self.style.MIGRATE_HEADING(
            "\nDIAGNÓSTICO DEL CORREO"))

        pasos = [self._configuracion, self._dns, self._puerto, self._smtp]
        fallo = None
        for paso in pasos:
            if not paso():
                fallo = paso.__name__
                break

        if fallo is None and opciones['enviar']:
            if not self._enviar(opciones['enviar']):
                fallo = '_enviar'

        self._titulo("Resumen")
        if fallo is None:
            if opciones['enviar']:
                self.stdout.write(self.style.SUCCESS(
                    "  El correo funciona de punta a punta. Si aun así la aplicación\n"
                    "  falla, recarga Apache: sudo systemctl reload apache2"))
            else:
                self.stdout.write(self.style.SUCCESS(
                    "  Conexión y credenciales correctas. Para probar el envío real:\n"
                    "  python manage.py diagnosticar_correo --enviar tucorreo@ejemplo.com"))
            return

        remedios = {
            '_configuracion': [
                "Revisa el .env que lee el servidor (/opt/solmed/.env):",
                "  EMAIL_HOST, EMAIL_PORT, EMAIL_HOST_USER, EMAIL_HOST_PASSWORD",
                "Después de cambiarlo: sudo systemctl reload apache2",
            ],
            '_dns': [
                "El servidor no resuelve el nombre del correo. Comprueba el nombre",
                "y el DNS de la máquina (cat /etc/resolv.conf).",
            ],
            '_puerto': [
                "Nada llega al servidor de correo. En orden:",
                "  1. Grupo de seguridad de la EC2 → reglas de SALIDA: debe permitir",
                "     el puerto de correo hacia 0.0.0.0/0.",
                "  2. Pregúntale al proveedor si el servidor sigue en ese puerto.",
                "  3. Si atiende en 587: en el .env pon EMAIL_PORT=587,",
                "     EMAIL_USE_SSL=False y EMAIL_USE_TLS=True.",
                "Y recarga Apache al terminar.",
            ],
            '_smtp': [
                "Se llega al servidor pero no deja entrar. Revisa usuario y",
                "contraseña en el .env, y que la cuenta siga activa.",
            ],
            '_enviar': [
                "La conexión y el ingreso funcionan, pero el envío se rechazó.",
                "El error de arriba trae el motivo (buzón lleno, remitente no",
                "autorizado, etc.).",
            ],
        }
        for linea in remedios[fallo]:
            self.stdout.write(self.style.WARNING(f"  {linea}"))
