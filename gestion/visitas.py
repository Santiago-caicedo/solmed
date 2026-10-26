"""
El módulo de VISITAS TÉCNICAS (oct-2026, pedido de la clienta): el formato
GC-F-01 versión 03 llevado al sistema.

El flujo (ajustado oct-2026 por pedido de Santiago):

1. La oficina (asesores y gestión) crea la SOLICITUD —sección 1 del formato,
   con la hora de ingreso— y el sistema le manda al cliente un correo con un
   enlace de un solo uso (token de aprobación) donde ve los detalles y la
   APRUEBA, o pide otra fecha. Sin la aprobación no se trabaja en campo.
2. Aprobada, el ejecutivo comercial llena en campo, desde el celular, las
   secciones 2 a 6, las fotos y su firma.
3. Al terminar pasa a la FIRMA DEL CLIENTE con el mismo mecanismo del acta de
   servicio: un QR / enlace público (token de firma, distinto del de
   aprobación) donde el cliente firma en su celular. Con esa firma la visita
   queda REALIZADA y sale su PDF en el formato.

Por qué DOS tokens y no uno: son dos actos distintos, de personas que pueden
ser distintas (quien aprueba en la oficina del cliente no siempre es quien
recibe la visita) y en momentos distintos. El de aprobación viaja por correo
días antes y se gasta al aprobar; el de firma no existe hasta que el
ejecutivo termina en campo y se gasta al firmar. Así un correo de solicitud
reenviado nunca sirve para firmar, y cada enlace es de un solo uso.
"""
import base64
import smtplib

from django.conf import settings
from django.contrib import messages
from django.core.files.base import ContentFile
from django.db import transaction
from django.db.models import Count, Q
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.template.defaultfilters import time as _filtro_hora
from django.template.loader import get_template
from django.urls import reverse
from django.utils import timezone
from django.utils.formats import date_format
from django.views import View
from django.views.generic import ListView
from weasyprint import HTML

from .forms import ServicioVisitaFormSet, VisitaCampoForm, VisitaProgramacionForm
from .models import FotoVisita, VisitaTecnica
from .views import AsesorRequiredMixin, PaginadoMixin, _decodificar_firma_png, _qr_data_uri, _reply_to


def _logo_b64():
    import os
    ruta = os.path.join(settings.BASE_DIR, 'static', 'images', 'logo-solmed.png')
    with open(ruta, 'rb') as fh:
        return "data:image/png;base64," + base64.b64encode(fh.read()).decode()


# ============================================================
#  CORREOS DE LA VISITA (al cliente y a la oficina)
# ============================================================

def _hora_texto(hora):
    return _filtro_hora(hora, 'g:i a') if hora else 'Por definir'


def _detalles_visita(visita):
    """Lo que el cliente necesita ver de la visita, ya en texto (correo y página pública)."""
    ejecutivo = visita.ejecutivo
    return [
        ('Empresa', visita.empresa),
        ('Fecha de la visita', date_format(visita.fecha_programada, r'l j \d\e F \d\e Y').capitalize()),
        ('Hora de ingreso', _hora_texto(visita.hora_inicio)),
        ('Dirección', ' · '.join(x for x in (visita.direccion, visita.sede_planta) if x)),
        ('Ejecutivo comercial', (ejecutivo.get_full_name() or ejecutivo.username) if ejecutivo else ''),
        ('Persona que recibe', ' · '.join(x for x in (visita.persona_recibe, visita.cargo_recibe) if x)),
        ('Observaciones de ingreso', visita.observaciones_ingreso),
    ]


