from django.shortcuts import render, redirect
from django.contrib import messages
from django.urls import reverse_lazy
from django.views.generic import ListView, CreateView, UpdateView, TemplateView, DetailView
from django.utils import timezone
from django.db.models import Sum
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db.models import Q
from .models import OrdenServicio

from .forms import DocumentoOrdenForm, OrdenServicioForm, VehiculoForm, ClienteForm
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

class CrearOrdenView(LoginRequiredMixin, CreateView):
    model = OrdenServicio
    form_class = OrdenServicioForm
    template_name = 'gestion/form_orden.html'
    success_url = reverse_lazy('gestion:lista_ordenes')
    success_message = "¡Orden de servicio creada exitosamente!"

    def form_valid(self, form):
        # Asigna automáticamente el usuario logueado como el asesor.
        form.instance.asesor = self.request.user
        return super().form_valid(form)

    def get_form(self, form_class=None):
        # Lógica para mostrar solo vehículos disponibles en el formulario.
        form = super().get_form(form_class)
        form.fields['vehiculo_asignado'].queryset = Vehiculo.objects.filter(estado='DISPONIBLE')
        return form

class ActualizarOrdenView(LoginRequiredMixin, UpdateView):
    model = OrdenServicio
    form_class = OrdenServicioForm
    template_name = 'gestion/form_orden.html'
    success_url = reverse_lazy('gestion:lista_ordenes')
    success_message = "¡Orden de servicio actualizada exitosamente!"

    def get_form(self, form_class=None):
        # Lógica para mostrar vehículos disponibles Y el que ya está asignado a la orden.
        form = super().get_form(form_class)
        orden_actual = self.get_object()
        vehiculos_disponibles = Vehiculo.objects.filter(estado='DISPONIBLE')
        if orden_actual.vehiculo_asignado:
            form.fields['vehiculo_asignado'].queryset = vehiculos_disponibles | Vehiculo.objects.filter(pk=orden_actual.vehiculo_asignado.pk)
        else:
            form.fields['vehiculo_asignado'].queryset = vehiculos_disponibles
        return form

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


class OrdenServicioDetailView(LoginRequiredMixin, DetailView):
    model = OrdenServicio
    template_name = 'gestion/ordenservicio_detail.html'
    context_object_name = 'orden'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        # Añadimos el formulario de subida al contexto
        context['form_documento'] = DocumentoOrdenForm()
        return context

    def post(self, request, *args, **kwargs):
        # Este método se ejecuta cuando se envía el formulario (POST)
        orden = self.get_object()
        form = DocumentoOrdenForm(request.POST, request.FILES)
        
        if form.is_valid():
            documento = form.save(commit=False)
            documento.orden = orden  # Asigna la orden actual al documento
            documento.save()
            messages.success(request, '¡Documento adjuntado exitosamente!')
        else:
            messages.error(request, 'Error al adjuntar el documento. Por favor, inténtalo de nuevo.')
            
        return redirect('gestion:detalle_orden', pk=orden.pk)