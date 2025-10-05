from django import forms
from .models import DocumentoOrden, Manifiesto, OrdenServicio, Vehiculo, Cliente
from django.contrib.auth.models import User, Group
from django.contrib.auth.forms import UserCreationForm

# Usamos ModelForm para que el formulario se construya a partir de nuestro modelo
class OrdenServicioForm(forms.ModelForm):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # self.instance es el objeto que se está editando.
        # Si .pk no existe, significa que es un objeto nuevo (se está creando).
        if not self.instance.pk:
            # Si es una orden nueva, eliminamos el campo 'estado_orden' del formulario.
            # No es necesario que el usuario lo vea o lo seleccione.
            if 'estado_orden' in self.fields:
                del self.fields['estado_orden']
                
    class Meta:
        model = OrdenServicio
        fields = [
            'cliente', 
            'fecha_servicio', 
            'direccion_servicio', 
            'descripcion', 
            'valor_servicio',
            'vehiculo_asignado', 
            'estado_orden', 
            'estado_pago'
        ]

        # Aquí ocurre la magia: personalizamos cómo se ve cada campo
        widgets = {
            'cliente': forms.Select(attrs={'class': 'form-select'}),
            'fecha_servicio': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'direccion_servicio': forms.TextInput(attrs={'class': 'form-control'}),
            'descripcion': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
            'valor_servicio': forms.NumberInput(attrs={'class': 'form-control'}),
            'vehiculo_asignado': forms.CheckboxSelectMultiple,
            'estado_orden': forms.Select(attrs={'class': 'form-select'}),
            'estado_pago': forms.Select(attrs={'class': 'form-select'}),
        }
        
        # Opcional: Cambiar las etiquetas que se muestran en el formulario
        labels = {
            'fecha_servicio': 'Fecha del Servicio',
            'valor_servicio': 'Valor del Servicio ($)',
            'vehiculo_asignado': 'Vehículo a Asignar',
        }

class VehiculoForm(forms.ModelForm):
    class Meta:
        model = Vehiculo
        fields = ['placa', 'marca', 'modelo', 'capacidad', 'estado']
        widgets = {
            'placa': forms.TextInput(attrs={'class': 'form-control'}),
            'marca': forms.TextInput(attrs={'class': 'form-control'}),
            'modelo': forms.TextInput(attrs={'class': 'form-control'}),
            'capacidad': forms.TextInput(attrs={'class': 'form-control'}),
            'estado': forms.Select(attrs={'class': 'form-select'}),
        }

class ClienteForm(forms.ModelForm):
    class Meta:
        model = Cliente
        # Añadimos los nuevos campos a la lista
        fields = [
            'nombre', 'identificacion', 'direccion', 'ciudad', 
            'persona_contacto', 'cargo_contacto', 'email', 'telefono'
        ]
        widgets = {
            'nombre': forms.TextInput(attrs={'class': 'form-control'}),
            'identificacion': forms.TextInput(attrs={'class': 'form-control'}),
            'direccion': forms.TextInput(attrs={'class': 'form-control'}),
            'ciudad': forms.TextInput(attrs={'class': 'form-control'}),
            'persona_contacto': forms.TextInput(attrs={'class': 'form-control'}),
            'cargo_contacto': forms.TextInput(attrs={'class': 'form-control'}),
            'email': forms.EmailInput(attrs={'class': 'form-control'}),
            'telefono': forms.TextInput(attrs={'class': 'form-control'}),
        }


class DocumentoOrdenForm(forms.ModelForm):
    class Meta:
        model = DocumentoOrden
        fields = ['archivo', 'descripcion']
        widgets = {
            'archivo': forms.FileInput(attrs={'class': 'form-control'}),
            'descripcion': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Ej: Foto de la carga, Remisión...'}),
        }
    


class ManifiestoForm(forms.ModelForm):
    class Meta:
        model = Manifiesto
        fields = ['nombre_receptor', 'cedula_receptor', 'tipo_residuo', 'observaciones']
        widgets = {
            'nombre_receptor': forms.TextInput(attrs={'class': 'form-control'}),
            'cedula_receptor': forms.TextInput(attrs={'class': 'form-control'}),
            'tipo_residuo': forms.TextInput(attrs={'class': 'form-control'}),
            'observaciones': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
        }


class CrearUsuarioForm(UserCreationForm):
    email = forms.EmailField(required=True, widget=forms.EmailInput(attrs={'class': 'form-control'}))
    first_name = forms.CharField(required=True, widget=forms.TextInput(attrs={'class': 'form-control'}))
    last_name = forms.CharField(required=True, widget=forms.TextInput(attrs={'class': 'form-control'}))
    grupo = forms.ModelChoiceField(queryset=Group.objects.all(), required=True, widget=forms.Select(attrs={'class': 'form-select'}))

    class Meta(UserCreationForm.Meta):
        model = User
        fields = UserCreationForm.Meta.fields + ('first_name', 'last_name', 'email')
        widgets = {
            'username': forms.TextInput(attrs={'class': 'form-control'}),
            'password1': forms.PasswordInput(attrs={'class': 'form-control'}),
            'password2': forms.PasswordInput(attrs={'class': 'form-control'}),
        }

class ActualizarUsuarioForm(forms.ModelForm):
    grupo = forms.ModelChoiceField(queryset=Group.objects.all(), required=True, widget=forms.Select(attrs={'class': 'form-select'}))

    class Meta:
        model = User
        fields = ['username', 'first_name', 'last_name', 'email', 'is_active']
        widgets = {
            'username': forms.TextInput(attrs={'class': 'form-control'}),
            'first_name': forms.TextInput(attrs={'class': 'form-control'}),
            'last_name': forms.TextInput(attrs={'class': 'form-control'}),
            'email': forms.EmailInput(attrs={'class': 'form-control'}),
            'is_active': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }

    def __init__(self, *args, **kwargs):
        # El método __init__ se usa para inicializar el valor del campo 'grupo'
        super().__init__(*args, **kwargs)
        if self.instance.pk:
            initial_group = self.instance.groups.first()
            if initial_group:
                self.fields['grupo'].initial = initial_group.pk