def _enviar_correo_visita(destinatarios, asunto, ctx):
    """
    Un correo de marca (texto + HTML) sobre la visita. Devuelve True si salió.
    Si el servidor de correo falla, el guardado de la visita no se cae: quien
    llama avisa en pantalla y se puede reenviar después.
    """
    from django.core.mail import EmailMultiAlternatives
    lineas = [ctx['saludo'], '', ctx['intro'], '']
    lineas += [f"{etiqueta}: {valor}" for etiqueta, valor in ctx.get('detalles', ()) if valor]
    if ctx.get('texto_extra'):
        lineas += ['', ctx['texto_extra']]
    if ctx.get('url'):
        lineas += ['', f"{ctx['url_boton']}: {ctx['url']}"]
    if ctx.get('nota'):
        lineas += ['', ctx['nota']]
    lineas += ['', 'SOLMED SAS']
    mensaje = EmailMultiAlternatives(
        subject=asunto, body='\n'.join(lineas), from_email=settings.DEFAULT_FROM_EMAIL,
        to=list(destinatarios), reply_to=_reply_to())
    mensaje.attach_alternative(get_template('gestion/correo_visita.html').render(ctx), 'text/html')
    try:
        mensaje.send(fail_silently=False)
    except (OSError, smtplib.SMTPException):
        return False
    return True


def _correos_oficina(visita):
    """A quién se le avisa lo que responde el cliente: el ejecutivo y quien programó."""
    personas = [p for p in (visita.ejecutivo, visita.creada_por) if p is not None and p.is_active]
    return sorted({p.email.strip() for p in personas if p.email and p.email.strip()})


def _cinta(visita):
    return (f"Visita {visita.codigo} · {date_format(visita.fecha_programada, 'd/m/Y')}"
            f" · {_hora_texto(visita.hora_inicio)}")


def enviar_solicitud(request, visita):
    """
    Le manda al cliente la solicitud de la visita con su enlace de aprobación
    (token de un solo uso). Devuelve (enviado, aviso para la pantalla).
    """
    correo = (visita.email or '').strip()
    if not correo:
        return False, "La visita no tiene correo del cliente: la solicitud no se envió. Ponlo en la programación y reenvíala."
    url = request.build_absolute_uri(
        reverse('gestion:aprobar_visita', kwargs={'token': visita.token_aprobacion}))
    nombre = visita.contacto or visita.persona_recibe
    reprogramada = visita.estado == 'REPROGRAMADA'
    ctx = {
        'titulo': 'Solicitud de visita técnica' if not reprogramada else 'Nueva fecha de visita técnica',
        'cinta': _cinta(visita),
        'saludo': f"Hola{', ' + nombre if nombre else ''}",
        'intro': ("SOLMED SAS solicita realizar una visita técnica en sus instalaciones. "
                  "Revise los detalles y apruébela con el botón de abajo; si la fecha u hora "
                  "no le sirven, desde ahí mismo puede pedir un cambio."
                  if not reprogramada else
                  "La visita técnica de SOLMED SAS cambió de fecha u hora. Revise los nuevos "
                  "detalles y apruébela de nuevo con el botón de abajo; si no le sirven, "
                  "desde ahí mismo puede pedir otro cambio."),
        'detalles': _detalles_visita(visita),
        'url': url, 'url_boton': 'Ver y aprobar la visita',
        'nota': 'Este enlace es personal y de un solo uso: deja de servir cuando la visita queda aprobada.',
    }
    asunto = f"Solicitud de visita técnica {visita.codigo} · SOLMED SAS"
    if not _enviar_correo_visita([correo], asunto, ctx):
        return False, "No se pudo enviar el correo al cliente. Reenvíalo desde la visita en un momento."
    visita.solicitud_enviada_en = timezone.now()
    visita.save(update_fields=['solicitud_enviada_en'])
    return True, f"Solicitud enviada a {correo}: el cliente la aprueba desde su correo."


def enviar_enlace_firma(request, visita):
    """Le manda al cliente el enlace para firmar la visita (si no pudo escanear el QR)."""
    correo = (visita.email or '').strip()
    if not correo:
        return False, "La visita no tiene correo del cliente."
    url = request.build_absolute_uri(
        reverse('gestion:firmar_visita', kwargs={'token': visita.asegurar_token_firma()}))
    nombre = visita.representante_cliente or visita.persona_recibe or visita.contacto
    ctx = {
        'titulo': 'Firma de la visita técnica', 'cinta': _cinta(visita),
        'saludo': f"Hola{', ' + nombre if nombre else ''}",
        'intro': ("Gracias por recibir la visita técnica de SOLMED SAS. Para dejar constancia de "
                  "la visita y de la información revisada, por favor fírmela desde el botón de abajo."),
        'detalles': _detalles_visita(visita)[:5],
        'url': url, 'url_boton': 'Firmar la visita',
        'texto_extra': ("La firma sirve como constancia de la visita y de la información revisada, "
                        "sin que implique aceptación de una cotización o contratación del servicio."),
        'nota': 'Este enlace es personal y de un solo uso.',
    }
    if not _enviar_correo_visita([correo], f"Firma de la visita técnica {visita.codigo} · SOLMED SAS", ctx):
        return False, "No se pudo enviar el correo al cliente."
    return True, f"Enlace de firma enviado a {correo}."


