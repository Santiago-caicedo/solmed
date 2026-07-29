import json
import mimetypes
import os
from django.conf import settings
from django.core.mail import EmailMessage
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
from .models import CURSOS_EXIGIBLES, DocumentoPersonal, EncuestaConductor, Manifiesto, OrdenServicio, Pago, PerfilPersona, Programacion, Recorrido, Sede, cursos_faltantes_ayudante, _recalcular_estado_orden
from django.http import JsonResponse
from django.contrib.auth.forms import SetPasswordForm
from .forms import DocumentoCorreoFormSet, DocumentoOrdenForm, DocumentoPersonalForm, EncuestaConductorForm, ManifiestoPaso1Form, ManifiestoPaso2Form, ManifiestoPaso3Form, ManifiestoPaso4Form, ManifiestoPaso5Form, OrdenServicioForm, PagoForm, PerfilPersonaForm, PersonaSinAccesoForm, ProgramacionForm, ProgramacionCuadrillaForm, RecorridoForm, ReporteFiltroForm, SedeFormSet, TerceroFormSet, VehiculoForm, ClienteForm, CrearUsuarioForm, ActualizarUsuarioForm
from .models import OrdenServicio, Vehiculo, Cliente, DocumentoAmbientalCliente, DocumentoCorreoCliente, Tercero


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

        # Camiones con carga PENDIENTE de disposición final (estadística/alerta).
        context['vehiculos_cargados'] = Vehiculo.objects.filter(cargado=True).order_by('placa')

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


class ClienteFormMixin:
    """
    Maneja, además del cliente:
      - Las SEDES y los TERCEROS del cliente (formsets inline).
      - La carga MÚLTIPLE de documentos ambientales ('documentos_ambientales') y
        la eliminación de los marcados ('eliminar_doc_ambiental').
    """
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        if 'sede_formset' not in context:
            if self.request.method == 'POST':
                context['sede_formset'] = SedeFormSet(
                    self.request.POST, instance=self.object, prefix='sede'
                )
            else:
                context['sede_formset'] = SedeFormSet(instance=self.object, prefix='sede')
        if 'tercero_formset' not in context:
            if self.request.method == 'POST':
                context['tercero_formset'] = TerceroFormSet(
                    self.request.POST, instance=self.object, prefix='tercero'
                )
            else:
                context['tercero_formset'] = TerceroFormSet(instance=self.object, prefix='tercero')
        if 'doc_correo_formset' not in context:
            if self.request.method == 'POST':
                context['doc_correo_formset'] = DocumentoCorreoFormSet(
                    self.request.POST, self.request.FILES, instance=self.object, prefix='doccorreo'
                )
            else:
                context['doc_correo_formset'] = DocumentoCorreoFormSet(instance=self.object, prefix='doccorreo')
        return context

    def form_valid(self, form):
        # El cliente aún sin guardar, para enlazar los formsets.
        self.object = form.save(commit=False)
        sede_formset = SedeFormSet(self.request.POST, instance=self.object, prefix='sede')
        tercero_formset = TerceroFormSet(self.request.POST, instance=self.object, prefix='tercero')
        doc_correo_formset = DocumentoCorreoFormSet(
            self.request.POST, self.request.FILES, instance=self.object, prefix='doccorreo'
        )
        # Cliente + sedes + terceros + documentos se validan juntos: si algo falla, no se guarda nada.
        if not (sede_formset.is_valid() and tercero_formset.is_valid() and doc_correo_formset.is_valid()):
            return self.render_to_response(self.get_context_data(
                form=form, sede_formset=sede_formset, tercero_formset=tercero_formset,
                doc_correo_formset=doc_correo_formset
            ))
        self.object.save()
        for fs in (sede_formset, tercero_formset, doc_correo_formset):
            fs.instance = self.object
            fs.save()

        # Documentos ambientales (carga múltiple + eliminación de los marcados).
        ids_eliminar = self.request.POST.getlist('eliminar_doc_ambiental')
        if ids_eliminar:
            self.object.documentos_ambientales.filter(pk__in=ids_eliminar).delete()
        for archivo in self.request.FILES.getlist('documentos_ambientales'):
            DocumentoAmbientalCliente.objects.create(cliente=self.object, archivo=archivo)

        messages.success(self.request, "Cliente guardado.")
        return HttpResponseRedirect(self.get_success_url())


class CrearClienteView(ClienteFormMixin, LoginRequiredMixin, CreateView):
    model = Cliente
    form_class = ClienteForm
    template_name = 'gestion/form_cliente.html'
    success_url = reverse_lazy('gestion:lista_clientes')

class ActualizarClienteView(ClienteFormMixin, LoginRequiredMixin, UpdateView):
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


def _programacion_de(recorrido):
    """Programación que originó la orden del recorrido, o None (órdenes manuales)."""
    orden = recorrido.orden
    if orden is None:
        return None
    return getattr(orden, 'programacion_origen', None)


def _instrucciones_servicio_de(recorrido):
    """Primera parte del acta definida por el asesor en la programación (o {})."""
    programacion = _programacion_de(recorrido)
    return programacion.instrucciones_acta() if programacion else {}


def _resumen_instrucciones_de(recorrido):
    """Resumen legible de las instrucciones del asesor para mostrárselo fijo al conductor."""
    programacion = _programacion_de(recorrido)
    return programacion.resumen_instrucciones() if programacion else []


def _acta_para_vista(recorrido):
    """
    Acta a mostrar en formato documento. Si el conductor ya la diligenció,
    devuelve el Manifiesto real; si no, uno SIN GUARDAR con las instrucciones
    del asesor (para previsualizar "hasta donde va"). Devuelve (acta, estado):
      - 'FIRMADA'    : el cliente ya firmó.
      - 'DILIGENCIADA': el conductor la llenó, falta firma del cliente.
      - 'PENDIENTE'  : solo hay instrucciones del asesor.
    """
    try:
        manifiesto = recorrido.manifiesto
    except Manifiesto.DoesNotExist:
        # OJO: NO pasar recorrido=recorrido; enlazar el recorrido a este Manifiesto
        # sin guardar contaminaría la caché inversa recorrido.manifiesto y haría
        # creer a las plantillas que el acta ya existe. El recorrido viaja aparte
        # en el contexto de la plantilla.
        datos = _instrucciones_servicio_de(recorrido)
        return Manifiesto(**datos), 'PENDIENTE'
    estado = 'FIRMADA' if manifiesto.estado_firma == 'FIRMADO' else 'DILIGENCIADA'
    return manifiesto, estado


def _actas_formato(recorridos):
    """[{recorrido, acta, estado}] para embeber el acta (formato documento) en la orden."""
    resultado = []
    for recorrido in recorridos:
        acta, estado = _acta_para_vista(recorrido)
        resultado.append({'recorrido': recorrido, 'acta': acta, 'estado': estado})
    return resultado


