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
            self._direcciones = sorted({d[4][0] for d in info})
            self._ok(f"{settings.EMAIL_HOST} → {', '.join(self._direcciones)}")
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
        disponibles = [p for p in otros if self._probar_puerto(settings.EMAIL_HOST, p)]
        for puerto in otros:
            self._nota(f"  · {puerto}: {'SÍ responde' if puerto in disponibles else 'tampoco'}")
        if disponibles:
            self._puerto_alterno = disponibles[0]
            self._nota(f"El servidor de correo atiende en {disponibles}: es cambio de "
                       f"puerto, se corrige en el .env (ver el resumen del final).")
            return False

        # Ningún puerto de correo responde. Aquí se separan dos causas que se
        # ven igual desde afuera: que esta máquina no pueda sacar tráfico por
        # esos puertos, o que el destino en concreto no conteste.
        self._nota("")
        self._nota("Ninguno responde. Separando las dos causas posibles:")
        internet = self._probar_puerto('google.com', 443)
        self._nota(f"  · salida a internet (google.com:443): "
                   f"{'SÍ' if internet else 'NO'}")
        correo_ajeno = self._probar_puerto('smtp.gmail.com', 465)
        self._nota(f"  · otro servidor de correo (smtp.gmail.com:465): "
                   f"{'SÍ' if correo_ajeno else 'NO'}")
        for ip in getattr(self, '_direcciones', []):
            alcanza = self._probar_puerto(ip, settings.EMAIL_PORT)
            self._nota(f"  · directo a {ip}:{settings.EMAIL_PORT}: "
                       f"{'SÍ' if alcanza else 'NO'}")

        if not internet:
            self._causa = 'sin_internet'
        elif correo_ajeno:
            self._causa = 'destino'
        else:
            self._causa = 'puertos_bloqueados'
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

    def _remedio_puerto(self):
        """Qué hacer, según cuál de las causas quedó en pie."""
        if getattr(self, '_puerto_alterno', None):
            puerto = self._puerto_alterno
            cifrado = ("EMAIL_USE_SSL=True y EMAIL_USE_TLS=False" if puerto == 465
                       else "EMAIL_USE_SSL=False y EMAIL_USE_TLS=True")
            return [
                f"El correo atiende en el puerto {puerto}, no en el "
                f"{settings.EMAIL_PORT}. En /opt/solmed/.env:",
                f"  EMAIL_PORT={puerto}",
                f"  {cifrado}",
                "Y recarga Apache: sudo systemctl reload apache2",
            ]
        causa = getattr(self, '_causa', None)
        if causa == 'sin_internet':
            return [
                "Esta máquina no está sacando tráfico a internet: ni siquiera",
                "abre google.com:443. Revisa la red de la instancia (tabla de",
                "rutas, NAT, grupo de seguridad) antes de mirar el correo.",
            ]
        if causa == 'destino':
            return [
                "La máquina SÍ puede abrir puertos de correo hacia afuera",
                "(smtp.gmail.com:465 responde), pero mail.vadomdata.com no",
                "contesta en ninguno. O sea que el bloqueo no es de la EC2:",
                "  1. Pregúntale al proveedor si el servidor de correo está",
                "     arriba y si bloqueó la IP de esta instancia (los hosting",
                "     suelen bloquear IPs de nube por abuso).",
                "  2. Ojo con el DNS: comprueba a qué IP resuelve aquí y",
                "     compárala con la de otra máquina donde el correo sí sale.",
                "     Si difieren, esta instancia está resolviendo a un servidor",
                "     equivocado.",
            ]
        return [
            "La máquina abre internet (google.com:443 responde) pero NINGÚN",
            "puerto de correo, ni siquiera hacia otro proveedor. Eso es un",
            "bloqueo de salida para esos puertos:",
            "  1. Grupo de seguridad de la EC2 → reglas de SALIDA: debe permitir",
            "     el puerto 465 (y 587) hacia 0.0.0.0/0.",
            "  2. Revisa también las ACL de red de la subred.",
            "  3. AWS bloquea el 25 por defecto; el 465 y el 587 no deberían",
            "     estarlo salvo que alguien restringiera la salida.",
            "Y recarga Apache al terminar.",
        ]

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
            '_puerto': self._remedio_puerto(),
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