def _avisar_oficina(request, visita, asunto, intro, texto_extra=''):
    correos = _correos_oficina(visita)
    if not correos:
        return
    _enviar_correo_visita(correos, asunto, {
        'titulo': 'Visita técnica', 'cinta': _cinta(visita), 'saludo': 'Hola',
        'intro': intro, 'detalles': _detalles_visita(visita)[:4], 'texto_extra': texto_extra,
        'url': request.build_absolute_uri(reverse('gestion:detalle_visita', kwargs={'pk': visita.pk})),
        'url_boton': 'Abrir la visita',
    })


# ============================================================
#  LA OFICINA: lista, solicitud (sección 1), detalle y estado
# ============================================================

class ListaVisitasView(AsesorRequiredMixin, PaginadoMixin, ListView):
    """Las visitas, la próxima arriba, con filtro por estado, ejecutivo y buscador."""
    model = VisitaTecnica
    template_name = 'gestion/lista_visitas.html'
    context_object_name = 'visitas'

    def _estado(self):
        estado = self.request.GET.get('estado', '')
        return estado if estado in dict(VisitaTecnica.ESTADO_CHOICES) else ''

    def get_queryset(self):
        qs = VisitaTecnica.objects.select_related('cliente', 'ejecutivo')
        if self._estado():
            qs = qs.filter(estado=self._estado())
        try:
            ejecutivo = int(self.request.GET.get('ejecutivo') or 0)
        except ValueError:
            ejecutivo = 0
        if ejecutivo:
            qs = qs.filter(ejecutivo_id=ejecutivo)
        q = self.request.GET.get('q', '').strip()
        if q:
            numero = q.upper().replace(f'{VisitaTecnica.PREFIJO}-', '').lstrip('0')
            filtro = (Q(empresa__icontains=q) | Q(nit__icontains=q) | Q(contacto__icontains=q)
                      | Q(cliente__nombre__icontains=q) | Q(direccion__icontains=q))
            if numero.isdigit():
                filtro |= Q(numero=int(numero))
            qs = qs.filter(filtro)
        return qs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        conteo = dict(VisitaTecnica.objects.values_list('estado').annotate(n=Count('pk')))
        context.update({
            'estado': self._estado(),
            'estados': [(c, n, conteo.get(c, 0)) for c, n in VisitaTecnica.ESTADO_CHOICES],
            'n_total': VisitaTecnica.objects.count(),
            'q': self.request.GET.get('q', '').strip(),
            'ejecutivo': self.request.GET.get('ejecutivo', ''),
            'ejecutivos': VisitaProgramacionForm().fields['ejecutivo'].queryset,
            'hoy': timezone.localdate(),
        })
        return context


