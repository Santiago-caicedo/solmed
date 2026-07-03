import json
import os
from django.conf import settings
from django.http import HttpResponseRedirect
from django.contrib.messages.views import SuccessMessageMixin
from django.contrib.auth.models import User, Group
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, render, redirect
from django.contrib import messages
from django.contrib.auth.mixins import UserPassesTestMixin
from django.template.loader import get_template
from django.urls import reverse, reverse_lazy
from django.core.files.base import ContentFile
from django.views import View
from io import BytesIO
import qrcode
from weasyprint import HTML
from xhtml2pdf import pisa
from django.db.models import Sum, Count
import base64
import datetime
from django.db.models.functions import TruncMonth
from decimal import Decimal 
from django.views.generic import ListView, CreateView, UpdateView, TemplateView, DetailView
from django.utils import timezone
from django.db.models import Sum
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db.models import Q
from .models import EncuestaConductor, Manifiesto, OrdenServicio, Pago, Programacion, Recorrido
from django.http import JsonResponse
from .forms import DocumentoOrdenForm, EncuestaConductorForm, ManifiestoPaso1Form, ManifiestoPaso2Form, ManifiestoPaso3Form, ManifiestoPaso4Form, ManifiestoPaso5Form, OrdenServicioForm, PagoForm, ProgramacionForm, ProgramacionCuadrillaFormSet, RecorridoForm, ReporteFiltroForm, VehiculoForm, ClienteForm, CrearUsuarioForm, ActualizarUsuarioForm
from .models import OrdenServicio, Vehiculo, Cliente, DocumentoAmbientalCliente


# --- NUEVO MIXIN DE SEGURIDAD PARA PLANIFICADORES ---
class PlanificadorRequiredMixin(LoginRequiredMixin, UserPassesTestMixin):
    def test_func(self):
        user = self.request.user
        return user.is_superuser or user.groups.filter(name='Planificadores').exists()


# --- NUEVO MIXIN DE SEGURIDAD PARA ASESORES Y ADMINS ---
class AsesorRequiredMixin(LoginRequiredMixin, UserPassesTestMixin):
    """
    Este Mixin restringe el acceso a Superusuarios y a miembros del grupo 'Asesores'.
    """
    def test_func(self):
        return self.request.user.is_superuser or self.request.user.groups.filter(name='Asesores').exists()


# --- MIXIN QUE BLOQUEA A LOS CONDUCTORES ---
class NoConductorRequiredMixin(LoginRequiredMixin, UserPassesTestMixin):
    """
    Permite el acceso a cualquier usuario autenticado EXCEPTO a los conductores.
    Se usa en vistas de gestión (como el expediente de la orden) a las que el
    conductor no debe entrar.
    """
    def test_func(self):
        user = self.request.user
        return user.is_superuser or not user.groups.filter(name='Conductores').exists()


# --- Vista Principal (Dashboard) ---
# Se protege con LoginRequiredMixin para que sea la página de inicio después del login.
class DashboardView(LoginRequiredMixin, TemplateView):
    template_name = 'gestion/dashboard.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        now = timezone.now()

        # --- MÉTRICAS ---
        # Mantenemos esta consulta porque la usamos en varios lugares
        ordenes_activas = OrdenServicio.objects.filter(estado_orden='EN_EJECUCION')
        context['ordenes_activas'] = ordenes_activas.count()
        
        cobranza = OrdenServicio.objects.filter(estado_pago='PENDIENTE').aggregate(total=Sum('valor_servicio'))
        context['cobranza_pendiente'] = cobranza['total'] or 0.00
        
        ingresos_mes_query = OrdenServicio.objects.filter(estado_orden='FINALIZADA')
        ingresos_mes_total = ingresos_mes_query.aggregate(total=Sum('valor_servicio'))
        context['ingresos_del_mes'] = ingresos_mes_total['total'] or 0.00
        context['servicios_completados_mes'] = ingresos_mes_query.count()

        context['ordenes_pendientes_iniciar'] = OrdenServicio.objects.filter(estado_orden='PROGRAMADA').count()
        
        # --- LÓGICA CORREGIDA PARA UTILIZACIÓN DE VEHÍCULOS ---
        total_vehiculos = Vehiculo.objects.filter(estado='OPERATIVO').count()
        if total_vehiculos > 0:
            # CORRECCIÓN: Buscamos vehículos que tengan recorridos cuya orden esté en ejecución.
            vehiculos_en_servicio_qs = Vehiculo.objects.filter(
                recorridos__orden__estado_orden='EN_EJECUCION'
            ).distinct()
            
            vehiculos_en_servicio = vehiculos_en_servicio_qs.count()
            
            context['utilizacion_vehiculos'] = round((vehiculos_en_servicio / total_vehiculos) * 100, 1)
            context['vehiculos_disponibles'] = total_vehiculos - vehiculos_en_servicio
        else:
            context['utilizacion_vehiculos'] = 0
            context['vehiculos_disponibles'] = 0

        # --- LISTAS ACCIONABLES ---
        context['servicios_hoy'] = Recorrido.objects.filter(
            fecha_recorrido=now.date(), 
            estado__in=['PROGRAMADO', 'EN_CURSO']
        )
        
        context['cobranza_prioritaria'] = OrdenServicio.objects.filter(
            estado_orden='FINALIZADA',
            estado_pago='PENDIENTE'
        ).order_by('fecha_creacion')

        # Vehículos con documentos vencidos o próximos a vencer (para el aviso del dashboard).
        context['vehiculos_con_alerta'] = [
            v for v in Vehiculo.objects.all() if v.tiene_alerta_documentos
        ]

        # Vehículos fuera de servicio (mantenimiento + stand by).
        context['vehiculos_mantenimiento'] = Vehiculo.objects.filter(estado='MANTENIMIENTO').count()
        context['vehiculos_stand_by'] = Vehiculo.objects.filter(estado='STAND_BY').count()
        context['vehiculos_fuera_servicio'] = context['vehiculos_mantenimiento'] + context['vehiculos_stand_by']

        return context


