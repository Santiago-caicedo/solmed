"""Formularios del plan de trabajo."""
from django import forms
from django.contrib.auth.models import User

from gestion.models import Dispositor, OrdenServicio, Proveedor, Vehiculo

from .models import Asignacion, Novedad


class AsignacionForm(forms.Form):
    """
    Alta de una actividad del plan para UNA O VARIAS personas a la vez (el
    mismo trabajo suele repartirse en pareja: "lavada del WHB123 → Juan y
    Pedro"). Las personas y las placas llegan como listas de ids (chips del
    tablero); los demás campos se validan según lo que la actividad pida
    (Asignacion.CAMPOS_POR_TIPO).
    """
    tipo = forms.ChoiceField(choices=Asignacion.TIPO_CHOICES)
    hora = forms.TimeField(required=False, input_formats=['%H:%M', '%H:%M:%S'])
    orden_numero = forms.CharField(required=False, max_length=10)
    proveedor = forms.ModelChoiceField(
        queryset=Proveedor.objects.filter(activo=True), required=False)
    dispositor = forms.ModelChoiceField(
        queryset=Dispositor.objects.filter(activo=True, tipo='PROVEEDOR'),
        required=False)
    detalle = forms.CharField(required=False, max_length=255)

    def __init__(self, data=None, personas_ids=None, vehiculos_ids=None, **kwargs):
        super().__init__(data, **kwargs)
        self.personas_ids = [p for p in (personas_ids or []) if str(p).isdigit()]
        self.vehiculos_ids = [v for v in (vehiculos_ids or []) if str(v).isdigit()]
        self.personas = []
        self.vehiculos = []

    def clean(self):
        cleaned = super().clean()
        tipo = cleaned.get('tipo')
        if not tipo:
            return cleaned
        campos = Asignacion.CAMPOS_POR_TIPO.get(tipo, {})
        etiqueta = dict(Asignacion.TIPO_CHOICES)[tipo]

        # ¿A quién? — al menos una persona, y que existan y estén activas.
        self.personas = list(
            User.objects.filter(pk__in=self.personas_ids, is_superuser=False)
            .exclude(perfil__retirado=True)
        )
        if not self.personas:
            self.add_error(None, "Marca al menos una persona para asignarle la actividad.")

        # ¿Con cuál placa? — solo si la actividad la pide.
        cleaned['orden'] = None
        if campos.get('vehiculos') == 'cargados':
            # Disponer solo tiene sentido sobre un camión CON residuo, y la
            # orden no se digita: es la que lo dejó cargado.
            self.vehiculos = list(Vehiculo.objects.filter(
                pk__in=self.vehiculos_ids, cargado=True))
            if not self.vehiculos:
                self.add_error(None, "Elige el camión cargado que se va a disponer. "
                                     "Solo aparecen los que tienen residuo pendiente.")
            elif len(self.vehiculos) > 1:
                self.add_error(None, "La disposición se asigna de a un camión: "
                                     "cada uno lleva su propia orden.")
            else:
                cleaned['orden'] = self.vehiculos[0].orden_que_cargo
        elif campos.get('vehiculos'):
            self.vehiculos = list(Vehiculo.objects.filter(pk__in=self.vehiculos_ids))
            if not self.vehiculos:
                self.add_error(None, f"«{etiqueta}» necesita la placa del vehículo.")
        else:
            self.vehiculos = []

        # La orden que se digita (actividades que la piden a mano).
        if campos.get('orden'):
            numero = (cleaned.get('orden_numero') or '').strip()
            if not numero.isdigit():
                self.add_error(None, "Escribe el número de la orden de servicio de la disposición.")
            else:
                cleaned['orden'] = OrdenServicio.objects.filter(pk=numero).first()
                if cleaned['orden'] is None:
                    self.add_error(None, f"La orden #{numero} no existe en el sistema.")

        # El detalle es obligatorio donde el formato lo exige (dice de QUÉ es).
        if campos.get('detalle') and not (cleaned.get('detalle') or '').strip():
            self.add_error(None, f"Describe en qué consiste «{etiqueta}».")

        # Lo que la actividad no pide, no se guarda (aunque venga en el POST).
        if not campos.get('hora'):
            cleaned['hora'] = None
        if not campos.get('proveedor'):
            cleaned['proveedor'] = None
        if not campos.get('dispositor'):
            cleaned['dispositor'] = None
        return cleaned

    def crear(self, plan, usuario):
        """
        Crea una asignación por persona (el mismo trabajo suele ir en pareja).
        Si la actividad dispone el residuo, el camión se descarga UNA vez —no
        una por persona— y queda el movimiento con su orden y su responsable.
        """
        creadas = []
        for persona in self.personas:
            asignacion = Asignacion.objects.create(
                plan=plan, persona=persona, tipo=self.cleaned_data['tipo'],
                orden=self.cleaned_data['orden'],
                proveedor=self.cleaned_data['proveedor'],
                dispositor=self.cleaned_data['dispositor'],
                hora=self.cleaned_data['hora'],
                detalle=(self.cleaned_data.get('detalle') or '').strip(),
                registrado_por=usuario,
            )
            asignacion.vehiculos.set(self.vehiculos)
            creadas.append(asignacion)

        if creadas and creadas[0].descarga_vehiculos and self.vehiculos:
            nombres = [a.persona_nombre for a in creadas]
            creadas[0].aplicar_descarga(self.vehiculos[0], nombres)
        return len(creadas)


class NovedadForm(forms.ModelForm):
    """Registro de una novedad (sección 2 del formato), por rango de fechas."""

    class Meta:
        model = Novedad
        fields = ['persona', 'tipo', 'fecha_inicio', 'fecha_fin', 'hora', 'detalle']
        widgets = {
            'persona': forms.Select(attrs={'class': 'form-select form-select-sm'}),
            'tipo': forms.Select(attrs={'class': 'form-select form-select-sm'}),
            'fecha_inicio': forms.DateInput(
                attrs={'class': 'form-control form-control-sm', 'type': 'date'},
                format='%Y-%m-%d'),
            'fecha_fin': forms.DateInput(
                attrs={'class': 'form-control form-control-sm', 'type': 'date'},
                format='%Y-%m-%d'),
            'hora': forms.TimeInput(
                attrs={'class': 'form-control form-control-sm', 'type': 'time'},
                format='%H:%M'),
            'detalle': forms.TextInput(attrs={
                'class': 'form-control form-control-sm',
                'placeholder': 'Detalle (en el examen médico: ingreso, periódico o anual)',
            }),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['fecha_inicio'].input_formats = ['%Y-%m-%d']
        self.fields['fecha_fin'].input_formats = ['%Y-%m-%d']
        self.fields['hora'].input_formats = ['%H:%M', '%H:%M:%S']
        # Personal activo (sin retirados ni superadministradores), por nombre.
        self.fields['persona'].queryset = (
            User.objects.filter(is_superuser=False, groups__isnull=False)
            .exclude(perfil__retirado=True)
            .order_by('first_name', 'username').distinct()
        )
        self.fields['persona'].empty_label = '--- Elige la persona ---'
        self.fields['persona'].label_from_instance = (
            lambda u: u.get_full_name() or u.username)

    def clean(self):
        cleaned = super().clean()
        inicio, fin = cleaned.get('fecha_inicio'), cleaned.get('fecha_fin')
        if inicio and fin and fin < inicio:
            self.add_error('fecha_fin', 'La fecha final no puede ser anterior a la de inicio.')
        return cleaned
