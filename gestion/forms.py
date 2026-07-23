from django import forms
from .models import Dispositor, DocumentoOrden, DocumentoPersonal, EncuestaConductor, Manifiesto, OrdenServicio, Pago, PerfilPersona, Programacion, ProgramacionCuadrilla, Recorrido, Vehiculo, Cliente
from django.contrib.auth.models import User, Group
from django.contrib.auth.forms import UserCreationForm
from django.utils.text import slugify
import datetime

# Usamos ModelForm para que el formulario se construya a partir de nuestro modelo
class OrdenServicioForm(forms.ModelForm):
    # Ya no necesitamos el método __init__ para este formulario
    class Meta:
        model = OrdenServicio
        # Campos de pago (valor_servicio, estado_pago) ocultos por ahora.
        fields = [
            'cliente',
            'direccion_servicio',
            'descripcion',
            'bascula', 'bascula_adjunto',
            'registro_fotografico', 'registro_fotografico_adjunto',
        ]

        widgets = {
            'cliente': forms.Select(attrs={'class': 'form-select'}),
            'direccion_servicio': forms.TextInput(attrs={'class': 'form-control'}),
            'descripcion': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
            'bascula': forms.Select(attrs={'class': 'form-select'}),
            'bascula_adjunto': forms.FileInput(attrs={'class': 'form-control'}),
            'registro_fotografico': forms.Select(attrs={'class': 'form-select'}),
            'registro_fotografico_adjunto': forms.FileInput(attrs={'class': 'form-control'}),
        }

class VehiculoForm(forms.ModelForm):
    class Meta:
        model = Vehiculo
        fields = [
            'placa', 'marca', 'modelo', 'capacidad', 'estado',
            'archivo_tarjeta',
            'fecha_vencimiento_soat', 'archivo_soat',
            'fecha_vencimiento_tecnomecanica', 'archivo_tecnomecanica',
        ]
        widgets = {
            'placa': forms.TextInput(attrs={'class': 'form-control'}),
            'marca': forms.TextInput(attrs={'class': 'form-control'}),
            'modelo': forms.TextInput(attrs={'class': 'form-control'}),
            'capacidad': forms.TextInput(attrs={'class': 'form-control'}),
            'estado': forms.Select(attrs={'class': 'form-select'}),
            'archivo_tarjeta': forms.FileInput(attrs={'class': 'form-control', 'accept': 'application/pdf'}),
            'fecha_vencimiento_soat': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}, format='%Y-%m-%d'),
            'archivo_soat': forms.FileInput(attrs={'class': 'form-control', 'accept': 'application/pdf'}),
            'fecha_vencimiento_tecnomecanica': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}, format='%Y-%m-%d'),
            'archivo_tecnomecanica': forms.FileInput(attrs={'class': 'form-control', 'accept': 'application/pdf'}),
        }

