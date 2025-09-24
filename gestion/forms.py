from django import forms
from .models import DocumentoOrden, OrdenServicio, Vehiculo, Cliente

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
        fields = ['nombre', 'identificacion', 'telefono', 'email', 'direccion']
        widgets = {
            'nombre': forms.TextInput(attrs={'class': 'form-control'}),
            'identificacion': forms.TextInput(attrs={'class': 'form-control'}),
            'telefono': forms.TextInput(attrs={'class': 'form-control'}),
            'email': forms.EmailInput(attrs={'class': 'form-control'}),
            'direccion': forms.TextInput(attrs={'class': 'form-control'}),
        }


class DocumentoOrdenForm(forms.ModelForm):
    class Meta:
        model = DocumentoOrden
        fields = ['archivo', 'descripcion']
        widgets = {
            'archivo': forms.FileInput(attrs={'class': 'form-control'}),
            'descripcion': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Ej: Foto de la carga, Remisión...'}),
        }