class ProgramarVisitaView(AsesorRequiredMixin, View):
    """
    Sección 1: crear la SOLICITUD de la visita (la oficina) o corregirla. Al
    crearla, el cliente recibe el correo con su enlace de aprobación. Si
    después cambia la fecha o la hora de ingreso, la aprobación anterior ya no
    vale: la visita pasa a «reprogramada» y el cliente recibe la nueva solicitud.
    """
    template_name = 'gestion/form_visita.html'

    def _visita(self, pk):
        return get_object_or_404(VisitaTecnica, pk=pk) if pk else None

    @staticmethod
    def _clientes():
        """
        Los clientes registrados con lo que la hoja se llena sola al elegir uno
        (razón social, NIT, contacto, teléfono, correo, dirección), para el
        desplegable «Ya es cliente» (pedido de Santiago, oct-2026).
        """
        from .models import Cliente
        return [{
            'pk': c.pk, 'nombre': c.nombre, 'nit': c.identificacion or '',
            'contacto': c.persona_contacto or '', 'cargo': c.cargo_contacto or '',
            'telefonos': ' / '.join(t for t in (c.telefono_celular, c.telefono_fijo, c.telefono) if t),
            'email': c.email or '',
            'direccion': ', '.join(d for d in (c.direccion, c.ciudad) if d),
        } for c in Cliente.objects.order_by('nombre')]

    def _contexto(self, form, visita):
        return {'form': form, 'visita': visita, 'clientes': self._clientes()}

    def get(self, request, pk=None):
        visita = self._visita(pk)
        initial = {} if visita else {'ejecutivo': request.user.pk}
        form = VisitaProgramacionForm(instance=visita, initial=initial)
        return render(request, self.template_name, self._contexto(form, visita))

    def post(self, request, pk=None):
        visita = self._visita(pk)
        # Se toma ANTES de ligar el formulario: el ModelForm escribe sobre la instancia.
        antes = (visita.fecha_programada, visita.hora_inicio) if visita else None
        form = VisitaProgramacionForm(request.POST, instance=visita)
        if not form.is_valid():
            messages.error(request, "Revisa el formulario.")
            return render(request, self.template_name, self._contexto(form, visita))
        nueva = form.save(commit=False)
        if visita is None:
            nueva.creada_por = request.user
        cliente = nueva.cliente
        if cliente is not None:
            # Lo que quedó en blanco se toma de la ficha del cliente.
            for campo, origen in (('nit', 'identificacion'), ('direccion', 'direccion'),
                                  ('contacto', 'persona_contacto'), ('cargo_contacto', 'cargo_contacto'),
                                  ('email', 'email'), ('telefonos', 'telefono_celular')):
                if not getattr(nueva, campo):
                    setattr(nueva, campo, getattr(cliente, origen) or '')

        cambio_fecha = visita is not None and (nueva.fecha_programada, nueva.hora_inicio) != antes
        if cambio_fecha and nueva.estado == 'CONFIRMADA':
            nueva.reiniciar_aprobacion()
            nueva.estado = 'REPROGRAMADA'
        nueva.save()

        if visita is None:
            messages.success(request, f"Visita {nueva.codigo} solicitada.")
            enviado, aviso = enviar_solicitud(request, nueva)
            (messages.info if enviado else messages.warning)(request, aviso)
        else:
            messages.success(request, f"Visita {nueva.codigo} actualizada.")
            if cambio_fecha and nueva.pendiente_aprobacion:
                enviado, aviso = enviar_solicitud(request, nueva)
                messages.warning(request, "Cambió la fecha o la hora de ingreso: el cliente debe "
                                          "aprobar de nuevo. " + aviso)
        return redirect('gestion:detalle_visita', pk=nueva.pk)


class DetalleVisitaView(AsesorRequiredMixin, View):
    """La visita completa: solicitud y aprobación, lo levantado en campo, fotos, firmas y PDF."""
    template_name = 'gestion/detalle_visita.html'

    def get(self, request, pk):
        visita = get_object_or_404(
            VisitaTecnica.objects.select_related('cliente', 'ejecutivo', 'creada_por')
            .prefetch_related('servicios', 'fotos'), pk=pk)
        return render(request, self.template_name, {
            'visita': visita,
            'estados': [c for c in VisitaTecnica.ESTADO_CHOICES if c[0] != 'REALIZADA'],
            'url_aprobacion': request.build_absolute_uri(
                reverse('gestion:aprobar_visita', kwargs={'token': visita.token_aprobacion})),
        })


