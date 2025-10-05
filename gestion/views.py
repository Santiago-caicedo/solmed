from django.http import HttpResponseRedirect
from django.contrib.messages.views import SuccessMessageMixin
from django.contrib.auth.models import User
from django.shortcuts import render, redirect
from django.contrib import messages
from django.contrib.auth.mixins import UserPassesTestMixin
from django.template.loader import get_template
from django.urls import reverse_lazy
from django.core.files.base import ContentFile
from django.views import View
from io import BytesIO
from xhtml2pdf import pisa
import base64
from django.views.generic import ListView, CreateView, UpdateView, TemplateView, DetailView
from django.utils import timezone
from django.db.models import Sum
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db.models import Q
from .models import OrdenServicio

from .forms import DocumentoOrdenForm, ManifiestoForm, OrdenServicioForm, VehiculoForm, ClienteForm, CrearUsuarioForm, ActualizarUsuarioForm
from .models import OrdenServicio, Vehiculo, Cliente

# --- Vista Principal (Dashboard) ---
# Se protege con LoginRequiredMixin para que sea la página de inicio después del login.
class DashboardView(LoginRequiredMixin, TemplateView):
    template_name = 'gestion/dashboard.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        now = timezone.now()

        # --- MÉTRICAS EXISTENTES ---
        context['ordenes_activas'] = OrdenServicio.objects.filter(estado_orden='EN_PROCESO').count()
        context['vehiculos_disponibles'] = Vehiculo.objects.filter(estado='DISPONIBLE').count()
        cobranza = OrdenServicio.objects.filter(estado_pago='PENDIENTE').aggregate(total=Sum('valor_servicio'))
        context['cobranza_pendiente'] = cobranza['total'] or 0.00

        # --- NUEVAS MÉTRICAS ---

        # 1. Ingresos y servicios completados del mes actual
        ingresos_mes_query = OrdenServicio.objects.filter(
            estado_orden='FINALIZADA', 
            fecha_servicio__year=now.year, 
            fecha_servicio__month=now.month
        )
        ingresos_mes_total = ingresos_mes_query.aggregate(total=Sum('valor_servicio'))
        context['ingresos_del_mes'] = ingresos_mes_total['total'] or 0.00
        context['servicios_completados_mes'] = ingresos_mes_query.count()

        # 2. Órdenes pendientes por iniciar
        context['ordenes_pendientes_iniciar'] = OrdenServicio.objects.filter(estado_orden='PENDIENTE').count()
        
        # 3. Tasa de utilización de vehículos
        total_vehiculos = Vehiculo.objects.count()
        if total_vehiculos > 0:
            vehiculos_en_servicio = Vehiculo.objects.filter(estado='EN_SERVICIO').count()
            utilizacion = (vehiculos_en_servicio / total_vehiculos) * 100
            context['utilizacion_vehiculos'] = round(utilizacion, 1)
        else:
            context['utilizacion_vehiculos'] = 0

        # --- LISTAS ACCIONABLES ---
        context['servicios_hoy'] = OrdenServicio.objects.filter(fecha_servicio=now.date(), estado_orden__in=['PENDIENTE', 'EN_PROCESO'])
        
        # Nueva lista: Órdenes finalizadas pendientes de pago
        context['cobranza_prioritaria'] = OrdenServicio.objects.filter(
            estado_orden='FINALIZADA', 
            estado_pago='PENDIENTE'
        ).order_by('fecha_servicio')

        return context


# --- Vistas para Órdenes de Servicio ---
# Todas las vistas de gestión se protegen con LoginRequiredMixin.
# Se usa 'form_class' para conectar la vista con el formulario personalizado.
class ListaOrdenesView(LoginRequiredMixin, ListView):
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

class CrearOrdenView(LoginRequiredMixin, SuccessMessageMixin, CreateView):
    model = OrdenServicio
    form_class = OrdenServicioForm
    template_name = 'gestion/form_orden.html'
    success_url = reverse_lazy('gestion:lista_ordenes')
    success_message = "¡Orden de servicio creada exitosamente!"

    # REEMPLAZA TU MÉTODO form_valid CON ESTE
    def form_valid(self, form):
        # Asigna el asesor antes de guardar
        form.instance.asesor = self.request.user
        
        # Guarda el formulario. El objeto principal se crea y guarda.
        self.object = form.save()
        
        # Redirige a la URL de éxito.
        # Los mixins se encargarán de mostrar el mensaje de éxito.
        return HttpResponseRedirect(self.get_success_url())