# --- Vistas para Órdenes de Servicio ---
# Todas las vistas de gestión se protegen con LoginRequiredMixin.
# Se usa 'form_class' para conectar la vista con el formulario personalizado.
class ListaOrdenesView(AsesorRequiredMixin, ListView):
    model = OrdenServicio
    template_name = 'gestion/lista_ordenes.html'
    context_object_name = 'ordenes'
    ordering = ['-fecha_creacion']

    def get_queryset(self):
        queryset = super().get_queryset()
        query = self.request.GET.get('q')
        
        # --- LÓGICA DE FILTROS ---
        estado_filtro = self.request.GET.get('estado')
        pago_filtro = self.request.GET.get('pago')

        # Búsqueda por texto
        if query:
            queryset = queryset.filter(
                Q(numero_orden__icontains=query) |
                Q(cliente__nombre__icontains=query)
            )
        
        # Filtro por estado de la orden
        if estado_filtro:
            queryset = queryset.filter(estado_orden=estado_filtro)
        
        # Filtro por estado del pago
        if pago_filtro:
            queryset = queryset.filter(estado_pago=pago_filtro)

        return queryset

    # --- MÉTODO NUEVO PARA PASAR DATOS EXTRAS A LA PLANTILLA ---
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        # Pasamos las opciones de los modelos para construir los dropdowns
        context['estado_choices'] = OrdenServicio.ESTADO_ORDEN_CHOICES
        context['pago_choices'] = OrdenServicio.ESTADO_PAGO_CHOICES
        
        # Pasamos los valores actuales de los filtros para que se mantengan seleccionados
        context['current_estado'] = self.request.GET.get('estado', '')
        context['current_pago'] = self.request.GET.get('pago', '')
        return context

class CrearOrdenView(LoginRequiredMixin, CreateView):
    """
    Crea la orden Y agenda su PRIMER recorrido en el mismo formulario.
    El recorrido usa prefix='rec' para no chocar con el campo 'descripcion'
    que existe en ambos formularios.
    """
    model = OrdenServicio
    form_class = OrdenServicioForm
    template_name = 'gestion/form_orden.html'
    success_url = reverse_lazy('gestion:lista_ordenes')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.setdefault('form_recorrido', RecorridoForm(prefix='rec'))
        return context

    def post(self, request, *args, **kwargs):
        self.object = None
        form = self.get_form()
        form_recorrido = RecorridoForm(request.POST, prefix='rec')
        if form.is_valid() and form_recorrido.is_valid():
            form.instance.asesor = request.user
            self.object = form.save()
            recorrido = form_recorrido.save(commit=False)
            recorrido.orden = self.object
            recorrido.save()  # actualiza el estado de la orden (lógica de Recorrido.save)
            messages.success(request, "Orden creada y primer recorrido agendado.")
            return HttpResponseRedirect(self.get_success_url())
        return self.render_to_response(
            self.get_context_data(form=form, form_recorrido=form_recorrido)
        )


class ActualizarOrdenView(LoginRequiredMixin, UpdateView):
    """
    Edita los datos de la orden y permite AÑADIR más recorridos (uno a uno).
    """
    model = OrdenServicio
    form_class = OrdenServicioForm
    template_name = 'gestion/form_orden.html'
    success_url = reverse_lazy('gestion:lista_ordenes')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.setdefault('form_recorrido', RecorridoForm(prefix='rec'))
        return context

    def post(self, request, *args, **kwargs):
        self.object = self.get_object()
        # Acción: añadir un recorrido a la orden existente.
        if 'submit_recorrido' in request.POST:
            form_recorrido = RecorridoForm(request.POST, prefix='rec')
            if form_recorrido.is_valid():
                recorrido = form_recorrido.save(commit=False)
                recorrido.orden = self.object
                recorrido.save()
                messages.success(request, "Recorrido añadido a la orden.")
                return HttpResponseRedirect(reverse('gestion:actualizar_orden', kwargs={'pk': self.object.pk}))
            # Recorrido inválido: re-render con el formulario de la orden SIN enlazar
            # (mostrando los datos actuales), solo con los errores del recorrido.
            form = self.form_class(instance=self.object)
            return self.render_to_response(
                self.get_context_data(form=form, form_recorrido=form_recorrido)
            )
        # Acción: guardar los cambios de la orden.
        return super().post(request, *args, **kwargs)

    def form_valid(self, form):
        self.object = form.save()
        messages.success(self.request, "Orden actualizada.")
        return HttpResponseRedirect(self.get_success_url())

# --- Vistas para Vehículos ---
class ListaVehiculosView(LoginRequiredMixin, ListView):
    model = Vehiculo
    template_name = 'gestion/lista_vehiculos.html'
    context_object_name = 'vehiculos'

class CrearVehiculoView(LoginRequiredMixin, CreateView):
    model = Vehiculo
    form_class = VehiculoForm
    template_name = 'gestion/form_vehiculo.html'
    success_url = reverse_lazy('gestion:lista_vehiculos')

class ActualizarVehiculoView(LoginRequiredMixin, UpdateView):
    model = Vehiculo
    form_class = VehiculoForm
    template_name = 'gestion/form_vehiculo.html'
    success_url = reverse_lazy('gestion:lista_vehiculos')

# --- Vistas para Clientes ---
class ListaClientesView(LoginRequiredMixin, ListView):
    model = Cliente
    template_name = 'gestion/lista_clientes.html'
    context_object_name = 'clientes'


class DocumentosAmbientalesClienteMixin:
    """
    Procesa la carga MÚLTIPLE de documentos ambientales (input file 'documentos_ambientales')
    y la eliminación de los marcados ('eliminar_doc_ambiental'), tras guardar el cliente.
    """
    def form_valid(self, form):
        response = super().form_valid(form)
        ids_eliminar = self.request.POST.getlist('eliminar_doc_ambiental')
        if ids_eliminar:
            self.object.documentos_ambientales.filter(pk__in=ids_eliminar).delete()
        for archivo in self.request.FILES.getlist('documentos_ambientales'):
            DocumentoAmbientalCliente.objects.create(cliente=self.object, archivo=archivo)
        return response


class CrearClienteView(DocumentosAmbientalesClienteMixin, LoginRequiredMixin, CreateView):
    model = Cliente
    form_class = ClienteForm
    template_name = 'gestion/form_cliente.html'
    success_url = reverse_lazy('gestion:lista_clientes')
    success_message = "¡Cliente creado exitosamente!"