class CambiarEstadoVisitaView(AsesorRequiredMixin, View):
    """
    Confirmar (si el cliente aceptó por teléfono o WhatsApp), reprogramar o
    cancelar desde el detalle. «Realizada» solo la pone la firma del cliente.
    Reprogramar borra la aprobación anterior y le reenvía la solicitud.
    """

    def post(self, request, pk):
        visita = get_object_or_404(VisitaTecnica, pk=pk)
        estado = request.POST.get('estado', '')
        if estado not in dict(VisitaTecnica.ESTADO_CHOICES) or estado == 'REALIZADA':
            messages.error(request, "Ese estado no se puede poner desde aquí.")
            return redirect('gestion:detalle_visita', pk=pk)
        if estado == 'CONFIRMADA' and not visita.aprobada_en:
            quien = request.user.get_full_name() or request.user.username
            visita.aprobada_en = timezone.now()
            visita.aprobada_por = f"Confirmada por la oficina ({quien})"
            visita.cliente_acepta = 'SI'
        if estado == 'REPROGRAMADA':
            visita.reiniciar_aprobacion()
        visita.estado = estado
        visita.save()
        messages.success(request, f"Visita {visita.codigo}: {visita.get_estado_display().lower()}.")
        if estado == 'REPROGRAMADA':
            enviado, aviso = enviar_solicitud(request, visita)
            (messages.info if enviado else messages.warning)(request, aviso)
        return redirect('gestion:detalle_visita', pk=pk)


class ReenviarSolicitudVisitaView(AsesorRequiredMixin, View):
    """Vuelve a mandar el correo de la solicitud (mismo enlace) mientras esté pendiente."""

    def post(self, request, pk):
        visita = get_object_or_404(VisitaTecnica, pk=pk)
        if not visita.pendiente_aprobacion:
            messages.error(request, "Esta visita ya no está pendiente de aprobación.")
        else:
            enviado, aviso = enviar_solicitud(request, visita)
            (messages.success if enviado else messages.warning)(request, aviso)
        return redirect('gestion:detalle_visita', pk=pk)


# ============================================================
#  EL CLIENTE (sin usuario): aprobar la solicitud
# ============================================================

class AprobarVisitaPublicaView(View):
    """
    Página PÚBLICA que abre el cliente desde el correo: ve los detalles de la
    visita y la aprueba (con su nombre), o pide otra fecha con un comentario.
    El enlace se gasta al aprobar: después solo dice que ya está aprobada.
    """
    template_name = 'gestion/visita_publica_aprobar.html'

    @staticmethod
    def _visita(token):
        return get_object_or_404(VisitaTecnica.objects.select_related('ejecutivo'), token_aprobacion=token)

    @staticmethod
    def _gracias(request, visita, modo):
        return render(request, 'gestion/visita_publica_gracias.html', {'visita': visita, 'modo': modo})

    def _cerrada(self, request, visita):
        if visita.estado == 'CANCELADA':
            return self._gracias(request, visita, 'cancelada')
        if visita.aprobada_en or visita.estado in ('CONFIRMADA', 'REALIZADA'):
            return self._gracias(request, visita, 'ya_aprobada')
        return None

    def _pantalla(self, request, visita, error='', **valores):
        return render(request, self.template_name, {
            'visita': visita, 'detalles': _detalles_visita(visita), 'error': error,
            'nombre': valores.get('nombre', visita.persona_recibe or visita.contacto),
            'cargo': valores.get('cargo', visita.cargo_recibe or visita.cargo_contacto),
            'comentario': valores.get('comentario', ''),
        })

    def get(self, request, token):
        visita = self._visita(token)
        return self._cerrada(request, visita) or self._pantalla(request, visita)

    def post(self, request, token):
        visita = self._visita(token)
        cerrada = self._cerrada(request, visita)
        if cerrada:
            return cerrada
        accion = request.POST.get('accion', '')
        nombre = (request.POST.get('nombre') or '').strip()
        cargo = (request.POST.get('cargo') or '').strip()
        comentario = (request.POST.get('comentario') or '').strip()
        valores = {'nombre': nombre, 'cargo': cargo, 'comentario': comentario}

        if accion == 'aprobar':
            if not nombre:
                return self._pantalla(request, visita, "Escribe tu nombre para aprobar la visita.", **valores)
            visita.estado = 'CONFIRMADA'
            visita.aprobada_en = timezone.now()
            visita.aprobada_por = nombre
            visita.cargo_aprobo = cargo
            visita.cliente_acepta = 'SI'
            visita.medio_confirmacion = 'CORREO'
            visita.comentario_cliente = ''
            visita.save()
            _avisar_oficina(request, visita, f"El cliente aprobó la visita {visita.codigo}",
                            f"{nombre}{' (' + cargo + ')' if cargo else ''} aprobó la visita técnica "
                            f"a {visita.empresa}. Ya se puede realizar.")
            return self._gracias(request, visita, 'aprobada')

        if accion == 'cambio':
            if not comentario:
                return self._pantalla(request, visita, "Cuéntanos qué fecha u hora te sirve.", **valores)
            visita.comentario_cliente = comentario
            visita.save(update_fields=['comentario_cliente'])
            _avisar_oficina(request, visita, f"El cliente pide otra fecha para la visita {visita.codigo}",
                            f"{nombre or 'El cliente'} de {visita.empresa} no aprobó la fecha propuesta "
                            "y dejó este comentario. Reprográmala desde la visita para que reciba la nueva solicitud.",
                            texto_extra=comentario)
            return self._gracias(request, visita, 'cambio')

        return self._pantalla(request, visita, "Elige una opción.", **valores)


