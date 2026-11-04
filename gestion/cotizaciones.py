"""
COTIZACIONES (nov-2026, pedido de Santiago).

Un archivo por cotización con un CONSECUTIVO automático (COT-0001, COT-0002…)
que pone el sistema al guardar y que no se repite ni se edita. A quién se
cotiza se dice de dos formas:

- un CLIENTE ACTIVO del sistema, elegido del desplegable (solo los de la
  cartera de la asesora), o
- si todavía no es cliente, el NOMBRE escrito a mano. Ese nombre no crea
  ningún cliente: si después se vuelve cliente, se edita la cotización y se
  le elige.

Quién ve qué (gestion/accesos.py, módulo `cotizaciones`): administradores
todo; una asesora con la casilla ve las de los clientes de su cartera y las
que ella misma registró sin cliente (igual que en el centro de correos).
Eliminar es de administradores salvo que se le abra la casilla.
"""
from django import forms
from django.contrib import messages
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views import View
from django.views.generic import ListView

from .cartera import clientes_de, tiene_cartera
from .models import Cliente, Cotizacion
from .views import AdministradorRequiredMixin, AsesorRequiredMixin, PaginadoMixin


class CotizacionForm(forms.ModelForm):
    """
    Registro y edición. `tipo` decide cuál de los dos campos vale: con
    «Cliente activo» se exige el cliente y se vacía el nombre manual; con «No
    es cliente» se exige el nombre y se suelta el cliente. El archivo es
    obligatorio al registrar; al editar, si no se sube otro, se conserva.
    """
    TIPOS = [('cliente', 'Cliente activo'), ('otro', 'No es cliente todavía')]
    tipo = forms.ChoiceField(choices=TIPOS, widget=forms.RadioSelect, initial='cliente',
                             label='¿A quién se cotiza?')

    class Meta:
        model = Cotizacion
        fields = ['fecha', 'asunto', 'cliente', 'nombre_manual', 'archivo']
        widgets = {
            'fecha': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}, format='%Y-%m-%d'),
            'asunto': forms.TextInput(attrs={'class': 'form-control',
                                             'placeholder': 'Ej: Succión y disposición de lodos, sede norte'}),
            'cliente': forms.Select(attrs={'class': 'form-select'}),
            'nombre_manual': forms.TextInput(attrs={'class': 'form-control',
                                                    'placeholder': 'Nombre de la empresa o persona'}),
            # FileInput a secas: el «Actualmente / Modificar» de Django sobra,
            # la plantilla ya dice qué archivo tiene y que otro lo reemplaza.
            'archivo': forms.FileInput(attrs={'class': 'form-control'}),
        }

    def __init__(self, *args, usuario=None, **kwargs):
        super().__init__(*args, **kwargs)
        # Cartera: la asesora solo puede cotizarle a sus clientes.
        clientes = clientes_de(usuario) if usuario is not None else Cliente.objects.all()
        self.fields['cliente'].queryset = clientes.order_by('nombre')
        self.fields['cliente'].required = False
        self.fields['cliente'].empty_label = '--- Elige el cliente ---'
        if self.instance.pk:
            self.fields['archivo'].required = False
            if not self.instance.cliente_id:
                self.fields['tipo'].initial = 'otro'

    def clean(self):
        datos = super().clean()
        if datos.get('tipo') == 'otro':
            datos['cliente'] = None
            if not (datos.get('nombre_manual') or '').strip():
                self.add_error('nombre_manual', 'Escribe a quién se le cotiza.')
        else:
            datos['nombre_manual'] = ''
            if datos.get('cliente') is None and 'cliente' not in self.errors:
                self.add_error('cliente', 'Elige el cliente, o marca «No es cliente todavía».')
        return datos


def _cotizaciones_de(user):
    """Las cotizaciones al alcance de la persona (cartera + las suyas sin cliente)."""
    qs = Cotizacion.objects.select_related('cliente', 'registrada_por')
    if not tiene_cartera(user):
        return qs
    return qs.filter(Q(cliente__in=clientes_de(user)) | Q(cliente__isnull=True, registrada_por=user))


class ListaCotizacionesView(AsesorRequiredMixin, PaginadoMixin, ListView):
    acceso = 'cotizaciones.ver'
    template_name = 'gestion/lista_cotizaciones.html'
    context_object_name = 'cotizaciones'

    def get_queryset(self):
        qs = _cotizaciones_de(self.request.user)
        q = (self.request.GET.get('q') or '').strip()
        if q:
            filtro = (Q(asunto__icontains=q) | Q(cliente__nombre__icontains=q)
                      | Q(nombre_manual__icontains=q))
            numero = q.upper().replace(f'{Cotizacion.PREFIJO}-', '').lstrip('0')
            if numero.isdigit():
                filtro |= Q(numero=int(numero))
            qs = qs.filter(filtro)
        return qs.order_by('-numero')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['q'] = (self.request.GET.get('q') or '').strip()
        return context


class _FormularioCotizacion:
    template_name = 'gestion/form_cotizacion.html'

    def _guardar(self, request, form):
        cotizacion = form.save(commit=False)
        if cotizacion.registrada_por_id is None:
            cotizacion.registrada_por = request.user
        cotizacion.save()
        return cotizacion


class CrearCotizacionView(AsesorRequiredMixin, _FormularioCotizacion, View):
    acceso = 'cotizaciones.editar'

    def get(self, request):
        return render(request, self.template_name, {'form': CotizacionForm(usuario=request.user)})

    def post(self, request):
        form = CotizacionForm(request.POST, request.FILES, usuario=request.user)
        if not form.is_valid():
            return render(request, self.template_name, {'form': form})
        cotizacion = self._guardar(request, form)
        messages.success(request, f"Cotización {cotizacion.codigo} registrada para {cotizacion.destinatario}.")
        return redirect('gestion:lista_cotizaciones')


class EditarCotizacionView(AsesorRequiredMixin, _FormularioCotizacion, View):
    acceso = 'cotizaciones.editar'

    def _cotizacion(self, request, pk):
        return get_object_or_404(_cotizaciones_de(request.user), pk=pk)

    def get(self, request, pk):
        cotizacion = self._cotizacion(request, pk)
        return render(request, self.template_name, {
            'form': CotizacionForm(instance=cotizacion, usuario=request.user), 'cotizacion': cotizacion})

    def post(self, request, pk):
        cotizacion = self._cotizacion(request, pk)
        form = CotizacionForm(request.POST, request.FILES, instance=cotizacion, usuario=request.user)
        if not form.is_valid():
            return render(request, self.template_name, {'form': form, 'cotizacion': cotizacion})
        cotizacion = self._guardar(request, form)
        messages.success(request, f"Cotización {cotizacion.codigo} actualizada.")
        return redirect('gestion:lista_cotizaciones')


class EliminarCotizacionView(AdministradorRequiredMixin, View):
    """Borra la cotización y su archivo. El consecutivo que tenía no se reutiliza."""
    acceso = 'cotizaciones.eliminar'

    def post(self, request, pk):
        cotizacion = get_object_or_404(_cotizaciones_de(request.user), pk=pk)
        codigo = cotizacion.codigo
        if cotizacion.archivo:
            cotizacion.archivo.delete(save=False)
        cotizacion.delete()
        messages.success(request, f"Cotización {codigo} eliminada.")
        return redirect(reverse('gestion:lista_cotizaciones'))