class ActualizarClienteView(DocumentosAmbientalesClienteMixin, LoginRequiredMixin, UpdateView):
    model = Cliente
    form_class = ClienteForm
    template_name = 'gestion/form_cliente.html'
    success_url = reverse_lazy('gestion:lista_clientes')





class OrdenServicioDetailView(LoginRequiredMixin, DetailView):
    model = OrdenServicio
    template_name = 'gestion/ordenservicio_detail.html'
    context_object_name = 'orden'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['form_documento'] = DocumentoOrdenForm()
        return context

    def post(self, request, *args, **kwargs):
        orden = self.get_object()
        form = DocumentoOrdenForm(request.POST, request.FILES)
        
        if form.is_valid():
            documento = form.save(commit=False)
            documento.orden = orden
            documento.save()
            messages.success(request, '¡Documento adjuntado exitosamente!')
        else:
            messages.error(request, 'Error al adjuntar el documento.')
            
        return redirect('gestion:detalle_orden', pk=orden.pk)

class VehiculoDetailView(LoginRequiredMixin, DetailView):
    model = Vehiculo
    template_name = 'gestion/vehiculo_detail.html'
    context_object_name = 'vehiculo'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        vehiculo = self.get_object()

        # --- Lógica de Agenda Diaria (ya es correcta) ---
        fecha_str = self.request.GET.get('fecha')
        if fecha_str:
            fecha_seleccionada = datetime.datetime.strptime(fecha_str, '%Y-%m-%d').date()
        else:
            fecha_seleccionada = timezone.now().date()
        
        context['fecha_seleccionada'] = fecha_seleccionada
        context['programacion_del_dia'] = Recorrido.objects.filter(
            vehiculo=vehiculo,
            fecha_recorrido=fecha_seleccionada
        ).order_by('orden__fecha_creacion')

        # --- LÓGICA CORREGIDA PARA HISTORIAL Y MÉTRICAS ---
        # Ahora el historial se basa en los recorridos completados, no en las órdenes.
        historial_recorridos = Recorrido.objects.filter(vehiculo=vehiculo, estado='COMPLETADO').order_by('-fecha_recorrido')
        context['historial_recorridos'] = historial_recorridos
        
        # Las métricas ahora se calculan a partir del historial de recorridos.
        context['total_servicios_realizados'] = historial_recorridos.count()
        
        # Sumamos el valor de las órdenes padres de los recorridos completados.
        # Nota: Esto podría sumar una orden varias veces si el vehículo hizo varios recorridos para ella.
        ingresos_generados = historial_recorridos.aggregate(total=Sum('orden__valor_servicio'))
        context['total_ingresos_generados'] = ingresos_generados['total'] or 0

        return context



# --- HELPERS COMPARTIDOS PARA EL MANIFIESTO ---

def _puede_gestionar_manifiesto(user, recorrido):
    """Solo el conductor asignado, un Asesor o un superusuario pueden llenar el manifiesto."""
    return (
        user.is_superuser
        or user.groups.filter(name='Asesores').exists()
        or recorrido.conductor_id == user.id
    )


def _guardar_firma_cliente(manifiesto, signature_data, pk):
    """Decodifica la firma en base64 (data-URL) y la guarda en el manifiesto."""
    formato, imgstr = signature_data.split(';base64,')
    ext = formato.split('/')[-1]
    signature_file = ContentFile(base64.b64decode(imgstr), name=f'firma_cliente_{pk}.{ext}')
    manifiesto.firma_cliente.save(signature_file.name, signature_file, save=True)


def _generar_pdf_manifiesto(manifiesto, request):
    """Renderiza el manifiesto a PDF (logo + firma embebidos en base64) y lo guarda."""
    recorrido = manifiesto.recorrido
    template = get_template('gestion/manifiesto_pdf.html')

    # 1. Logo a base64
    logo_path = os.path.join(settings.BASE_DIR, 'static', 'images', 'logo-solmed.png')
    with open(logo_path, "rb") as image_file:
        logo_b64 = "data:image/png;base64," + base64.b64encode(image_file.read()).decode('utf-8')

    # 2. Firma a base64
    firma_cliente_b64 = None
    if manifiesto.firma_cliente:
        # .open() funciona tanto con el storage local como con S3 (a diferencia de .path).
        with manifiesto.firma_cliente.open("rb") as image_file:
            firma_cliente_b64 = "data:image/png;base64," + base64.b64encode(image_file.read()).decode('utf-8')

    context = {
        'manifiesto': manifiesto, 'recorrido': recorrido, 'orden': recorrido.orden,
        'logo_b64': logo_b64, 'firma_cliente_b64': firma_cliente_b64,
    }
    html_string = template.render(context)
    html = HTML(string=html_string, base_url=request.build_absolute_uri())
    pdf = html.write_pdf()

    pdf_file = ContentFile(pdf, name=f'manifiesto_recorrido_{recorrido.pk}.pdf')
    manifiesto.pdf_generado = pdf_file
    manifiesto.save()


def _generar_pdf_encuesta_conductor(encuesta, request):
    """Renderiza la encuesta de cierre del conductor a un PDF independiente y lo guarda."""
    recorrido = encuesta.recorrido
    template = get_template('gestion/encuesta_conductor_pdf.html')

    logo_path = os.path.join(settings.BASE_DIR, 'static', 'images', 'logo-solmed.png')
    with open(logo_path, "rb") as image_file:
        logo_b64 = "data:image/png;base64," + base64.b64encode(image_file.read()).decode('utf-8')

    context = {
        'encuesta': encuesta,
        'recorrido': recorrido,
        'orden': recorrido.orden,
        'logo_b64': logo_b64,
    }
    html_string = template.render(context)
    html = HTML(string=html_string, base_url=request.build_absolute_uri())
    pdf = html.write_pdf()

    pdf_file = ContentFile(pdf, name=f'encuesta_conductor_recorrido_{recorrido.pk}.pdf')
    encuesta.pdf_generado.save(pdf_file.name, pdf_file, save=True)


def _qr_data_uri(url):
    """Genera un PNG de código QR para la URL dada y lo devuelve como data-URI base64."""
    qr_img = qrcode.make(url)
    buffer = BytesIO()
    qr_img.save(buffer, format='PNG')
    return "data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode('utf-8')