# ============================================================
#  EL EJECUTIVO EN CAMPO (secciones 2 a 6, fotos y su firma)
# ============================================================

def _guardar_firma(visita, campo, datos, nombre):
    """Guarda una firma del pad (PNG en data URI ya validado) en el campo dicho."""
    crudo = _decodificar_firma_png(datos)
    if crudo is None:
        return False
    getattr(visita, campo).save(f'{nombre}_{visita.pk}.png', ContentFile(crudo), save=False)
    return True


class CampoVisitaView(AsesorRequiredMixin, View):
    """
    Secciones 2 a 6 y la firma del ejecutivo: lo que se llena en la visita,
    desde el celular. Solo con la visita APROBADA por el cliente. Se puede
    guardar por partes y volver; «Guardar y pasar a la firma del cliente»
    lleva al QR con el que el cliente firma (eso la marca realizada).
    """
    template_name = 'gestion/campo_visita.html'

    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated:
            visita = get_object_or_404(VisitaTecnica, pk=kwargs.get('pk'))
            if not visita.en_campo_permitido:
                messages.error(
                    request,
                    "La visita todavía no se puede trabajar en campo: el cliente debe aprobarla primero."
                    if visita.pendiente_aprobacion else "Esta visita está cancelada.")
                return redirect('gestion:detalle_visita', pk=visita.pk)
        return super().dispatch(request, *args, **kwargs)

    def _contexto(self, visita, form, formset):
        return {
            'visita': visita, 'form': form, 'formset': formset,
            'fotos': visita.fotos.all(),
        }

    def get(self, request, pk):
        visita = get_object_or_404(VisitaTecnica, pk=pk)
        initial = {}
        if not visita.ejecutivo_realizo:
            quien = visita.ejecutivo or request.user
            initial['ejecutivo_realizo'] = quien.get_full_name() or quien.username
        if not visita.representante_cliente:
            initial['representante_cliente'] = visita.persona_recibe or visita.contacto
            initial['cargo_representante'] = visita.cargo_recibe or visita.cargo_contacto
        form = VisitaCampoForm(instance=visita, initial=initial)
        formset = ServicioVisitaFormSet(instance=visita, prefix='srv')
        return render(request, self.template_name, self._contexto(visita, form, formset))

    def post(self, request, pk):
        visita = get_object_or_404(VisitaTecnica, pk=pk)
        form = VisitaCampoForm(request.POST, instance=visita)
        formset = ServicioVisitaFormSet(request.POST, instance=visita, prefix='srv')
        a_firma = 'a_firma' in request.POST
        if not (form.is_valid() and formset.is_valid()):
            messages.error(request, "Revisa lo marcado: falta algo.")
            return render(request, self.template_name, self._contexto(visita, form, formset))

        with transaction.atomic():
            visita = form.save(commit=False)
            formset.save()
            _guardar_firma(visita, 'firma_ejecutivo', request.POST.get('firma_ejecutivo_data'), 'firma_ejecutivo')
            if request.FILES.get('sello_cliente'):
                visita.sello_cliente = request.FILES['sello_cliente']
            visita.save()
            for foto in request.FILES.getlist('fotos'):
                FotoVisita.objects.create(visita=visita, archivo=foto, subida_por=request.user)

        if a_firma and visita.estado != 'REALIZADA':
            messages.success(request, "Datos guardados. Ahora firma el cliente.")
            return redirect('gestion:firma_visita', pk=visita.pk)
        messages.success(request, "Guardado. Puedes seguir llenando la visita cuando quieras."
                         if visita.estado != 'REALIZADA' else "Corrección guardada.")
        if 'seguir' in request.POST:
            return redirect('gestion:campo_visita', pk=visita.pk)
        return redirect('gestion:detalle_visita', pk=visita.pk)


