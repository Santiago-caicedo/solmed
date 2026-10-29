"""Formularios del plan de trabajo."""
import datetime

from django import forms
from django.contrib.auth.models import User

from gestion.models import Dispositor, OrdenServicio, Proveedor, Vehiculo

from .models import Asignacion, Novedad, TipoPersonalizado, tipo_personalizado_de


def validar_horas(form, cleaned, campo_fin):
    """La hora final es opcional, pero va con la de inicio y después de ella."""
    inicio, fin = cleaned.get('hora'), cleaned.get('hora_fin')
    if fin and not inicio:
        form.add_error(campo_fin, "Escribe también la hora de inicio.")
    elif inicio and fin and fin <= inicio:
        form.add_error(campo_fin, "La hora final debe ser posterior a la de inicio.")


# Lo que se puede elegir en los selectores de un descuento (como en «Corregir datos»).
DESCUENTO_HORAS = list(range(13))
DESCUENTO_MINUTOS = list(range(0, 60, 5))


def leer_descuentos(form, cleaned, sufijo='', quien=''):
    """
    Los descuentos de horas que llegan del popup como listas paralelas
    (des_horas, des_minutos, des_motivo): [(minutos, motivo)]. Las filas
    vacías se saltan. Cada fila necesita un tiempo mayor que cero y su
    motivo; en total no pueden pasar del tiempo entre las dos horas, y solo
    tienen sentido si esas horas suman (casilla «Sumar estas horas…»). Los
    errores van al formulario (sin campo) y entonces devuelve None.

    `sufijo` y `quien` son para el popup de Disposiciones, que pide los
    tiempos de CADA persona (des_horas_<id>…) y nombra a quién falta algo.
    """
    data = form.data
    horas_l = data.getlist(f'des_horas{sufijo}') if hasattr(data, 'getlist') else []
    minutos_l = data.getlist(f'des_minutos{sufijo}') if hasattr(data, 'getlist') else []
    motivos_l = data.getlist(f'des_motivo{sufijo}') if hasattr(data, 'getlist') else []
    filas, errores = [], []
    for i in range(max(len(horas_l), len(minutos_l), len(motivos_l))):
        h = (horas_l[i] if i < len(horas_l) else '').strip()
        m = (minutos_l[i] if i < len(minutos_l) else '').strip()
        motivo = (motivos_l[i] if i < len(motivos_l) else '').strip()
        if not (h or m or motivo):
            continue
        if not (h.isdigit() and m.isdigit() and int(h) in DESCUENTO_HORAS
                and int(m) in DESCUENTO_MINUTOS):
            errores.append("Descuento de horas: elige un valor de la lista.")
            continue
        total = int(h) * 60 + int(m)
        if not total and not motivo:
            continue    # se tocó «Añadir descuento» y la fila quedó sin llenar
        if not total:
            errores.append("Descuento de horas: elige cuánto tiempo se descuenta.")
        if not motivo:
            errores.append("Descuento de horas: escribe el motivo del descuento.")
        if total and motivo:
            filas.append((total, motivo))
    if filas and not errores:
        inicio, fin = cleaned.get('hora'), cleaned.get('hora_fin')
        if not cleaned.get('suma_horas'):
            errores.append("Para descontar horas, marca «Sumar estas horas al historial "
                           "de horas trabajadas».")
        elif inicio and fin:
            minutos = (fin.hour * 60 + fin.minute) - (inicio.hour * 60 + inicio.minute)
            suma = sum(t for t, _ in filas)
            if suma > minutos:
                errores.append(f"Los descuentos ({_texto_horas(suma)}) son más que el tiempo "
                               f"entre las dos horas ({_texto_horas(minutos)}).")
    for e in errores:
        form.add_error(None, f"{quien}: {e}" if quien else e)
    return None if errores else filas


def _hora_de(valor):
    """«07:30» → time; vacío → None; lo que no sea una hora → ValueError."""
    valor = (valor or '').strip()
    if not valor:
        return None
    return datetime.datetime.strptime(valor[:5], '%H:%M').time()


