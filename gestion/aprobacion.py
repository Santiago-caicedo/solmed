"""
El proceso de facturación SIMPLE (15-nov-2026, Santiago): lo que pasa entre
la comercial, el cliente y la administradora después de armar la
preliquidación.

  1. La comercial la envía al cliente → `enviar_a_revision` crea un enlace
     único (RevisionCliente) y manda el correo. Cada reenvío crea otro
     enlace y deja el anterior sin vigencia.
  2. El cliente abre el enlace (RevisionClienteView, sin usuario): ve la
     preliquidación, baja los documentos y la aprueba o la devuelve con
     observaciones → `responder_revision`.
  3. Aprobada, la comercial escribe las instrucciones para facturar y la
     pasa a «Lista para facturar» → `pasar_a_lista` (correo a la
     administración).
  4. La administradora factura en su software contable y sube la FEV y el
     XML (en DetalleFacturaView): queda «Facturada» y termina.

Un PDF aparte (concepto que va en su propia preliquidación) acompaña al
global en todo el proceso: el cliente lo ve en el mismo enlace y las etapas
se le copian; solo la FEV es de cada uno.
"""
import mimetypes
import os

from django.conf import settings
from django.contrib import messages
from django.core.mail import EmailMultiAlternatives
from django.http import FileResponse, Http404, HttpResponse
from django.shortcuts import get_object_or_404, render
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone
from django.views import View

from .models import ADJUNTOS_FACTURA, EnvioCorreo, Factura, FotoRegistro, RevisionCliente

# Lo que el cliente puede ver por el enlace: los adjuntos de siempre, menos la
# factura electrónica y el XML (esos los sube la administradora al final).
DOCUMENTOS_CLIENTE = tuple((c, n) for c, n in ADJUNTOS_FACTURA if c not in ('factura', 'xml'))


def _v():
    """views.py importa este módulo; para no dar la vuelta, sus ayudantes se cargan al usarlos."""
    from . import views
    return views


# ============================================================
#  Qué ve el cliente
# ============================================================

def documentos_para_el_cliente(factura, solo_marcados=True):
    """
    Los documentos del enlace, en el orden de siempre: por cada punto marcado
    en «Documentos para el cliente», su nombre y sus archivos como (nombre,
    clave de descarga). Al final, el PDF de cada concepto aparte.
    """
    v = _v()
    lineas = list(factura.lineas.select_related('orden'))
    grupos = []

    def grupo(clave, etiqueta, archivos):
        if archivos:
            grupos.append({'clave': clave, 'etiqueta': etiqueta, 'archivos': archivos})

    for clave, etiqueta in DOCUMENTOS_CLIENTE:
        if solo_marcados and not getattr(factura, f'copiar_{clave}'):
            continue
        if clave == 'orden_compra':
            archivos = ([(v._nombre_archivo(factura.archivo_orden_compra), 'orden_compra')]
                        if factura.archivo_orden_compra else [])
        elif clave == 'orden_pedido':
            archivos = ([(v._nombre_archivo(factura.archivo_orden_pedido), 'orden_pedido')]
                        if factura.archivo_orden_pedido else [])
        elif clave == 'actas':
            archivos = [(f"Acta de servicio · orden #{a.recorrido.orden_id}", f"acta_{a.recorrido_id}")
                        for a in factura.actas_firmadas()]
        elif clave == 'basculas':
            archivos = [(f"Tiquete de báscula · orden #{l.orden_id}", f"bascula_{l.orden_id}")
                        for l in lineas if l.copiar_bascula and l.orden.bascula_adjunto]
        elif clave == 'excel':
            archivos = [(f"Preliquidacion_{factura.codigo}.xlsx", 'excel')]
        elif clave == 'informes':
            archivos = [(i.nombre, f"informe_{i.pk}") for i in factura.informes]
        elif clave == 'fotos':
            fotos = (FotoRegistro.objects.filter(orden__lineas_factura__factura=factura)
                     .select_related('orden').order_by('orden__numero_orden', 'subido_en'))
            archivos = [(f"Foto del servicio · orden #{f.orden.numero_orden}", f"foto_{f.pk}") for f in fotos]
        else:   # otros
            archivos = [(o.nombre, f"otro_{o.pk}") for o in factura.otros_adjuntos]
        grupo(clave, etiqueta, archivos)
    for hijo in factura.apartes.order_by('numero'):
        grupo('aparte', f"Preliquidación aparte {hijo.codigo}",
              [(f"Preliquidacion_{hijo.codigo}.pdf", f"aparte_{hijo.pk}")])
    return grupos


