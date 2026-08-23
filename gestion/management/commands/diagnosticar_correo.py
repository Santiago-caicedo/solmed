"""
Averigua por qué no salen los correos, paso a paso y sin adivinar.

Revisa en orden lo que puede fallar —la configuración que la app está usando,
el DNS, el puerto, el saludo del servidor SMTP y las credenciales— y al final
dice qué hacer con lo que encontró.

    python manage.py diagnosticar_correo
    python manage.py diagnosticar_correo --red
    python manage.py diagnosticar_correo --enviar tucorreo@ejemplo.com

No imprime la contraseña: solo si está puesta y cuántos caracteres tiene.
"""
import json
import smtplib
import socket
import ssl
import urllib.error
import urllib.parse
import urllib.request

from django.conf import settings
from django.core.mail import EmailMessage
from django.core.management.base import BaseCommand
from django.utils import timezone

ESPERA = 8          # segundos por intento: lo suficiente sin dejar colgado a nadie
PUERTOS_ALTERNOS = (587, 465, 25)

# Se le pregunta a resolutores públicos por HTTPS (DNS-over-HTTPS) en vez de por
# el puerto 53: así funciona sin instalar «dig» y sin depender del DNS local,
# que es justamente lo que se quiere poner a prueba.
RESOLUTORES_PUBLICOS = (
    ('Google', 'https://dns.google/resolve?name={nombre}&type=A'),
    ('Cloudflare', 'https://cloudflare-dns.com/dns-query?name={nombre}&type=A'),
)
DONDE_VER_MI_IP = 'https://checkip.amazonaws.com'