def leer_tiempos_por_persona(form, personas):
    """
    Los tiempos de CADA persona del popup de Disposiciones (oct-2026, pedido
    de Santiago): hora_<id>, hora_fin_<id>, suma_horas_<id> y sus descuentos
    (des_horas_<id>…). Las mismas reglas que una actividad del plan, con el
    nombre de la persona en el error. {persona.pk: {hora, hora_fin,
    suma_horas, descuentos}}; las que tengan error no entran.
    """
    data, tiempos = form.data, {}
    for persona in personas:
        nombre = persona.get_full_name() or persona.username
        try:
            t = {'hora': _hora_de(data.get(f'hora_{persona.pk}')),
                 'hora_fin': _hora_de(data.get(f'hora_fin_{persona.pk}')),
                 'suma_horas': data.get(f'suma_horas_{persona.pk}') in ('1', 'on', 'true')}
        except ValueError:
            form.add_error(None, f"{nombre}: escribe las horas como hh:mm.")
            continue
        inicio, fin = t['hora'], t['hora_fin']
        if fin and not inicio:
            form.add_error(None, f"{nombre}: escribe también la hora de inicio.")
            continue
        if inicio and fin and fin <= inicio:
            form.add_error(None, f"{nombre}: la hora final debe ser posterior a la de inicio.")
            continue
        if t['suma_horas'] and not (inicio and fin):
            form.add_error(None, f"{nombre}: para sumar estas horas al historial de horas "
                                 f"trabajadas, escribe la hora de inicio y la final.")
            continue
        t['descuentos'] = leer_descuentos(form, t, sufijo=f'_{persona.pk}', quien=nombre)
        tiempos[persona.pk] = t
    return tiempos


def _texto_horas(minutos):
    """2 h 30 min · 2 h · 15 min (como gestion.views._texto_horas)."""
    horas, resto = divmod(minutos, 60)
    if not horas and resto:
        return f"{resto} min"
    return f"{horas} h {resto:02d} min" if resto else f"{horas} h"


def guardar_descuentos(filas, **duenio):
    """Crea los DescuentoHoras de una actividad (asignacion=) o novedad (novedad=)."""
    from .models import DescuentoHoras
    for minutos, motivo in filas or []:
        DescuentoHoras.objects.create(minutos=minutos, motivo=motivo, **duenio)