def _claves_permitidas(factura):
    return {clave for g in documentos_para_el_cliente(factura) for _n, clave in g['archivos']}


def abrir_documento(factura, clave, request=None):
    """
    El archivo que pide el enlace: (nombre, contenido o archivo abierto, tipo).
    Solo lo que el enlace muestra; cualquier otra clave es 404.
    """
    v = _v()
    if clave == 'pdf':
        return f"Preliquidacion_{factura.codigo}.pdf", v._pdf_factura(factura, request), 'application/pdf'
    if clave not in _claves_permitidas(factura):
        raise Http404
    if clave == 'excel':
        return (f"Preliquidacion_{factura.codigo}.xlsx", v._excel_factura(factura),
                'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    if clave in ('orden_compra', 'orden_pedido'):
        campo = getattr(factura, f'archivo_{clave}')
        return _archivo(campo, f"{'Orden_compra' if clave == 'orden_compra' else 'Orden_pedido'}_{factura.codigo}")
    tipo, _, pk = clave.partition('_')
    pk = int(pk)
    if tipo == 'acta':
        acta = factura.actas_firmadas().get(recorrido_id=pk)
        return f"Acta_servicio_{acta.recorrido.orden_id}.pdf", v._pdf_manifiesto(acta), 'application/pdf'
    if tipo == 'bascula':
        linea = factura.lineas.select_related('orden').get(orden_id=pk)
        return _archivo(linea.orden.bascula_adjunto, f"Bascula_orden_{pk}")
    if tipo == 'informe':
        informe = factura.informes.get(pk=pk)
        return _archivo(informe.archivo, os.path.splitext(informe.nombre)[0] or informe.archivo.name)
    if tipo == 'foto':
        foto = FotoRegistro.objects.get(pk=pk, orden__lineas_factura__factura=factura)
        return _archivo(foto.archivo, f"Foto_orden_{foto.orden_id}_{pk}")
    if tipo == 'otro':
        otro = factura.otros_adjuntos.get(pk=pk)
        return _archivo(otro.archivo, os.path.splitext(otro.nombre)[0] or otro.archivo.name)
    if tipo == 'aparte':
        hijo = factura.apartes.get(pk=pk)
        return f"Preliquidacion_{hijo.codigo}.pdf", v._pdf_factura(hijo, request), 'application/pdf'
    raise Http404


def _archivo(campo, nombre):
    extension = os.path.splitext(campo.name)[1] or ''
    return (f"{nombre}{extension}", campo.open('rb'),
            mimetypes.guess_type(campo.name)[0] or 'application/octet-stream')


# ============================================================
#  Los pasos del proceso
# ============================================================

def _y_sus_apartes(factura):
    return [factura] + list(factura.apartes.all())


def _poner_estado(factura, estado, **campos):
    """La etapa, en el global y en sus PDF aparte."""
    for f in _y_sus_apartes(factura):
        f.estado = estado
        for campo, valor in campos.items():
            setattr(f, campo, valor)
        f.save(update_fields=['estado'] + list(campos))


def enviar_a_revision(request, factura, correos, copias=()):
    """
    Crea el enlace del cliente y se lo manda. Devuelve True si el correo
    salió. Un enlace anterior abierto queda sin vigencia.
    """
    v = _v()
    correos = [c for c in correos if c]
    if not correos:
        messages.error(request, "Escribe el correo de facturación del cliente para poder enviarle la preliquidación.")
        return False
    copias = [c for c in copias if c and c not in correos]
    factura.revisiones.filter(vigente=True).update(vigente=False)
    marcados = [clave for clave, _ in DOCUMENTOS_CLIENTE if getattr(factura, f'copiar_{clave}')]
    revision = RevisionCliente.objects.create(
        factura=factura, enviada_por=request.user, enviada_a=', '.join(correos)[:500], documentos=marcados)
    enlace = request.build_absolute_uri(reverse('gestion:revision_cliente', args=[revision.token]))

    ordenes = ', '.join(f"#{l.orden_id}" for l in factura.lineas.all())
    asunto = f"Preliquidación {factura.codigo} para su aprobación — SOLMED SAS"
    documentos = documentos_para_el_cliente(factura)
    mensaje = (f"Buen día,\n\nLe enviamos la preliquidación {factura.codigo} correspondiente a las órdenes de "
               f"servicio {ordenes}, por ${factura.total:,.0f}, para su revisión y aprobación antes de "
               f"expedir la factura electrónica.\n\nEn el siguiente enlace puede ver la preliquidación, "
               f"descargar los documentos y aprobarla o pedirnos correcciones:\n{enlace}").replace(',', '.')
    html = render_to_string('gestion/correo_revision_cliente.html', {
        'factura': factura, 'enlace': enlace, 'ordenes': ordenes, 'total': factura.total,
        'documentos': documentos, 'cliente': factura.cliente,
    })
    adjuntos = [(f"Preliquidacion_{factura.codigo}.pdf", v._pdf_factura(factura, request), 'application/pdf')]
    for hijo in factura.apartes.order_by('numero'):
        adjuntos.append((f"Preliquidacion_{hijo.codigo}.pdf", v._pdf_factura(hijo, request), 'application/pdf'))
    destinatarios = ', '.join(correos) + (" · copia: " + ', '.join(copias) if copias else '')
    registro = EnvioCorreo(
        cliente=factura.cliente, destinatarios=destinatarios[:500], asunto=asunto, mensaje=mensaje,
        adjuntos=[f"factura:{factura.pk}"], adjuntos_detalle=[a[0] for a in adjuntos],
        responder_a=', '.join(v._reply_to()), enviado_por=request.user)
    correo = EmailMultiAlternatives(subject=asunto, body=mensaje + "\n\nCordialmente,\nSOLMED SAS",
                                    from_email=settings.DEFAULT_FROM_EMAIL, to=correos, cc=copias,
                                    reply_to=v._reply_to())
    correo.attach_alternative(html, 'text/html')
    for nombre, contenido, tipo in adjuntos:
        correo.attach(nombre, contenido, tipo)
    try:
        correo.send(fail_silently=False)
    except Exception as e:  # noqa: BLE001 - lo que sea que rechace el servidor de correo
        registro.estado = 'FALLIDO'
        registro.error = str(e)
        registro.save()
        revision.vigente = False
        revision.save(update_fields=['vigente'])
        messages.error(request, f"El servidor de correo rechazó el envío ({e}). La preliquidación sigue "
                                "en tus manos; quedó registrado como fallido en el Centro de correos.")
        return False
    registro.save()
    _poner_estado(factura, 'ESPERANDO_CLIENTE')
    v._registrar_evento(factura, 'Enviada al cliente para su aprobación', request.user, 'ESPERANDO_CLIENTE',
                        f"A {destinatarios}")
    messages.success(request, f"{factura.codigo} enviada a {', '.join(correos)}. El cliente la aprueba o la "
                              "devuelve desde su enlace; te avisamos por correo.")
    return True


def responder_revision(request, revision, respuesta, nombre, cargo='', observaciones=''):
    """Lo que el cliente dijo en su enlace: aprobada o devuelta con observaciones."""
    v = _v()
    factura = revision.factura
    ahora = timezone.now()
    revision.respuesta = respuesta
    revision.respondida_en = ahora
    revision.nombre = nombre[:150]
    revision.cargo = cargo[:100]
    revision.observaciones = observaciones
    revision.save()
    estado = 'APROBADA' if respuesta == 'APROBADA' else 'DEVUELTA'
    _poner_estado(factura, estado, cliente_respondio_en=ahora, cliente_nombre=nombre[:150],
                  cliente_cargo=cargo[:100], observaciones_cliente=observaciones)
    quien = f"{nombre}{' (' + cargo + ')' if cargo else ''}"
    titulo = (f"Aprobada por el cliente · {quien}" if estado == 'APROBADA'
              else f"Devuelta por el cliente · {quien}")
    v._registrar_evento(factura, titulo, None, estado, observaciones)
    comercial = factura.comercial
    if comercial is not None and comercial.email:
        if estado == 'APROBADA':
            lineas = [f"{quien} aprobó la preliquidación {factura.codigo} de {factura.cliente.nombre}.", "",
                      "Ahora: escribe las instrucciones para facturar y pásala a «Lista para facturar»."]
        else:
            lineas = [f"{quien} devolvió la preliquidación {factura.codigo} de {factura.cliente.nombre} "
                      "con observaciones:", "", observaciones, "",
                      "Ahora: corrige lo que pide y vuelve a enviársela (recibirá un enlace nuevo)."]
        lineas += [""] + v._resumen_para_correo(factura)
        v._correo_proceso(request, factura, [comercial.email],
                          f"{factura.codigo} · {dict(Factura.ESTADO_CHOICES)[estado]} · {factura.cliente.nombre}",
                          lineas)


def pasar_a_lista(request, factura, instrucciones):
    """La comercial terminó: queda lista para que la administradora facture."""
    v = _v()
    factura.concepto_facturacion = instrucciones
    factura.save(update_fields=['concepto_facturacion'])
    _poner_estado(factura, 'LISTA', pasada_a_facturacion_por=request.user, pasada_a_facturacion_en=timezone.now())
    v._registrar_evento(factura, 'Lista para facturar', request.user, 'LISTA', instrucciones)
    v._correo_proceso(
        request, factura, v._correos_administradoras(excepto=request.user),
        f"Lista para facturar {factura.codigo} · {factura.cliente.nombre}",
        [f"{v._nombre_de(request.user)} dejó lista para facturar la preliquidación {factura.codigo}, "
         f"aprobada por el cliente{' (' + factura.cliente_nombre + ')' if factura.cliente_nombre else ''}.", ""]
        + v._resumen_para_correo(factura)
        + ["", "Instrucciones para facturar:", instrucciones or '—'])
    messages.success(request, f"{factura.codigo} quedó lista para facturar: se le avisó a la administración.")


def devolver_a_comercial(request, factura, nota):
    """La administradora la regresa (a «Aprobada») para que la comercial complete algo."""
    v = _v()
    _poner_estado(factura, 'APROBADA')
    v._registrar_evento(factura, 'Devuelta a la comercial', request.user, 'APROBADA', nota)
    comercial = factura.comercial
    if comercial is not None and comercial != request.user and comercial.email:
        v._correo_proceso(request, factura, [comercial.email],
                          f"{factura.codigo} · devuelta a la comercial · {factura.cliente.nombre}",
                          [f"{v._nombre_de(request.user)} te devolvió la preliquidación {factura.codigo}:", "",
                           nota, ""] + v._resumen_para_correo(factura))
    messages.warning(request, f"{factura.codigo} volvió a la comercial con tu nota.")


def volver_a_preliquidacion(request, factura, motivo):
    """Se anula el enlace abierto (o la aprobación) y la comercial la retoma."""
    v = _v()
    factura.revisiones.filter(vigente=True).update(vigente=False)
    _poner_estado(factura, 'PRELIQUIDACION')
    v._registrar_evento(factura, 'De vuelta en preliquidación', request.user, 'PRELIQUIDACION', motivo)


# ============================================================
#  El enlace del cliente (sin usuario)
# ============================================================

class RevisionClienteView(View):
    """
    La página del cliente: la preliquidación, sus documentos y dos botones,
    aprobar o pedir correcciones. Ya respondida, se ve lo que respondió; un
    enlace reemplazado dice que hay una versión más reciente.
    """
    template_name = 'gestion/preliquidacion_publica.html'

    @staticmethod
    def _revision(token):
        return get_object_or_404(RevisionCliente.objects.select_related('factura__cliente'), token=token)

    def _pantalla(self, request, revision, error='', recien=False, **valores):
        v = _v()
        factura = revision.factura
        return render(request, self.template_name, {
            'revision': revision, 'factura': factura, 'cliente': factura.cliente,
            'lineas': v._lineas_con_detalle(factura), 'total': factura.total,
            'apartes': list(factura.apartes.order_by('numero')),
            'documentos': documentos_para_el_cliente(factura),
            'n_documentos': sum(len(g['archivos']) for g in documentos_para_el_cliente(factura)),
            'vigente': revision.vigente, 'abierta': revision.abierta, 'recien': recien,
            'error': error,
            'nombre': valores.get('nombre', ''), 'cargo': valores.get('cargo', ''),
            'observaciones': valores.get('observaciones', ''),
            'pedir': valores.get('pedir', False),
        })

    def get(self, request, token):
        return self._pantalla(request, self._revision(token))

    def post(self, request, token):
        revision = self._revision(token)
        if not revision.abierta:
            return self._pantalla(request, revision)
        accion = request.POST.get('accion', '')
        nombre = ' '.join((request.POST.get('nombre') or '').split())
        cargo = ' '.join((request.POST.get('cargo') or '').split())
        observaciones = (request.POST.get('observaciones') or '').strip()
        valores = {'nombre': nombre, 'cargo': cargo, 'observaciones': observaciones,
                   'pedir': accion == 'devolver'}
        if accion not in ('aprobar', 'devolver'):
            return self._pantalla(request, revision, "No se reconoció la acción.", **valores)
        if not nombre:
            return self._pantalla(request, revision, "Escriba su nombre: queda como constancia de quién responde.",
                                  **valores)
        if accion == 'devolver' and not observaciones:
            return self._pantalla(request, revision, "Cuéntenos qué hay que corregir: sin observaciones no "
                                                     "sabríamos qué cambiar.", **valores)
        responder_revision(request, revision, 'APROBADA' if accion == 'aprobar' else 'DEVUELTA',
                           nombre, cargo, observaciones)
        revision.refresh_from_db()
        return self._pantalla(request, revision, recien=True)


class RevisionArchivoView(View):
    """Un archivo del enlace: el PDF de la preliquidación o cualquiera de sus documentos."""

    def get(self, request, token, clave):
        revision = get_object_or_404(RevisionCliente.objects.select_related('factura'), token=token)
        if not revision.vigente:
            raise Http404
        try:
            nombre, contenido, tipo = abrir_documento(revision.factura, clave, request)
        except (ValueError, Factura.DoesNotExist, FotoRegistro.DoesNotExist):
            raise Http404
        except Exception as e:   # noqa: BLE001 - un pk que no es de esta factura
            if 'DoesNotExist' in type(e).__name__:
                raise Http404
            raise
        disposicion = 'attachment' if request.GET.get('descargar') else 'inline'
        if isinstance(contenido, (bytes, bytearray)):
            respuesta = HttpResponse(contenido, content_type=tipo)
        else:
            respuesta = FileResponse(contenido, content_type=tipo)
        respuesta['Content-Disposition'] = f'{disposicion}; filename="{nombre}"'
        return respuesta
