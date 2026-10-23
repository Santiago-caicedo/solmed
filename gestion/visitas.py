"""
El módulo de VISITAS TÉCNICAS (oct-2026, pedido de la clienta): el formato
GC-F-01 versión 03 llevado al sistema.

La oficina (asesores y gestión) programa la visita —sección 1— desde el
computador; el ejecutivo comercial llena en campo, desde el celular, la
información técnica del servicio, las condiciones de acceso, las evidencias,
las conclusiones, la validación y las firmas (secciones 2 a 6), y la marca
realizada. La visita queda archivada con su PDF en el formato. La empresa
puede ser un cliente registrado o un prospecto que aún no existe.
"""
import base64

from django.conf import settings
from django.contrib import messages
from django.core.files.base import ContentFile
from django.db import transaction
from django.db.models import Count, Q
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import get_template
from django.urls import reverse
from django.utils import timezone
from django.views import View
from django.views.generic import ListView
from weasyprint import HTML

from .forms import ServicioVisitaFormSet, VisitaCampoForm, VisitaProgramacionForm
from .models import FotoVisita, VisitaTecnica
from .views import AsesorRequiredMixin, PaginadoMixin, _decodificar_firma_png


def _logo_b64():
    import os
    ruta = os.path.join(settings.BASE_DIR, 'static', 'images', 'logo-solmed.png')
    with open(ruta, 'rb') as fh:
        return "data:image/png;base64," + base64.b64encode(fh.read()).decode()


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
    """Sección 1: crear o corregir la programación de una visita (la oficina)."""
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
        nueva.save()
        messages.success(request, f"Visita {nueva.codigo} {'actualizada' if visita else 'programada'}.")
        return redirect('gestion:detalle_visita', pk=nueva.pk)


class DetalleVisitaView(AsesorRequiredMixin, View):
    """La visita completa: programación, lo levantado en campo, fotos, firmas y PDF."""
    template_name = 'gestion/detalle_visita.html'

    def get(self, request, pk):
        visita = get_object_or_404(
            VisitaTecnica.objects.select_related('cliente', 'ejecutivo', 'creada_por')
            .prefetch_related('servicios', 'fotos'), pk=pk)
        return render(request, self.template_name, {
            'visita': visita,
            'estados': [c for c in VisitaTecnica.ESTADO_CHOICES if c[0] != 'REALIZADA'],
        })


class CambiarEstadoVisitaView(AsesorRequiredMixin, View):
    """Confirmar, reprogramar o cancelar desde el detalle. «Realizada» se marca en campo."""

    def post(self, request, pk):
        visita = get_object_or_404(VisitaTecnica, pk=pk)
        estado = request.POST.get('estado', '')
        if estado not in dict(VisitaTecnica.ESTADO_CHOICES) or estado == 'REALIZADA':
            messages.error(request, "Ese estado no se puede poner desde aquí.")
        else:
            visita.estado = estado
            visita.save(update_fields=['estado'])
            messages.success(request, f"Visita {visita.codigo}: {visita.get_estado_display().lower()}.")
        return redirect('gestion:detalle_visita', pk=pk)


def _guardar_firma(visita, campo, datos, nombre):
    """Guarda una firma del pad (PNG en data URI ya validado) en el campo dicho."""
    crudo = _decodificar_firma_png(datos)
    if crudo is None:
        return False
    getattr(visita, campo).save(f'{nombre}_{visita.pk}.png', ContentFile(crudo), save=False)
    return True


class CampoVisitaView(AsesorRequiredMixin, View):
    """
    Secciones 2 a 6 y firmas: lo que el ejecutivo llena en la visita, desde el
    celular. Se puede guardar por partes y volver; «Guardar y marcar realizada»
    cierra la visita (exige el nombre del representante del cliente y su
    firma, que es la constancia de la visita).
    """
    template_name = 'gestion/campo_visita.html'

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
        cerrar = 'marcar_realizada' in request.POST
        ok = form.is_valid() and formset.is_valid()
        if ok and cerrar:
            if not (form.cleaned_data.get('representante_cliente') or '').strip():
                form.add_error('representante_cliente',
                               "Para marcarla realizada, di quién atendió la visita por el cliente.")
                ok = False
            if not visita.firma_cliente and _decodificar_firma_png(request.POST.get('firma_cliente_data')) is None:
                messages.error(request, "Para marcarla realizada falta la firma del cliente.")
                ok = False
        if not ok:
            messages.error(request, "Revisa lo marcado: falta algo.")
            return render(request, self.template_name, self._contexto(visita, form, formset))

        with transaction.atomic():
            visita = form.save(commit=False)
            formset.save()
            _guardar_firma(visita, 'firma_cliente', request.POST.get('firma_cliente_data'), 'firma_cliente')
            _guardar_firma(visita, 'firma_ejecutivo', request.POST.get('firma_ejecutivo_data'), 'firma_ejecutivo')
            if request.FILES.get('sello_cliente'):
                visita.sello_cliente = request.FILES['sello_cliente']
            if cerrar:
                visita.estado = 'REALIZADA'
                visita.realizada_en = timezone.now()
                if not visita.fecha_cierre:
                    visita.fecha_cierre = timezone.localdate()
            visita.save()
            for foto in request.FILES.getlist('fotos'):
                FotoVisita.objects.create(visita=visita, archivo=foto, subida_por=request.user)

        if cerrar:
            messages.success(request, f"Visita {visita.codigo} realizada. Ya puedes descargar su PDF.")
            return redirect('gestion:detalle_visita', pk=visita.pk)
        messages.success(request, "Guardado. Puedes seguir llenando la visita cuando quieras.")
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