class GenerarManifiestoView(LoginRequiredMixin, View):
    """
    Wizard que llena EL CONDUCTOR: solo los datos operativos (paso1-4).
    Al terminar el paso 4 se persiste el manifiesto y se redirige a la pantalla
    del QR; la encuesta de satisfacción y la firma las completa el cliente en su
    propio dispositivo a través de la URL pública (EncuestaPublicaView).
    """
    FORMS = [
        ("paso1", ManifiestoPaso1Form), ("paso2", ManifiestoPaso2Form),
        ("paso3", ManifiestoPaso3Form), ("paso4", ManifiestoPaso4Form),
    ]
    TEMPLATES = {
        "paso1": 'gestion/manifiesto_wizard/paso1.html',
        "paso2": 'gestion/manifiesto_wizard/paso2.html',
        "paso3": 'gestion/manifiesto_wizard/paso3.html',
        "paso4": 'gestion/manifiesto_wizard/paso4.html',
    }

    def get_form_step(self, step_name):
        for name, form_class in self.FORMS:
            if name == step_name:
                return form_class
        return None

    def dispatch(self, request, *args, **kwargs):
        # Control de propiedad: evita que un usuario llene el manifiesto de otro recorrido.
        if request.user.is_authenticated:
            recorrido = get_object_or_404(Recorrido, pk=kwargs.get('pk'))
            if not _puede_gestionar_manifiesto(request.user, recorrido):
                messages.error(request, "No tienes permiso para llenar este manifiesto.")
                return redirect('gestion:dashboard_redirect')
        return super().dispatch(request, *args, **kwargs)

    def get(self, request, pk, step='paso1'):
        recorrido = get_object_or_404(Recorrido, pk=pk)
        manifiesto_data = request.session.get(f'manifiesto_data_{pk}', {})
        try:
            manifiesto_instance = recorrido.manifiesto
        except Manifiesto.DoesNotExist:
            manifiesto_instance = None

        FormClass = self.get_form_step(step)
        template_path = self.TEMPLATES.get(step)
        if not FormClass or not template_path:
            messages.error(request, "Paso de formulario inválido.")
            return redirect('gestion:detalle_orden', pk=recorrido.orden.pk)

        form = FormClass(initial=manifiesto_data, instance=manifiesto_instance)

        return render(request, template_path, {
            'recorrido': recorrido, 'form': form, 'current_step': step, 'pk': pk,
            'manifiesto_instance': manifiesto_instance,
        })

    def post(self, request, pk, step='paso1'):
        recorrido = get_object_or_404(Recorrido, pk=pk)
        manifiesto_data = request.session.get(f'manifiesto_data_{pk}', {})
        try:
            manifiesto_instance = recorrido.manifiesto
        except Manifiesto.DoesNotExist:
            manifiesto_instance = None

        FormClass = self.get_form_step(step)
        if FormClass is None:
            messages.error(request, "Paso de formulario inválido.")
            return redirect('gestion:detalle_orden', pk=recorrido.orden.pk)

        form = FormClass(request.POST, instance=manifiesto_instance)
        if not form.is_valid():
            messages.error(request, "Por favor, corrija los errores en el formulario.")
            return render(request, self.TEMPLATES[step], {
                'recorrido': recorrido, 'form': form, 'current_step': step, 'pk': pk,
            })

        # Acumulamos los datos del paso en la sesión (serializando tipos no JSON).
        cleaned_data = form.cleaned_data
        for key, value in cleaned_data.items():
            if isinstance(value, (datetime.time, Decimal)):
                cleaned_data[key] = str(value)
        manifiesto_data.update(cleaned_data)
        request.session[f'manifiesto_data_{pk}'] = manifiesto_data

        current_index = [name for name, _ in self.FORMS].index(step)
        if current_index + 1 < len(self.FORMS):
            next_step_name = self.FORMS[current_index + 1][0]
            return redirect('gestion:firmar_manifiesto_step', pk=pk, step=next_step_name)

        # --- Último paso del conductor: persistir el manifiesto y pasar al QR ---
        Manifiesto.objects.update_or_create(
            recorrido=recorrido,
            defaults={**manifiesto_data, 'estado_firma': 'PENDIENTE_FIRMA'},
        )
        if f'manifiesto_data_{pk}' in request.session:
            del request.session[f'manifiesto_data_{pk}']
        return redirect('gestion:manifiesto_qr', pk=pk)


class ManifiestoQRView(LoginRequiredMixin, View):
    """Muestra al conductor el QR para que el cliente firme desde su dispositivo."""
    template_name = 'gestion/manifiesto_wizard/qr.html'

    def get(self, request, pk):
        recorrido = get_object_or_404(Recorrido, pk=pk)
        if not _puede_gestionar_manifiesto(request.user, recorrido):
            messages.error(request, "No tienes permiso para ver este manifiesto.")
            return redirect('gestion:dashboard_redirect')

        try:
            manifiesto = recorrido.manifiesto
        except Manifiesto.DoesNotExist:
            messages.error(request, "Primero debes llenar los datos del manifiesto.")
            return redirect('gestion:firmar_manifiesto_step', pk=pk, step='paso1')

        url_publica = request.build_absolute_uri(
            reverse('gestion:encuesta_publica', kwargs={'token': manifiesto.token_publico})
        )
        return render(request, self.template_name, {
            'recorrido': recorrido,
            'manifiesto': manifiesto,
            'url_publica': url_publica,
            'qr_b64': _qr_data_uri(url_publica),
        })


@login_required
def manifiesto_estado_json(request, pk):
    """Endpoint de polling para que la pantalla del QR detecte cuándo firma el cliente."""
    recorrido = get_object_or_404(Recorrido, pk=pk)
    try:
        manifiesto = recorrido.manifiesto
    except Manifiesto.DoesNotExist:
        return JsonResponse({'firmado': False, 'pdf_url': None})

    pdf_url = manifiesto.pdf_generado.url if manifiesto.pdf_generado else None
    try:
        recorrido.encuesta_conductor
        encuesta_pendiente = False
    except EncuestaConductor.DoesNotExist:
        encuesta_pendiente = True
    return JsonResponse({
        'firmado': manifiesto.estado_firma == 'FIRMADO',
        'pdf_url': pdf_url,
        'encuesta_pendiente': encuesta_pendiente,
        'encuesta_url': reverse('gestion:encuesta_conductor', kwargs={'pk': pk}),
    })