class ActualizarOrdenView(LoginRequiredMixin, SuccessMessageMixin, UpdateView):
    model = OrdenServicio
    form_class = OrdenServicioForm
    template_name = 'gestion/form_orden.html'
    success_url = reverse_lazy('gestion:lista_ordenes')
    success_message = "¡Orden de servicio actualizada exitosamente!"

    # AÑADE ESTE MÉTODO form_valid TAMBIÉN AQUÍ
    def form_valid(self, form):
        # El proceso es idéntico para actualizar
        self.object = form.save()
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

class CrearClienteView(LoginRequiredMixin, CreateView):
    model = Cliente
    form_class = ClienteForm
    template_name = 'gestion/form_cliente.html'
    success_url = reverse_lazy('gestion:lista_clientes')
    success_message = "¡Cliente creado exitosamente!"

class ActualizarClienteView(LoginRequiredMixin, UpdateView):
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

        # Obtenemos TODAS las órdenes activas (no solo la primera)
        context['ordenes_activas'] = vehiculo.ordenes.filter(estado_orden='EN_PROCESO').order_by('fecha_servicio')
        
        # El resto de la lógica sigue igual...
        context['servicios_futuros'] = vehiculo.ordenes.filter(estado_orden='PENDIENTE', fecha_servicio__gte=timezone.now().date()).order_by('fecha_servicio')
        historial = vehiculo.ordenes.filter(estado_orden='FINALIZADA').order_by('-fecha_servicio')
        context['historial_ordenes'] = historial
        context['total_servicios_realizados'] = historial.count()
        ingresos_generados = historial.aggregate(total=Sum('valor_servicio'))
        context['total_ingresos_generados'] = ingresos_generados['total'] or 0

        return context



class GenerarManifiestoView(LoginRequiredMixin, View):
    
    def get(self, request, pk):
        orden = OrdenServicio.objects.get(pk=pk)
        form = ManifiestoForm()
        return render(request, 'gestion/firmar_manifiesto.html', {'orden': orden, 'form': form})

    def post(self, request, pk):
        orden = OrdenServicio.objects.get(pk=pk)
        form = ManifiestoForm(request.POST)
        
        # El dato de la firma viene como una cadena de texto base64
        signature_data = request.POST.get('signature_data')

        if form.is_valid() and signature_data:
            # Decodificar y guardar la imagen de la firma
            format, imgstr = signature_data.split(';base64,') 
            ext = format.split('/')[-1] 
            signature_file = ContentFile(base64.b64decode(imgstr), name=f'firma_orden_{pk}.{ext}')
            
            # Crear la instancia del manifiesto pero sin guardarla aún
            manifiesto = form.save(commit=False)
            manifiesto.orden = orden
            manifiesto.firma_receptor = signature_file
            manifiesto.save() # Ahora sí se guarda con la firma

            # --- Generación del PDF ---
            template = get_template('gestion/manifiesto_pdf.html')
            context = {'manifiesto': manifiesto, 'orden': orden}
            html = template.render(context)
            
            # Crear el PDF en memoria
            pdf_buffer = BytesIO()
            pisa_status = pisa.CreatePDF(html, dest=pdf_buffer)

            if not pisa_status.err:
                # Guardar el PDF en el modelo
                pdf_file = ContentFile(pdf_buffer.getvalue(), name=f'manifiesto_orden_{pk}.pdf')
                manifiesto.pdf_generado = pdf_file
                manifiesto.save()
                messages.success(request, 'Manifiesto generado y firmado exitosamente.')
            else:
                messages.error(request, 'Error al generar el PDF.')

            return redirect('gestion:detalle_orden', pk=orden.pk)

        return render(request, 'gestion/firmar_manifiesto.html', {'orden': orden, 'form': form})


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