class EliminarFotoVisitaView(AsesorRequiredMixin, View):
    def post(self, request, pk, foto_pk):
        foto = get_object_or_404(FotoVisita, pk=foto_pk, visita_id=pk)
        foto.archivo.delete(save=False)
        foto.delete()
        messages.success(request, "Foto eliminada.")
        return redirect(request.POST.get('volver') or reverse('gestion:campo_visita', kwargs={'pk': pk}))


# ============================================================
#  LA FIRMA DEL CLIENTE: QR del ejecutivo y página pública
# ============================================================

class FirmaVisitaView(AsesorRequiredMixin, View):
    """
    El QR y el enlace con el que el cliente firma la visita desde su celular
    (igual que el acta de servicio), y la espera hasta que firme. El token de
    firma nace aquí, al terminar en campo. Con POST se le manda el enlace al
    correo del cliente.
    """
    template_name = 'gestion/firma_visita.html'

    def _visita(self, request, pk):
        visita = get_object_or_404(VisitaTecnica, pk=pk)
        if not visita.en_campo_permitido:
            messages.error(request, "El cliente debe aprobar la visita antes de poder firmarla.")
            return None
        return visita

    def get(self, request, pk):
        visita = self._visita(request, pk)
        if visita is None:
            return redirect('gestion:detalle_visita', pk=pk)
        url = request.build_absolute_uri(
            reverse('gestion:firmar_visita', kwargs={'token': visita.asegurar_token_firma()}))
        return render(request, self.template_name, {
            'visita': visita, 'url_publica': url, 'qr_b64': _qr_data_uri(url),
            'firmada': visita.estado == 'REALIZADA',
            'sin_datos': not visita.servicios.exists() and not visita.alcance_preliminar,
        })

    def post(self, request, pk):
        visita = self._visita(request, pk)
        if visita is None:
            return redirect('gestion:detalle_visita', pk=pk)
        if visita.estado == 'REALIZADA':
            messages.info(request, "El cliente ya firmó esta visita.")
        else:
            enviado, aviso = enviar_enlace_firma(request, visita)
            (messages.success if enviado else messages.warning)(request, aviso)
        return redirect('gestion:firma_visita', pk=pk)


class EstadoFirmaVisitaView(AsesorRequiredMixin, View):
    """Sondeo de la pantalla del QR: ¿ya firmó el cliente?"""

    def get(self, request, pk):
        visita = get_object_or_404(VisitaTecnica, pk=pk)
        return JsonResponse({'firmada': visita.estado == 'REALIZADA'})