class AsignacionForm(forms.Form):
    """
    Alta de una actividad del plan para UNA O VARIAS personas a la vez (el
    mismo trabajo suele repartirse en pareja: "lavada del WHB123 → Juan y
    Pedro"). Las personas y las placas llegan como listas de ids (chips del
    tablero); los demás campos se validan según lo que la actividad pida
    (Asignacion.CAMPOS_POR_TIPO).
    """
    # Un código del formato o «P:<id>», una actividad creada en el popup.
    tipo = forms.CharField(max_length=20)
    hora = forms.TimeField(required=False, input_formats=['%H:%M', '%H:%M:%S'])
    hora_fin = forms.TimeField(required=False, input_formats=['%H:%M', '%H:%M:%S'])
    # Marcada, las horas suman en el centro de control (exige las dos horas).
    suma_horas = forms.BooleanField(required=False)
    orden_numero = forms.CharField(required=False, max_length=10)
    proveedor = forms.ModelChoiceField(
        queryset=Proveedor.objects.filter(activo=True), required=False)
    dispositor = forms.ModelChoiceField(
        queryset=Dispositor.objects.filter(activo=True, tipo='PROVEEDOR'),
        required=False)
    detalle = forms.CharField(required=False, max_length=255)
    # Para las actividades que no piden placa: marcada, se dice cuál(es)
    # vehículo(s) se usó (oct-2026).
    uso_vehiculo = forms.BooleanField(required=False)
    # Marcada, se le avisa por correo a cada persona asignada (opcional:
    # muchas actividades se reparten de viva voz en la formación).
    notificar = forms.BooleanField(required=False)

    def __init__(self, data=None, personas_ids=None, vehiculos_ids=None,
                 ordenes_ids=None, vehiculo_viaje=None, tiempos_por_persona=False,
                 **kwargs):
        super().__init__(data, **kwargs)
        # El popup de Disposiciones pide las horas, la casilla de sumar y los
        # descuentos de CADA persona (paso «Tiempos», oct-2026); el plan de
        # trabajo, unos solos para todos.
        self.tiempos_por_persona = tiempos_por_persona
        self.tiempos = {}
        self.personas_ids = [p for p in (personas_ids or []) if str(p).isdigit()]
        self.vehiculos_ids = [v for v in (vehiculos_ids or []) if str(v).isdigit()]
        # El vehículo que hizo el viaje de una disposición. Solo lo manda el
        # popup del panel de disposiciones (oct-2026); el plan de trabajo no,
        # así sus casillas de placa no se cuelan en una disposición.
        self.vehiculo_viaje = str(vehiculo_viaje) if str(vehiculo_viaje or '').isdigit() else None
        self.ordenes_ids = [o for o in (ordenes_ids or []) if str(o).isdigit()]
        self.personas = []
        self.vehiculos = []
        self.ordenes = []

    def clean(self):
        cleaned = super().clean()
        tipo = cleaned.get('tipo')
        if not tipo:
            return cleaned
        cleaned['tipo_personalizado'] = None
        if tipo.startswith('P:'):
            personalizado = tipo_personalizado_de(tipo, 'ACTIVIDAD')
            if personalizado is None:
                self.add_error(None, "Esa actividad ya no está en la lista: elige otra.")
                return cleaned
            tipo = cleaned['tipo'] = 'PERSONALIZADA'
            cleaned['tipo_personalizado'] = personalizado
            etiqueta = personalizado.nombre
        elif tipo == 'PERSONALIZADA' or tipo not in dict(Asignacion.TIPO_CHOICES):
            self.add_error(None, "Elige una actividad de la lista.")
            return cleaned
        else:
            etiqueta = dict(Asignacion.TIPO_CHOICES)[tipo]
        campos = Asignacion.CAMPOS_POR_TIPO.get(tipo, {})

        # ¿A quién? — al menos una persona, y que existan y estén activas.
        self.personas = list(
            User.objects.filter(pk__in=self.personas_ids, is_superuser=False)
            .exclude(perfil__retirado=True)
        )
        if not self.personas:
            self.add_error(None, "Marca al menos una persona para asignarle la actividad.")

        # ¿Con cuál placa? — solo si la actividad la pide.
        cleaned['orden'] = None
        if campos.get('ordenes') == 'pendientes':
            # Disponer se hace POR ORDEN: se marcan las que salieron en el
            # viaje (la orden no se digita). Solo las que siguen sin disponer.
            # Las que ya van en un viaje AGENDADO tampoco (oct-2026): se
            # disponen al confirmarlo o vuelven a estar libres si se cancela.
            from .viajes import ids_ordenes_agendadas
            self.ordenes = list(
                OrdenServicio.objects
                .filter(pk__in=self.ordenes_ids, estado_disposicion='PENDIENTE')
                .exclude(pk__in=ids_ordenes_agendadas())
                .prefetch_related('recorridos__vehiculo').order_by('numero_orden'))
            if not self.ordenes:
                self.add_error(None, "Marca cuál orden se va a disponer. Solo "
                                     "aparecen las que siguen sin disponer y no "
                                     "están agendadas en otro viaje.")
            elif self.vehiculo_viaje:
                # El vehículo que hizo el viaje de disposición, elegido en el
                # popup del panel de disposiciones (oct-2026, pedido de
                # Santiago): ese es el que queda en el plan.
                self.vehiculos = list(Vehiculo.objects.filter(pk=self.vehiculo_viaje))
                if not self.vehiculos:
                    self.add_error(None, "El vehículo elegido para el viaje ya no existe.")
            else:
                # Sin vehículo elegido, las placas van de referencia (el camión
                # de cada orden): un viaje puede llevar órdenes de placas distintas.
                self.vehiculos = sorted(
                    {r.vehiculo for o in self.ordenes for r in o.recorridos.all()
                     if r.vehiculo_id},
                    key=lambda v: v.placa)
                # Una sola orden → queda en la asignación; varias → la traza
                # por orden vive en las disposiciones enlazadas.
                cleaned['orden'] = self.ordenes[0] if len(self.ordenes) == 1 else None
        elif campos.get('vehiculos'):
            self.vehiculos = list(Vehiculo.objects.filter(pk__in=self.vehiculos_ids))
            if not self.vehiculos:
                self.add_error(None, f"«{etiqueta}» necesita la placa del vehículo.")
        elif cleaned.get('uso_vehiculo'):
            # Cualquier otra actividad puede llevar vehículo si se marca.
            self.vehiculos = list(Vehiculo.objects.filter(pk__in=self.vehiculos_ids))
            if not self.vehiculos:
                self.add_error(None, "Marcaste que se usó vehículo: elige cuál.")
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
        validar_horas(self, cleaned, None)
        # Sumar al historial de horas trabajadas exige saber cuántas fueron.
        if cleaned.get('suma_horas') and not (cleaned.get('hora') and cleaned.get('hora_fin')):
            self.add_error(None, "Para sumar estas horas al historial de horas trabajadas, "
                                 "escribe la hora de inicio y la final.")
        if self.tiempos_por_persona:
            self.descuentos = []
            self.tiempos = leer_tiempos_por_persona(self, self.personas)
        else:
            self.descuentos = leer_descuentos(self, cleaned)
        if not campos.get('proveedor'):
            cleaned['proveedor'] = None
        if not campos.get('dispositor'):
            cleaned['dispositor'] = None
        return cleaned

    def crear(self, plan, usuario, viaje=None):
        """
        Crea una asignación por persona (el mismo trabajo suele ir en pareja).
        Si la actividad dispone el residuo, cada orden queda dispuesta UNA vez
        —no una por persona— con su registro y su responsable.

        Con `viaje` (un viaje de disposición AGENDADO, oct-2026) cada
        actividad queda enlazada a él y NO dispone nada todavía: las órdenes
        se disponen cuando la oficina confirma que el viaje se hizo.
        """
        creadas = []
        for persona in self.personas:
            # Los tiempos de esa persona (Disposiciones) o los de todos (plan).
            t = self.tiempos.get(persona.pk) or {
                'hora': self.cleaned_data['hora'], 'hora_fin': self.cleaned_data['hora_fin'],
                'suma_horas': bool(self.cleaned_data.get('suma_horas')),
                'descuentos': self.descuentos}
            asignacion = Asignacion.objects.create(
                plan=plan, persona=persona, tipo=self.cleaned_data['tipo'],
                tipo_personalizado=self.cleaned_data['tipo_personalizado'],
                orden=self.cleaned_data['orden'],
                proveedor=self.cleaned_data['proveedor'],
                dispositor=self.cleaned_data['dispositor'],
                hora=t['hora'],
                hora_fin=t['hora_fin'],
                suma_horas=t['suma_horas'],
                detalle=(self.cleaned_data.get('detalle') or '').strip(),
                registrado_por=usuario,
                viaje=viaje,
            )
            asignacion.vehiculos.set(self.vehiculos)
            guardar_descuentos(t['descuentos'], asignacion=asignacion)
            creadas.append(asignacion)

        if creadas and creadas[0].dispone_ordenes and self.ordenes and viaje is None:
            nombres = [a.persona_nombre for a in creadas]
            creadas[0].aplicar_disposicion(nombres, self.ordenes)
            # La pareja comparte la misma disposición: todos enlazan los mismos
            # registros, y quitar a uno no la deshace mientras quede el otro.
            for a in creadas[1:]:
                a.disposiciones.set(creadas[0].disposiciones.all())
        return creadas