class EncuestaConductorView(LoginRequiredMixin, View):
    """
    Encuesta de cierre (PESV + gestión ambiental) que llena EL CONDUCTOR tras
    firmarse el manifiesto del cliente. Diligenciarla marca el recorrido como
    COMPLETADO. Solo el conductor asignado, un Asesor o un superusuario acceden.
    """
    template_name = 'gestion/encuesta_conductor.html'

    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated:
            recorrido = get_object_or_404(Recorrido, pk=kwargs.get('pk'))
            if not _puede_gestionar_manifiesto(request.user, recorrido):
                messages.error(request, "No tienes permiso para llenar esta encuesta.")
                return redirect('gestion:dashboard_redirect')
        return super().dispatch(request, *args, **kwargs)

    def _get_instancia(self, recorrido):
        try:
            return recorrido.encuesta_conductor
        except EncuestaConductor.DoesNotExist:
            return None

    def get(self, request, pk):
        recorrido = get_object_or_404(Recorrido, pk=pk)
        instancia = self._get_instancia(recorrido)
        return render(request, self.template_name, {
            'recorrido': recorrido,
            'form': EncuestaConductorForm(instance=instancia),
            'ya_diligenciada': instancia is not None,
        })

    def post(self, request, pk):
        recorrido = get_object_or_404(Recorrido, pk=pk)
        instancia = self._get_instancia(recorrido)
        form = EncuestaConductorForm(request.POST, instance=instancia)
        if form.is_valid():
            encuesta = form.save(commit=False)
            encuesta.recorrido = recorrido
            encuesta.save()  # marca el recorrido como COMPLETADO
            _generar_pdf_encuesta_conductor(encuesta, request)  # genera el PDF de evidencia
            messages.success(
                request,
                "Encuesta de cierre registrada. El recorrido fue marcado como completado."
            )
            return redirect('gestion:dashboard_redirect')
        messages.error(request, "Por favor, corrige los errores en la encuesta.")
        return render(request, self.template_name, {
            'recorrido': recorrido,
            'form': form,
            'ya_diligenciada': instancia is not None,
        })


class EncuestaPublicaView(View):
    """
    Página PÚBLICA (sin login) que abre el cliente al escanear el QR.
    Contiene la encuesta de satisfacción (paso5) + la firma de conformidad.
    Es de un solo uso: una vez FIRMADO, el token deja de ser utilizable.
    """
    template_name = 'gestion/manifiesto_wizard/encuesta_publica.html'
    template_gracias = 'gestion/manifiesto_wizard/encuesta_gracias.html'

    def get(self, request, token):
        manifiesto = get_object_or_404(Manifiesto, token_publico=token)
        if manifiesto.estado_firma == 'FIRMADO':
            return render(request, self.template_gracias, {
                'manifiesto': manifiesto, 'ya_firmado': True,
            })
        return render(request, self.template_name, {
            'manifiesto': manifiesto,
            'recorrido': manifiesto.recorrido,
            'orden': manifiesto.recorrido.orden,
            'form': ManifiestoPaso5Form(instance=manifiesto),
        })

    def post(self, request, token):
        manifiesto = get_object_or_404(Manifiesto, token_publico=token)
        if manifiesto.estado_firma == 'FIRMADO':
            return render(request, self.template_gracias, {
                'manifiesto': manifiesto, 'ya_firmado': True,
            })

        form = ManifiestoPaso5Form(request.POST, instance=manifiesto)
        signature_data = request.POST.get('signature_data')
        nombre_responsable_cliente = request.POST.get('nombre_responsable_cliente')

        if form.is_valid() and signature_data and nombre_responsable_cliente:
            manifiesto = form.save(commit=False)
            manifiesto.nombre_responsable_cliente = nombre_responsable_cliente
            manifiesto.estado_firma = 'FIRMADO'
            manifiesto.save()

            _guardar_firma_cliente(manifiesto, signature_data, manifiesto.recorrido.pk)
            _generar_pdf_manifiesto(manifiesto, request)

            return render(request, self.template_gracias, {
                'manifiesto': manifiesto, 'ya_firmado': False,
            })

        if not signature_data or not nombre_responsable_cliente:
            messages.error(request, 'Falta la firma o el nombre de quien recibe.')
        else:
            messages.error(request, 'Por favor, corrija los errores en la encuesta.')
        return render(request, self.template_name, {
            'manifiesto': manifiesto,
            'recorrido': manifiesto.recorrido,
            'orden': manifiesto.recorrido.orden,
            'form': form,
        })



# --- Mixin de Seguridad para Superusuarios ---
# Usaremos esto para proteger las vistas de administración
class SuperuserRequiredMixin(LoginRequiredMixin, UserPassesTestMixin):
    def test_func(self):
        return self.request.user.is_superuser

# --- Vistas para Administración de Usuarios ---

class ListaUsuariosView(SuperuserRequiredMixin, ListView):
    model = User
    template_name = 'gestion/lista_usuarios.html'
    context_object_name = 'usuarios'

class CrearUsuarioView(SuperuserRequiredMixin, SuccessMessageMixin, CreateView):
    model = User
    form_class = CrearUsuarioForm
    template_name = 'gestion/form_usuario.html'
    success_url = reverse_lazy('gestion:lista_usuarios')
    success_message = "¡Usuario creado exitosamente!"

    def form_valid(self, form):
        # El formulario UserCreationForm se encarga de guardar el usuario y hashear la contraseña
        response = super().form_valid(form)
        
        # Asignamos el usuario al grupo seleccionado
        grupo = form.cleaned_data['grupo']
        self.object.groups.add(grupo)
        
        return response

class ActualizarUsuarioView(SuperuserRequiredMixin, SuccessMessageMixin, UpdateView):
    model = User
    form_class = ActualizarUsuarioForm
    template_name = 'gestion/form_usuario.html'
    success_url = reverse_lazy('gestion:lista_usuarios')
    success_message = "¡Usuario actualizado exitosamente!"

    def form_valid(self, form):
        # Guardamos el usuario
        response = super().form_valid(form)
        
        # Actualizamos la pertenencia al grupo
        grupo = form.cleaned_data['grupo']
        self.object.groups.clear() # Limpiamos los grupos anteriores
        self.object.groups.add(grupo) # Añadimos el nuevo grupo

        return response