class ActaFormatoView(NoConductorRequiredMixin, View):
    """
    Vista del acta (Orden de Servicio) en el MISMO formato del PDF final, pero en
    la plataforma y pre-llenada "hasta donde va": las instrucciones del asesor
    (definidas en la programación) más lo que el conductor haya diligenciado.
    Solo para gestión (asesor/superusuario): el CONDUCTOR NO accede al acta como
    documento ni la descarga; él solo la diligencia (asistente) y muestra el QR.
    """
    template_name = 'gestion/acta_formato.html'

    def get(self, request, pk):
        recorrido = get_object_or_404(Recorrido, pk=pk)
        acta, estado = _acta_para_vista(recorrido)
        return render(request, self.template_name, {
            'recorrido': recorrido, 'orden': recorrido.orden,
            'manifiesto': acta, 'estado_acta': estado,
        })


# ============================================================
#  NOTA DE NOMENCLATURA: en el back se llama "Manifiesto" (modelo, estas
#  vistas y URLs manifiesto_*); en el front se muestra como "ACTA DE SERVICIO".
#  Es la ejecución de la orden que firma el cliente. Ver Manifiesto en models.py.
# ============================================================
class GenerarManifiestoView(LoginRequiredMixin, View):
    """
    Wizard que llena EL CONDUCTOR: solo los datos operativos (paso1, paso3, paso4).
    La primera parte del acta (Succión/Sondeo/Lavado/Transporte) NO la llena el
    conductor: son las instrucciones que definió el asesor en la programación y se
    copian al acta al cerrarla. Al terminar se persiste el manifiesto (acta de
    servicio) y se redirige al QR; la encuesta de satisfacción y la firma las
    completa el cliente en su propio dispositivo (EncuestaPublicaView).
    """
    # Paso 2 (Succión/Sondeo/Lavado/Transporte) YA NO lo llena el conductor: son
    # las "Instrucciones del servicio" que define el asesor en la programación y
    # se copian al acta al cerrarla (ver post()). Por eso no está en el asistente.
    FORMS = [
        ("paso1", ManifiestoPaso1Form),
        ("paso3", ManifiestoPaso3Form), ("paso4", ManifiestoPaso4Form),
    ]
    TEMPLATES = {
        "paso1": 'gestion/manifiesto_wizard/paso1.html',
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
                messages.error(request, "No tienes permiso para llenar esta acta de servicio.")
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
            'instrucciones_resumen': _resumen_instrucciones_de(recorrido),
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
                'instrucciones_resumen': _resumen_instrucciones_de(recorrido),
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
        # La primera parte del acta (Succión/Sondeo/Lavado/Transporte) no la llena
        # el conductor: la definió el asesor en la programación. Se copia aquí.
        instrucciones = _instrucciones_servicio_de(recorrido)
        Manifiesto.objects.update_or_create(
            recorrido=recorrido,
            defaults={**instrucciones, **manifiesto_data, 'estado_firma': 'PENDIENTE_FIRMA'},
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
            messages.error(request, "No tienes permiso para ver esta acta de servicio.")
            return redirect('gestion:dashboard_redirect')

        try:
            manifiesto = recorrido.manifiesto
        except Manifiesto.DoesNotExist:
            messages.error(request, "Primero debes llenar los datos del acta de servicio.")
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

    def get_queryset(self):
        # Precargamos personal y sus documentos (se usan varias veces en la plantilla).
        return super().get_queryset().prefetch_related(
            'recorridos__vehiculo',
            'recorridos__conductor__documentos_personales',
            'recorridos__ayudante__documentos_personales',
            'recorridos__ayudante2__documentos_personales',
        )

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

        # Personal (conductores/ayudantes) de esta orden con documentos vencidos o
        # por vencer, para avisar en el expediente. Se recorre una sola vez.
        personal_con_alerta = []
        vistos = set()
        for recorrido in self.object.recorridos.all():
            for persona in (recorrido.conductor, recorrido.ayudante, recorrido.ayudante2):
                if persona and persona.pk not in vistos:
                    vistos.add(persona.pk)
                    docs_alerta = [d for d in persona.documentos_personales.all() if d.tiene_alerta]
                    if docs_alerta:
                        personal_con_alerta.append({'persona': persona, 'documentos': docs_alerta})
        context['personal_con_alerta'] = personal_con_alerta
        # Acta(s) en formato documento (igual al PDF) para la pestaña de la orden.
        context['actas_formato'] = _actas_formato(
            self.object.recorridos.all().order_by('fecha_recorrido'))
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


class EditarRecorridoView(NoConductorRequiredMixin, UpdateView):
    """
    Corrige un recorrido que quedó mal (fecha, vehículo, conductor, ayudante).
    Es la forma de arreglar una orden sin borrarla.
    """
    model = Recorrido
    form_class = RecorridoForm
    template_name = 'gestion/form_recorrido.html'

    def form_valid(self, form):
        form.save()   # Recorrido.save recalcula el estado de la orden
        messages.success(self.request, "Recorrido actualizado.")
        return redirect('gestion:detalle_orden', pk=self.object.orden_id)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['orden'] = self.object.orden
        return context


class EliminarRecorridoView(NoConductorRequiredMixin, View):
    """
    Quita un recorrido de la orden (solo POST). Al borrarlo caen su manifiesto y
    su encuesta (CASCADE) y se recalcula el estado de la orden. La orden completa
    solo se elimina desde el admin de Django.
    """
    def post(self, request, pk):
        recorrido = get_object_or_404(Recorrido, pk=pk)
        orden = recorrido.orden
        recorrido.delete()
        _recalcular_estado_orden(orden)
        messages.success(request, "Recorrido eliminado de la orden.")
        return redirect('gestion:detalle_orden', pk=orden.pk)


@login_required
def feed_calendario(request):
    user = request.user

    # Si el usuario es un conductor, filtra solo sus recorridos
    if user.groups.filter(name='Conductores').exists():
        recorridos = Recorrido.objects.filter(conductor=user)
    # Si es asesor o admin, muestra todos los recorridos
    else:
        recorridos = Recorrido.objects.all()

    recorridos = recorridos.exclude(
        orden__estado_orden='CANCELADA'
    ).select_related('vehiculo', 'orden')
    
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
        mis_recorridos = self.object.recorridos.filter(
            conductor=self.request.user
        ).select_related('vehiculo').order_by('-fecha_recorrido')
        context['mis_recorridos'] = mis_recorridos
        # Acta(s) en formato documento (igual al PDF) para la pestaña del conductor.
        context['actas_formato'] = _actas_formato(mis_recorridos)
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

        # 4. Obtener recursos DISPONIBLES (conductores activos, sin retirados)
        conductores = Group.objects.get(name='Conductores').user_set.exclude(perfil__retirado=True)

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

# Documentos estándar del expediente (también define el orden de presentación).
DOCUMENTOS_ESTANDAR = [
    ('CEDULA', 'Cédula de ciudadanía'),
    ('SEGURIDAD_SOCIAL', 'Seguridad social vigente'),
    ('LICENCIA', 'Licencia de conducción'),
    ('CURSO_ALTURAS', 'Certificado curso de alturas'),
    ('CURSO_CONFINADOS', 'Certificado espacios confinados'),
]


def _documentos_requeridos_por_rol(nombres_grupos):
    """
    Tipos de documento OBLIGATORIOS en el expediente según el/los rol(es).
    La seguridad social se exige a CUALQUIER persona con rol asignado (todos los
    cargos la cargan). Los conductores llevan además cédula y licencia; los
    ayudantes, cédula. Los cursos de alturas y espacios confinados no son
    obligatorios: cada programación decide si los exige (ver Programacion.exige_curso_*).
    """
    requeridos = set()
    if nombres_grupos:
        # Toda persona con un rol debe mantener su seguridad social vigente.
        requeridos.add('SEGURIDAD_SOCIAL')
    if 'Conductores' in nombres_grupos:
        requeridos |= {'CEDULA', 'LICENCIA'}
    if 'Ayudantes' in nombres_grupos:
        requeridos |= {'CEDULA'}
    return requeridos


# Roles cuyas personas NO acceden a la plataforma: se registran solo para su
# expediente y para poder asignarlas a las cuadrillas. No tienen usuario ni
# contraseña utilizables (ver PersonaSinAccesoForm).
GRUPOS_SIN_ACCESO = {'Ayudantes'}

# Documentos que llevan fecha de vigencia (se puede fijar/editar con el botón
# "Vigencia" del expediente). La seguridad social ahora se controla por vigencia
# manual (ya no por el mes calendario).
TIPOS_CON_VIGENCIA = {'SEGURIDAD_SOCIAL', 'LICENCIA', 'CURSO_ALTURAS', 'CURSO_CONFINADOS'}


def _grupo_es_sin_acceso(grupo):
    """True si el rol seleccionado no debe tener acceso al sistema."""
    return grupo is not None and grupo.name in GRUPOS_SIN_ACCESO


def _persona_sin_acceso(persona):
    """True si la persona está registrada sin acceso a la plataforma."""
    return bool(set(persona.groups.values_list('name', flat=True)) & GRUPOS_SIN_ACCESO)


def _grupo_de_post(request):
    """Grupo (rol) enviado en el POST del formulario de persona, si es válido."""
    return Group.objects.filter(pk=request.POST.get('grupo')).first()


def _ids_grupos_sin_acceso():
    """IDs de los roles sin acceso, para que el formulario reaccione en vivo."""
    return list(Group.objects.filter(name__in=GRUPOS_SIN_ACCESO).values_list('id', flat=True))


def _documentos_aplicables_por_rol(nombres_grupos):
    """
    Casillas del expediente que se muestran para ese rol (en el orden estándar).
    Los cursos solo aparecen en ayudantes y la licencia solo en conductores;
    la cédula está siempre disponible aunque no sea obligatoria.
    """
    aplicables = _documentos_requeridos_por_rol(nombres_grupos) | {'CEDULA'}
    if 'Ayudantes' in nombres_grupos:
        # Opcionales en el expediente, pero exigibles desde una programación.
        aplicables |= {'CURSO_ALTURAS', 'CURSO_CONFINADOS'}
    return [(tipo, label) for tipo, label in DOCUMENTOS_ESTANDAR if tipo in aplicables]


def _ss_vigente(docs):
    """
    Seguridad social vigente de una persona: la de mayor fecha de vencimiento
    entre las que aún no han vencido. La vigencia se fija a mano al cargarla, así
    que ya NO se usa el mes calendario. Devuelve el DocumentoPersonal o None.
    `docs` es la lista de sus documentos (ya cargada).
    """
    candidatas = [
        d for d in docs
        if d.tipo == 'SEGURIDAD_SOCIAL' and d.vigente
    ]
    if not candidatas:
        return None
    return max(candidatas, key=lambda d: d.fecha_vencimiento)


def _estado_documentos_personal():
    """
    Por cada persona con requisitos documentales, los documentos REQUERIDOS que
    le faltan y el enlace a su ficha. Se pasa a la plantilla de programación
    (JSON) para avisar en vivo cuando se asigna a alguien sin la documentación
    al día.
      - Toda persona con rol: seguridad social vigente.
      - Conductores: además cédula y licencia.
      - Ayudantes:   además cédula (los cursos se exigen desde cada programación).
    """
    tipo_label = dict(DocumentoPersonal.TIPO_CHOICES)
    mes_actual = timezone.localdate().strftime('%Y-%m')
    # Cualquier persona ACTIVA con rol asignado (los retirados no se asignan).
    usuarios = (
        User.objects.filter(groups__isnull=False)
        .exclude(perfil__retirado=True)
        .distinct()
        .prefetch_related('groups', 'documentos_personales')
    )
    data = {}
    for u in usuarios:
        nombres = set(u.groups.values_list('name', flat=True))
        requeridos = _documentos_requeridos_por_rol(nombres)
        docs = list(u.documentos_personales.all())
        subidos = {d.tipo for d in docs}
        faltan = []
        # Seguridad social: al día = existe una con vigencia y sin vencer (la
        # vigencia se pone a mano al cargarla; ya no depende del mes calendario).
        ss_doc = _ss_vigente(docs)
        for tipo, _label in DOCUMENTOS_ESTANDAR:   # orden estable de presentación
            if tipo not in requeridos:
                continue
            if tipo == 'SEGURIDAD_SOCIAL':
                if ss_doc is None:
                    faltan.append('Seguridad social vigente')
            elif tipo not in subidos:
                faltan.append(tipo_label[tipo])
        # Cursos vigentes (no obligatorios en el expediente, pero exigibles
        # desde la programación): sirven para avisar en vivo al asignar.
        cursos = {
            tipo: any(d.tipo == tipo and not d.vencido for d in docs)
            for tipo, _etiqueta in CURSOS_EXIGIBLES
        }
        data[u.id] = {
            'nombre': u.get_full_name() or u.username,
            'faltan': faltan,
            'cursos': cursos,
            'es_ayudante': 'Ayudantes' in nombres,
            'url': reverse('gestion:ficha_persona', args=[u.id]),
            'ss_al_dia': ss_doc is not None,
            'ss_vence': ss_doc.fecha_vencimiento.strftime('%d/%m/%Y') if ss_doc else '',
            'ss_url': ss_doc.archivo.url if ss_doc else '',
        }
    return data


def _validar_cursos_cuadrilla(form, cuadrilla_form):
    """
    Si la programación exige cursos, comprueba que el ayudante asignado los tenga
    vigentes. Marca el error en el campo 'ayudante' de la cuadrilla.
    Devuelve True si cumple.
    """
    exige_alturas = form.cleaned_data.get('exige_curso_alturas') == 'SI'
    exige_confinados = form.cleaned_data.get('exige_curso_confinados') == 'SI'
    if not (exige_alturas or exige_confinados):
        return True
    todo_ok = True
    for campo in ('ayudante', 'ayudante2'):
        ayudante = cuadrilla_form.cleaned_data.get(campo)
        motivos = cursos_faltantes_ayudante(ayudante, exige_alturas, exige_confinados)
        if not motivos:
            continue
        todo_ok = False
        nombre = ayudante.get_full_name() or ayudante.username
        cuadrilla_form.add_error(
            campo,
            f"{nombre} {' y '.join(motivos)}. Este servicio exige esos cursos: "
            f"carga el soporte en su expediente o asigna otro ayudante."
        )
    return todo_ok


def _tiene_ss_vigente(persona):
    """True si la persona tiene una seguridad social con vigencia sin vencer."""
    if persona is None:
        return True
    return persona.documentos_personales.filter(
        tipo='SEGURIDAD_SOCIAL',
        fecha_vencimiento__gte=timezone.localdate(),
    ).exists()


def _validar_ss_cuadrilla(form, cuadrilla_form):
    """
    La seguridad social vigente del personal asignado (conductor y ayudante) debe
    estar cargada: es lo que se enviará al cliente. Marca el error en su campo.
    Devuelve True si ambos la tienen vigente.
    """
    todo_ok = True
    for campo in ('conductor', 'ayudante', 'ayudante2'):
        persona = cuadrilla_form.cleaned_data.get(campo)
        if persona is None or _tiene_ss_vigente(persona):
            continue
        todo_ok = False
        nombre = persona.get_full_name() or persona.username
        cuadrilla_form.add_error(
            campo,
            f"{nombre} no tiene seguridad social vigente. Se enviará al cliente, "
            f"así que debe estar al día: cárgala con su vigencia en el expediente."
        )
    return todo_ok


def _direcciones_clientes():
    """
    Mapa {id_cliente: dirección registrada} para autocompletar la dirección de
    la programación al elegir el cliente en el formulario.
    """
    return {
        str(pk): direccion or ''
        for pk, direccion in Cliente.objects.values_list('pk', 'direccion')
    }


def _sedes_por_cliente():
    """
    Mapa {id_cliente: [{id, nombre, direccion}, ...]} de las sedes activas, para
    poblar en vivo el desplegable de sede al elegir el cliente en la programación.
    """
    data = {}
    sedes = Sede.objects.filter(activa=True).values(
        'id', 'cliente_id', 'nombre', 'direccion'
    ).order_by('nombre')
    for s in sedes:
        data.setdefault(str(s['cliente_id']), []).append({
            'id': s['id'], 'nombre': s['nombre'], 'direccion': s['direccion'] or '',
        })
    return data


def _terceros_por_cliente():
    """
    Mapa {id_cliente: [{id, nombre, direccion, contacto, telefono}, ...]} de los
    terceros activos, para poblar en vivo el desplegable de tercero al elegir el
    cliente en la programación (y arrastrar su dirección y contacto).
    """
    data = {}
    terceros = Tercero.objects.filter(activo=True).values(
        'id', 'cliente_id', 'nombre', 'direccion', 'persona_contacto', 'telefono'
    ).order_by('nombre')
    for t in terceros:
        data.setdefault(str(t['cliente_id']), []).append({
            'id': t['id'], 'nombre': t['nombre'], 'direccion': t['direccion'] or '',
            'contacto': t['persona_contacto'] or '', 'telefono': t['telefono'] or '',
        })
    return data


def _docs_correo_por_cliente():
    """
    Mapa {id_cliente: [nombre_documento, ...]} de los documentos del cliente que
    se adjuntan al correo de la orden, para mostrarlos en la vista previa.
    """
    data = {}
    for doc in DocumentoCorreoCliente.objects.select_related('cliente'):
        nombre = doc.descripcion or os.path.basename(doc.archivo.name)
        data.setdefault(str(doc.cliente_id), []).append(nombre)
    return data


def _vehiculos_cargados():
    """
    Mapa {id_vehiculo: detalle} de los camiones con carga PENDIENTE de
    disposición, para alertar en vivo al asignarlos en la programación.
    """
    return {
        str(pk): detalle or 'carga pendiente de disposición'
        for pk, detalle in Vehiculo.objects.filter(cargado=True)
                                            .values_list('pk', 'cargado_detalle')
    }


def _disposicion_meta():
    """IDs de los destinos internos especiales, para la lógica del formulario."""
    from .models import Dispositor
    nombres = {d.nombre: d.pk for d in Dispositor.objects.filter(tipo='INTERNO')}
    return {
        'dejar_cargado': nombres.get(Dispositor.DEJAR_CARRO_CARGADO),
        'trasiego_placa': nombres.get(Dispositor.TRASIEGO_PLACA),
    }


def _avisar_carga_pendiente(request, programacion, orden):
    """
    Tras generar la orden: si el servicio quedó SIN disposición final, avisa
    qué quedó cargado (camiones o tanques) para que el personal lo tenga en cuenta.
    """
    from .models import Dispositor
    if programacion.requiere_disposicion_final != 'NO' or not programacion.dispositor_final_id:
        return
    destino = programacion.dispositor_final.nombre
    if destino == Dispositor.DEJAR_CARRO_CARGADO:
        placas = ", ".join(sorted({
            r.vehiculo.placa for r in orden.recorridos.all() if r.vehiculo_id
        }))
        messages.warning(
            request,
            f"OJO: sin disposición final — el/los camión(es) {placas} quedaron CARGADOS, "
            f"pendientes de disposición."
        )
    elif destino == Dispositor.TRASIEGO_PLACA and programacion.trasiego_vehiculo_id:
        messages.warning(
            request,
            f"OJO: el contenido se trasegó al camión {programacion.trasiego_vehiculo.placa}, "
            f"que quedó CARGADO pendiente de disposición."
        )
    elif destino in Dispositor.TANQUES:
        messages.warning(
            request,
            f"OJO: el contenido quedó en {destino.title()} (tanques SOLMED), "
            f"pendiente de disposición final."
        )


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


def _contexto_programacion(context):
    """Datos compartidos por el formulario de programación (JSON para el JS)."""
    context['personal_docs'] = _estado_documentos_personal()
    context['direcciones_clientes'] = _direcciones_clientes()
    context['sedes_por_cliente'] = _sedes_por_cliente()
    context['terceros_por_cliente'] = _terceros_por_cliente()
    context['docs_correo_por_cliente'] = _docs_correo_por_cliente()
    context['vehiculos_cargados'] = _vehiculos_cargados()
    context['disposicion_meta'] = _disposicion_meta()
    # Instrucciones del servicio: pares (casilla, cantidad) para renderizar la
    # primera parte del acta (Succión y Sondeo) en dos columnas alineadas.
    form = context.get('form')
    if form is not None:
        context['instrucciones_succion'] = [
            (form['succ_canecas'], form['succ_canecas_cant']),
            (form['succ_pozos_inspeccion'], form['succ_pozos_inspeccion_cant']),
            (form['succ_pozos_septicos'], form['succ_pozos_septicos_cant']),
            (form['succ_tanques'], form['succ_tanques_cant']),
            (form['succ_trampas_grasa'], form['succ_trampas_grasa_cant']),
        ]
        context['instrucciones_sondeo'] = [
            (form['sond_red_aguas_lluvias'], form['sond_red_aguas_lluvias_cant']),
            (form['sond_red_aguas_negras'], form['sond_red_aguas_negras_cant']),
            (form['sond_red_acueducto'], form['sond_red_acueducto_cant']),
            (form['sond_correctivo'], form['sond_correctivo_cant']),
            (form['sond_preventivo'], form['sond_preventivo_cant']),
        ]
    return context


class CrearProgramacionView(AsesorRequiredMixin, CreateView):
    model = Programacion
    form_class = ProgramacionForm
    template_name = 'gestion/form_programacion.html'
    success_url = reverse_lazy('gestion:lista_programaciones')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        if 'cuadrilla_form' not in context:
            data = self.request.POST if self.request.method == 'POST' else None
            context['cuadrilla_form'] = ProgramacionCuadrillaForm(data, prefix='cuadrilla')
        _contexto_programacion(context)
        return context

    def form_valid(self, form):
        # Una programación = un vehículo = una orden. Una sola cuadrilla.
        cuadrilla_form = ProgramacionCuadrillaForm(self.request.POST, prefix='cuadrilla')
        if not cuadrilla_form.is_valid():
            return self.render_to_response(
                self.get_context_data(form=form, cuadrilla_form=cuadrilla_form))
        cursos_ok = _validar_cursos_cuadrilla(form, cuadrilla_form)
        ss_ok = _validar_ss_cuadrilla(form, cuadrilla_form)
        if not (cursos_ok and ss_ok):
            messages.error(
                self.request,
                "No se guardó: revisa la documentación del personal asignado "
                "(seguridad social vigente y cursos exigidos)."
            )
            return self.render_to_response(
                self.get_context_data(form=form, cuadrilla_form=cuadrilla_form))

        form.instance.creado_por = self.request.user
        self.object = form.save()
        cuadrilla = cuadrilla_form.save(commit=False)
        cuadrilla.programacion = self.object
        cuadrilla.save()

        # Se genera la orden inmediatamente (no queda en borrador) y se envía la
        # seguridad social al cliente.
        try:
            orden = self.object.convertir_en_orden(self.request.user)
        except ValueError as e:
            messages.warning(self.request, f"Programación creada en borrador: {e}")
            return HttpResponseRedirect(self.get_success_url())

        messages.success(
            self.request,
            f"Programación creada y Orden #{orden.numero_orden} generada."
        )
        try:
            enviado, detalle = _enviar_seguridad_social_cliente(orden, self.object)
        except Exception as e:
            enviado, detalle = False, f"no se pudo enviar el correo de seguridad social ({e})."
        (messages.success if enviado else messages.warning)(self.request, detalle.capitalize())
        _avisar_carga_pendiente(self.request, self.object, orden)

        return HttpResponseRedirect(reverse('gestion:detalle_orden', kwargs={'pk': orden.pk}))


class ActualizarProgramacionView(AsesorRequiredMixin, UpdateView):
    model = Programacion
    form_class = ProgramacionForm
    template_name = 'gestion/form_programacion.html'
    success_url = reverse_lazy('gestion:lista_programaciones')

    def dispatch(self, request, *args, **kwargs):
        # Una programación ya convertida en orden es de solo lectura.
        self.object = self.get_object()
        if self.object.orden_id:
            messages.info(
                request,
                f"Esta programación ya generó la Orden #{self.object.orden.numero_orden}. "
                "Corrige lo que quedó mal desde la orden (datos y recorridos)."
            )
            return redirect('gestion:detalle_orden', pk=self.object.orden_id)
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        if 'cuadrilla_form' not in context:
            data = self.request.POST if self.request.method == 'POST' else None
            context['cuadrilla_form'] = ProgramacionCuadrillaForm(
                data, prefix='cuadrilla', instance=self.object.cuadrillas.first())
        _contexto_programacion(context)
        return context

    def form_valid(self, form):
        cuadrilla_form = ProgramacionCuadrillaForm(
            self.request.POST, prefix='cuadrilla', instance=self.object.cuadrillas.first())
        if not cuadrilla_form.is_valid():
            return self.render_to_response(
                self.get_context_data(form=form, cuadrilla_form=cuadrilla_form))
        cursos_ok = _validar_cursos_cuadrilla(form, cuadrilla_form)
        ss_ok = _validar_ss_cuadrilla(form, cuadrilla_form)
        if not (cursos_ok and ss_ok):
            messages.error(
                self.request,
                "No se guardó: revisa la documentación del personal asignado "
                "(seguridad social vigente y cursos exigidos)."
            )
            return self.render_to_response(
                self.get_context_data(form=form, cuadrilla_form=cuadrilla_form))
        self.object = form.save()
        cuadrilla = cuadrilla_form.save(commit=False)
        cuadrilla.programacion = self.object
        cuadrilla.save()
        messages.success(self.request, "Programación actualizada.")
        return HttpResponseRedirect(self.get_success_url())


def _personal_de_la_orden(orden):
    """Conductores y ayudantes (sin repetir) de todos los recorridos de la orden."""
    personas = {}
    for recorrido in orden.recorridos.select_related('conductor', 'ayudante', 'ayudante2'):
        for persona, rol in ((recorrido.conductor, 'Conductor'),
                             (recorrido.ayudante, 'Ayudante'),
                             (recorrido.ayudante2, 'Ayudante')):
            if persona and persona.pk not in personas:
                personas[persona.pk] = (persona, rol)
    return list(personas.values())


def _enviar_seguridad_social_cliente(orden, programacion):
    """
    Envía al cliente, por correo, la seguridad social vigente del personal de la
    orden. Los archivos se leen del storage con .open() (funciona igual en S3 que
    en local, a diferencia de .path). El asunto lleva el número de orden y SOLMED.

    Devuelve (enviado: bool, detalle: str) para informar al usuario.
    """
    destinatario = (programacion.correo_seguridad_social or '').strip()
    if not destinatario:
        return False, "no se envió el correo de seguridad social: la programación no tiene correo del cliente."

    personal = _personal_de_la_orden(orden)
    if not personal:
        return False, "no se envió el correo: la orden no tiene personal asignado."

    adjuntos = []          # (nombre_archivo, contenido, tipo)
    lineas = []            # cuerpo del correo
    sin_ss = []            # personas sin SS vigente
    for persona, rol in personal:
        nombre = persona.get_full_name() or persona.username
        doc = _ss_vigente(list(persona.documentos_personales.all()))
        if not doc:
            sin_ss.append(f"{nombre} ({rol})")
            lineas.append(f"- {nombre} ({rol}): SIN seguridad social vigente")
            continue
        # Lectura segura tanto en S3 como en disco local.
        with doc.archivo.open('rb') as fh:
            contenido = fh.read()
        base = os.path.basename(doc.archivo.name)
        ext = os.path.splitext(base)[1] or '.pdf'
        nombre_limpio = nombre.replace(' ', '_')
        tipo = mimetypes.guess_type(base)[0] or 'application/octet-stream'
        adjuntos.append((f"SS_{nombre_limpio}{ext}", contenido, tipo))
        lineas.append(f"- {nombre} ({rol}) — vigente hasta {doc.fecha_vencimiento.strftime('%d/%m/%Y')}")

    # Documentos del cliente que se adjuntan a TODA orden suya (además de la SS).
    lineas_cliente = []
    if orden.cliente_id:
        for doc in orden.cliente.documentos_correo.all():
            with doc.archivo.open('rb') as fh:
                contenido = fh.read()
            base = os.path.basename(doc.archivo.name)
            tipo = mimetypes.guess_type(base)[0] or 'application/octet-stream'
            adjuntos.append((base, contenido, tipo))
            lineas_cliente.append(f"- {doc.descripcion or base}")

    asunto = f"SOLMED - Seguridad social - Orden de servicio #{orden.numero_orden}"
    cuerpo = (
        f"Buen día,\n\n"
        f"Adjuntamos la seguridad social vigente del personal que participa "
        f"en la orden de servicio SOLMED #{orden.numero_orden}"
        f"{' para ' + orden.cliente.nombre if orden.cliente_id else ''}:\n\n"
        + "\n".join(lineas)
    )
    if lineas_cliente:
        cuerpo += "\n\nDocumentos del cliente:\n" + "\n".join(lineas_cliente)
    cuerpo += "\n\nCordialmente,\nSOLMED SAS"

    correo = EmailMessage(
        subject=asunto,
        body=cuerpo,
        from_email=settings.DEFAULT_FROM_EMAIL,
        to=[destinatario],
    )
    for nombre_archivo, contenido, tipo in adjuntos:
        correo.attach(nombre_archivo, contenido, tipo)
    correo.send(fail_silently=False)

    detalle = f"correo de seguridad social enviado a {destinatario} ({len(adjuntos)} documento(s) adjunto(s))"
    if sin_ss:
        detalle += f". OJO: sin seguridad social vigente: {', '.join(sin_ss)}"
    return True, detalle


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

        # Se envía la seguridad social al cliente. Un fallo del correo NO revierte
        # la orden (ya está creada): solo se informa para reintentar.
        try:
            enviado, detalle = _enviar_seguridad_social_cliente(orden, programacion)
        except Exception as e:
            enviado, detalle = False, f"no se pudo enviar el correo de seguridad social ({e})."
        (messages.success if enviado else messages.warning)(request, detalle.capitalize())
        _avisar_carga_pendiente(request, programacion, orden)

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


# ============================================================
#  MÓDULO PERSONAL (personas de la plataforma)
#  Panel dedicado a las personas: cuenta (accesos), datos personales y
#  expediente documental, todo en una sola ficha. Gestionado por Asesores
#  y superusuarios.
# ============================================================

def _perfil_de(persona):
    """Devuelve (creándolo si no existe) el perfil de datos de la persona."""
    perfil, _ = PerfilPersona.objects.get_or_create(usuario=persona)
    return perfil


class ListaPersonalView(AsesorRequiredMixin, ListView):
    model = User
    template_name = 'gestion/lista_personal.html'
    context_object_name = 'usuarios'

    def get_queryset(self):
        qs = (
            User.objects.all()
            .select_related('perfil')
            .prefetch_related('groups', 'documentos_personales')
        )
        q = self.request.GET.get('q', '').strip()
        rol = self.request.GET.get('rol', '')
        estado = self.request.GET.get('estado', '')

        if q:
            qs = qs.filter(
                Q(first_name__icontains=q) | Q(last_name__icontains=q)
                | Q(username__icontains=q) | Q(perfil__numero_documento__icontains=q)
            )
        if rol:
            qs = qs.filter(groups__name=rol)
        if estado == 'retirado':
            qs = qs.filter(perfil__retirado=True)
        elif estado == 'activo':
            qs = qs.exclude(perfil__retirado=True)

        # Los retirados van al final (trazabilidad); dentro, por nombre.
        return qs.order_by('perfil__retirado', 'first_name', 'username').distinct()

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        # Estado documental (faltantes) para conductores/ayudantes.
        docs = _estado_documentos_personal()
        for usuario in context['usuarios']:
            info = docs.get(usuario.id)
            usuario.doc_faltan = info['faltan'] if info else None
            usuario.tiene_requisitos = info is not None
            usuario.sin_acceso = _persona_sin_acceso(usuario)
            perfil = getattr(usuario, 'perfil', None)
            usuario.esta_retirado = bool(perfil and perfil.retirado)

        # Datos para la barra de filtros.
        context['roles'] = Group.objects.order_by('name')
        context['q'] = self.request.GET.get('q', '')
        context['rol_sel'] = self.request.GET.get('rol', '')
        context['estado_sel'] = self.request.GET.get('estado', '')
        return context


class CrearPersonaView(AsesorRequiredMixin, View):
    """
    Da de alta a una persona. El ROL se elige primero porque determina todo lo
    demás: los roles con acceso (conductores, asesores...) llevan usuario y
    contraseña; los ayudantes NO acceden al sistema, así que solo se registran
    sus datos y su expediente documental.
    """
    template_name = 'gestion/form_persona.html'

    def get(self, request):
        return render(request, self.template_name, {
            'form': CrearUsuarioForm(),
            'perfil_form': PerfilPersonaForm(),
            'crear': True,
            'grupos_sin_acceso_ids': json.dumps(_ids_grupos_sin_acceso()),
        })

    def post(self, request):
        grupo = _grupo_de_post(request)
        sin_acceso = _grupo_es_sin_acceso(grupo)
        # Los ayudantes no llevan usuario ni contraseña: se usa el formulario
        # reducido, que crea la cuenta inactiva y sin contraseña utilizable.
        FormClass = PersonaSinAccesoForm if sin_acceso else CrearUsuarioForm

        form = FormClass(request.POST)
        perfil_form = PerfilPersonaForm(request.POST)
        if form.is_valid() and perfil_form.is_valid():
            usuario = form.save()
            usuario.groups.add(form.cleaned_data['grupo'])
            perfil = perfil_form.save(commit=False)
            perfil.usuario = usuario
            perfil.save()
            if sin_acceso:
                messages.success(
                    request,
                    "Ayudante registrado. No tiene acceso al sistema: solo se gestiona su expediente."
                )
            else:
                messages.success(request, "Persona creada correctamente.")
            return redirect('gestion:ficha_persona', pk=usuario.pk)
        return render(request, self.template_name, {
            'form': form, 'perfil_form': perfil_form, 'crear': True,
            'sin_acceso': sin_acceso,
            'grupos_sin_acceso_ids': json.dumps(_ids_grupos_sin_acceso()),
        })


class FichaPersonaView(AsesorRequiredMixin, View):
    """Ficha completa de la persona: accesos, datos personales y expediente."""
    template_name = 'gestion/ficha_persona.html'

    def _context(self, persona):
        mes_actual = timezone.localdate().strftime('%Y-%m')
        docs = list(persona.documentos_personales.all())
        por_tipo = {}
        for d in docs:
            por_tipo.setdefault(d.tipo, []).append(d)

        grupos = set(persona.groups.values_list('name', flat=True))
        requeridos = _documentos_requeridos_por_rol(grupos)

        # Seguridad social vigente (por fecha de vencimiento, no por mes).
        ss_vigente = _ss_vigente(docs)
        ss_todos = por_tipo.get('SEGURIDAD_SOCIAL', [])
        # La más reciente cargada (para avisar cuál está vencida si no hay vigente).
        ss_ultima = max(
            ss_todos,
            key=lambda d: d.fecha_vencimiento or datetime.date.min,
            default=None,
        )

        # Una casilla por cada documento que aplica al rol, con su estado.
        # Los cursos solo aparecen en ayudantes; la licencia, solo en conductores.
        slots = []
        for tipo, label in _documentos_aplicables_por_rol(grupos):
            if tipo == 'SEGURIDAD_SOCIAL':
                # Cargada = existe una con vigencia sin vencer (manual, no por mes).
                doc = ss_vigente
            else:
                lista = por_tipo.get(tipo, [])
                doc = lista[0] if lista else None   # el más reciente (orden -fecha_subida)
            slots.append({
                'tipo': tipo, 'label': label, 'doc': doc,
                'cargado': doc is not None,
                'requerido': tipo in requeridos,
                'es_ss': tipo == 'SEGURIDAD_SOCIAL',
                'es_licencia': tipo == 'LICENCIA',
                'es_curso': tipo in ('CURSO_ALTURAS', 'CURSO_CONFINADOS'),
                'con_vigencia': tipo in TIPOS_CON_VIGENCIA,
            })

        otros = por_tipo.get('OTRO', [])
        faltan_requeridos = [s['label'] for s in slots if s['requerido'] and not s['cargado']]

        perfil = _perfil_de(persona)
        return {
            'persona': persona,
            'perfil': perfil,
            'retirado': perfil.retirado,
            'fecha_retiro': perfil.fecha_retiro,
            'mes_actual': mes_actual,
            # Tiene requisitos documentales (conductores, ayudantes y asesores).
            'es_personal': bool(requeridos),
            # Todos los que la llevan deben mantener su seguridad social vigente.
            'exige_ss': 'SEGURIDAD_SOCIAL' in requeridos,
            'sin_acceso': _persona_sin_acceso(persona),
            'dias_alerta': DocumentoPersonal.DIAS_ALERTA_VENCIMIENTO,
            'ss_al_dia': ss_vigente is not None,
            'slots': slots,
            # Hay seguridad social cargada pero ninguna vigente (todas vencidas).
            'ss_vencida': ss_vigente is None and ss_ultima is not None,
            'ss_ultima': ss_ultima,
            'ss_total': len(ss_todos),
            'otros': otros,
            'faltan_requeridos': faltan_requeridos,
        }

    def get(self, request, pk):
        persona = get_object_or_404(User, pk=pk)
        return render(request, self.template_name, self._context(persona))

    def post(self, request, pk):
        # Carga de un documento al expediente (cada casilla envía su 'tipo').
        persona = get_object_or_404(User, pk=pk)
        form = DocumentoPersonalForm(request.POST, request.FILES)
        if form.is_valid():
            documento = form.save(commit=False)
            documento.usuario = persona
            documento.save()
            messages.success(request, "Documento cargado.")
        else:
            messages.error(request, "No se pudo cargar el documento (revisa el archivo).")
        return redirect('gestion:ficha_persona', pk=pk)


class EditarCuentaPersonaView(AsesorRequiredMixin, View):
    """Edita la cuenta (usuario, nombre, correo, rol, estado) y el perfil de datos."""
    template_name = 'gestion/form_persona.html'

    def get(self, request, pk):
        persona = get_object_or_404(User, pk=pk)
        sin_acceso = _persona_sin_acceso(persona)
        FormClass = PersonaSinAccesoForm if sin_acceso else ActualizarUsuarioForm
        return render(request, self.template_name, {
            'form': FormClass(instance=persona),
            'perfil_form': PerfilPersonaForm(instance=_perfil_de(persona)),
            'persona': persona,
            'crear': False,
            'sin_acceso': sin_acceso,
            'grupos_sin_acceso_ids': json.dumps(_ids_grupos_sin_acceso()),
        })

    def post(self, request, pk):
        persona = get_object_or_404(User, pk=pk)
        grupo = _grupo_de_post(request)
        sin_acceso = _grupo_es_sin_acceso(grupo)
        FormClass = PersonaSinAccesoForm if sin_acceso else ActualizarUsuarioForm

        datos = request.POST.copy()
        # Al pasar de un rol sin acceso a uno con acceso, el formulario mostrado
        # no traía usuario ni estado: se reutiliza el identificador existente y
        # se activa la cuenta (la contraseña se define aparte).
        daba_acceso_nuevo = not sin_acceso and _persona_sin_acceso(persona)
        if daba_acceso_nuevo:
            datos.setdefault('username', persona.username)
            datos['is_active'] = 'on'

        form = FormClass(datos, instance=persona)
        perfil_form = PerfilPersonaForm(request.POST, instance=_perfil_de(persona))
        if form.is_valid() and perfil_form.is_valid():
            usuario = form.save()
            usuario.groups.clear()
            usuario.groups.add(form.cleaned_data['grupo'])
            perfil_form.save()
            messages.success(request, "Datos de la persona actualizados.")
            if daba_acceso_nuevo:
                messages.info(
                    request,
                    f"Esta persona ahora tiene acceso al sistema con el usuario "
                    f"«{usuario.username}». Asígnale una contraseña para que pueda entrar."
                )
            return redirect('gestion:ficha_persona', pk=usuario.pk)
        return render(request, self.template_name, {
            'form': form, 'perfil_form': perfil_form, 'persona': persona, 'crear': False,
            'sin_acceso': sin_acceso,
            'grupos_sin_acceso_ids': json.dumps(_ids_grupos_sin_acceso()),
        })


class CambiarPasswordPersonaView(AsesorRequiredMixin, View):
    """Cambia la contraseña de acceso de una persona (no aplica a los ayudantes)."""
    template_name = 'gestion/cambiar_password.html'

    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated:
            persona = get_object_or_404(User, pk=kwargs.get('pk'))
            if _persona_sin_acceso(persona):
                messages.info(
                    request,
                    "Los ayudantes no acceden al sistema, así que no tienen contraseña. "
                    "Cambia su rol si necesitas darle acceso."
                )
                return redirect('gestion:ficha_persona', pk=persona.pk)
        return super().dispatch(request, *args, **kwargs)

    def get(self, request, pk):
        persona = get_object_or_404(User, pk=pk)
        return render(request, self.template_name, {'form': self._form(persona), 'persona': persona})

    def post(self, request, pk):
        persona = get_object_or_404(User, pk=pk)
        form = self._form(persona, request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, "Contraseña actualizada.")
            return redirect('gestion:ficha_persona', pk=persona.pk)
        return render(request, self.template_name, {'form': form, 'persona': persona})

    def _form(self, persona, data=None):
        form = SetPasswordForm(persona, data)
        for field in form.fields.values():
            field.widget.attrs['class'] = 'form-control'
        return form


class HistorialSeguridadSocialView(AsesorRequiredMixin, View):
    """
    Historial completo de la seguridad social de una persona. Cada carga lleva su
    vigencia (fecha de vencimiento) puesta a mano: está vigente mientras no venza,
    y las vencidas quedan aquí como soporte histórico.
    """
    template_name = 'gestion/historial_seguridad_social.html'

    def _context(self, persona):
        documentos = persona.documentos_personales.filter(
            tipo='SEGURIDAD_SOCIAL'
        ).order_by('-fecha_vencimiento', '-fecha_subida')

        registros = [{
            'doc': documento,
            'vigente': documento.vigente,
        } for documento in documentos]

        return {
            'persona': persona,
            'perfil': _perfil_de(persona),
            'registros': registros,
            'al_dia': any(r['vigente'] for r in registros),
            'total': len(registros),
            'dias_alerta': DocumentoPersonal.DIAS_ALERTA_VENCIMIENTO,
        }

    def get(self, request, pk):
        persona = get_object_or_404(User, pk=pk)
        return render(request, self.template_name, self._context(persona))

    def post(self, request, pk):
        """Carga una seguridad social (con su vigencia) desde el historial."""
        persona = get_object_or_404(User, pk=pk)
        datos = request.POST.copy()
        datos['tipo'] = 'SEGURIDAD_SOCIAL'
        form = DocumentoPersonalForm(datos, request.FILES)
        if form.is_valid():
            documento = form.save(commit=False)
            documento.usuario = persona
            documento.save()
            messages.success(
                request,
                f"Seguridad social cargada (vigente hasta "
                f"{documento.fecha_vencimiento.strftime('%d/%m/%Y')})."
            )
        else:
            messages.error(request, "No se pudo cargar: revisa el archivo y la vigencia.")
        return redirect('gestion:historial_seguridad_social', pk=pk)


class ActualizarVigenciaDocumentoView(AsesorRequiredMixin, View):
    """
    Fija o edita la vigencia (fecha de vencimiento) de un documento del
    expediente desde el pop-up de la ficha. Solo POST.
    """
    def post(self, request, pk):
        documento = get_object_or_404(DocumentoPersonal, pk=pk)
        fecha = request.POST.get('fecha_vencimiento', '').strip()

        if not fecha:
            # Vaciar el campo = el documento queda sin vigencia registrada.
            documento.fecha_vencimiento = None
            documento.save(update_fields=['fecha_vencimiento'])
            messages.success(request, "Vigencia eliminada del documento.")
            return redirect('gestion:ficha_persona', pk=documento.usuario_id)

        try:
            documento.fecha_vencimiento = datetime.datetime.strptime(fecha, '%Y-%m-%d').date()
        except ValueError:
            messages.error(request, "La fecha de vigencia no es válida.")
            return redirect('gestion:ficha_persona', pk=documento.usuario_id)

        documento.save(update_fields=['fecha_vencimiento'])
        messages.success(
            request,
            f"Vigencia registrada: vence el {documento.fecha_vencimiento.strftime('%d/%m/%Y')}."
        )
        return redirect('gestion:ficha_persona', pk=documento.usuario_id)


class CambiarEstadoPersonaView(AsesorRequiredMixin, View):
    """
    Retira o reactiva a una persona (solo POST). Al retirar, deja de aparecer en
    las asignaciones (programación, recorridos, planificación) y se le bloquea el
    acceso; su ficha y expediente se conservan para trazabilidad. Al reactivar, se
    restaura el acceso salvo que sea un rol sin acceso (ayudante).
    """
    def post(self, request, pk):
        persona = get_object_or_404(User, pk=pk)
        perfil = _perfil_de(persona)
        if perfil.retirado:
            perfil.retirado = False
            perfil.fecha_retiro = None
            perfil.save(update_fields=['retirado', 'fecha_retiro'])
            if not _persona_sin_acceso(persona):
                persona.is_active = True
                persona.save(update_fields=['is_active'])
            messages.success(request, "Persona reactivada. Vuelve a estar disponible para asignaciones.")
        else:
            perfil.retirado = True
            perfil.fecha_retiro = timezone.localdate()
            perfil.save(update_fields=['retirado', 'fecha_retiro'])
            persona.is_active = False
            persona.save(update_fields=['is_active'])
            messages.success(
                request,
                "Persona marcada como retirada. Ya no aparece en las asignaciones; "
                "su expediente se conserva para trazabilidad."
            )
        return redirect('gestion:ficha_persona', pk=pk)


class EliminarDocumentoPersonalView(AsesorRequiredMixin, View):
    """Elimina un documento del expediente (solo POST)."""
    def post(self, request, pk):
        documento = get_object_or_404(DocumentoPersonal, pk=pk)
        usuario_pk = documento.usuario_id
        # Al borrar desde el historial de seguridad social se vuelve allí.
        volver_a_historial = request.POST.get('origen') == 'seguridad_social'
        documento.delete()
        messages.success(request, "Documento eliminado del expediente.")
        if volver_a_historial:
            return redirect('gestion:historial_seguridad_social', pk=usuario_pk)
        return redirect('gestion:ficha_persona', pk=usuario_pk)

# ============================================================
#  DOCUMENTACIÓN INTERNA DE SOLMED
#  Panel con los documentos de la propia empresa (RUT, cámara, certificaciones,
#  etc.), a la mano para las áreas. Gestionado por asesores y superusuarios.
# ============================================================
class DocumentacionSolmedView(AsesorRequiredMixin, View):
    template_name = 'gestion/documentacion.html'

    def _context(self):
        from .models import DocumentoInterno
        docs = list(DocumentoInterno.objects.all())
        por_tipo = {}
        for d in docs:
            por_tipo.setdefault(d.tipo, []).append(d)
        # Una tarjeta por tipo, en el orden de las opciones del modelo.
        secciones = []
        for tipo, label in DocumentoInterno.TIPO_CHOICES:
            secciones.append({
                'tipo': tipo,
                'label': label,
                'docs': por_tipo.get(tipo, []),
                'con_fecha': tipo in DocumentoInterno.TIPOS_CON_FECHA,
                'es_bancaria': tipo == DocumentoInterno.TIPO_MULTIPLE,
                'multiple': tipo == DocumentoInterno.TIPO_MULTIPLE,
            })
        return {
            'secciones': secciones,
            'entidades_bancarias': DocumentoInterno.ENTIDADES_BANCARIAS,
        }

    def get(self, request):
        return render(request, self.template_name, self._context())

    def post(self, request):
        from .forms import DocumentoInternoForm
        form = DocumentoInternoForm(request.POST, request.FILES)
        if form.is_valid():
            form.save()
            messages.success(request, "Documento cargado.")
        else:
            errores = "; ".join(
                f"{form.fields.get(c).label or c}: {e[0]}" for c, e in form.errors.items()
            )
            messages.error(request, f"No se pudo cargar el documento. {errores}")
        return redirect('gestion:documentacion')


class EliminarDocumentoInternoView(AsesorRequiredMixin, View):
    """Elimina un documento interno de SOLMED (solo POST)."""
    def post(self, request, pk):
        from .models import DocumentoInterno
        documento = get_object_or_404(DocumentoInterno, pk=pk)
        documento.delete()
        messages.success(request, "Documento eliminado.")
        return redirect('gestion:documentacion')