class NovedadForm(forms.ModelForm):
    """Registro de una novedad (sección 2 del formato), por rango de fechas."""

    class Meta:
        model = Novedad
        fields = ['persona', 'tipo', 'fecha_inicio', 'fecha_fin', 'hora', 'hora_fin',
                  'suma_horas', 'detalle']
        widgets = {
            'suma_horas': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
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
            'hora_fin': forms.TimeInput(
                attrs={'class': 'form-control form-control-sm', 'type': 'time'},
                format='%H:%M'),
            'detalle': forms.TextInput(attrs={
                'class': 'form-control form-control-sm',
                'placeholder': 'Detalle (en el examen médico: ingreso, periódico o anual)',
            }),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Las novedades del formato y, en su grupo, las creadas en el popup
        # (viajan como «P:<id>»; clean_tipo las convierte).
        propias = [(t.valor, t.nombre) for t in
                   TipoPersonalizado.objects.filter(ambito='NOVEDAD', activo=True)]
        self.fields['tipo'] = forms.ChoiceField(
            choices=([('', '---------')]
                     + [g for g in Novedad.TIPO_CHOICES if g[0] != 'Creadas en el plan']
                     + ([('Creadas en el plan', propias)] if propias else [])),
            widget=forms.Select(attrs={'class': 'form-select form-select-sm'}))
        self.fields['fecha_inicio'].input_formats = ['%Y-%m-%d']
        self.fields['fecha_fin'].input_formats = ['%Y-%m-%d']
        self.fields['hora'].input_formats = ['%H:%M', '%H:%M:%S']
        self.fields['hora_fin'].input_formats = ['%H:%M', '%H:%M:%S']
        # Personal activo (sin retirados ni superadministradores), por nombre.
        self.fields['persona'].queryset = (
            User.objects.filter(is_superuser=False, groups__isnull=False)
            .exclude(perfil__retirado=True)
            .order_by('first_name', 'username').distinct()
        )
        self.fields['persona'].empty_label = '--- Elige la persona ---'
        self.fields['persona'].label_from_instance = (
            lambda u: u.get_full_name() or u.username)

    def clean_tipo(self):
        valor = self.cleaned_data['tipo']
        self.instance.tipo_personalizado = None
        if valor.startswith('P:'):
            personalizado = tipo_personalizado_de(valor, 'NOVEDAD')
            if personalizado is None:
                raise forms.ValidationError("Esa novedad ya no está en la lista: elige otra.")
            self.instance.tipo_personalizado = personalizado
            return 'PERSONALIZADA'
        return valor

    def clean(self):
        cleaned = super().clean()
        inicio, fin = cleaned.get('fecha_inicio'), cleaned.get('fecha_fin')
        if inicio and fin and fin < inicio:
            self.add_error('fecha_fin', 'La fecha final no puede ser anterior a la de inicio.')
        validar_horas(self, cleaned, 'hora_fin')
        # Sumar al historial de horas trabajadas exige saber cuántas fueron.
        if cleaned.get('suma_horas') and not (cleaned.get('hora') and cleaned.get('hora_fin')):
            self.add_error('suma_horas', "Para sumar estas horas, escribe la hora de inicio y la final.")
        self.descuentos = leer_descuentos(self, cleaned)
        return cleaned

    def guardar_descuentos(self, novedad):
        guardar_descuentos(self.descuentos, novedad=novedad)