class OrdenServicioDetailView(NoConductorRequiredMixin, DetailView):
    model = OrdenServicio
    template_name = 'gestion/ordenservicio_detail.html'
    context_object_name = 'orden'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        # Añadimos el formulario para añadir nuevos recorridos
        context['form_recorrido'] = RecorridoForm()
        # Mantenemos el formulario para subir documentos
        context['form_documento'] = DocumentoOrdenForm()
        # Vehículos operativos con documentos vencidos/por vencer (aviso al asignar).
        context['vehiculos_con_alerta'] = [
            v for v in Vehiculo.objects.filter(estado='OPERATIVO') if v.tiene_alerta_documentos
        ]
        return context

    def post(self, request, *args, **kwargs):
        orden = self.get_object()
        
        # Identificamos qué formulario se está enviando
        if 'submit_recorrido' in request.POST:
            form = RecorridoForm(request.POST)
            if form.is_valid():
                recorrido = form.save(commit=False)
                recorrido.orden = orden
                recorrido.save() # Al guardar, el método save() del modelo actualizará la orden
                messages.success(request, 'Recorrido añadido exitosamente.')
            else:
                messages.error(request, 'Error al añadir el recorrido.')
        
        elif 'submit_documento' in request.POST:
            form = DocumentoOrdenForm(request.POST, request.FILES)
            if form.is_valid():
                documento = form.save(commit=False)
                documento.orden = orden
                documento.save()
                messages.success(request, 'Documento adjuntado exitosamente.')
            else:
                messages.error(request, 'Error al adjuntar el documento.')
            
        return redirect('gestion:detalle_orden', pk=orden.pk)


def completar_recorrido(request, pk):
    recorrido = get_object_or_404(Recorrido, pk=pk)
    
    if request.method == 'POST':
        recorrido.estado = 'COMPLETADO'
        recorrido.save() # La lógica automática en el modelo se disparará aquí
        messages.success(request, f'Recorrido del {recorrido.fecha_recorrido} marcado como completado.')
        
    return redirect('gestion:detalle_orden', pk=recorrido.orden.pk)


def feed_calendario(request):
    user = request.user
    
    # Si el usuario es un conductor, filtra solo sus recorridos
    if user.groups.filter(name='Conductores').exists():
        recorridos = Recorrido.objects.filter(conductor=user)
    # Si es asesor o admin, muestra todos los recorridos
    else:
        recorridos = Recorrido.objects.all()

    recorridos = recorridos.exclude(orden__estado_orden='CANCELADA')
    
    eventos = []
    colores_vehiculos = {}
    colores_disponibles = ['#007bff', '#28a745', '#dc3545', '#ffc107', '#17a2b8', '#6610f2']

    for recorrido in recorridos:
        vehiculo_id = recorrido.vehiculo.id
        if vehiculo_id not in colores_vehiculos:
            colores_vehiculos[vehiculo_id] = colores_disponibles[len(colores_vehiculos) % len(colores_disponibles)]

        evento = {
            'title': f'Orden #{recorrido.orden.numero_orden} - {recorrido.vehiculo.placa}',
            'start': recorrido.fecha_recorrido.strftime("%Y-%m-%d"),
            'url': reverse('gestion:detalle_orden', args=[recorrido.orden.pk]),
            'color': colores_vehiculos[vehiculo_id],
        }
        eventos.append(evento)
    
    return JsonResponse(eventos, safe=False)


class CalendarioView(LoginRequiredMixin, TemplateView):
    template_name = 'gestion/calendario.html'



# --- VISTA PARA REPORTES (SOLO SUPERUSUARIOS) ---

class ReportesView(SuperuserRequiredMixin, ListView):
    template_name = 'gestion/reportes.html'
    
    def get_queryset(self):
        # No usamos un queryset por defecto, lo generamos dinámicamente
        return None

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        form = ReporteFiltroForm(self.request.GET or None)
        context['form'] = form

        report_type = self.request.GET.get('report_type')
        resultados = []
        chart_labels = []
        chart_data = []
        chart_type = 'bar' # Por defecto
        total_general = 0

        if form.is_valid() and report_type:
            
            # --- REPORTE 1: FACTURACIÓN POR CLIENTE ---
            if report_type == 'facturacion_cliente' and form.cleaned_data.get('fecha_inicio'):
                fecha_inicio = form.cleaned_data['fecha_inicio']
                fecha_fin = form.cleaned_data['fecha_fin']
                
                resultados = Recorrido.objects.filter(
                    estado='COMPLETADO', fecha_recorrido__range=[fecha_inicio, fecha_fin]
                ).values('orden__cliente__nombre').annotate(
                    total_facturado=Sum('orden__valor_servicio'), numero_servicios=Count('id')
                ).order_by('-total_facturado')
                
                chart_labels = [item['orden__cliente__nombre'] for item in resultados]
                chart_data = [float(item['total_facturado']) for item in resultados]
                total_general = sum(chart_data)

            # --- REPORTE 2: RENDIMIENTO POR VEHÍCULO ---
            elif report_type == 'rendimiento_vehiculo' and form.cleaned_data.get('fecha_inicio'):
                fecha_inicio = form.cleaned_data['fecha_inicio']
                fecha_fin = form.cleaned_data['fecha_fin']
                
                resultados = Recorrido.objects.filter(
                    estado='COMPLETADO', fecha_recorrido__range=[fecha_inicio, fecha_fin]
                ).values('vehiculo__placa').annotate(
                    total_facturado=Sum('orden__valor_servicio'), numero_servicios=Count('id')
                ).order_by('-total_facturado')

                chart_labels = [item['vehiculo__placa'] for item in resultados]
                chart_data = [float(item['total_facturado']) for item in resultados]
                total_general = sum(chart_data)

            # --- REPORTE 3: TENDENCIA MENSUAL ---
            elif report_type == 'tendencia_mensual' and form.cleaned_data.get('año'):
                año = form.cleaned_data['año']
                
                resultados = Recorrido.objects.filter(
                    estado='COMPLETADO', fecha_recorrido__year=año
                ).annotate(
                    mes=TruncMonth('fecha_recorrido') # Agrupa por mes
                ).values('mes').annotate(
                    total_facturado=Sum('orden__valor_servicio')
                ).order_by('mes')

                meses = ["Ene", "Feb", "Mar", "Abr", "May", "Jun", "Jul", "Ago", "Sep", "Oct", "Nov", "Dic"]
                chart_labels = [meses[item['mes'].month - 1] for item in resultados]
                chart_data = [float(item['total_facturado']) for item in resultados]
                chart_type = 'line' # Cambiamos a gráfico de líneas
                total_general = sum(chart_data)

        context['resultados'] = resultados
        context['report_type'] = report_type
        context['chart_labels'] = json.dumps(chart_labels)
        context['chart_data'] = json.dumps(chart_data)
        context['chart_type'] = chart_type
        context['total_general'] = total_general
        
        return context