class Command(BaseCommand):
    help = "Diagnostica el envío de correo: configuración, DNS, puerto, SMTP y credenciales."

    def add_arguments(self, parser):
        parser.add_argument('--enviar', default=None, metavar='CORREO',
                            help='Si todo lo demás pasa, manda un correo de prueba ahí.')
        parser.add_argument('--red', action='store_true',
                            help='Compara lo que resuelve esta máquina contra lo que '
                                 'resuelve el DNS público y prueba cada dirección. '
                                 'Separa «el servidor no llega» de «apunta a otro lado».')
        parser.add_argument('--probar', default=None, metavar='HOST[:PUERTO]',
                            help='Solo prueba si se alcanza ese destino y termina. '
                                 'Sirve para comparar contra otra máquina.')

    # ---------- utilidades de salida ----------

    def _titulo(self, texto):
        self.stdout.write(self.style.MIGRATE_HEADING(f"\n{texto}"))

    def _ok(self, texto):
        self.stdout.write(self.style.SUCCESS(f"  ✓ {texto}"))

    def _mal(self, texto):
        self.stdout.write(self.style.ERROR(f"  ✗ {texto}"))
        return False

    def _nota(self, texto=''):
        self.stdout.write(f"    {texto}" if texto else "")

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

    def _pedir(self, url, cabeceras=None):
        """Trae una URL y devuelve el texto, o None si no se pudo."""
        peticion = urllib.request.Request(url, headers=cabeceras or {})
        try:
            with urllib.request.urlopen(peticion, timeout=ESPERA) as respuesta:
                return respuesta.read().decode('utf-8', 'replace')
        except (urllib.error.URLError, OSError, ValueError):
            return None

    def _dns_publico(self, nombre):
        """Qué direcciones da el DNS público para ese nombre, por resolutor."""
        resultado = {}
        for quien, plantilla in RESOLUTORES_PUBLICOS:
            crudo = self._pedir(
                plantilla.format(nombre=urllib.parse.quote(nombre)),
                {'accept': 'application/dns-json'})
            if crudo is None:
                resultado[quien] = None
                continue
            try:
                datos = json.loads(crudo)
            except ValueError:
                resultado[quien] = None
                continue
            # type 1 = registro A; los CNAME intermedios no interesan aquí.
            resultado[quien] = sorted(
                r['data'] for r in datos.get('Answer', ()) if r.get('type') == 1)
        return resultado

    def _resuelve_aqui(self, nombre):
        try:
            return sorted({d[4][0] for d in socket.getaddrinfo(nombre, None)})
        except socket.gaierror:
            return []

    def _red(self):
        """
        La pregunta que separa las dos causas del «time out»: ¿esta máquina no
        alcanza el correo, o lo está buscando en una dirección equivocada?
        Para responderla hace falta un tercero —el DNS público— porque el DNS
        de la máquina es sospechoso y no puede ser juez de sí mismo.
        """
        nombre, puerto = settings.EMAIL_HOST, settings.EMAIL_PORT
        if not nombre:
            return self._mal("Falta EMAIL_HOST en el .env: no hay nombre que revisar.")

        self._titulo(f"1. ¿A qué dirección apunta {nombre} aquí?")
        aqui = self._resuelve_aqui(nombre)
        if aqui:
            self._nota(f"esta máquina  {', '.join(aqui)}")
        else:
            self._mal("Esta máquina no resuelve el nombre.")

        self._titulo("2. ¿Y según el DNS público?")
        publicas = set()
        for quien, direcciones in self._dns_publico(nombre).items():
            if direcciones is None:
                self._nota(f"{quien:<13} no se pudo consultar")
            elif direcciones:
                publicas.update(direcciones)
                self._nota(f"{quien:<13} {', '.join(direcciones)}")
            else:
                self._nota(f"{quien:<13} sin registro A")

        coinciden = publicas and set(aqui) == publicas
        if publicas and aqui and not coinciden:
            self._mal("No coinciden: esta máquina busca el correo en otra parte.")
        elif coinciden:
            self._ok("Coinciden: el nombre se está resolviendo bien.")

        self._titulo(f"3. ¿Cuáles responden en el puerto {puerto}?")
        candidatas = sorted(set(aqui) | publicas)
        responden = []
        for ip in candidatas:
            de_donde = []
            if ip in aqui:
                de_donde.append('local')
            if ip in publicas:
                de_donde.append('público')
            if self._probar_puerto(ip, puerto):
                responden.append(ip)
                self._ok(f"{ip}  responde        (DNS {'+'.join(de_donde)})")
            else:
                self._mal(f"{ip}  no responde     (DNS {'+'.join(de_donde)})")

        hay_internet = self._probar_puerto('google.com', 443)
        self._nota(f"salida a internet (google.com:443): {'SÍ' if hay_internet else 'NO'}")
        mi_ip = (self._pedir(DONDE_VER_MI_IP) or '').strip()

        # ---------- qué hacer con lo anterior ----------
        self._titulo("Qué significa")
        utiles = [ip for ip in responden if ip not in aqui]

        if responden and set(responden) & set(aqui):
            self.stdout.write(self.style.SUCCESS(
                "  La red está bien: el correo se alcanza desde aquí."))
            self._nota("Si el envío igual falla, ya no es la red: corre el diagnóstico")
            self._nota("completo (sin --red) para revisar credenciales y cifrado.")
        elif utiles:
            self.stdout.write(self.style.WARNING(
                "  El correo SÍ se alcanza, pero no en la dirección que resuelve esta máquina."))
            self._nota("El problema es de resolución, no de bloqueo. Se fija el nombre a mano:")
            self._nota("")
            self._nota(f'  echo "{utiles[0]}  {nombre}" | sudo tee -a /etc/hosts')
            self._nota(f"  python manage.py diagnosticar_correo --enviar tucorreo@ejemplo.com")
            self._nota("")
            self._nota("Es un parche: lo de fondo se corrige en la zona DNS del dominio.")
        elif not hay_internet:
            self.stdout.write(self.style.ERROR(
                "  Esta máquina no está saliendo a internet: eso explica todo lo demás."))
        else:
            self.stdout.write(self.style.WARNING(
                "  Hay internet, pero ninguna dirección del correo responde."))
            self._nota("Queda una sola explicación: el hosting no acepta conexiones")
            self._nota("SMTP desde esta máquina. Es común — los proveedores filtran")
            self._nota("rangos de nube completos para frenar spam.")
            self._nota("")
            self._nota(f"Escríbeles pidiendo habilitar esta IP para SMTP: {mi_ip or '(no se pudo consultar)'}")

        if mi_ip:
            self._nota("")
            self._nota(f"IP pública de esta máquina: {mi_ip}")
        return bool(responden)

    def _solo_probar(self, destino):
        """
        Prueba un destino suelto. Con el nombre resuelve primero y prueba cada
        IP por separado: así se ve si el problema es a dónde apunta el DNS o
        si de plano no se llega al servidor.
        """
        host, _, puerto = destino.partition(':')
        puerto = int(puerto) if puerto.isdigit() else settings.EMAIL_PORT
        self._titulo(f"¿Se alcanza {host}:{puerto} desde esta máquina?")

        try:
            socket.inet_aton(host)
            direcciones = [host]
        except OSError:
            try:
                direcciones = sorted({d[4][0] for d in socket.getaddrinfo(host, None)})
                self._nota(f"{host} → {', '.join(direcciones)}")
            except socket.gaierror as e:
                self._mal(f"No resuelve «{host}» ({e}).")
                return

        alcanzadas = []
        for ip in direcciones:
            if self._probar_puerto(ip, puerto):
                alcanzadas.append(ip)
                self._ok(f"{ip}:{puerto} responde")
            else:
                self._mal(f"{ip}:{puerto} no responde")
        self._titulo("Resumen")
        if alcanzadas:
            self.stdout.write(self.style.SUCCESS(
                f"  Esta máquina sí llega a {', '.join(alcanzadas)}."))
        else:
            self.stdout.write(self.style.WARNING(
                "  Esta máquina no llega a ninguna de esas direcciones."))

    def handle(self, *args, **opciones):
        if opciones['probar']:
            self._solo_probar(opciones['probar'])
            return
        if opciones['red']:
            self.stdout.write(self.style.MIGRATE_HEADING(
                "\nDIAGNÓSTICO DE RED DEL CORREO"))
            self._red()
            return

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
