import os
from django.conf import settings
from django.http import HttpResponseRedirect
from django.contrib.messages.views import SuccessMessageMixin
from django.contrib.auth.models import User
from django.shortcuts import get_object_or_404, render, redirect
from django.contrib import messages
from django.contrib.auth.mixins import UserPassesTestMixin
from django.template.loader import get_template
from django.urls import reverse_lazy
from django.core.files.base import ContentFile
from django.views import View
from io import BytesIO
from weasyprint import HTML
from xhtml2pdf import pisa
import base64
import datetime
from decimal import Decimal 
from django.views.generic import ListView, CreateView, UpdateView, TemplateView, DetailView
from django.utils import timezone
from django.db.models import Sum
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db.models import Q
from .models import Manifiesto, OrdenServicio, Recorrido

from .forms import DocumentoOrdenForm, ManifiestoPaso1Form, ManifiestoPaso2Form, ManifiestoPaso3Form, ManifiestoPaso4Form, ManifiestoPaso5Form, OrdenServicioForm, RecorridoForm, VehiculoForm, ClienteForm, CrearUsuarioForm, ActualizarUsuarioForm
from .models import OrdenServicio, Vehiculo, Cliente

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
    FORMS = [
        ("paso1", ManifiestoPaso1Form), ("paso2", ManifiestoPaso2Form),
        ("paso3", ManifiestoPaso3Form), ("paso4", ManifiestoPaso4Form),
        ("paso5", ManifiestoPaso5Form),
    ]
    TEMPLATES = {
        "paso1": 'gestion/manifiesto_wizard/paso1.html',
        "paso2": 'gestion/manifiesto_wizard/paso2.html',
        "paso3": 'gestion/manifiesto_wizard/paso3.html',
        "paso4": 'gestion/manifiesto_wizard/paso4.html',
        "paso5": 'gestion/manifiesto_wizard/paso5.html',
        "firma": 'gestion/manifiesto_wizard/firma.html',
    }

    def get_form_step(self, step_name):
        for name, form_class in self.FORMS:
            if name == step_name:
                return form_class
        return None

    def get(self, request, pk, step='paso1'):
        recorrido = get_object_or_404(Recorrido, pk=pk)
        manifiesto_data = request.session.get(f'manifiesto_data_{pk}', {})
        try:
            manifiesto_instance = recorrido.manifiesto
        except Manifiesto.DoesNotExist:
            manifiesto_instance = None

        template_path = self.TEMPLATES.get(step)
        if not template_path:
            messages.error(request, "Paso de formulario inválido.")
            return redirect('gestion:detalle_orden', pk=recorrido.orden.pk)

        FormClass = self.get_form_step(step) if step != 'firma' else None
        form = FormClass(initial=manifiesto_data, instance=manifiesto_instance) if FormClass else None

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

        if 'submit_firma' in request.POST:
            signature_data = request.POST.get('signature_data')
            nombre_responsable_cliente = request.POST.get('nombre_responsable_cliente')

            if signature_data and nombre_responsable_cliente:
                # --- Guardado del Manifiesto ---
                final_data = manifiesto_data
                final_data['nombre_responsable_cliente'] = nombre_responsable_cliente
                
                manifiesto, created = Manifiesto.objects.update_or_create(
                    recorrido=recorrido, defaults=final_data
                )

                # Guardar firma
                format, imgstr = signature_data.split(';base64,')
                ext = format.split('/')[-1]
                signature_file = ContentFile(base64.b64decode(imgstr), name=f'firma_cliente_{pk}.{ext}')
                manifiesto.firma_cliente.save(signature_file.name, signature_file, save=True)

                # --- LÓGICA DEFINITIVA PARA IMÁGENES EN PDF ---
                template = get_template('gestion/manifiesto_pdf.html')

                # 1. Convertir el LOGO a Base64
                logo_path = os.path.join(settings.BASE_DIR, 'static', 'images', 'logo-solmed.png')
                with open(logo_path, "rb") as image_file:
                    logo_b64 = "data:image/png;base64," + base64.b64encode(image_file.read()).decode('utf-8')
                
                # 2. Convertir la FIRMA a Base64
                firma_cliente_b64 = None
                if manifiesto.firma_cliente:
                    with open(manifiesto.firma_cliente.path, "rb") as image_file:
                        firma_cliente_b64 = "data:image/png;base64," + base64.b64encode(image_file.read()).decode('utf-8')
                
                context = {
                    'manifiesto': manifiesto, 'recorrido': recorrido, 'orden': recorrido.orden,
                    'logo_b64': logo_b64, 'firma_cliente_b64': firma_cliente_b64
                }
                html_string = template.render(context)
                html = HTML(string=html_string, base_url=request.build_absolute_uri())
                pdf = html.write_pdf()

                pdf_file = ContentFile(pdf, name=f'manifiesto_recorrido_{pk}.pdf')
                manifiesto.pdf_generado = pdf_file
                manifiesto.save()
                
                messages.success(request, 'Manifiesto generado y firmado exitosamente.')
                if f'manifiesto_data_{pk}' in request.session:
                    del request.session[f'manifiesto_data_{pk}']
                return redirect('gestion:detalle_orden', pk=recorrido.orden.pk)

            else:
                messages.error(request, 'Falta la firma o el nombre del responsable.')
                return render(request, self.TEMPLATES['firma'], {'recorrido': recorrido, 'pk': pk, 'current_step': 'firma'})
        
        # --- Lógica para pasos intermedios ---
        FormClass = self.get_form_step(step)
        form = FormClass(request.POST, instance=manifiesto_instance)
        if form.is_valid():
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
            else:
                return redirect('gestion:firmar_manifiesto_step', pk=pk, step='firma')
        else:
            messages.error(request, "Por favor, corrija los errores en el formulario.")
            return render(request, self.TEMPLATES[step], {'recorrido': recorrido, 'form': form, 'current_step': step, 'pk': pk})



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


class OrdenServicioDetailView(LoginRequiredMixin, DetailView):
    model = OrdenServicio
    template_name = 'gestion/ordenservicio_detail.html'
    context_object_name = 'orden'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        # Añadimos el formulario para añadir nuevos recorridos
        context['form_recorrido'] = RecorridoForm()
        # Mantenemos el formulario para subir documentos
        context['form_documento'] = DocumentoOrdenForm()
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