# --- Mixin de Seguridad para Conductores ---
class ConductorRequiredMixin(LoginRequiredMixin, UserPassesTestMixin):
    def test_func(self):
        return self.request.user.groups.filter(name='Conductores').exists()

# --- NUEVA VISTA: DASHBOARD DEL CONDUCTOR ---
class DashboardConductorView(ConductorRequiredMixin, TemplateView):
    template_name = 'gestion/dashboard_conductor.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        conductor = self.request.user
        hoy = timezone.now().date()

        # Recorridos para el día de hoy
        context['recorridos_hoy'] = Recorrido.objects.filter(
            conductor=conductor,
            fecha_recorrido=hoy
        ).order_by('orden__fecha_creacion')

        # Recorridos para los próximos 7 días
        proxima_semana = hoy + datetime.timedelta(days=7)
        context['recorridos_proximos'] = Recorrido.objects.filter(
            conductor=conductor,
            fecha_recorrido__gt=hoy,
            fecha_recorrido__lte=proxima_semana
        ).order_by('fecha_recorrido')
        
        return context
    

@login_required
def dashboard_redirect_view(request):
    user = request.user
    if user.groups.filter(name='Conductores').exists():
        return redirect('gestion:dashboard_conductor')
    else: # Asesores y Superusuarios
        return redirect('gestion:dashboard')
    


# --- VISTA PRINCIPAL PARA CONDUCTORES ---
class MisRecorridosView(ConductorRequiredMixin, ListView):
    model = Recorrido
    template_name = 'gestion/mis_recorridos.html'
    context_object_name = 'recorridos'

    def get_queryset(self):
        # Filtramos para mostrar solo los recorridos del usuario logueado
        # que no estén completados, ordenados por fecha.
        hoy = timezone.now().date()
        return Recorrido.objects.filter(
            conductor=self.request.user,
            fecha_recorrido__gte=hoy,
            estado__in=['PROGRAMADO', 'EN_CURSO']
        ).order_by('fecha_recorrido')


# --- HISTORIAL DEL CONDUCTOR ---
class HistorialConductorView(ConductorRequiredMixin, ListView):
    """
    Historial de TODOS los recorridos del conductor (los más recientes primero).
    Surface también las encuestas de cierre pendientes para que pueda completarlas.
    """
    model = Recorrido
    template_name = 'gestion/historial_conductor.html'
    context_object_name = 'recorridos'
    paginate_by = 25

    def get_queryset(self):
        return Recorrido.objects.filter(
            conductor=self.request.user
        ).select_related('orden', 'orden__cliente', 'vehiculo').order_by('-fecha_recorrido')


# --- VISTA DE ORDEN (SOLO LECTURA) PARA EL CONDUCTOR ---
class OrdenConductorDetailView(ConductorRequiredMixin, DetailView):
    """
    Ficha de SOLO LECTURA de la orden, pensada para el conductor.
    Solo deja ver órdenes en las que el conductor tiene algún recorrido asignado
    (cualquier otra devuelve 404). No expone datos financieros ni de gestión.
    """
    model = OrdenServicio
    template_name = 'gestion/orden_conductor_detail.html'
    context_object_name = 'orden'

    def get_queryset(self):
        # Restringe el acceso a las órdenes propias del conductor.
        return OrdenServicio.objects.filter(
            recorridos__conductor=self.request.user
        ).distinct()

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        # Solo los recorridos de esta orden asignados a este conductor.
        context['mis_recorridos'] = self.object.recorridos.filter(
            conductor=self.request.user
        ).select_related('vehiculo').order_by('-fecha_recorrido')
        return context


# --- NUEVA VISTA: TABLERO DE PLANIFICACIÓN ---
class PlanificacionView(PlanificadorRequiredMixin, TemplateView):
    template_name = 'gestion/planificacion.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        
        # 1. Obtener la fecha (igual que en el expediente del vehículo)
        fecha_str = self.request.GET.get('fecha')
        fecha_seleccionada = timezone.now().date()
        if fecha_str:
            try:
                fecha_seleccionada = datetime.datetime.strptime(fecha_str, '%Y-%m-%d').date()
            except ValueError:
                pass # Mantener la fecha de hoy si el formato es incorrecto
        
        context['fecha_seleccionada'] = fecha_seleccionada

        # 2. Obtener los recorridos del día
        recorridos_del_dia = Recorrido.objects.filter(fecha_recorrido=fecha_seleccionada).select_related('vehiculo', 'conductor', 'orden__cliente')
        context['recorridos_del_dia'] = recorridos_del_dia

        # 3. Identificar recursos OCUPADOS
        vehiculos_ocupados_ids = [r.vehiculo.id for r in recorridos_del_dia if r.vehiculo]
        conductores_ocupados_ids = [r.conductor.id for r in recorridos_del_dia if r.conductor]

        # 4. Obtener recursos DISPONIBLES
        conductores = Group.objects.get(name='Conductores').user_set.all()
        
        context['vehiculos_disponibles'] = Vehiculo.objects.filter(estado='OPERATIVO').exclude(id__in=vehiculos_ocupados_ids)
        context['conductores_disponibles'] = conductores.exclude(id__in=conductores_ocupados_ids)

        return context

    def post(self, request, *args, **kwargs):
        # Esta lógica maneja la re-asignación
        recorrido_id = request.POST.get('recorrido_id')
        nuevo_vehiculo_id = request.POST.get('vehiculo')
        nuevo_conductor_id = request.POST.get('conductor')

        try:
            recorrido = Recorrido.objects.get(id=recorrido_id)
            if nuevo_vehiculo_id:
                recorrido.vehiculo_id = nuevo_vehiculo_id
            if nuevo_conductor_id:
                recorrido.conductor_id = nuevo_conductor_id
            recorrido.save()
            messages.success(request, f"Recorrido #{recorrido.id} re-asignado exitosamente.")
        except Recorrido.DoesNotExist:
            messages.error(request, "El recorrido que intentas modificar no existe.")
            
        # Redirige a la misma página de planificación con la fecha seleccionada
        fecha = request.POST.get('fecha', timezone.now().date().isoformat())
        return redirect(f"{reverse('gestion:planificacion')}?fecha={fecha}")