class ClienteForm(forms.ModelForm):
    class Meta:
        model = Cliente
        # Añadimos los nuevos campos a la lista
        fields = [
            'nombre', 'sigla', 'identificacion', 'direccion', 'ciudad',
            'telefono_fijo', 'telefono_celular',
            'persona_contacto', 'cargo_contacto', 'email', 'telefono',
            # Contacto Comercial
            'comercial_nombre', 'comercial_telefono', 'comercial_cargo', 'comercial_correo',
            # Contacto Contabilidad y Facturación Electrónica
            'contab_nombre', 'contab_telefono', 'contab_cargo', 'contab_correo',
            'contab_correo_facturacion', 'contab_domicilio_fiscal',
            # Contacto Ambiental
            'ambiental_nombre', 'ambiental_telefono', 'ambiental_cargo', 'ambiental_correo',
            # Contacto SST
            'sst_nombre', 'sst_telefono', 'sst_cargo', 'sst_correo',
            # Documentos a adjuntar (fijos)
            'doc_rut', 'doc_camara_comercio', 'doc_cedula_rep_legal',
        ]
        widgets = {
            'nombre': forms.TextInput(attrs={'class': 'form-control'}),
            'sigla': forms.TextInput(attrs={'class': 'form-control'}),
            'identificacion': forms.TextInput(attrs={'class': 'form-control'}),
            'direccion': forms.TextInput(attrs={'class': 'form-control'}),
            'ciudad': forms.TextInput(attrs={'class': 'form-control'}),
            'telefono_fijo': forms.TextInput(attrs={'class': 'form-control'}),
            'telefono_celular': forms.TextInput(attrs={'class': 'form-control'}),
            'persona_contacto': forms.TextInput(attrs={'class': 'form-control'}),
            'cargo_contacto': forms.TextInput(attrs={'class': 'form-control'}),
            'email': forms.EmailInput(attrs={'class': 'form-control'}),
            'telefono': forms.TextInput(attrs={'class': 'form-control'}),
            'doc_rut': forms.FileInput(attrs={'class': 'form-control'}),
            'doc_camara_comercio': forms.FileInput(attrs={'class': 'form-control'}),
            'doc_cedula_rep_legal': forms.FileInput(attrs={'class': 'form-control'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Aplica el estilo Bootstrap a los campos que no tienen un widget explícito
        # (las secciones de contacto Comercial / Contabilidad / Ambiental / SST).
        for field in self.fields.values():
            css = field.widget.attrs.get('class', '')
            if 'form-control' not in css and 'form-select' not in css:
                field.widget.attrs['class'] = (css + ' form-control').strip()


class DocumentoOrdenForm(forms.ModelForm):
    class Meta:
        model = DocumentoOrden
        fields = ['archivo', 'descripcion']
        widgets = {
            'archivo': forms.FileInput(attrs={'class': 'form-control'}),
            'descripcion': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Ej: Foto de la carga, Remisión...'}),
        }
    


# --- Formularios para cada sección del Manifiesto ---

class ManifiestoPaso1Form(forms.ModelForm): # Cabecera e Info del Servicio
    class Meta:
        model = Manifiesto
        fields = [
            'auxiliar1', 'auxiliar2'
        ]
        labels = {
            'auxiliar1': 'Auxiliar 1',
            'auxiliar2': 'Auxiliar 2',
        }
        widgets = {
            'auxiliar1': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Nombre Auxiliar 1'}),
            'auxiliar2': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Nombre Auxiliar 2'}),
        }

class ManifiestoPaso2Form(forms.ModelForm): # Succión y Transporte / Sondeo / Lavado / Transporte
    class Meta:
        model = Manifiesto
        fields = [
            # Succión y Transporte
            'succ_canecas', 'succ_canecas_cant',
            'succ_pozos_inspeccion', 'succ_pozos_inspeccion_cant',
            'succ_pozos_septicos', 'succ_pozos_septicos_cant',
            'succ_tanques', 'succ_tanques_cant',
            'succ_trampas_grasa', 'succ_trampas_grasa_cant',
            'succ_otros', 'succ_otros_cant',
            # Sondeo
            'sond_red_aguas_lluvias', 'sond_red_aguas_lluvias_cant',
            'sond_red_aguas_negras', 'sond_red_aguas_negras_cant',
            'sond_red_acueducto', 'sond_red_acueducto_cant',
            'sond_correctivo', 'sond_correctivo_cant',
            'sond_preventivo', 'sond_preventivo_cant',
            'sond_diametro',
            # Lavado
            'lavado_concepto', 'lavado_cantidad', 'lavado_correctivo', 'lavado_preventivo',
            # Transporte
            'transporte_tipo', 'transporte_cantidad',
        ]
        widgets = {
            'succ_canecas_cant': forms.TextInput(attrs={'class': 'form-control form-control-sm', 'placeholder': 'Ton/M³'}),
            'succ_pozos_inspeccion_cant': forms.TextInput(attrs={'class': 'form-control form-control-sm', 'placeholder': 'Ton/M³'}),
            'succ_pozos_septicos_cant': forms.TextInput(attrs={'class': 'form-control form-control-sm', 'placeholder': 'Ton/M³'}),
            'succ_tanques_cant': forms.TextInput(attrs={'class': 'form-control form-control-sm', 'placeholder': 'Ton/M³'}),
            'succ_trampas_grasa_cant': forms.TextInput(attrs={'class': 'form-control form-control-sm', 'placeholder': 'Ton/M³'}),
            'succ_otros': forms.TextInput(attrs={'class': 'form-control form-control-sm', 'placeholder': 'Especifique'}),
            'succ_otros_cant': forms.TextInput(attrs={'class': 'form-control form-control-sm', 'placeholder': 'Ton/M³'}),
            'sond_diametro': forms.TextInput(attrs={'class': 'form-control form-control-sm', 'placeholder': 'Diámetro'}),
            'lavado_concepto': forms.TextInput(attrs={'class': 'form-control form-control-sm', 'placeholder': 'Concepto'}),
            'lavado_cantidad': forms.TextInput(attrs={'class': 'form-control form-control-sm', 'placeholder': 'H/ML/Cantidad'}),
            'lavado_correctivo': forms.TextInput(attrs={'class': 'form-control form-control-sm', 'placeholder': 'Valor Correctivo'}),
            'lavado_preventivo': forms.TextInput(attrs={'class': 'form-control form-control-sm', 'placeholder': 'Valor Preventivo'}),
            'transporte_tipo': forms.TextInput(attrs={'class': 'form-control form-control-sm', 'placeholder': 'Tipo'}),
            'transporte_cantidad': forms.TextInput(attrs={'class': 'form-control form-control-sm', 'placeholder': 'Cantidad'}),
        }
        labels = {
            'succ_canecas': 'Canecas', 'succ_canecas_cant': '',
            'succ_pozos_inspeccion': 'Pozos de inspección', 'succ_pozos_inspeccion_cant': '',
            'succ_pozos_septicos': 'Pozos Sépticos', 'succ_pozos_septicos_cant': '',
            'succ_tanques': 'Tanques', 'succ_tanques_cant': '',
            'succ_trampas_grasa': 'Trampas de Grasa', 'succ_trampas_grasa_cant': '',
            'succ_otros': 'Otros ¿Cuál?', 'succ_otros_cant': '',
            
            'sond_red_aguas_lluvias': 'Red de agua lluvias', 'sond_red_aguas_lluvias_cant': '',
            'sond_red_aguas_negras': 'Red de aguas negras', 'sond_red_aguas_negras_cant': '',
            'sond_red_acueducto': 'Red Acueducto', 'sond_red_acueducto_cant': '',
            'sond_correctivo': 'Correctivo', 'sond_correctivo_cant': '',
            'sond_preventivo': 'Preventivo', 'sond_preventivo_cant': '',
            'sond_diametro': 'Diámetro',

            'lavado_concepto': 'Concepto', 
            'lavado_cantidad': 'Cantidad',
            'lavado_correctivo': 'Correctivo', 
            'lavado_preventivo': 'Preventivo',

            'transporte_tipo': 'Tipo', 'transporte_cantidad': 'Cantidad',
        }

class ManifiestoPaso3Form(forms.ModelForm):
    class Meta:
        model = Manifiesto
        fields = [
            'tiempo_inicio_operativo', 'tiempo_final_operativo',
            'tiempo_llegada_disposicion', 'tiempo_salida_disposicion',
            'horometro_inicio', 'horometro_final',
            'km_salida_solmed', 'km_llegada_empresa', 'km_llegada_disposicion',
            'km_llegada_solmed'
        ]
        widgets = {
            # --- Campos de Tiempos ---
            'tiempo_inicio_operativo': forms.TimeInput(attrs={'class': 'form-control', 'type': 'time'}, format='%H:%M'),
            'tiempo_final_operativo': forms.TimeInput(attrs={'class': 'form-control', 'type': 'time'}, format='%H:%M'),
            'tiempo_llegada_disposicion': forms.TimeInput(attrs={'class': 'form-control', 'type': 'time'}, format='%H:%M'), # NUEVO
            'tiempo_salida_disposicion': forms.TimeInput(attrs={'class': 'form-control', 'type': 'time'}, format='%H:%M'), # NUEVO
            
            # --- Campos de Horómetro (AHORA TIPO TIME) ---
            'horometro_inicio': forms.TimeInput(attrs={'class': 'form-control', 'type': 'time'}, format='%H:%M'), # CAMBIADO
            'horometro_final': forms.TimeInput(attrs={'class': 'form-control', 'type': 'time'}, format='%H:%M'), # CAMBIADO
            
            # --- Campos de Kilómetros ---
            'km_salida_solmed': forms.NumberInput(attrs={'class': 'form-control'}),
            'km_llegada_empresa': forms.NumberInput(attrs={'class': 'form-control'}),
            'km_llegada_disposicion': forms.NumberInput(attrs={'class': 'form-control'}),
            'km_llegada_solmed': forms.NumberInput(attrs={'class': 'form-control'}), # NUEVO
        }
        labels = {
            'tiempo_llegada_disposicion': 'H. Llegada sitio Disposición', # NUEVO
            'tiempo_salida_disposicion': 'H. Salida sitio Disposición', # NUEVO
            'horometro_inicio': 'H. Inicio',
            'horometro_final': 'H. Final',
            'km_llegada_solmed': 'Llegada Solmed', # NUEVO
        }

class ManifiestoPaso4Form(forms.ModelForm): # Responsable / Firma / Observaciones
    class Meta:
        model = Manifiesto
        fields = [
            'nombre_responsable_empresa',
            'observaciones',
        ]
        widgets = {
            'nombre_responsable_empresa': forms.TextInput(attrs={'class': 'form-control'}),
            'observaciones': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
        }
        labels = {
            'nombre_responsable_empresa': 'Nombre del Responsable',
            'observaciones': 'Observaciones',
        }

class ManifiestoPaso5Form(forms.ModelForm): # Satisfacción
    class Meta:
        model = Manifiesto
        fields = [
            'eval_atencion', 'eval_amabilidad', 'eval_solucion_inquietudes', 'eval_asesoria',
            'eval_puntualidad', 'eval_calidad_servicio', 'eval_oportunidad',
            'eval_cumplimiento_condiciones', 'eval_solucion_problemas',
            'eval_volveria_contratar', 'eval_nos_recomendaria',
        ]
        widgets = {
            'eval_atencion': forms.RadioSelect,
            'eval_amabilidad': forms.RadioSelect,
            'eval_solucion_inquietudes': forms.RadioSelect,
            'eval_asesoria': forms.RadioSelect,
            'eval_puntualidad': forms.RadioSelect,
            'eval_calidad_servicio': forms.RadioSelect,
            'eval_oportunidad': forms.RadioSelect,
            'eval_cumplimiento_condiciones': forms.RadioSelect,
            'eval_solucion_problemas': forms.RadioSelect,
            'eval_volveria_contratar': forms.RadioSelect,
            'eval_nos_recomendaria': forms.RadioSelect,
        }
        labels = {
            'eval_atencion': '1. ATENCIÓN',
            'eval_amabilidad': '2. AMABILIDAD',
            'eval_solucion_inquietudes': '3. SOLUCIÓN DE INQUIETUDES',
            'eval_asesoria': '4. ASESORÍA',
            'eval_puntualidad': '5. PUNTUALIDAD',
            'eval_calidad_servicio': '6. CALIDAD DEL SERVICIO',
            'eval_oportunidad': '7. OPORTUNIDAD',
            'eval_cumplimiento_condiciones': '8. CUMPLIMIENTO DE CONDICIONES',
            'eval_solucion_problemas': '9. SOLUCIÓN DE PROBLEMAS',
            'eval_volveria_contratar': '10. NOS VOLVERÍA A CONTRATAR',
            'eval_nos_recomendaria': '11. NOS RECOMENDARÍA',
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

def generar_username(first_name, last_name, numero_documento=''):
    """
    Construye un identificador interno único para una persona SIN acceso al
    sistema (ayudantes). No es una credencial: nunca se muestra como usuario ni
    sirve para iniciar sesión; solo identifica el registro internamente.
    """
    base = slugify(numero_documento) or slugify(f"{first_name} {last_name}") or 'persona'
    base = base.replace('-', '.')[:140]
    username = base
    contador = 2
    while User.objects.filter(username=username).exists():
        username = f"{base}.{contador}"
        contador += 1
    return username


class PersonaSinAccesoForm(forms.ModelForm):
    """
    Alta/edición de una persona que NO accede a la plataforma (ayudantes): se
    registra únicamente para su expediente y para poder asignarla a las
    cuadrillas. No se le pide usuario ni contraseña; internamente la cuenta
    queda inactiva y sin contraseña utilizable.
    """
    grupo = forms.ModelChoiceField(
        queryset=Group.objects.all(), required=True,
        widget=forms.Select(attrs={'class': 'form-select'})
    )

    class Meta:
        model = User
        fields = ['first_name', 'last_name', 'email']
        labels = {
            'first_name': 'Nombres',
            'last_name': 'Apellidos',
            'email': 'Correo (opcional)',
        }
        widgets = {
            'first_name': forms.TextInput(attrs={'class': 'form-control'}),
            'last_name': forms.TextInput(attrs={'class': 'form-control'}),
            'email': forms.EmailInput(attrs={'class': 'form-control'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['first_name'].required = True
        self.fields['last_name'].required = True
        self.fields['email'].required = False
        if self.instance.pk:
            grupo_actual = self.instance.groups.first()
            if grupo_actual:
                self.fields['grupo'].initial = grupo_actual.pk

    def save(self, commit=True):
        usuario = super().save(commit=False)
        if not usuario.pk:
            # El número de documento viaja en el mismo POST (formulario de perfil).
            usuario.username = generar_username(
                usuario.first_name, usuario.last_name,
                self.data.get('numero_documento', ''),
            )
        # Sin acceso: contraseña inutilizable y cuenta inactiva.
        usuario.set_unusable_password()
        usuario.is_active = False
        if commit:
            usuario.save()
        return usuario


class PerfilPersonaForm(forms.ModelForm):
    """Datos personales de la persona (complementan la cuenta de usuario)."""
    class Meta:
        model = PerfilPersona
        fields = ['numero_documento', 'telefono', 'cargo', 'direccion']
        widgets = {
            'numero_documento': forms.TextInput(attrs={'class': 'form-control'}),
            'telefono': forms.TextInput(attrs={'class': 'form-control'}),
            'cargo': forms.TextInput(attrs={'class': 'form-control'}),
            'direccion': forms.TextInput(attrs={'class': 'form-control'}),
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



class RecorridoForm(forms.ModelForm):
    class Meta:
        model = Recorrido
        fields = ['fecha_recorrido', 'vehiculo', 'conductor', 'ayudante', 'descripcion']
        widgets = {
            'fecha_recorrido': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'vehiculo': forms.Select(attrs={'class': 'form-select'}),
            'conductor': forms.Select(attrs={'class': 'form-select'}),
            'ayudante': forms.Select(attrs={'class': 'form-select'}),
            'descripcion': forms.TextInput(attrs={'class': 'form-control'}),
        }
        labels = {
            'fecha_recorrido': 'Fecha del Recorrido',
            'vehiculo': 'Vehículo a Asignar',
            'conductor': 'Conductor a Asignar',
            'ayudante': 'Ayudante (Opcional)',
            'descripcion': 'Descripción (Opcional)',
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Filtramos para que solo se puedan seleccionar vehículos operativos
        self.fields['vehiculo'].queryset = Vehiculo.objects.filter(estado='OPERATIVO')
        
        # Filtramos para que solo se puedan seleccionar usuarios del grupo "Conductores"
        try:
            conductores_group = Group.objects.get(name='Conductores')
            self.fields['conductor'].queryset = conductores_group.user_set.all()
        except Group.DoesNotExist:
            self.fields['conductor'].queryset = User.objects.none()

        # Filtramos para que solo se puedan seleccionar usuarios del grupo "Ayudantes"
        try:
            ayudantes_group = Group.objects.get(name='Ayudantes')
            self.fields['ayudante'].queryset = ayudantes_group.user_set.all()
        except Group.DoesNotExist:
            self.fields['ayudante'].queryset = User.objects.none()



class ProgramacionForm(forms.ModelForm):
    """
    Cabecera + checklist operativo de la programación anticipada. Las cuadrillas
    (conductor/placa/ayudante) se manejan aparte en ProgramacionCuadrillaFormSet.
    """
    class Meta:
        model = Programacion
        fields = [
            'fecha', 'hora_ingreso_bodega', 'hora_servicio',
            'cliente', 'sede', 'direccion', 'correo_seguridad_social',
            'observaciones_servicio',
            'paleada',
            'responsable_sg',
            'exige_curso_alturas',
            'exige_curso_confinados',
            'nombre_contacto_recibe',
        ]
        widgets = {
            'fecha': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}, format='%Y-%m-%d'),
            'hora_ingreso_bodega': forms.TimeInput(attrs={'class': 'form-control', 'type': 'time'}, format='%H:%M'),
            'hora_servicio': forms.TimeInput(attrs={'class': 'form-control', 'type': 'time'}, format='%H:%M'),
            'cliente': forms.Select(attrs={'class': 'form-select'}),
            'sede': forms.TextInput(attrs={'class': 'form-control'}),
            'direccion': forms.TextInput(attrs={'class': 'form-control'}),
            'correo_seguridad_social': forms.EmailInput(attrs={'class': 'form-control'}),
            'observaciones_servicio': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
            'paleada': forms.Select(attrs={'class': 'form-select'}),
            'responsable_sg': forms.Select(attrs={'class': 'form-select'}),
            'exige_curso_alturas': forms.Select(attrs={'class': 'form-select'}),
            'exige_curso_confinados': forms.Select(attrs={'class': 'form-select'}),
            'nombre_contacto_recibe': forms.TextInput(attrs={'class': 'form-control'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # El date input HTML solo reconoce el valor si el formato es YYYY-MM-DD.
        self.fields['fecha'].input_formats = ['%Y-%m-%d']
        # Los desplegables con opciones vacías muestran "---------".
        for campo in ('paleada', 'responsable_sg'):
            self.fields[campo].empty_label = '---------'


class ProgramacionCuadrillaForm(forms.ModelForm):
    """Una fila CONDUCTOR / PLACA / AYUDANTE del formato, con sus novedades."""
    class Meta:
        model = ProgramacionCuadrilla
        fields = ['conductor', 'vehiculo', 'ayudante', 'ayudante_novedad']
        widgets = {
            'conductor': forms.Select(attrs={'class': 'form-select form-select-sm'}),
            'vehiculo': forms.Select(attrs={'class': 'form-select form-select-sm'}),
            'ayudante': forms.Select(attrs={'class': 'form-select form-select-sm'}),
            'ayudante_novedad': forms.Select(attrs={'class': 'form-select form-select-sm'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Solo vehículos operativos y usuarios por rol (igual que RecorridoForm).
        self.fields['vehiculo'].queryset = Vehiculo.objects.filter(estado='OPERATIVO')
        try:
            self.fields['conductor'].queryset = Group.objects.get(name='Conductores').user_set.all()
        except Group.DoesNotExist:
            self.fields['conductor'].queryset = User.objects.none()
        try:
            self.fields['ayudante'].queryset = Group.objects.get(name='Ayudantes').user_set.all()
        except Group.DoesNotExist:
            self.fields['ayudante'].queryset = User.objects.none()


# Formset en línea: hasta 3 cuadrillas nuevas por defecto (CONDUCTOR 1/2/3 del formato).
ProgramacionCuadrillaFormSet = forms.inlineformset_factory(
    Programacion, ProgramacionCuadrilla,
    form=ProgramacionCuadrillaForm,
    extra=3, can_delete=True,
)


class DocumentoPersonalForm(forms.ModelForm):
    """Carga de un documento al expediente de un conductor o ayudante."""
    class Meta:
        model = DocumentoPersonal
        fields = ['tipo', 'periodo', 'archivo', 'descripcion', 'fecha_vencimiento']
        widgets = {
            'tipo': forms.Select(attrs={'class': 'form-select'}),
            'periodo': forms.TextInput(attrs={'class': 'form-control', 'type': 'month'}),
            'archivo': forms.FileInput(attrs={'class': 'form-control'}),
            'descripcion': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Opcional'}),
            'fecha_vencimiento': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}, format='%Y-%m-%d'),
        }
        labels = {
            'periodo': 'Mes que cubre (solo seguridad social)',
            'fecha_vencimiento': 'Vencimiento (solo licencia)',
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['fecha_vencimiento'].input_formats = ['%Y-%m-%d']
        self.fields['descripcion'].required = False
        self.fields['fecha_vencimiento'].required = False
        self.fields['periodo'].required = False
        # Sugerir el mes actual (útil para la seguridad social).
        if not self.is_bound and not self.initial.get('periodo'):
            self.fields['periodo'].initial = datetime.date.today().strftime('%Y-%m')

    def clean(self):
        cleaned = super().clean()
        if cleaned.get('tipo') == 'SEGURIDAD_SOCIAL':
            # La seguridad social es mensual: si no indican el mes, se asume el actual.
            if not cleaned.get('periodo'):
                cleaned['periodo'] = datetime.date.today().strftime('%Y-%m')
        else:
            # El periodo solo aplica a seguridad social.
            cleaned['periodo'] = ''
        return cleaned


class ReporteFiltroForm(forms.Form):
    REPORT_CHOICES = [
        ('facturacion_cliente', 'Facturación por Cliente'),
        ('rendimiento_vehiculo', 'Rendimiento por Vehículo'),
        ('tendencia_mensual', 'Tendencia Mensual de Ingresos'),
    ]

    report_type = forms.ChoiceField(
        label="Tipo de Reporte",
        choices=REPORT_CHOICES,
        widget=forms.Select(attrs={'class': 'form-select'})
    )

    fecha_inicio = forms.DateField(
        label="Fecha de Inicio",
        widget=forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
        required=False # Lo hacemos opcional
    )
    fecha_fin = forms.DateField(
        label="Fecha de Fin",
        widget=forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
        required=False # Lo hacemos opcional
    )
    
    # Creamos una lista de años para el filtro de tendencia
    YEAR_CHOICES = [(r,r) for r in range(2023, datetime.date.today().year + 2)]
    año = forms.ChoiceField(
        label="Año",
        choices=YEAR_CHOICES,
        initial=datetime.date.today().year,
        widget=forms.Select(attrs={'class': 'form-select'}),
        required=False
    )



class PagoForm(forms.ModelForm):
    class Meta:
        model = Pago
        fields = ['fecha_pago', 'monto', 'metodo_pago', 'notas']
        widgets = {
            'fecha_pago': forms.DateTimeInput(attrs={'class': 'form-control', 'type': 'datetime-local'}),
            'monto': forms.NumberInput(attrs={'class': 'form-control'}),
            'metodo_pago': forms.Select(attrs={'class': 'form-select'}),
            'notas': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
        }


class EncuestaConductorForm(forms.ModelForm):
    """Encuesta de cierre (PESV + ambiental) que diligencia el conductor."""
    class Meta:
        model = EncuestaConductor
        fields = [
            'presento_fatiga', 'nivel_combustible',
            'tipo_residuo', 'dispositor_final',
            'riesgo_vial',
            'hubo_incidente', 'tipo_incidente', 'descripcion_incidente',
        ]
        widgets = {
            'presento_fatiga': forms.RadioSelect,
            'nivel_combustible': forms.RadioSelect,
            'tipo_residuo': forms.Select(attrs={'class': 'form-select'}),
            'dispositor_final': forms.Select(attrs={'class': 'form-select'}),
            'riesgo_vial': forms.Select(attrs={'class': 'form-select'}),
            'hubo_incidente': forms.RadioSelect,
            'tipo_incidente': forms.Select(attrs={'class': 'form-select'}),
            'descripcion_incidente': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Solo dispositores activos en el desplegable.
        self.fields['dispositor_final'].queryset = Dispositor.objects.filter(activo=True)
        # Estos campos solo se exigen si hubo incidente (ver clean()).
        self.fields['tipo_incidente'].required = False
        self.fields['descripcion_incidente'].required = False

    def clean(self):
        cleaned = super().clean()
        if cleaned.get('hubo_incidente') == 'SI' and not cleaned.get('tipo_incidente'):
            self.add_error(
                'tipo_incidente',
                'Debes seleccionar el tipo de evento cuando reportas un incidente.'
            )
        return cleaned