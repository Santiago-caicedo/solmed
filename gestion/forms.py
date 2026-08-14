from django import forms
from django.db.models import Q
from .models import Banco, Bascula, ContactoProveedor, Dispositor, DocumentoCorreoCliente, DocumentoDispositor, DocumentoInterno, DocumentoOrden, DocumentoPersonal, DocumentoProveedor, EncuestaConductor, FiltroAceite, Manifiesto, OrdenServicio, Pago, PerfilPersona, Programacion, ProgramacionCuadrilla, Proveedor, Recorrido, Sede, SitioInicio, Tercero, TipoResiduo, Vehiculo, Cliente
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

class FiltroAceiteForm(forms.ModelForm):
    """Registro de un cambio de filtro o aceite en el expediente del vehículo."""
    class Meta:
        model = FiltroAceite
        fields = ['tipo', 'fecha_cambio', 'cantidad', 'unidad',
                  'kilometraje', 'referencia', 'observaciones']
        widgets = {
            'tipo': forms.Select(attrs={'class': 'form-select form-select-sm'}),
            'fecha_cambio': forms.DateInput(attrs={'class': 'form-control form-control-sm', 'type': 'date'}, format='%Y-%m-%d'),
            'cantidad': forms.NumberInput(attrs={'class': 'form-control form-control-sm', 'min': '0.01', 'step': '0.01'}),
            'unidad': forms.Select(attrs={'class': 'form-select form-select-sm'}),
            'kilometraje': forms.NumberInput(attrs={'class': 'form-control form-control-sm', 'min': '0', 'placeholder': 'Opcional'}),
            'referencia': forms.TextInput(attrs={'class': 'form-control form-control-sm', 'placeholder': 'Ej: Mobil Delvac 15W-40'}),
            'observaciones': forms.TextInput(attrs={'class': 'form-control form-control-sm', 'placeholder': 'Opcional'}),
        }
        labels = {
            'fecha_cambio': 'Fecha del cambio',
            'kilometraje': 'Kilometraje',
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['fecha_cambio'].input_formats = ['%Y-%m-%d']
        self.fields['tipo'].choices = [('', '--- Elige filtro o aceite ---')] + list(FiltroAceite.TIPO_CHOICES)

    def clean_cantidad(self):
        cantidad = self.cleaned_data.get('cantidad')
        if cantidad is not None and cantidad <= 0:
            raise forms.ValidationError('La cantidad debe ser mayor que cero.')
        return cantidad


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


class SedeForm(forms.ModelForm):
    """Una sede (sucursal) del cliente."""
    class Meta:
        model = Sede
        fields = ['nombre', 'direccion', 'ciudad', 'telefono', 'persona_contacto', 'activa']
        widgets = {
            'nombre': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Ej: Sede Centro'}),
            'direccion': forms.TextInput(attrs={'class': 'form-control'}),
            'ciudad': forms.TextInput(attrs={'class': 'form-control'}),
            'telefono': forms.TextInput(attrs={'class': 'form-control'}),
            'persona_contacto': forms.TextInput(attrs={'class': 'form-control'}),
            'activa': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }


# Sedes del cliente (bloque dinámico en el formulario de cliente).
SedeFormSet = forms.inlineformset_factory(
    Cliente, Sede, form=SedeForm,
    extra=1, can_delete=True,
)


class TerceroForm(forms.ModelForm):
    """Un tercero (punto de recogida) del cliente."""
    class Meta:
        model = Tercero
        fields = ['nombre', 'direccion', 'ciudad', 'telefono', 'persona_contacto', 'activo']
        widgets = {
            'nombre': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Nombre del tercero'}),
            'direccion': forms.TextInput(attrs={'class': 'form-control'}),
            'ciudad': forms.TextInput(attrs={'class': 'form-control'}),
            'telefono': forms.TextInput(attrs={'class': 'form-control'}),
            'persona_contacto': forms.TextInput(attrs={'class': 'form-control'}),
            'activo': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }


# Terceros del cliente (bloque dinámico en el formulario de cliente).
TerceroFormSet = forms.inlineformset_factory(
    Cliente, Tercero, form=TerceroForm,
    extra=1, can_delete=True,
)


class DocumentoCorreoForm(forms.ModelForm):
    """
    Un documento del cliente que se adjunta al correo de sus órdenes: se escribe
    el nombre y luego se carga el archivo (como en el expediente del personal).
    """
    class Meta:
        model = DocumentoCorreoCliente
        fields = ['descripcion', 'archivo']
        widgets = {
            'descripcion': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Nombre del documento'}),
            'archivo': forms.FileInput(attrs={'class': 'form-control'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # El nombre es obligatorio (en las filas que se diligencien).
        self.fields['descripcion'].required = True


# Documentos del cliente para el correo (bloque dinámico: nombre + archivo por fila).
DocumentoCorreoFormSet = forms.inlineformset_factory(
    Cliente, DocumentoCorreoCliente, form=DocumentoCorreoForm,
    extra=1, can_delete=True,
)


class DocumentoOrdenForm(forms.ModelForm):
    class Meta:
        model = DocumentoOrden
        fields = ['archivo', 'descripcion']
        widgets = {
            'archivo': forms.FileInput(attrs={'class': 'form-control'}),
            'descripcion': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Ej: Foto de la carga, Remisión...'}),
        }
    


# --- Formularios para cada sección del Manifiesto ---


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
            'hora_salida_solmed', 'hora_llegada_empresa', 'hora_llegada_disposicion',
            'hora_llegada_solmed'
        ]
        widgets = {
            # --- Campos de Tiempos ---
            'tiempo_inicio_operativo': forms.TimeInput(attrs={'class': 'form-control', 'type': 'time'}, format='%H:%M'),
            'tiempo_final_operativo': forms.TimeInput(attrs={'class': 'form-control', 'type': 'time'}, format='%H:%M'),
            'tiempo_llegada_disposicion': forms.TimeInput(attrs={'class': 'form-control', 'type': 'time'}, format='%H:%M'), # NUEVO
            'tiempo_salida_disposicion': forms.TimeInput(attrs={'class': 'form-control', 'type': 'time'}, format='%H:%M'), # NUEVO
            
            # --- Tiempos de recorrido (antes kilómetros) ---
            'hora_salida_solmed': forms.TimeInput(attrs={'class': 'form-control', 'type': 'time'}, format='%H:%M'),
            'hora_llegada_empresa': forms.TimeInput(attrs={'class': 'form-control', 'type': 'time'}, format='%H:%M'),
            'hora_llegada_disposicion': forms.TimeInput(attrs={'class': 'form-control', 'type': 'time'}, format='%H:%M'),
            'hora_llegada_solmed': forms.TimeInput(attrs={'class': 'form-control', 'type': 'time'}, format='%H:%M'),
        }
        labels = {
            'tiempo_llegada_disposicion': 'H. Llegada sitio Disposición', # NUEVO
            'tiempo_salida_disposicion': 'H. Salida sitio Disposición', # NUEVO
            'hora_llegada_solmed': 'Llegada SolMed',
        }

class NovedadOperacionalForm(forms.Form):
    """
    Una fila del bloque NOVEDADES OPERACIONALES: la casilla, su observación y
    sus horas. Es un Form suelto (no ModelForm) porque las filas son fijas: se
    dibujan las 12 del formato y solo se guardan las marcadas.
    """
    marcada = forms.BooleanField(
        required=False, widget=forms.CheckboxInput(attrs={'class': 'form-check-input'}))
    observacion = forms.CharField(
        required=False, max_length=255,
        widget=forms.TextInput(attrs={'class': 'form-control form-control-sm',
                                      'placeholder': 'Observaciones'}))
    hora_inicio = forms.TimeField(
        required=False, input_formats=['%H:%M'],
        widget=forms.TimeInput(attrs={'class': 'form-control form-control-sm',
                                      'type': 'time'}, format='%H:%M'))
    hora_final = forms.TimeField(
        required=False, input_formats=['%H:%M'],
        widget=forms.TimeInput(attrs={'class': 'form-control form-control-sm',
                                      'type': 'time'}, format='%H:%M'))

    def tiene_datos(self):
        """¿Vale la pena guardarla? (marcada o con algo escrito)"""
        d = self.cleaned_data
        return bool(d.get('marcada') or d.get('observacion')
                    or d.get('hora_inicio') or d.get('hora_final'))


class MedidaACPMForm(forms.Form):
    """Una casilla del bloque CONTROL DE ACPM: la medida y su foto."""
    medida = forms.CharField(
        required=False, max_length=50,
        widget=forms.TextInput(attrs={'class': 'form-control form-control-sm',
                                      'placeholder': 'Medida'}))
    foto = forms.ImageField(
        required=False,
        widget=forms.ClearableFileInput(attrs={'class': 'form-control form-control-sm',
                                               'accept': 'image/*'}))


class ManifiestoPaso4Form(forms.ModelForm):
    """
    Cierre del acta. El RESPONSABLE EMPRESA es el conductor asignado, así que
    no se pide: se copia del recorrido al cerrar (ver GenerarManifiestoView).
    Aquí el conductor solo escribe las observaciones.
    """
    class Meta:
        model = Manifiesto
        fields = ['observaciones']
        widgets = {
            'observaciones': forms.Textarea(attrs={
                'class': 'form-control', 'rows': 4,
                'placeholder': 'Novedades del servicio, algo que el cliente deba saber…',
            }),
        }
        labels = {'observaciones': 'Observaciones del día'}

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

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # En el modelo las calificaciones permiten NULL, así que el ModelForm
        # las dejaba opcionales: el cliente podía firmar sin calificar nada.
        # La encuesta exige responder las 11 preguntas.
        for campo in self.fields.values():
            campo.required = True


# Roles que dan acceso más allá del módulo de Personal. Talento Humano no
# puede repartirlos: si no, podría crearse a sí mismo un usuario Administrador.
ROLES_DE_GESTION = ('Administradores', 'Asesores', 'Planificadores')


def roles_asignables(usuario):
    """
    Los roles que ese usuario puede otorgar. Gestión los otorga todos; Talento
    Humano, todos MENOS los de gestión (no puede subir a nadie —ni a sí mismo—
    por encima de su propio alcance).
    """
    todos = Group.objects.all()
    if usuario is None or not usuario.is_authenticated:
        return todos
    es_gestion = (usuario.is_superuser
                  or usuario.groups.filter(
                      name__in=('Administradores', 'Asesores')).exists())
    if es_gestion:
        return todos
    return todos.exclude(name__in=ROLES_DE_GESTION)


class RolLimitadoMixin:
    """
    Recorta el desplegable de rol según quién esté creando o editando. Al ser
    un ModelChoiceField, la restricción también se aplica en el servidor: un
    POST manipulado con un rol fuera de la lista no valida.
    """
    def __init__(self, *args, autor=None, **kwargs):
        super().__init__(*args, **kwargs)
        if autor is not None:
            self.fields['grupo'].queryset = roles_asignables(autor)


class CrearUsuarioForm(RolLimitadoMixin, UserCreationForm):
    email = forms.EmailField(
        label="Correo electrónico", required=True,
        widget=forms.EmailInput(attrs={'class': 'form-control'})
    )
    first_name = forms.CharField(
        label="Nombres", required=True,
        widget=forms.TextInput(attrs={'class': 'form-control'})
    )
    last_name = forms.CharField(
        label="Apellidos", required=True,
        widget=forms.TextInput(attrs={'class': 'form-control'})
    )
    grupo = forms.ModelChoiceField(
        label="Rol", queryset=Group.objects.all(), required=True,
        widget=forms.Select(attrs={'class': 'form-select'})
    )

    class Meta(UserCreationForm.Meta):
        model = User
        fields = UserCreationForm.Meta.fields + ('first_name', 'last_name', 'email')
        widgets = {
            'username': forms.TextInput(attrs={'class': 'form-control'}),
            'password1': forms.PasswordInput(attrs={'class': 'form-control'}),
            'password2': forms.PasswordInput(attrs={'class': 'form-control'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Etiquetas y ayudas en español (las de UserCreationForm vienen en inglés).
        self.fields['username'].label = "Usuario para iniciar sesión"
        self.fields['username'].help_text = (
            "Hasta 150 caracteres. Solo letras, números y los signos @/./+/-/_"
        )
        self.fields['password1'].label = "Contraseña"
        self.fields['password1'].help_text = (
            "Mínimo 8 caracteres. No puede ser solo números ni una contraseña común."
        )
        self.fields['password2'].label = "Confirmar contraseña"
        self.fields['password2'].help_text = "Escribe la misma contraseña para verificarla."

def _nombre_persona(usuario):
    """
    Etiqueta para los desplegables de personal: el nombre completo, y solo si no
    lo tiene, el identificador de la cuenta. Evita mostrar la cédula (que es el
    username autogenerado de los ayudantes sin acceso).
    """
    return usuario.get_full_name() or usuario.username


def _mostrar_nombres(campo):
    """Hace que un ModelChoiceField de usuarios muestre el nombre, no el username."""
    campo.label_from_instance = _nombre_persona


def _csv_a_lista(csv):
    """Convierte 'A,B' en ['A', 'B'] (para novedades multi-selección)."""
    return [c for c in (csv or '').split(',') if c]


def personal_activo_del_grupo(nombre_grupo):
    """
    Usuarios ACTIVOS (no retirados) de un grupo, para los desplegables de
    asignación. Los retirados quedan fuera de todas las actividades del core.
    """
    try:
        grupo = Group.objects.get(name=nombre_grupo)
    except Group.DoesNotExist:
        return User.objects.none()
    return grupo.user_set.exclude(perfil__retirado=True)


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


class PersonaSinAccesoForm(RolLimitadoMixin, forms.ModelForm):
    """
    Alta/edición de una persona que NO accede a la plataforma (ayudantes): se
    registra únicamente para su expediente y para poder asignarla a las
    cuadrillas. No se le pide usuario ni contraseña; internamente la cuenta
    queda inactiva y sin contraseña utilizable.
    """
    grupo = forms.ModelChoiceField(
        label="Rol", queryset=Group.objects.all(), required=True,
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


class ActualizarUsuarioForm(RolLimitadoMixin, forms.ModelForm):
    grupo = forms.ModelChoiceField(
        label="Rol", queryset=Group.objects.all(), required=True,
        widget=forms.Select(attrs={'class': 'form-select'})
    )

    class Meta:
        model = User
        fields = ['username', 'first_name', 'last_name', 'email', 'is_active']
        labels = {
            'username': 'Usuario para iniciar sesión',
            'first_name': 'Nombres',
            'last_name': 'Apellidos',
            'email': 'Correo electrónico',
            'is_active': 'Cuenta activa (puede iniciar sesión)',
        }
        help_texts = {
            'username': 'Hasta 150 caracteres. Solo letras, números y los signos @/./+/-/_',
            'is_active': '',
        }
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
        fields = ['fecha_recorrido', 'vehiculo', 'conductor', 'ayudante', 'ayudante2', 'descripcion']
        widgets = {
            'fecha_recorrido': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'vehiculo': forms.Select(attrs={'class': 'form-select'}),
            'conductor': forms.Select(attrs={'class': 'form-select'}),
            'ayudante': forms.Select(attrs={'class': 'form-select'}),
            'ayudante2': forms.Select(attrs={'class': 'form-select'}),
            'descripcion': forms.TextInput(attrs={'class': 'form-control'}),
        }
        labels = {
            'fecha_recorrido': 'Fecha del Recorrido',
            'vehiculo': 'Vehículo a Asignar',
            'conductor': 'Conductor a Asignar',
            'ayudante': 'Ayudante (Opcional)',
            'ayudante2': 'Segundo ayudante (Opcional)',
            'descripcion': 'Descripción (Opcional)',
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Filtramos para que solo se puedan seleccionar vehículos operativos
        self.fields['vehiculo'].queryset = Vehiculo.objects.filter(estado='OPERATIVO')

        # Solo conductores/ayudantes ACTIVOS (los retirados no se pueden asignar).
        self.fields['conductor'].queryset = personal_activo_del_grupo('Conductores')
        for campo in ('ayudante', 'ayudante2'):
            self.fields[campo].queryset = personal_activo_del_grupo('Ayudantes')
            _mostrar_nombres(self.fields[campo])

        # Mostrar el nombre en los desplegables, no el username (cédula del ayudante).
        _mostrar_nombres(self.fields['conductor'])



class ProgramacionForm(forms.ModelForm):
    """
    Cabecera + checklist operativo de la programación anticipada. Las cuadrillas
    (conductor/placa/ayudante) se manejan aparte en ProgramacionCuadrillaFormSet.
    """
    # Los cursos exigidos al ayudante se manejan como interruptores Sí/No.
    # En el modelo siguen guardándose como 'SI'/'NO' (ver clean_* más abajo).
    CAMPOS_SWITCH = ('exige_curso_alturas', 'exige_curso_confinados')

    exige_curso_alturas = forms.BooleanField(
        required=False, label="¿El ayudante debe tener curso de alturas?",
        widget=forms.CheckboxInput(attrs={'class': 'form-check-input', 'role': 'switch'})
    )
    exige_curso_confinados = forms.BooleanField(
        required=False, label="¿El ayudante debe tener curso de espacios confinados?",
        widget=forms.CheckboxInput(attrs={'class': 'form-check-input', 'role': 'switch'})
    )

    # El sitio de inicio y el residuo salen de catálogos que se agregan y se
    # eliminan desde el popup "Administrar" del propio formulario (igual que
    # las básculas), así que aquí solo van sus desplegables.

    # Cuando NO hay disposición final: a dónde queda el contenido (trasiegos /
    # dejar carro cargado). Se guarda en el mismo campo dispositor_final.
    # Eventualidad: crear la programación SIN avisar por correo al personal
    # (no se guarda en el modelo; solo aplica al momento de crear).
    sin_correos = forms.BooleanField(
        required=False,
        label="No enviar el aviso por correo al conductor ni a los ayudantes",
        widget=forms.CheckboxInput(attrs={'class': 'form-check-input', 'role': 'switch'}),
        help_text="Todo se crea igual (orden, recorrido, enlaces); solo se omite "
                  "el correo. Después puedes reenviarlo desde el expediente de la orden.",
    )

    destino_sin_disposicion = forms.ModelChoiceField(
        queryset=Dispositor.objects.none(), required=False,
        label="¿Dónde queda el contenido?",
        widget=forms.Select(attrs={'class': 'form-select'}),
        empty_label='--- Elige el destino ---',
        help_text="Si el servicio pasa sin dejar contenido (p. ej. sondeo o "
                  "lavado), elige «NO HAY DISPOSICIÓN».",
    )

    class Meta:
        model = Programacion
        fields = [
            'fecha', 'hora_ingreso_bodega', 'sitio_inicio', 'hora_servicio',
            'cliente', 'sede_cliente', 'tercero', 'direccion',
            'observaciones_servicio',
            'paleada',
            'bascula', 'bascula_sitio',
            'registro_fotografico',
            'responsable_sg',
            'requiere_disposicion_final',
            'dispositor_final',
            'trasiego_vehiculo',
            'exige_curso_alturas',
            'exige_curso_confinados',
            'nombre_contacto_recibe',
        ] + list(Programacion.CAMPOS_INSTRUCCIONES_ACTA)
        widgets = {
            'fecha': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}, format='%Y-%m-%d'),
            'hora_ingreso_bodega': forms.TimeInput(attrs={'class': 'form-control', 'type': 'time'}, format='%H:%M'),
            'sitio_inicio': forms.Select(attrs={'class': 'form-select'}),
            'hora_servicio': forms.TimeInput(attrs={'class': 'form-control', 'type': 'time'}, format='%H:%M'),
            'cliente': forms.Select(attrs={'class': 'form-select'}),
            'sede_cliente': forms.Select(attrs={'class': 'form-select'}),
            'tercero': forms.Select(attrs={'class': 'form-select'}),
            'direccion': forms.TextInput(attrs={'class': 'form-control'}),
            'observaciones_servicio': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
            'paleada': forms.Select(attrs={'class': 'form-select'}),
            'bascula_sitio': forms.Select(attrs={'class': 'form-select'}),
            'bascula': forms.Select(attrs={'class': 'form-select'}),
            'registro_fotografico': forms.Select(attrs={'class': 'form-select'}),
            'responsable_sg': forms.Select(attrs={'class': 'form-select'}),
            'requiere_disposicion_final': forms.Select(attrs={'class': 'form-select'}),
            'dispositor_final': forms.Select(attrs={'class': 'form-select'}),
            'trasiego_vehiculo': forms.Select(attrs={'class': 'form-select'}),
            'nombre_contacto_recibe': forms.TextInput(attrs={'class': 'form-control'}),
            # Caracterización del residuo: desplegable alimentado por el catálogo
            # TipoResiduo (el valor guardado sigue siendo el NOMBRE, ver models).
            'transporte_tipo': forms.Select(attrs={'class': 'form-select form-select-sm'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # El date input HTML solo reconoce el valor si el formato es YYYY-MM-DD.
        self.fields['fecha'].input_formats = ['%Y-%m-%d']
        # Los desplegables con opciones vacías muestran "---------".
        for campo in ('paleada', 'bascula', 'registro_fotografico', 'responsable_sg',
                      'requiere_disposicion_final'):
            self.fields[campo].empty_label = '---------'
        # Disposición SÍ -> solo proveedores externos; NO -> destinos internos
        # (trasiegos / dejar carro cargado). Ambos parametrizables en el admin.
        self.fields['dispositor_final'].queryset = Dispositor.objects.filter(
            activo=True, tipo='PROVEEDOR')
        self.fields['dispositor_final'].empty_label = '--- Elige el proveedor ---'
        self.fields['destino_sin_disposicion'].queryset = Dispositor.objects.filter(
            activo=True, tipo='INTERNO')
        self.fields['trasiego_vehiculo'].queryset = Vehiculo.objects.filter(estado='OPERATIVO')
        self.fields['trasiego_vehiculo'].empty_label = '--- Elige la placa ---'
        # Al editar: si lo guardado es un destino interno, va en el campo de "No".
        if self.instance.pk and self.instance.dispositor_final_id \
                and self.instance.dispositor_final.tipo == 'INTERNO':
            self.initial['destino_sin_disposicion'] = self.instance.dispositor_final_id
            self.initial['dispositor_final'] = None
        # El interruptor se marca solo si el valor guardado es 'SI'
        # (sin esto, 'NO' se leería como texto no vacío = encendido).
        for campo in self.CAMPOS_SWITCH:
            self.initial[campo] = getattr(self.instance, campo, '') == 'SI'

        # Sede: solo las sedes activas del cliente elegido. OJO con el orden: en
        # un POST manda el cliente DEL FORMULARIO (al editar se puede cambiar de
        # cliente, y filtrar por el guardado rechazaba la sede nueva como si no
        # se hubiera elegido); sin POST, el del borrador que se edita.
        sedes = Sede.objects.filter(activa=True).select_related('cliente')
        cliente_actual = self._cliente_en_juego()
        if cliente_actual:
            sedes = sedes.filter(cliente_id=cliente_actual)
        self.fields['sede_cliente'].queryset = sedes
        self.fields['sede_cliente'].empty_label = '--- Sin sede específica ---'
        self.fields['sede_cliente'].label = 'Sede'

        # Básculas activas (+ la guardada, aunque esté inactiva, al editar).
        basculas = Q(activo=True)
        if self.instance.pk and self.instance.bascula_sitio_id:
            basculas |= Q(pk=self.instance.bascula_sitio_id)
        self.fields['bascula_sitio'].queryset = Bascula.objects.filter(basculas)
        self.fields['bascula_sitio'].empty_label = '--- Elige la báscula ---'

        # Residuos del catálogo (activos) + el valor ya guardado, para no perderlo
        # al editar si alguien lo desactivó o se escribió a mano antes.
        nombres = list(TipoResiduo.objects.filter(activo=True).values_list('nombre', flat=True))
        guardado = (self.instance.transporte_tipo or '').strip() if self.instance else ''
        if guardado and guardado not in nombres:
            nombres.append(guardado)
        self.fields['transporte_tipo'].widget.choices = (
            [('', '--- Elige el residuo ---')] + [(n, n) for n in sorted(nombres)]
        )

        # Sitios de inicio activos (más el guardado, aunque esté inactivo, para
        # que al editar no se pierda la selección).
        sitios = Q(activo=True)
        if self.instance.pk and self.instance.sitio_inicio_id:
            sitios |= Q(pk=self.instance.sitio_inicio_id)
        self.fields['sitio_inicio'].queryset = SitioInicio.objects.filter(sitios)
        self.fields['sitio_inicio'].empty_label = '--- Elige el sitio ---'

        # Tercero: misma lógica (y mismo orden) que la sede.
        terceros = Tercero.objects.filter(activo=True).select_related('cliente')
        if cliente_actual:
            terceros = terceros.filter(cliente_id=cliente_actual)
        self.fields['tercero'].queryset = terceros
        self.fields['tercero'].empty_label = '--- Sin tercero ---'
        self.fields['tercero'].label = 'Tercero'

        # --- Instrucciones del servicio (primera parte del acta) ---
        # Casillas de qué se hace + su cantidad. Es lo que antes llenaba el
        # conductor; ahora lo define el asesor y se copia al acta.
        checks_instrucciones = (
            'succ_canecas', 'succ_pozos_inspeccion', 'succ_pozos_septicos',
            'succ_tanques', 'succ_trampas_grasa', 'sond_red_aguas_lluvias',
            'sond_red_aguas_negras', 'sond_red_acueducto', 'sond_correctivo',
            'sond_preventivo',
        )
        for campo in Programacion.CAMPOS_INSTRUCCIONES_ACTA:
            widget = self.fields[campo].widget
            if campo in checks_instrucciones:
                widget.attrs['class'] = 'form-check-input'
            else:
                widget.attrs.setdefault('class', 'form-control form-control-sm')
                if campo.endswith('_cant'):
                    widget.attrs.setdefault('placeholder', 'Ton/M³ · H/ML · Cant.')

    def _cliente_en_juego(self):
        """
        El cliente que rige los desplegables dependientes (sede y tercero): el
        del POST si lo hay (puede cambiarse al editar), si no el ya guardado.
        None = sin filtro (la pertenencia igual la valida clean()).
        """
        if self.data:
            try:
                return int(self.data.get('cliente'))
            except (TypeError, ValueError):
                return None
        if self.instance.pk:
            return self.instance.cliente_id
        return None

    def _switch_a_si_no(self, campo):
        return 'SI' if self.cleaned_data.get(campo) else 'NO'

    def clean_exige_curso_alturas(self):
        return self._switch_a_si_no('exige_curso_alturas')

    def clean_exige_curso_confinados(self):
        return self._switch_a_si_no('exige_curso_confinados')

    def clean(self):
        cleaned = super().clean()

        cliente = cleaned.get('cliente')
        sede = cleaned.get('sede_cliente')
        tercero = cleaned.get('tercero')
        if cliente and sede and sede.cliente_id != cliente.id:
            self.add_error('sede_cliente', 'Esa sede no pertenece al cliente seleccionado.')
        if cliente and tercero and tercero.cliente_id != cliente.id:
            self.add_error('tercero', 'Ese tercero no pertenece al cliente seleccionado.')
        # El servicio ocurre en un solo lugar: sede o tercero, no ambos.
        if sede and tercero:
            self.add_error('tercero', 'Elige la sede o el tercero, pero no ambos.')
        # Si el cliente tiene sedes, exigir que se elija una (salvo que el
        # servicio se recoja donde un tercero).
        if cliente and not sede and not tercero and cliente.sedes.filter(activa=True).exists():
            self.add_error('sede_cliente', 'Este cliente tiene sedes: elige a cuál corresponde el servicio.')

        # --- Báscula ---
        # Sí ('PESAN') -> hay que decir en cuál; otra respuesta -> se limpia.
        if cleaned.get('bascula') == 'PESAN':
            if not cleaned.get('bascula_sitio'):
                self.add_error('bascula_sitio', 'Indica en cuál báscula se pesará.')
        else:
            cleaned['bascula_sitio'] = None

        # --- Disposición final ---
        # SÍ  -> proveedor externo obligatorio (el contenido se dispone).
        # NO  -> destino interno obligatorio (queda en camión o tanques SOLMED);
        #        se guarda en el mismo dispositor_final. Si es trasiego a placa,
        #        también la placa destino.
        requiere = cleaned.get('requiere_disposicion_final')
        if requiere == 'SI':
            if not cleaned.get('dispositor_final'):
                self.add_error('dispositor_final', 'Indica con cuál proveedor se hará la disposición final.')
            cleaned['trasiego_vehiculo'] = None
        elif requiere == 'NO':
            destino = cleaned.get('destino_sin_disposicion')
            if not destino:
                self.add_error(
                    'destino_sin_disposicion',
                    'Indica dónde queda el contenido. Si el servicio pasa sin dejar nada '
                    'pendiente, elige «NO HAY DISPOSICIÓN».')
            cleaned['dispositor_final'] = destino
            if destino and destino.nombre == Dispositor.TRASIEGO_PLACA:
                if not cleaned.get('trasiego_vehiculo'):
                    self.add_error('trasiego_vehiculo', 'Indica a cuál placa se trasiega el contenido.')
            else:
                cleaned['trasiego_vehiculo'] = None
        else:
            cleaned['dispositor_final'] = None
            cleaned['trasiego_vehiculo'] = None
        return cleaned


class NovedadesCheckbox(forms.CheckboxSelectMultiple):
    """
    Checkboxes de novedades que marcan cuáles le exigen al ayudante subir una
    FOTO: les pone `data-foto="1"` para que la plantilla las distinga a la vista
    (ver ProgramacionCuadrilla.NOVEDADES_CON_FOTO).
    """
    def create_option(self, name, value, *args, **kwargs):
        option = super().create_option(name, value, *args, **kwargs)
        if str(value) in ProgramacionCuadrilla.NOVEDADES_CON_FOTO:
            option['attrs']['data-foto'] = '1'
        return option


class ProgramacionCuadrillaForm(forms.ModelForm):
    """
    Personal y vehículo del servicio: UNA cuadrilla por programación (una orden =
    un vehículo = un recorrido = un acta). Conductor y placa son obligatorios;
    puede llevar hasta dos ayudantes. Las novedades de cada ayudante son de
    selección múltiple (se guardan como CSV en el modelo). Formulario único con
    prefijo 'cuadrilla' (no como formset).
    """
    ayudante_novedad = forms.MultipleChoiceField(
        choices=ProgramacionCuadrilla.NOVEDAD_CHOICES, required=False,
        widget=NovedadesCheckbox, label="Novedades del ayudante"
    )
    ayudante2_novedad = forms.MultipleChoiceField(
        choices=ProgramacionCuadrilla.NOVEDAD_CHOICES, required=False,
        widget=NovedadesCheckbox, label="Novedades del segundo ayudante"
    )

    class Meta:
        model = ProgramacionCuadrilla
        # Las novedades se manejan aparte (CSV); no van en Meta.fields.
        fields = ['conductor', 'vehiculo', 'ayudante', 'ayudante2',
                  'apoya_disposicion_vehiculo', 'ayudante2_apoya_disposicion_vehiculo']
        widgets = {
            'conductor': forms.Select(attrs={'class': 'form-select'}),
            'vehiculo': forms.Select(attrs={'class': 'form-select'}),
            'ayudante': forms.Select(attrs={'class': 'form-select'}),
            'ayudante2': forms.Select(attrs={'class': 'form-select'}),
            'apoya_disposicion_vehiculo': forms.Select(attrs={'class': 'form-select'}),
            'ayudante2_apoya_disposicion_vehiculo': forms.Select(attrs={'class': 'form-select'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Solo vehículos operativos y personal ACTIVO (retirados excluidos).
        self.fields['vehiculo'].queryset = Vehiculo.objects.filter(estado='OPERATIVO')
        self.fields['conductor'].queryset = personal_activo_del_grupo('Conductores')
        for campo in ('ayudante', 'ayudante2'):
            self.fields[campo].queryset = personal_activo_del_grupo('Ayudantes')
            _mostrar_nombres(self.fields[campo])
        # Placa de la que se apoya la disposición (solo vehículos operativos).
        for campo in ('apoya_disposicion_vehiculo', 'ayudante2_apoya_disposicion_vehiculo'):
            self.fields[campo].queryset = Vehiculo.objects.filter(estado='OPERATIVO')
            self.fields[campo].empty_label = '--- Elige la placa ---'
        # Conductor y vehículo son obligatorios (la orden necesita ambos).
        self.fields['conductor'].required = True
        self.fields['vehiculo'].required = True
        self.fields['vehiculo'].empty_label = '--- Elige la placa ---'
        self.fields['conductor'].empty_label = '--- Elige el conductor ---'
        self.fields['ayudante'].empty_label = '--- Sin ayudante ---'
        self.fields['ayudante2'].empty_label = '--- Sin segundo ayudante ---'
        _mostrar_nombres(self.fields['conductor'])
        # Novedades: valores iniciales desde el CSV guardado.
        if self.instance and self.instance.pk:
            self.initial['ayudante_novedad'] = _csv_a_lista(self.instance.ayudante_novedad)
            self.initial['ayudante2_novedad'] = _csv_a_lista(self.instance.ayudante2_novedad)

    def clean(self):
        cleaned = super().clean()
        # Un mismo ayudante no puede ir dos veces.
        a1, a2 = cleaned.get('ayudante'), cleaned.get('ayudante2')
        if a1 and a2 and a1 == a2:
            self.add_error('ayudante2', 'El segundo ayudante no puede ser el mismo que el primero.')
        # Novedades solo si hay ese ayudante.
        if not a1:
            cleaned['ayudante_novedad'] = []
        if not a2:
            cleaned['ayudante2_novedad'] = []

        # "Apoya disposición de:" requiere indicar la placa; si no se marca, se limpia.
        apoya = ProgramacionCuadrilla.APOYA_DISPOSICION
        for campo_nov, campo_veh in (
            ('ayudante_novedad', 'apoya_disposicion_vehiculo'),
            ('ayudante2_novedad', 'ayudante2_apoya_disposicion_vehiculo'),
        ):
            if apoya in (cleaned.get(campo_nov) or []):
                if not cleaned.get(campo_veh):
                    self.add_error(campo_veh, 'Indica de cuál vehículo se apoya la disposición.')
            else:
                cleaned[campo_veh] = None
        return cleaned

    def save(self, commit=True):
        obj = super().save(commit=False)
        obj.ayudante_novedad = ','.join(self.cleaned_data.get('ayudante_novedad', []))
        obj.ayudante2_novedad = ','.join(self.cleaned_data.get('ayudante2_novedad', []))
        if commit:
            obj.save()
        return obj


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
            'periodo': 'Mes que cubre (opcional)',
            'fecha_vencimiento': 'Vigente hasta',
        }

    # Documentos cuya validez se controla por la vigencia (fecha de vencimiento)
    # que se pone a mano al cargarlos. La seguridad social ya NO depende del mes.
    TIPOS_REQUIEREN_VIGENCIA = ('SEGURIDAD_SOCIAL',)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['fecha_vencimiento'].input_formats = ['%Y-%m-%d']
        self.fields['descripcion'].required = False
        self.fields['fecha_vencimiento'].required = False
        self.fields['periodo'].required = False

    def clean(self):
        cleaned = super().clean()
        tipo = cleaned.get('tipo')
        # La seguridad social ahora se controla por su vigencia (manual), no por
        # el mes: exigimos la fecha "vigente hasta" al cargarla.
        if tipo in self.TIPOS_REQUIEREN_VIGENCIA and not cleaned.get('fecha_vencimiento'):
            self.add_error(
                'fecha_vencimiento',
                'Indica hasta qué fecha está vigente este documento.'
            )
        # El periodo (mes) es informativo y solo aplica a la seguridad social.
        if tipo != 'SEGURIDAD_SOCIAL':
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
    """
    Encuesta de cierre (PESV) que diligencia el conductor: siete preguntas de
    Sí/No sobre seguridad vial y su salud. La última abre el tipo de evento y su
    descripción cuando la respuesta es Sí.
    """
    class Meta:
        model = EncuestaConductor
        fields = list(EncuestaConductor.CAMPOS_PREGUNTAS) + [
            'tipo_incidente', 'descripcion_incidente',
        ]
        widgets = {
            **{campo: forms.RadioSelect for campo in EncuestaConductor.CAMPOS_PREGUNTAS},
            'tipo_incidente': forms.Select(attrs={'class': 'form-select'}),
            'descripcion_incidente': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Las siete preguntas son obligatorias; el detalle del evento solo se
        # exige si se reportó una condición de riesgo (ver clean()).
        for campo in EncuestaConductor.CAMPOS_PREGUNTAS:
            self.fields[campo].required = True
        self.fields['tipo_incidente'].required = False
        self.fields['descripcion_incidente'].required = False

    def preguntas(self):
        """Los campos de las siete preguntas, numerados, para la plantilla."""
        return [
            {'numero': i, 'campo': self[campo]}
            for i, campo in enumerate(EncuestaConductor.CAMPOS_PREGUNTAS, start=1)
        ]

    def clean(self):
        cleaned = super().clean()
        if cleaned.get('condicion_riesgo') == 'SI':
            if not cleaned.get('tipo_incidente'):
                self.add_error(
                    'tipo_incidente',
                    'Indica el tipo de evento cuando reportas una condición de riesgo.'
                )
            if not (cleaned.get('descripcion_incidente') or '').strip():
                self.add_error(
                    'descripcion_incidente',
                    'Describe brevemente lo ocurrido.'
                )
        else:
            # Sin condición de riesgo no se guarda detalle del evento.
            cleaned['tipo_incidente'] = ''
            cleaned['descripcion_incidente'] = ''
        return cleaned

class DispositorForm(forms.ModelForm):
    """
    Alta/edición de un proveedor de disposición final desde su panel. El tipo
    NO se pide: el panel solo gestiona proveedores externos (los destinos
    internos especiales — trasiegos, dejar cargado — se siembran por migración).
    """
    class Meta:
        model = Dispositor
        fields = ['nombre', 'descripcion', 'activo']
        labels = {
            'nombre': 'Nombre del proveedor',
            'descripcion': 'Descripción',
            'activo': 'Activo (aparece en los desplegables)',
        }
        widgets = {
            'nombre': forms.TextInput(attrs={'class': 'form-control'}),
            'descripcion': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Tipo de planta o celda, licencia ambiental, ciudad…',
            }),
            'activo': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }


class DocumentoDispositorForm(forms.ModelForm):
    """Carga de un documento al expediente de un proveedor (dispositor)."""
    class Meta:
        model = DocumentoDispositor
        fields = ['tipo', 'archivo', 'descripcion']
        widgets = {
            'tipo': forms.HiddenInput(),
            'archivo': forms.FileInput(attrs={'class': 'form-control form-control-sm'}),
            'descripcion': forms.TextInput(attrs={'class': 'form-control form-control-sm', 'placeholder': 'Detalle (opcional)'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['descripcion'].required = False


class ProveedorForm(forms.ModelForm):
    """
    Alta/edición de un proveedor general (bienes y servicios). Los contactos
    van aparte, en ContactoProveedorFormSet; el expediente se carga en la ficha.
    """
    class Meta:
        model = Proveedor
        fields = ['nit', 'razon_social', 'nombre_comercial', 'direccion',
                  'banco', 'tipo_cuenta', 'numero_cuenta', 'activo']
        widgets = {
            'nit': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Ej: 900123456-7'}),
            'razon_social': forms.TextInput(attrs={'class': 'form-control'}),
            'nombre_comercial': forms.TextInput(attrs={'class': 'form-control'}),
            'direccion': forms.TextInput(attrs={'class': 'form-control'}),
            'banco': forms.Select(attrs={'class': 'form-select'}),
            'tipo_cuenta': forms.Select(attrs={'class': 'form-select'}),
            'numero_cuenta': forms.TextInput(attrs={'class': 'form-control'}),
            'activo': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Solo bancos activos, sin sacar del desplegable el que ya tenga puesto.
        bancos = Banco.objects.filter(activo=True)
        if self.instance.pk and self.instance.banco_id:
            bancos = Banco.objects.filter(Q(activo=True) | Q(pk=self.instance.banco_id))
        self.fields['banco'].queryset = bancos
        self.fields['banco'].empty_label = 'Sin banco'


class ContactoProveedorForm(forms.ModelForm):
    """Una fila de contacto del proveedor. Fila vacía = sin contacto."""
    class Meta:
        model = ContactoProveedor
        fields = ['nombre', 'area', 'correo', 'celular']
        widgets = {
            'nombre': forms.TextInput(attrs={'class': 'form-control form-control-sm', 'placeholder': 'Nombre'}),
            'area': forms.TextInput(attrs={'class': 'form-control form-control-sm', 'placeholder': 'Área o cargo'}),
            'correo': forms.EmailInput(attrs={'class': 'form-control form-control-sm', 'placeholder': 'Correo'}),
            'celular': forms.TextInput(attrs={'class': 'form-control form-control-sm', 'placeholder': 'Celular'}),
        }

    def clean(self):
        datos = super().clean()
        # Si la fila trae algún dato, tiene que llevar el nombre del contacto.
        if not datos.get('nombre') and (datos.get('area') or datos.get('correo') or datos.get('celular')):
            self.add_error('nombre', 'Ponle nombre a este contacto.')
        return datos


class _ContactosProveedorBase(forms.BaseInlineFormSet):
    def save(self, commit=True):
        objetos = super().save(commit=commit)
        # Vaciar por completo la fila de un contacto existente equivale a quitarlo.
        if commit:
            for form in self.forms:
                c = form.instance
                if c.pk and not (c.nombre or c.area or c.correo or c.celular):
                    c.delete()
        return objetos


ContactoProveedorFormSet = forms.inlineformset_factory(
    Proveedor, ContactoProveedor,
    form=ContactoProveedorForm, formset=_ContactosProveedorBase,
    extra=ContactoProveedor.MAX_CONTACTOS, max_num=ContactoProveedor.MAX_CONTACTOS,
    validate_max=True, can_delete=False,
)


class DocumentoProveedorForm(forms.ModelForm):
    """Carga de un documento (con nombre libre) al expediente del proveedor general."""
    class Meta:
        model = DocumentoProveedor
        fields = ['nombre', 'archivo']
        widgets = {
            'nombre': forms.TextInput(attrs={
                'class': 'form-control form-control-sm',
                'placeholder': 'Ej: RUT, cámara de comercio, certificación bancaria…',
            }),
            'archivo': forms.FileInput(attrs={'class': 'form-control form-control-sm'}),
        }


class DocumentoInternoForm(forms.ModelForm):
    """Carga de un documento interno de SOLMED (RUT, cámara, certificaciones, etc.)."""
    class Meta:
        model = DocumentoInterno
        fields = ['tipo', 'archivo', 'fecha', 'entidad', 'descripcion']
        widgets = {
            'tipo': forms.HiddenInput(),
            'archivo': forms.FileInput(attrs={'class': 'form-control form-control-sm'}),
            'fecha': forms.DateInput(attrs={'class': 'form-control form-control-sm', 'type': 'date'}, format='%Y-%m-%d'),
            'entidad': forms.TextInput(attrs={
                'class': 'form-control form-control-sm', 'list': 'entidades-bancarias',
                'placeholder': 'Banco / cuenta',
            }),
            'descripcion': forms.TextInput(attrs={'class': 'form-control form-control-sm', 'placeholder': 'Detalle (opcional)'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['fecha'].input_formats = ['%Y-%m-%d']
        for campo in ('fecha', 'entidad', 'descripcion'):
            self.fields[campo].required = False

    def clean(self):
        cleaned = super().clean()
        tipo = cleaned.get('tipo')
        # Fecha obligatoria en los tipos que la requieren (RUT, cámara).
        if tipo in DocumentoInterno.TIPOS_CON_FECHA and not cleaned.get('fecha'):
            self.add_error('fecha', 'Indica la fecha del documento.')
        # Certificación bancaria: la entidad/cuenta es obligatoria.
        if tipo == DocumentoInterno.TIPO_MULTIPLE and not cleaned.get('entidad'):
            self.add_error('entidad', 'Indica el banco o la cuenta.')
        # Documentación adicional: el nombre es la llave del reemplazo.
        if tipo == DocumentoInterno.TIPO_ADICIONAL:
            cleaned['descripcion'] = (cleaned.get('descripcion') or '').strip()
            if not cleaned['descripcion']:
                self.add_error('descripcion', 'Ponle nombre al documento.')
        return cleaned


class OrdenHistoricaForm(forms.Form):
    """
    Registra una orden ANTERIOR al consecutivo del sistema: actas que ya se
    llenaron en físico y solo deben quedar archivadas con su número, el
    cliente, el vehículo y el escaneo del acta. No pasa por la programación.
    """
    numero_orden = forms.IntegerField(
        min_value=1, label="Número de la orden",
        widget=forms.NumberInput(attrs={'class': 'form-control'}),
        help_text=(f"El consecutivo que trae el acta física (menor que "
                   f"{OrdenServicio.NUMERO_INICIAL}, donde arranca el sistema)."),
    )
    cliente = forms.ModelChoiceField(
        queryset=Cliente.objects.order_by('nombre'), label="Cliente",
        widget=forms.Select(attrs={'class': 'form-select'}),
        empty_label='--- Elige el cliente ---',
    )
    vehiculo = forms.ModelChoiceField(
        queryset=Vehiculo.objects.order_by('placa'), label="Vehículo",
        widget=forms.Select(attrs={'class': 'form-select'}),
        empty_label='--- Elige el vehículo ---',
    )
    fecha_servicio = forms.DateField(
        label="Fecha del servicio",
        widget=forms.DateInput(attrs={'class': 'form-control', 'type': 'date'},
                               format='%Y-%m-%d'),
    )
    acta = forms.FileField(
        label="Acta diligenciada (PDF o foto)",
        widget=forms.ClearableFileInput(attrs={
            'class': 'form-control', 'accept': 'application/pdf,image/*'}),
        help_text="El escaneo o la foto del acta que se llenó en físico.",
    )
    descripcion = forms.CharField(
        required=False, label="Descripción (opcional)",
        widget=forms.Textarea(attrs={'class': 'form-control', 'rows': 2}),
    )

    def clean_numero_orden(self):
        numero = self.cleaned_data['numero_orden']
        if numero >= OrdenServicio.NUMERO_INICIAL:
            raise forms.ValidationError(
                f"Solo es para órdenes históricas: el número debe ser menor "
                f"que {OrdenServicio.NUMERO_INICIAL}. Las nuevas salen de la "
                f"programación con su consecutivo automático.")
        if OrdenServicio.objects.filter(pk=numero).exists():
            raise forms.ValidationError(f"Ya existe la orden #{numero}.")
        return numero