class RegistrarPagoView(AsesorRequiredMixin, CreateView):
    model = Pago
    form_class = PagoForm
    template_name = 'gestion/registrar_pago.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        # Obtenemos la orden desde la URL y la pasamos a la plantilla
        context['orden'] = get_object_or_404(OrdenServicio, pk=self.kwargs['orden_pk'])
        return context

    def form_valid(self, form):
        # Asignamos la orden al pago antes de guardarlo
        orden = get_object_or_404(OrdenServicio, pk=self.kwargs['orden_pk'])
        form.instance.orden = orden
        messages.success(self.request, "Pago registrado exitosamente.")
        return super().form_valid(form)

    def get_success_url(self):
        # Después de registrar el pago, volvemos al expediente de la orden
        return reverse('gestion:detalle_orden', kwargs={'pk': self.kwargs['orden_pk']})


# ============================================================
#  MÓDULO DE PROGRAMACIÓN (paso PREVIO a la Orden de Servicio)
#  Lo gestionan los Asesores (y superusuarios). Al confirmar una
#  programación se genera automáticamente la orden + primer recorrido.
# ============================================================

class ListaProgramacionesView(AsesorRequiredMixin, ListView):
    model = Programacion
    template_name = 'gestion/lista_programaciones.html'
    context_object_name = 'programaciones'

    def get_queryset(self):
        qs = Programacion.objects.select_related(
            'cliente', 'orden'
        ).prefetch_related('cuadrillas')
        estado_filtro = self.request.GET.get('estado')
        if estado_filtro:
            qs = qs.filter(estado=estado_filtro)
        return qs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['estado_choices'] = Programacion.ESTADO_CHOICES
        context['current_estado'] = self.request.GET.get('estado', '')
        return context


class CrearProgramacionView(AsesorRequiredMixin, CreateView):
    model = Programacion
    form_class = ProgramacionForm
    template_name = 'gestion/form_programacion.html'
    success_url = reverse_lazy('gestion:lista_programaciones')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        if self.request.method == 'POST':
            context['formset'] = ProgramacionCuadrillaFormSet(
                self.request.POST, prefix='cuadrilla'
            )
        else:
            context['formset'] = ProgramacionCuadrillaFormSet(prefix='cuadrilla')
        return context

    def form_valid(self, form):
        context = self.get_context_data()
        formset = context['formset']
        if not formset.is_valid():
            return self.form_invalid(form)
        form.instance.creado_por = self.request.user
        self.object = form.save()
        formset.instance = self.object
        formset.save()
        messages.success(self.request, "Programación creada.")
        return HttpResponseRedirect(self.get_success_url())


class ActualizarProgramacionView(AsesorRequiredMixin, UpdateView):
    model = Programacion
    form_class = ProgramacionForm
    template_name = 'gestion/form_programacion.html'
    success_url = reverse_lazy('gestion:lista_programaciones')

    def dispatch(self, request, *args, **kwargs):
        # Una programación ya convertida en orden es de solo lectura.
        self.object = self.get_object()
        if self.object.orden_id:
            messages.info(request, "Esta programación ya generó una orden y no puede editarse.")
            return redirect('gestion:detalle_orden', pk=self.object.orden_id)
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        if self.request.method == 'POST':
            context['formset'] = ProgramacionCuadrillaFormSet(
                self.request.POST, instance=self.object, prefix='cuadrilla'
            )
        else:
            context['formset'] = ProgramacionCuadrillaFormSet(
                instance=self.object, prefix='cuadrilla'
            )
        return context

    def form_valid(self, form):
        context = self.get_context_data()
        formset = context['formset']
        if not formset.is_valid():
            return self.form_invalid(form)
        self.object = form.save()
        formset.instance = self.object
        formset.save()
        messages.success(self.request, "Programación actualizada.")
        return HttpResponseRedirect(self.get_success_url())


class ConvertirProgramacionView(AsesorRequiredMixin, View):
    """Genera la Orden de Servicio + un recorrido por cuadrilla (solo POST)."""
    def post(self, request, pk):
        programacion = get_object_or_404(Programacion, pk=pk)

        if programacion.orden_id:
            messages.info(request, "Esta programación ya tiene una orden generada.")
            return redirect('gestion:detalle_orden', pk=programacion.orden_id)
        if programacion.estado == 'CANCELADA':
            messages.error(request, "No puedes generar una orden desde una programación cancelada.")
            return redirect('gestion:lista_programaciones')

        try:
            orden = programacion.convertir_en_orden(request.user)
        except ValueError as e:
            messages.error(request, str(e))
            return redirect('gestion:actualizar_programacion', pk=pk)

        messages.success(
            request,
            f"Orden #{orden.numero_orden} generada desde la programación "
            f"({orden.recorridos.count()} recorrido(s)). Completa el valor y los documentos que falten."
        )
        return redirect('gestion:detalle_orden', pk=orden.pk)


class CancelarProgramacionView(AsesorRequiredMixin, View):
    """Marca la programación como CANCELADA (solo POST). No aplica si ya generó orden."""
    def post(self, request, pk):
        programacion = get_object_or_404(Programacion, pk=pk)
        if programacion.orden_id:
            messages.error(request, "No puedes cancelar una programación que ya generó una orden.")
        else:
            programacion.estado = 'CANCELADA'
            programacion.save()
            messages.success(request, "Programación cancelada.")
        return redirect('gestion:lista_programaciones')