class FirmarVisitaPublicaView(View):
    """
    Página PÚBLICA (sin usuario) que abre el cliente con el QR o el enlace:
    ve el resumen de lo levantado y firma con el dedo. Con la firma la visita
    queda REALIZADA; el enlace deja de servir.
    """
    template_name = 'gestion/visita_publica_firmar.html'

    @staticmethod
    def _visita(token):
        return get_object_or_404(
            VisitaTecnica.objects.select_related('ejecutivo').prefetch_related('servicios'),
            token_firma=token)

    @staticmethod
    def _gracias(request, visita, modo):
        return render(request, 'gestion/visita_publica_gracias.html', {'visita': visita, 'modo': modo})

    def _cerrada(self, request, visita):
        if visita.estado == 'REALIZADA':
            return self._gracias(request, visita, 'ya_firmada')
        if visita.estado == 'CANCELADA':
            return self._gracias(request, visita, 'cancelada')
        return None

    def _pantalla(self, request, visita, error='', nombre=None, cargo=None):
        return render(request, self.template_name, {
            'visita': visita, 'detalles': _detalles_visita(visita)[:5], 'error': error,
            'servicios': list(visita.servicios.all()),
            'nombre': nombre if nombre is not None else (
                visita.representante_cliente or visita.persona_recibe or visita.contacto),
            'cargo': cargo if cargo is not None else (
                visita.cargo_representante or visita.cargo_recibe or visita.cargo_contacto),
        })

    def get(self, request, token):
        visita = self._visita(token)
        return self._cerrada(request, visita) or self._pantalla(request, visita)

    def post(self, request, token):
        visita = self._visita(token)
        cerrada = self._cerrada(request, visita)
        if cerrada:
            return cerrada
        nombre = (request.POST.get('nombre') or '').strip()
        cargo = (request.POST.get('cargo') or '').strip()
        # La firma se valida ANTES de tocar la visita: si no es un PNG legítimo
        # no queda realizada y el cliente puede volver a intentarlo.
        firma = _decodificar_firma_png(request.POST.get('signature_data'))
        if not nombre or firma is None:
            return self._pantalla(request, visita, "Falta la firma o el nombre de quien firma.", nombre, cargo)

        ahora = timezone.now()
        with transaction.atomic():
            visita.representante_cliente = nombre
            visita.cargo_representante = cargo
            visita.estado = 'REALIZADA'
            visita.realizada_en = ahora
            visita.firmada_en = ahora
            visita.val_constancia = True
            if not visita.fecha_cierre:
                visita.fecha_cierre = timezone.localdate()
            visita.firma_cliente.save(f'firma_cliente_{visita.pk}.png', ContentFile(firma), save=False)
            visita.save()
        _avisar_oficina(request, visita, f"El cliente firmó la visita {visita.codigo}",
                        f"{nombre}{' (' + cargo + ')' if cargo else ''} firmó la visita técnica a "
                        f"{visita.empresa}. Quedó realizada y su PDF ya se puede descargar.")
        return self._gracias(request, visita, 'firmada')


# ============================================================
#  PDF DEL FORMATO
# ============================================================

def _imagen_b64(campo):
    """Una imagen del storage como data URI, para embeberla en el PDF (o '' si no hay)."""
    import mimetypes
    if not campo:
        return ''
    try:
        with campo.open('rb') as fh:
            contenido = fh.read()
    except (OSError, ValueError):
        return ''
    tipo = mimetypes.guess_type(campo.name)[0] or 'image/png'
    return f"data:{tipo};base64," + base64.b64encode(contenido).decode()


def _pdf_visita(visita, request):
    """El formato GC-F-01 v03 con lo registrado, generado al momento (no se guarda)."""
    template = get_template('gestion/visita_pdf.html')
    html = template.render({
        'visita': visita,
        'servicios': list(visita.servicios.all()),
        'fotos': [{'src': _imagen_b64(f.archivo), 'nota': f.nota} for f in visita.fotos.all()],
        'firma_ejecutivo': _imagen_b64(visita.firma_ejecutivo),
        'firma_cliente': _imagen_b64(visita.firma_cliente),
        'sello_cliente': _imagen_b64(visita.sello_cliente),
        'logo_b64': _logo_b64(),
        'filas_vacias': range(max(0, 4 - visita.servicios.count())),
    })
    return HTML(string=html, base_url=request.build_absolute_uri()).write_pdf()


class VisitaPDFView(AsesorRequiredMixin, View):
    def get(self, request, pk):
        visita = get_object_or_404(VisitaTecnica, pk=pk)
        respuesta = HttpResponse(_pdf_visita(visita, request), content_type='application/pdf')
        modo = 'inline' if request.GET.get('ver') else 'attachment'
        respuesta['Content-Disposition'] = f'{modo}; filename="visita_tecnica_{visita.codigo}.pdf"'
        return respuesta
