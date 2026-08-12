import json
import mimetypes
import os
from django.conf import settings
from django.core.mail import EmailMessage
from django.http import Http404, HttpResponse, HttpResponseRedirect
from django.contrib.messages.views import SuccessMessageMixin
from django.contrib.auth.models import User, Group
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, render, redirect
from django.contrib import messages
from django.contrib.auth.mixins import UserPassesTestMixin
from django.template.loader import get_template
from django.urls import reverse, reverse_lazy
from django.core.files.base import ContentFile
from django.core.paginator import Paginator
from django.views import View
from io import BytesIO
import qrcode
from weasyprint import HTML
from django.db import IntegrityError, transaction
from django.db.models import Avg, F, Min, Q, Sum, Count
import base64
import datetime
from django.db.models.functions import ExtractYear, TruncMonth
from decimal import Decimal 
from django.views.generic import ListView, CreateView, UpdateView, TemplateView, DetailView, FormView
from django.utils import timezone
from django.db.models import Sum
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db.models import Q
from .models import CURSOS_EXIGIBLES, DocumentoPersonal, EncuestaConductor, FotoAyudante, Manifiesto, OrdenServicio, Pago, PerfilPersona, Programacion, ProgramacionCuadrilla, Recorrido, Sede, cursos_faltantes_ayudante, _recalcular_estado_orden
from django.http import JsonResponse
from django.contrib.auth.forms import SetPasswordForm
from .renumeracion import reubicar_orden
from .forms import DocumentoCorreoFormSet, DocumentoOrdenForm, DocumentoPersonalForm, EncuestaConductorForm, FiltroAceiteForm, ManifiestoPaso2Form, ManifiestoPaso3Form, ManifiestoPaso4Form, ManifiestoPaso5Form, OrdenHistoricaForm, OrdenServicioForm, PagoForm, PerfilPersonaForm, PersonaSinAccesoForm, ProgramacionForm, ProgramacionCuadrillaForm, RecorridoForm, ReporteFiltroForm, SedeFormSet, TerceroFormSet, VehiculoForm, ClienteForm, CrearUsuarioForm, ActualizarUsuarioForm
from .models import Bascula, EnvioCorreo, MedidaACPM, NovedadOperacional, OrdenServicio, SitioInicio, TipoResiduo, Vehiculo, Cliente, DocumentoAmbientalCliente, DocumentoCorreoCliente, DocumentoOrden, FiltroAceite, Tercero


def rango_de_paginas(page_obj, a_los_lados=2):
    """
    Números de página a dibujar alrededor de la actual, con elipsis donde la
    lista se recorta. Devuelve [{'numero': n, 'elipsis': bool}] (vacío si no hay
    paginación). Lo consume `partials/_paginacion.html`.
    """
    if page_obj is None:
        return []
    rango = []
    for p in page_obj.paginator.get_elided_page_range(
            page_obj.number, on_each_side=a_los_lados, on_ends=1):
        # get_elided_page_range devuelve enteros y, donde recorta, la elipsis.
        rango.append({'numero': p, 'elipsis': not isinstance(p, int)})
    return rango


class PaginadoMixin:
    """
    Paginación uniforme de los listados: fija el tamaño de página y expone el
    rango de páginas que dibuja `partials/_paginacion.html`. Los filtros de la
    URL se conservan al cambiar de página (lo hace el tag `querystring`).
    """
    paginate_by = 20
    paginas_a_los_lados = 2

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['pagina_rango'] = rango_de_paginas(
            context.get('page_obj'), self.paginas_a_los_lados
        )
        return context


# --- NUEVO MIXIN DE SEGURIDAD PARA PLANIFICADORES ---
def es_administrador(user):
    """
    Administrador de la plataforma: el superusuario y el rol 'Administradores'.
    Hacen exactamente lo mismo DENTRO de la app; la diferencia es que el rol
    Administradores no entra al admin de Django (eso exige is_staff).
    """
    return user.is_authenticated and (
        user.is_superuser or user.groups.filter(name='Administradores').exists()
    )


class PlanificadorRequiredMixin(LoginRequiredMixin, UserPassesTestMixin):
    def test_func(self):
        user = self.request.user
        return es_administrador(user) or user.groups.filter(name='Planificadores').exists()


# --- NUEVO MIXIN DE SEGURIDAD PARA ASESORES Y ADMINS ---
class AsesorRequiredMixin(LoginRequiredMixin, UserPassesTestMixin):
    """
    Restringe el acceso a administradores (superusuario o rol Administradores)
    y a miembros del grupo 'Asesores'.
    """
    def test_func(self):
        user = self.request.user
        return es_administrador(user) or user.groups.filter(name='Asesores').exists()


# --- MIXIN QUE BLOQUEA A LOS CONDUCTORES ---
class AdministradorRequiredMixin(LoginRequiredMixin, UserPassesTestMixin):
    def test_func(self):
        return es_administrador(self.request.user)


SuperuserRequiredMixin = AdministradorRequiredMixin


class NoConductorRequiredMixin(LoginRequiredMixin, UserPassesTestMixin):
    """
    Permite el acceso a cualquier usuario autenticado EXCEPTO a los conductores.
    Se usa en vistas de gestión (como el expediente de la orden) a las que el
    conductor no debe entrar.
    """
    def test_func(self):
        user = self.request.user
        return es_administrador(user) or not user.groups.filter(name='Conductores').exists()


# Nombres cortos de los meses para las series de 12 meses del tablero.
MESES_CORTOS = ['Ene', 'Feb', 'Mar', 'Abr', 'May', 'Jun',
                'Jul', 'Ago', 'Sep', 'Oct', 'Nov', 'Dic']


# --- Vista Principal (Dashboard) ---
# Se protege con LoginRequiredMixin para que sea la página de inicio después del login.
class DashboardView(LoginRequiredMixin, TemplateView):
    """
    Parte de operaciones: estadísticas clave de todo lo mapeado en el sistema
    (servicios, órdenes, actas, flota, personal, proveedores, PESV, cobranza y
    conciliación) más el centro de alertas accionable.
    """
    template_name = 'gestion/dashboard.html'

    def dispatch(self, request, *args, **kwargs):
        # El conductor tiene su propio tablero: si llega aquí por URL, se le
        # redirige en vez de mostrarle las cifras de gestión.
        if (request.user.is_authenticated and not es_administrador(request.user)
                and request.user.groups.filter(name='Conductores').exists()):
            return redirect('gestion:dashboard_conductor')
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        hoy = timezone.localdate()
        inicio_mes = hoy.replace(day=1)
        context['hoy'] = hoy

        # ================= HOY (agenda operativa) =================
        recorridos_hoy = (
            Recorrido.objects.filter(fecha_recorrido=hoy)
            .exclude(orden__estado_orden='CANCELADA')
            .select_related('orden__cliente', 'vehiculo', 'conductor')
            .order_by('orden__fecha_creacion')
        )
        context['servicios_hoy'] = recorridos_hoy
        context['servicios_hoy_total'] = recorridos_hoy.count()
        vehiculos_en_ruta_hoy = (
            recorridos_hoy.exclude(vehiculo=None).values('vehiculo').distinct().count()
        )
        context['vehiculos_en_ruta_hoy'] = vehiculos_en_ruta_hoy

        # ================= ÓRDENES =================
        conteo_estados = dict(
            OrdenServicio.objects.values_list('estado_orden')
            .annotate(c=Count('numero_orden'))
        )
        colores_estado = {
            'PROGRAMADA': 'neutro', 'EN_EJECUCION': 'acero',
            'FINALIZADA': 'verde', 'CANCELADA': 'gris',
        }
        ordenes_por_estado = [{
            'codigo': codigo, 'label': label,
            'total': conteo_estados.get(codigo, 0),
            'tono': colores_estado.get(codigo, 'neutro'),
        } for codigo, label in OrdenServicio.ESTADO_ORDEN_CHOICES]
        context['ordenes_por_estado'] = ordenes_por_estado
        context['ordenes_estado_max'] = max([e['total'] for e in ordenes_por_estado] + [1])
        context['ordenes_total'] = sum(e['total'] for e in ordenes_por_estado)
        context['ordenes_activas'] = conteo_estados.get('EN_EJECUCION', 0)

        # ================= SERVICIOS (recorridos completados) =================
        completados = Recorrido.objects.filter(estado='COMPLETADO')
        context['servicios_completados_mes'] = completados.filter(
            fecha_recorrido__gte=inicio_mes, fecha_recorrido__lte=hoy
        ).count()
        context['servicios_completados_total'] = completados.count()

        # Actividad de los últimos 12 meses (incluye meses en cero).
        anio, mes = hoy.year, hoy.month
        claves_meses = []
        for _ in range(12):
            claves_meses.append((anio, mes))
            mes -= 1
            if mes == 0:
                mes, anio = 12, anio - 1
        claves_meses.reverse()
        desde = datetime.date(claves_meses[0][0], claves_meses[0][1], 1)
        conteo_meses = {
            (m.year, m.month): c for m, c in
            completados.filter(fecha_recorrido__gte=desde)
            .annotate(mes=TruncMonth('fecha_recorrido'))
            .values('mes').annotate(c=Count('id')).values_list('mes', 'c')
        }
        servicios_por_mes = [{
            'label': MESES_CORTOS[m - 1],
            'anio': a,
            'total': conteo_meses.get((a, m), 0),
            'actual': (a, m) == (hoy.year, hoy.month),
        } for a, m in claves_meses]
        context['servicios_por_mes'] = servicios_por_mes
        context['servicios_mes_max'] = max([x['total'] for x in servicios_por_mes] + [1])

        # Top clientes por servicios completados en el año.
        top_clientes = list(
            completados.filter(fecha_recorrido__year=hoy.year)
            .values('orden__cliente__nombre', 'orden__cliente_id')
            .annotate(total=Count('id')).order_by('-total')[:5]
        )
        context['top_clientes'] = top_clientes
        context['top_clientes_max'] = max([c['total'] for c in top_clientes] + [1])

        # ================= ACTAS DE SERVICIO =================
        context['actas_firmadas'] = Manifiesto.objects.filter(estado_firma='FIRMADO').count()
        context['actas_por_firmar'] = Manifiesto.objects.filter(estado_firma='PENDIENTE_FIRMA').count()

        # ================= PESV (encuestas de cierre del conductor) =================
        # Una fila por pregunta: cuántas respuestas exigen atención este mes.
        # En fatiga, molestias y condición de riesgo la alerta es responder SÍ;
        # en las demás (pausas activas, tiempos, cabina, zonas de descanso), NO.
        encuestas_mes = EncuestaConductor.objects.filter(fecha_diligenciamiento__date__gte=inicio_mes)
        total_encuestas = encuestas_mes.count()
        etiquetas_pesv = {
            'presento_fatiga': 'Reportó fatiga o microsueños',
            'realizo_pausas_activas': 'No hizo las pausas activas',
            'molestias_fisicas': 'Reportó molestias físicas',
            'tiempos_adecuados': 'Tiempos de ruta no realistas',
            'cabina_optima': 'Cabina en mal estado',
            'zonas_seguras_descanso': 'Sin zonas seguras de descanso',
            'condicion_riesgo': 'Condición de riesgo o casi-accidente',
        }
        pesv_preguntas = []
        for campo in EncuestaConductor.CAMPOS_PREGUNTAS:
            respuesta_alerta = 'SI' if campo in EncuestaConductor.PREGUNTAS_ALERTA_SI else 'NO'
            pesv_preguntas.append({
                'label': etiquetas_pesv[campo],
                'total': encuestas_mes.filter(**{campo: respuesta_alerta}).count(),
            })
        context['pesv'] = {
            'encuestas_mes': total_encuestas,
            'preguntas': pesv_preguntas,
            'hallazgos': sum(p['total'] for p in pesv_preguntas),
            'casi_accidentes': encuestas_mes.filter(condicion_riesgo='SI').count(),
        }

        # ================= FLOTA =================
        vehiculos = list(Vehiculo.objects.all())
        operativos = [v for v in vehiculos if v.estado == 'OPERATIVO']
        flota = {
            'total': len(vehiculos),
            'operativos': len(operativos),
            'en_ruta_hoy': vehiculos_en_ruta_hoy,
            'disponibles': max(len(operativos) - vehiculos_en_ruta_hoy, 0),
            'mantenimiento': sum(1 for v in vehiculos if v.estado == 'MANTENIMIENTO'),
            'stand_by': sum(1 for v in vehiculos if v.estado == 'STAND_BY'),
            'cargados': sum(1 for v in vehiculos if v.cargado),
        }
        context['flota'] = flota
        context['vehiculos_con_alerta'] = [v for v in vehiculos if v.tiene_alerta_documentos]
        context['vehiculos_cargados'] = sorted(
            (v for v in vehiculos if v.cargado), key=lambda v: v.placa
        )

        # ================= PERSONAL =================
        docs_personal = _estado_documentos_personal()
        personal_ss_ok = sum(1 for d in docs_personal.values() if d['ss_al_dia'])
        context['personal'] = {
            'con_requisitos': len(docs_personal),
            'ss_al_dia': personal_ss_ok,
            'ss_pendiente': len(docs_personal) - personal_ss_ok,
            'conductores': User.objects.filter(groups__name='Conductores')
                                       .exclude(perfil__retirado=True).count(),
            'ayudantes': User.objects.filter(groups__name='Ayudantes')
                                     .exclude(perfil__retirado=True).count(),
        }
        personal_con_faltantes = [d for d in docs_personal.values() if d['faltan']]

        # ================= PROVEEDORES (dispositores) =================
        tipos_doc_proveedor = [t for t, _ in DocumentoDispositor.TIPO_CHOICES]
        proveedores = list(
            Dispositor.objects.filter(tipo='PROVEEDOR', activo=True)
            .prefetch_related('documentos')
        )
        proveedores_incompletos = [
            p for p in proveedores
            if {d.tipo for d in p.documentos.all()} < set(tipos_doc_proveedor)
        ]
        context['proveedores'] = {
            'activos': len(proveedores),
            'incompletos': len(proveedores_incompletos),
        }

        # ================= COBRANZA Y CONCILIACIÓN =================
        context['cobranza_pendiente'] = OrdenServicio.objects.filter(
            estado_pago='PENDIENTE'
        ).aggregate(total=Sum('valor_servicio'))['total'] or 0
        context['cobranza_prioritaria'] = (
            OrdenServicio.objects.filter(estado_orden='FINALIZADA', estado_pago='PENDIENTE')
            .select_related('cliente').order_by('fecha_creacion')[:6]
        )
        pendientes_conciliacion = (
            OrdenServicio.objects.filter(estado_conciliacion='PENDIENTE')
            .exclude(estado_orden='CANCELADA')
            .select_related('cliente').order_by('fecha_creacion')
        )
        context['pendientes_conciliacion_count'] = pendientes_conciliacion.count()

        # ================= CENTRO DE ALERTAS (cola accionable) =================
        # nivel 'err' = requiere acción ya; 'warn' = atender pronto.
        alertas = []
        for v in context['vehiculos_cargados']:
            alertas.append({
                'nivel': 'err', 'icono': 'bi-truck',
                'texto': f"{v.placa} está CARGADO, pendiente de disposición final",
                'detalle': v.cargado_detalle or '',
                'url': reverse('gestion:detalle_vehiculo', args=[v.pk]),
            })
        for v in context['vehiculos_con_alerta']:
            for d in v.documentos_por_vencer():
                vencido = d['vencido']
                alertas.append({
                    'nivel': 'err' if vencido else 'warn',
                    'icono': 'bi-file-earmark-x' if vencido else 'bi-clock-history',
                    'texto': (f"{v.placa}: {d['documento']} "
                              + (f"vencido hace {d['dias_abs']} día(s)" if vencido
                                 else f"vence en {d['dias_restantes']} día(s)")),
                    'detalle': d['fecha'].strftime('%d/%m/%Y'),
                    'url': reverse('gestion:actualizar_vehiculo', args=[v.pk]),
                })
        for info in personal_con_faltantes:
            sin_ss = not info['ss_al_dia']
            alertas.append({
                'nivel': 'err' if sin_ss else 'warn',
                'icono': 'bi-person-x' if sin_ss else 'bi-person-exclamation',
                'texto': f"{info['nombre']}: falta {', '.join(info['faltan']).lower()}",
                'detalle': '',
                'url': info['url'],
            })
        n = context['pendientes_conciliacion_count']
        if n:
            # Se nombran las primeras órdenes para saber CUÁLES son de un vistazo;
            # el enlace lleva al listado filtrado con todas.
            numeros = list(pendientes_conciliacion.values_list('numero_orden', flat=True)[:5])
            detalle = 'Orden' + ('es ' if len(numeros) > 1 else ' ')
            detalle += ', '.join(f'#{numero}' for numero in numeros)
            if n > len(numeros):
                detalle += f' y {n - len(numeros)} más'
            alertas.append({
                'nivel': 'warn', 'icono': 'bi-calculator',
                'texto': (f"{n} orden pendiente de conciliación (Transporte - Cantidad)" if n == 1
                          else f"{n} órdenes pendientes de conciliación (Transporte - Cantidad)"),
                'detalle': detalle,
                'url': reverse('gestion:lista_ordenes') + '?conciliacion=PENDIENTE',
            })
        n = context['actas_por_firmar']
        if n:
            alertas.append({
                'nivel': 'warn', 'icono': 'bi-pen',
                'texto': (f"{n} acta diligenciada espera la firma del cliente" if n == 1
                          else f"{n} actas diligenciadas esperan la firma del cliente"),
                'detalle': '',
                'url': reverse('gestion:lista_ordenes') + '?estado=EN_EJECUCION',
            })
        n = len(proveedores_incompletos)
        if n:
            alertas.append({
                'nivel': 'warn', 'icono': 'bi-recycle',
                'texto': (f"{n} proveedor con el expediente incompleto" if n == 1
                          else f"{n} proveedores con el expediente incompleto"),
                'detalle': ', '.join(p.nombre for p in proveedores_incompletos[:4]),
                'url': reverse('gestion:lista_dispositores'),
            })
        alertas.sort(key=lambda a: 0 if a['nivel'] == 'err' else 1)
        context['alertas'] = alertas[:14]
        context['alertas_criticas'] = sum(1 for a in alertas if a['nivel'] == 'err')
        context['alertas_restantes'] = max(len(alertas) - 14, 0)
        context['alertas_total'] = len(alertas)

        return context


# --- Vistas para Órdenes de Servicio ---
# Todas las vistas de gestión se protegen con LoginRequiredMixin.
# Se usa 'form_class' para conectar la vista con el formulario personalizado.
class ListaOrdenesView(AsesorRequiredMixin, PaginadoMixin, ListView):
    model = OrdenServicio
    template_name = 'gestion/lista_ordenes.html'
    context_object_name = 'ordenes'
    # De la orden más alta a la más baja (el número es el consecutivo).
    ordering = ['-numero_orden']

    def get_queryset(self):
        # La fecha que se lista es la de REALIZACIÓN del servicio (la del
        # recorrido), no la de creación de la orden en el sistema.
        queryset = super().get_queryset().annotate(
            fecha_servicio=Min('recorridos__fecha_recorrido'))
        query = self.request.GET.get('q')
        
        # --- LÓGICA DE FILTROS ---
        estado_filtro = self.request.GET.get('estado')
        pago_filtro = self.request.GET.get('pago')
        conciliacion_filtro = self.request.GET.get('conciliacion')

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

        # Filtro por conciliación de "Transporte - Cantidad"
        if conciliacion_filtro:
            queryset = queryset.filter(estado_conciliacion=conciliacion_filtro)

        return queryset

    # --- MÉTODO NUEVO PARA PASAR DATOS EXTRAS A LA PLANTILLA ---
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        # Pasamos las opciones de los modelos para construir los dropdowns
        context['estado_choices'] = OrdenServicio.ESTADO_ORDEN_CHOICES
        context['pago_choices'] = OrdenServicio.ESTADO_PAGO_CHOICES
        context['conciliacion_choices'] = OrdenServicio.CONCILIACION_CHOICES

        # Pasamos los valores actuales de los filtros para que se mantengan seleccionados
        context['current_estado'] = self.request.GET.get('estado', '')
        context['current_pago'] = self.request.GET.get('pago', '')
        context['current_conciliacion'] = self.request.GET.get('conciliacion', '')
        return context

# Las órdenes NO se crean a mano (se eliminó CrearOrdenView): siempre nacen de
# una programación, que valida personal/documentos y dispara los correos.
# ÚNICA excepción: las órdenes HISTÓRICAS (anteriores al consecutivo 22207),
# actas que ya se llenaron en físico y solo se archivan con su escaneo.
class OrdenHistoricaView(AsesorRequiredMixin, FormView):
    """
    Registra una orden anterior al arranque del sistema: número real del acta
    física, cliente, vehículo, fecha y el PDF/foto del acta. Queda finalizada
    y por fuera de conciliación y cobros; no dispara correos ni validaciones
    de personal.
    """
    template_name = 'gestion/orden_historica_form.html'
    form_class = OrdenHistoricaForm

    def form_valid(self, form):
        datos = form.cleaned_data
        with transaction.atomic():
            orden = OrdenServicio(
                numero_orden=datos['numero_orden'],
                cliente=datos['cliente'],
                asesor=self.request.user,
                direccion_servicio='',
                descripcion=(datos['descripcion'] or
                             'Orden histórica: acta diligenciada en físico.'),
                estado_orden='FINALIZADA',
                estado_pago='PAGADO',
                estado_conciliacion='NO_APLICA',
            )
            orden.save()
            Recorrido.objects.create(
                orden=orden, vehiculo=datos['vehiculo'],
                fecha_recorrido=datos['fecha_servicio'], estado='COMPLETADO')
            DocumentoOrden.objects.create(
                orden=orden, archivo=datos['acta'],
                descripcion='Acta de servicio diligenciada en físico')
        messages.success(
            self.request,
            f"Orden histórica #{orden.numero_orden} registrada con su acta.")
        return redirect('gestion:detalle_orden', pk=orden.pk)


class CambiarNumeroOrdenView(AdministradorRequiredMixin, View):
    """
    Solo administradores: cambia el número (consecutivo) de una orden y la
    coloca en su sitio, corriendo un puesto las que estorben para que la
    numeración no quede con huecos ni repetidos.
    """
    def post(self, request, pk):
        orden = get_object_or_404(OrdenServicio, pk=pk)
        crudo = (request.POST.get('numero_orden') or '').strip()
        if not crudo.isdigit() or int(crudo) <= 0:
            messages.error(request, "Escribe un número de orden válido.")
            return redirect('gestion:detalle_orden', pk=orden.pk)

        nuevo = int(crudo)
        if nuevo == orden.numero_orden:
            messages.info(request, "La orden ya tiene ese número.")
            return redirect('gestion:detalle_orden', pk=orden.pk)

        movimientos = reubicar_orden(orden.numero_orden, nuevo)
        corridas = len(movimientos) - 1
        aviso = f"La orden #{orden.numero_orden} ahora es la #{nuevo}."
        if corridas:
            aviso += (f" Se corrieron {corridas} orden(es) un puesto para "
                      f"hacerle sitio.")
        messages.success(request, aviso)
        return redirect('gestion:detalle_orden', pk=nuevo)


class ActualizarOrdenView(NoConductorRequiredMixin, UpdateView):
    """
    Edita los datos de la orden. Los recorridos NO se agregan aquí: cada orden
    nace de su programación con los que le corresponden (se pueden corregir o
    quitar uno a uno, pero no añadir nuevos).
    """
    model = OrdenServicio
    form_class = OrdenServicioForm
    template_name = 'gestion/form_orden.html'
    success_url = reverse_lazy('gestion:lista_ordenes')

    def form_valid(self, form):
        self.object = form.save()
        messages.success(self.request, "Orden actualizada.")
        return HttpResponseRedirect(self.get_success_url())

def _contactos_cliente(cliente):
    """Los contactos del cliente por área, saltando los que están vacíos."""
    areas = [
        ('Principal', 'persona_contacto', 'cargo_contacto', 'email', 'telefono'),
        ('Comercial', 'comercial_nombre', 'comercial_cargo', 'comercial_correo', 'comercial_telefono'),
        ('Contabilidad', 'contab_nombre', 'contab_cargo', 'contab_correo', 'contab_telefono'),
        ('Ambiental', 'ambiental_nombre', 'ambiental_cargo', 'ambiental_correo', 'ambiental_telefono'),
        ('SST', 'sst_nombre', 'sst_cargo', 'sst_correo', 'sst_telefono'),
    ]
    contactos = []
    for etiqueta, campo_nombre, campo_cargo, campo_correo, campo_tel in areas:
        nombre = (getattr(cliente, campo_nombre, '') or '').strip()
        correo = (getattr(cliente, campo_correo, '') or '').strip()
        telefono = (getattr(cliente, campo_tel, '') or '').strip()
        if not (nombre or correo or telefono):
            continue
        contactos.append({
            'etiqueta': etiqueta,
            'nombre': nombre or '—',
            'cargo': (getattr(cliente, campo_cargo, '') or '').strip(),
            'correo': correo,
            'telefono': telefono,
        })
    return contactos


class FichaClienteView(AsesorRequiredMixin, PaginadoMixin, ListView):
    """
    Expediente del cliente: su centro de control. Reúne los indicadores del
    histórico (servicios, satisfacción, conciliación), las gráficas, la lista
    paginada y filtrable de TODAS sus órdenes, y sus datos de contacto, sedes,
    terceros y documentos.
    """
    model = OrdenServicio
    template_name = 'gestion/ficha_cliente.html'
    context_object_name = 'ordenes'
    paginate_by = 15

    # Los once aspectos de la encuesta de satisfacción del acta, en el orden
    # en que se le preguntan al cliente.
    ASPECTOS = [
        ('eval_atencion', 'Atención'),
        ('eval_amabilidad', 'Amabilidad'),
        ('eval_solucion_inquietudes', 'Solución de inquietudes'),
        ('eval_asesoria', 'Asesoría'),
        ('eval_puntualidad', 'Puntualidad'),
        ('eval_calidad_servicio', 'Calidad del servicio'),
        ('eval_oportunidad', 'Oportunidad'),
        ('eval_cumplimiento_condiciones', 'Cumplimiento de condiciones'),
        ('eval_solucion_problemas', 'Solución de problemas'),
        ('eval_volveria_contratar', 'Volvería a contratar'),
        ('eval_nos_recomendaria', 'Nos recomendaría'),
    ]

    def get_cliente(self):
        if not hasattr(self, '_cliente'):
            self._cliente = get_object_or_404(Cliente, pk=self.kwargs['pk'])
        return self._cliente

    def _ordenes_del_cliente(self):
        """Todas las órdenes del cliente, con la fecha del servicio anotada."""
        return (OrdenServicio.objects
                .filter(cliente=self.get_cliente())
                .annotate(fecha_servicio=Min('recorridos__fecha_recorrido')))

    def get_queryset(self):
        qs = self._ordenes_del_cliente().prefetch_related(
            'recorridos__vehiculo', 'recorridos__manifiesto')
        pedido = self.request.GET
        if pedido.get('estado'):
            qs = qs.filter(estado_orden=pedido['estado'])
        if pedido.get('conciliacion'):
            qs = qs.filter(estado_conciliacion=pedido['conciliacion'])
        if pedido.get('anio'):
            qs = qs.filter(recorridos__fecha_recorrido__year=pedido['anio'])
        texto = (pedido.get('q') or '').strip()
        if texto:
            qs = qs.filter(
                Q(numero_orden__icontains=texto) |
                Q(direccion_servicio__icontains=texto))
        # Sin huecos ni repetidos al paginar: la más reciente primero.
        return qs.order_by('-numero_orden').distinct()

    def _indicadores(self, ordenes):
        """Las cifras de la cabecera, sobre TODO el histórico (sin filtros)."""
        hoy = timezone.localdate()
        recorridos = Recorrido.objects.filter(orden__cliente=self.get_cliente())
        firmadas = Manifiesto.objects.filter(
            recorrido__orden__cliente=self.get_cliente(), estado_firma='FIRMADO')

        promedios = firmadas.aggregate(
            **{campo: Avg(campo) for campo, _ in self.ASPECTOS})
        valores = [v for v in promedios.values() if v is not None]
        satisfaccion = sum(valores) / len(valores) if valores else None

        ultimo = recorridos.order_by('-fecha_recorrido').first()
        return {
            'total_ordenes': ordenes.count(),
            'ordenes_anio': ordenes.filter(
                recorridos__fecha_recorrido__year=hoy.year).distinct().count(),
            'ultimo_servicio': ultimo.fecha_recorrido if ultimo else None,
            'satisfaccion': satisfaccion,
            'actas_firmadas': firmadas.count(),
            'por_conciliar': ordenes.filter(estado_conciliacion='PENDIENTE').count(),
            'por_firmar': Manifiesto.objects.filter(
                recorrido__orden__cliente=self.get_cliente(),
                estado_firma='PENDIENTE_FIRMA').count(),
        }, promedios

    def _servicios_por_mes(self):
        """Los últimos 12 meses de servicios (incluidos los meses en cero)."""
        hoy = timezone.localdate()
        primero = (hoy.replace(day=1) - datetime.timedelta(days=334)).replace(day=1)
        filas = (Recorrido.objects
                 .filter(orden__cliente=self.get_cliente(),
                         fecha_recorrido__gte=primero)
                 .annotate(mes=TruncMonth('fecha_recorrido'))
                 .values('mes').annotate(n=Count('id')).order_by('mes'))
        conteo = {f['mes'].strftime('%Y-%m'): f['n'] for f in filas if f['mes']}

        MESES = ['ene', 'feb', 'mar', 'abr', 'may', 'jun',
                 'jul', 'ago', 'sep', 'oct', 'nov', 'dic']
        etiquetas, datos = [], []
        cursor = primero
        for _ in range(12):
            etiquetas.append(f"{MESES[cursor.month - 1]} {cursor.year % 100:02d}")
            datos.append(conteo.get(cursor.strftime('%Y-%m'), 0))
            # Primer día del mes siguiente.
            cursor = (cursor.replace(day=28) + datetime.timedelta(days=4)).replace(day=1)
        return etiquetas, datos

    def _servicios_por_lugar(self):
        """Dónde se le presta el servicio: sede, tercero o dirección."""
        conteo = {}
        for orden in (OrdenServicio.objects
                      .filter(cliente=self.get_cliente())
                      .select_related('programacion_origen__sede_cliente',
                                      'programacion_origen__tercero')):
            programacion = getattr(orden, 'programacion_origen', None)
            if programacion is not None and programacion.sede_cliente_id:
                lugar = programacion.sede_cliente.nombre
            elif programacion is not None and programacion.tercero_id:
                lugar = f"{programacion.tercero.nombre} (tercero)"
            else:
                lugar = orden.direccion_servicio or 'Sin lugar registrado'
            conteo[lugar] = conteo.get(lugar, 0) + 1
        # Los ocho lugares más frecuentes; el resto se agrupa.
        ordenado = sorted(conteo.items(), key=lambda par: -par[1])
        principales, resto = ordenado[:8], ordenado[8:]
        if resto:
            principales.append(('Otros lugares', sum(n for _l, n in resto)))
        return [l for l, _n in principales], [n for _l, n in principales]

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        cliente = self.get_cliente()
        todas = self._ordenes_del_cliente()
        indicadores, promedios = self._indicadores(todas)

        etiquetas_mes, datos_mes = self._servicios_por_mes()
        lugares, datos_lugar = self._servicios_por_lugar()
        aspectos = [
            {'etiqueta': etiqueta, 'valor': round(promedios[campo], 2)}
            for campo, etiqueta in self.ASPECTOS if promedios.get(campo) is not None
        ]

        anios = sorted(
            {f['anio'] for f in Recorrido.objects
             .filter(orden__cliente=cliente)
             .annotate(anio=ExtractYear('fecha_recorrido'))
             .values('anio') if f['anio']},
            reverse=True)

        context.update({
            'cliente': cliente,
            'indicadores': indicadores,
            'aspectos': aspectos,
            'anios': anios,
            'estado_choices': OrdenServicio.ESTADO_ORDEN_CHOICES,
            'conciliacion_choices': OrdenServicio.CONCILIACION_CHOICES,
            'filtros': {
                'q': self.request.GET.get('q', ''),
                'estado': self.request.GET.get('estado', ''),
                'conciliacion': self.request.GET.get('conciliacion', ''),
                'anio': self.request.GET.get('anio', ''),
            },
            'hay_filtros': any(self.request.GET.get(c) for c in
                               ('q', 'estado', 'conciliacion', 'anio')),
            # Series para las gráficas (las publica {{ graficas|json_script }}).
            'graficas': ({
                'meses': {'etiquetas': etiquetas_mes, 'datos': datos_mes},
                'lugares': {'etiquetas': lugares, 'datos': datos_lugar},
                'aspectos': {
                    'etiquetas': [a['etiqueta'] for a in aspectos],
                    'datos': [a['valor'] for a in aspectos],
                },
            }),
            'contactos': _contactos_cliente(cliente),
            'sedes': cliente.sedes.all(),
            'terceros': cliente.terceros.all(),
            'documentos_ambientales': cliente.documentos_ambientales.all(),
            'correos_enviados': EnvioCorreo.objects.filter(
                cliente=cliente).order_by('-fecha')[:5],
        })
        return context


# --- Vistas para Vehículos ---
class ListaVehiculosView(NoConductorRequiredMixin, PaginadoMixin, ListView):
    model = Vehiculo
    template_name = 'gestion/lista_vehiculos.html'
    context_object_name = 'vehiculos'
    # Orden estable: sin él la paginación puede repetir o saltarse filas.
    ordering = ['placa']

class CrearVehiculoView(NoConductorRequiredMixin, CreateView):
    model = Vehiculo
    form_class = VehiculoForm
    template_name = 'gestion/form_vehiculo.html'
    success_url = reverse_lazy('gestion:lista_vehiculos')

class ActualizarVehiculoView(NoConductorRequiredMixin, UpdateView):
    model = Vehiculo
    form_class = VehiculoForm
    template_name = 'gestion/form_vehiculo.html'
    success_url = reverse_lazy('gestion:lista_vehiculos')

# --- Vistas para Clientes ---
class ListaClientesView(NoConductorRequiredMixin, PaginadoMixin, ListView):
    model = Cliente
    template_name = 'gestion/lista_clientes.html'
    context_object_name = 'clientes'
    ordering = ['nombre']

    def get_queryset(self):
        """Busca por razón social, sigla, NIT, ciudad o persona de contacto."""
        queryset = super().get_queryset()
        q = self.request.GET.get('q', '').strip()
        if q:
            queryset = queryset.filter(
                Q(nombre__icontains=q) | Q(sigla__icontains=q)
                | Q(identificacion__icontains=q) | Q(ciudad__icontains=q)
                | Q(persona_contacto__icontains=q)
            )
        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['q'] = self.request.GET.get('q', '')
        return context


class ClienteFormMixin:
    """
    Maneja, además del cliente:
      - Las SEDES y los TERCEROS del cliente (formsets inline).
      - La carga MÚLTIPLE de documentos ambientales ('documentos_ambientales') y
        la eliminación de los marcados ('eliminar_doc_ambiental').
    """
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        if 'sede_formset' not in context:
            if self.request.method == 'POST':
                context['sede_formset'] = SedeFormSet(
                    self.request.POST, instance=self.object, prefix='sede'
                )
            else:
                context['sede_formset'] = SedeFormSet(instance=self.object, prefix='sede')
        if 'tercero_formset' not in context:
            if self.request.method == 'POST':
                context['tercero_formset'] = TerceroFormSet(
                    self.request.POST, instance=self.object, prefix='tercero'
                )
            else:
                context['tercero_formset'] = TerceroFormSet(instance=self.object, prefix='tercero')
        if 'doc_correo_formset' not in context:
            if self.request.method == 'POST':
                context['doc_correo_formset'] = DocumentoCorreoFormSet(
                    self.request.POST, self.request.FILES, instance=self.object, prefix='doccorreo'
                )
            else:
                context['doc_correo_formset'] = DocumentoCorreoFormSet(instance=self.object, prefix='doccorreo')
        return context

    def form_valid(self, form):
        # El cliente aún sin guardar, para enlazar los formsets.
        self.object = form.save(commit=False)
        sede_formset = SedeFormSet(self.request.POST, instance=self.object, prefix='sede')
        tercero_formset = TerceroFormSet(self.request.POST, instance=self.object, prefix='tercero')
        doc_correo_formset = DocumentoCorreoFormSet(
            self.request.POST, self.request.FILES, instance=self.object, prefix='doccorreo'
        )
        # Cliente + sedes + terceros + documentos se validan juntos: si algo falla, no se guarda nada.
        if not (sede_formset.is_valid() and tercero_formset.is_valid() and doc_correo_formset.is_valid()):
            return self.render_to_response(self.get_context_data(
                form=form, sede_formset=sede_formset, tercero_formset=tercero_formset,
                doc_correo_formset=doc_correo_formset
            ))
        self.object.save()
        for fs in (sede_formset, tercero_formset, doc_correo_formset):
            fs.instance = self.object
            fs.save()

        # Documentos ambientales (carga múltiple + eliminación de los marcados).
        ids_eliminar = self.request.POST.getlist('eliminar_doc_ambiental')
        if ids_eliminar:
            self.object.documentos_ambientales.filter(pk__in=ids_eliminar).delete()
        for archivo in self.request.FILES.getlist('documentos_ambientales'):
            DocumentoAmbientalCliente.objects.create(cliente=self.object, archivo=archivo)

        messages.success(self.request, "Cliente guardado.")
        return HttpResponseRedirect(self.get_success_url())


class CrearClienteView(ClienteFormMixin, NoConductorRequiredMixin, CreateView):
    model = Cliente
    form_class = ClienteForm
    template_name = 'gestion/form_cliente.html'
    success_url = reverse_lazy('gestion:lista_clientes')

class ActualizarClienteView(ClienteFormMixin, NoConductorRequiredMixin, UpdateView):
    model = Cliente
    form_class = ClienteForm
    template_name = 'gestion/form_cliente.html'
    success_url = reverse_lazy('gestion:lista_clientes')





class MarcarCargaVehiculoView(AsesorRequiredMixin, View):
    """
    Marca a mano la CARGA o la DESCARGA (disposición) de un camión, desde su
    expediente. Complementa el flujo automático de las órdenes: sirve cuando el
    residuo se dispone por fuera de una orden o el estado quedó mal. La nota es
    obligatoria y todo queda en el historial (MovimientoCargaVehiculo).
    """
    def post(self, request, pk):
        from .models import Dispositor, MovimientoCargaVehiculo
        vehiculo = get_object_or_404(Vehiculo, pk=pk)
        accion = request.POST.get('accion', '')
        nota = request.POST.get('nota', '').strip()
        destino = redirect('gestion:detalle_vehiculo', pk=pk)

        if accion not in ('CARGA', 'DESCARGA'):
            messages.error(request, "Acción no válida.")
            return destino
        if not nota:
            messages.error(
                request,
                "Escribe la nota: a dónde se dispuso el contenido (o de dónde "
                "viene la carga). Es la trazabilidad del residuo."
            )
            return destino
        if accion == 'DESCARGA' and not vehiculo.cargado:
            messages.info(request, f"El camión {vehiculo.placa} no está marcado como cargado.")
            return destino
        if accion == 'CARGA' and vehiculo.cargado:
            messages.info(
                request,
                f"El camión {vehiculo.placa} ya está marcado como cargado "
                f"({vehiculo.cargado_detalle})."
            )
            return destino

        dispositor = None
        if accion == 'DESCARGA':
            dispositor = Dispositor.objects.filter(
                pk=request.POST.get('dispositor') or 0, tipo='PROVEEDOR').first()
            vehiculo.cargado = False
            vehiculo.cargado_detalle = ''
            mensaje = f"Camión {vehiculo.placa} marcado como descargado."
        else:
            vehiculo.cargado = True
            vehiculo.cargado_detalle = f"Carga manual: {nota}"
            mensaje = f"Camión {vehiculo.placa} marcado como CARGADO, pendiente de disposición."
        vehiculo.save(update_fields=['cargado', 'cargado_detalle'])
        MovimientoCargaVehiculo.objects.create(
            vehiculo=vehiculo, accion=accion, nota=nota,
            dispositor=dispositor, registrado_por=request.user,
        )
        messages.success(request, mensaje)
        return destino


class VehiculoDetailView(NoConductorRequiredMixin, DetailView):
    model = Vehiculo
    template_name = 'gestion/vehiculo_detail.html'
    context_object_name = 'vehiculo'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        vehiculo = self.get_object()

        # --- Lógica de Agenda Diaria (ya es correcta) ---
        fecha_str = self.request.GET.get('fecha')
        if fecha_str:
            fecha_seleccionada = datetime.datetime.strptime(fecha_str, '%Y-%m-%d').date()
        else:
            fecha_seleccionada = timezone.localdate()
        
        context['fecha_seleccionada'] = fecha_seleccionada
        context['programacion_del_dia'] = Recorrido.objects.filter(
            vehiculo=vehiculo,
            fecha_recorrido=fecha_seleccionada
        ).order_by('orden__fecha_creacion')

        # --- Carga de residuo: historial y proveedores para la descarga manual ---
        from .models import Dispositor
        context['movimientos_carga'] = (
            vehiculo.movimientos_carga.select_related('dispositor', 'registrado_por')[:12]
        )
        context['proveedores_disposicion'] = Dispositor.objects.filter(
            tipo='PROVEEDOR', activo=True).order_by('nombre')

        # --- LÓGICA CORREGIDA PARA HISTORIAL Y MÉTRICAS ---
        # Ahora el historial se basa en los recorridos completados, no en las órdenes.
        historial_recorridos = Recorrido.objects.filter(vehiculo=vehiculo, estado='COMPLETADO').order_by('-fecha_recorrido')
        context['historial_recorridos'] = historial_recorridos
        
        # Las métricas ahora se calculan a partir del historial de recorridos.
        context['total_servicios_realizados'] = historial_recorridos.count()
        
        # Sumamos el valor de las órdenes padres de los recorridos completados.
        # Nota: Esto podría sumar una orden varias veces si el vehículo hizo varios recorridos para ella.
        ingresos_generados = historial_recorridos.aggregate(total=Sum('orden__valor_servicio'))
        context['total_ingresos_generados'] = ingresos_generados['total'] or 0

        # --- Filtros y aceites (mantenimiento) ---
        registros = list(vehiculo.filtros_aceites.all())   # ya ordenados: más reciente primero
        # Último cambio por tipo (el primero que aparece de cada tipo).
        resumen, vistos = [], set()
        for r in registros:
            if r.tipo not in vistos:
                vistos.add(r.tipo)
                resumen.append(r)
        context['filtros_registros'] = registros
        context['filtros_resumen'] = resumen
        context['form_filtro_aceite'] = FiltroAceiteForm(
            initial={'fecha_cambio': timezone.localdate()})
        # El registro lo gestionan asesores y superusuarios (el resto solo consulta).
        context['puede_gestionar_filtros'] = (
            es_administrador(self.request.user)
            or self.request.user.groups.filter(name='Asesores').exists()
        )
        return context



class RegistrarFiltroAceiteView(AsesorRequiredMixin, View):
    """Registra un cambio de filtro o aceite en el expediente del vehículo (solo POST)."""
    def post(self, request, pk):
        vehiculo = get_object_or_404(Vehiculo, pk=pk)
        form = FiltroAceiteForm(request.POST)
        if form.is_valid():
            registro = form.save(commit=False)
            registro.vehiculo = vehiculo
            registro.save()
            messages.success(
                request,
                f"{registro.get_tipo_display()} registrado "
                f"({registro.cantidad.normalize()} {registro.get_unidad_display()})."
            )
        else:
            errores = "; ".join(
                f"{form.fields[c].label or c}: {e[0]}" for c, e in form.errors.items()
            )
            messages.error(request, f"No se pudo registrar el cambio. {errores}")
        return redirect('gestion:detalle_vehiculo', pk=pk)


class EliminarFiltroAceiteView(AsesorRequiredMixin, View):
    """Elimina un registro de filtro/aceite del expediente del vehículo (solo POST)."""
    def post(self, request, pk):
        registro = get_object_or_404(FiltroAceite, pk=pk)
        vehiculo_pk = registro.vehiculo_id
        registro.delete()
        messages.success(request, "Registro eliminado del historial de filtros y aceites.")
        return redirect('gestion:detalle_vehiculo', pk=vehiculo_pk)


# --- HELPERS COMPARTIDOS PARA EL MANIFIESTO ---

def _puede_gestionar_manifiesto(user, recorrido):
    """Solo el conductor asignado, un Asesor o un superusuario pueden llenar el manifiesto."""
    return (
        es_administrador(user)
        or user.groups.filter(name='Asesores').exists()
        or recorrido.conductor_id == user.id
    )


def _guardar_firma_cliente(manifiesto, signature_data, pk):
    """Decodifica la firma en base64 (data-URL) y la guarda en el manifiesto."""
    formato, imgstr = signature_data.split(';base64,')
    ext = formato.split('/')[-1]
    signature_file = ContentFile(base64.b64decode(imgstr), name=f'firma_cliente_{pk}.{ext}')
    manifiesto.firma_cliente.save(signature_file.name, signature_file, save=True)


def _pdf_manifiesto(manifiesto, request):
    """
    Renderiza el acta (manifiesto) a PDF y devuelve los bytes. NO se guarda en
    el storage: se genera al momento de descargarla, así siempre sale con los
    datos vigentes (si gestión corrige algo después de la firma —decisión del
    usuario—, el PDF se regenera al día en la próxima descarga).
    """
    recorrido = manifiesto.recorrido
    template = get_template('gestion/manifiesto_pdf.html')

    # 1. Logo a base64
    logo_path = os.path.join(settings.BASE_DIR, 'static', 'images', 'logo-solmed.png')
    with open(logo_path, "rb") as image_file:
        logo_b64 = "data:image/png;base64," + base64.b64encode(image_file.read()).decode('utf-8')

    # 2. Firma a base64
    firma_cliente_b64 = None
    if manifiesto.firma_cliente:
        # .open() funciona tanto con el storage local como con S3 (a diferencia de .path).
        with manifiesto.firma_cliente.open("rb") as image_file:
            firma_cliente_b64 = "data:image/png;base64," + base64.b64encode(image_file.read()).decode('utf-8')

    context = {
        'manifiesto': manifiesto, 'recorrido': recorrido, 'orden': recorrido.orden,
        'logo_b64': logo_b64, 'firma_cliente_b64': firma_cliente_b64,
    }
    html_string = template.render(context)
    html = HTML(string=html_string, base_url=request.build_absolute_uri())
    return html.write_pdf()


class ActaPDFView(NoConductorRequiredMixin, View):
    """
    Descarga el PDF del acta de servicio, generado al momento con los datos
    vigentes. Solo gestión: el conductor no accede al acta como documento.
    """
    def get(self, request, pk):
        recorrido = get_object_or_404(Recorrido, pk=pk)
        manifiesto = getattr(recorrido, 'manifiesto', None)
        if manifiesto is None:
            raise Http404("Este recorrido aún no tiene acta de servicio.")
        respuesta = HttpResponse(
            _pdf_manifiesto(manifiesto, request),
            content_type='application/pdf')
        respuesta['Content-Disposition'] = (
            f'attachment; filename="acta_servicio_recorrido_{recorrido.pk}.pdf"')
        return respuesta


def _pdf_encuesta_conductor(encuesta, request):
    """
    Renderiza la encuesta de cierre a PDF y devuelve los bytes. NO se guarda
    en el storage: la base de datos es la fuente de verdad y el documento se
    genera al momento de descargarlo (siempre con el diseño vigente).
    """
    recorrido = encuesta.recorrido
    template = get_template('gestion/encuesta_conductor_pdf.html')

    logo_path = os.path.join(settings.BASE_DIR, 'static', 'images', 'logo-solmed.png')
    with open(logo_path, "rb") as image_file:
        logo_b64 = "data:image/png;base64," + base64.b64encode(image_file.read()).decode('utf-8')

    context = {
        'encuesta': encuesta,
        'recorrido': recorrido,
        'orden': recorrido.orden,
        'logo_b64': logo_b64,
        # Números de las preguntas cuya respuesta exige atención (veredicto).
        'preguntas_alerta': [
            str(r['numero']) for r in encuesta.respuestas() if r['alerta']],
    }
    html_string = template.render(context)
    html = HTML(string=html_string, base_url=request.build_absolute_uri())
    return html.write_pdf()


class EncuestaConductorPDFView(LoginRequiredMixin, View):
    """
    Descarga el PDF de la encuesta de cierre de un recorrido, generado al
    momento. El conductor solo puede bajar la de SUS recorridos; gestión, la
    de cualquiera.
    """
    def get(self, request, pk):
        recorrido = get_object_or_404(Recorrido, pk=pk)
        es_conductor = request.user.groups.filter(name='Conductores').exists()
        if es_conductor and recorrido.conductor_id != request.user.id:
            raise Http404("Ese recorrido no es tuyo.")
        encuesta = getattr(recorrido, 'encuesta_conductor', None)
        if encuesta is None:
            raise Http404("Este recorrido aún no tiene encuesta de cierre.")
        respuesta = HttpResponse(
            _pdf_encuesta_conductor(encuesta, request),
            content_type='application/pdf')
        respuesta['Content-Disposition'] = (
            f'attachment; filename="encuesta_cierre_recorrido_{recorrido.pk}.pdf"')
        return respuesta


def _qr_data_uri(url):
    """Genera un PNG de código QR para la URL dada y lo devuelve como data-URI base64."""
    qr_img = qrcode.make(url)
    buffer = BytesIO()
    qr_img.save(buffer, format='PNG')
    return "data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode('utf-8')


def _programacion_de(recorrido):
    """Programación que originó la orden del recorrido, o None (órdenes manuales)."""
    orden = recorrido.orden
    if orden is None:
        return None
    return getattr(orden, 'programacion_origen', None)


def _instrucciones_servicio_de(recorrido):
    """Primera parte del acta definida por el asesor en la programación (o {})."""
    programacion = _programacion_de(recorrido)
    return programacion.instrucciones_acta() if programacion else {}


def _resumen_instrucciones_de(recorrido):
    """Resumen legible de las instrucciones del asesor para mostrárselo fijo al conductor."""
    programacion = _programacion_de(recorrido)
    return programacion.resumen_instrucciones() if programacion else []


def _acta_para_vista(recorrido):
    """
    Acta a mostrar en formato documento. Si el conductor ya la diligenció,
    devuelve el Manifiesto real; si no, uno SIN GUARDAR con las instrucciones
    del asesor (para previsualizar "hasta donde va"). Devuelve (acta, estado):
      - 'FIRMADA'    : el cliente ya firmó.
      - 'DILIGENCIADA': el conductor la llenó, falta firma del cliente.
      - 'PENDIENTE'  : solo hay instrucciones del asesor.
    """
    try:
        manifiesto = recorrido.manifiesto
    except Manifiesto.DoesNotExist:
        # OJO: NO pasar recorrido=recorrido; enlazar el recorrido a este Manifiesto
        # sin guardar contaminaría la caché inversa recorrido.manifiesto y haría
        # creer a las plantillas que el acta ya existe. El recorrido viaja aparte
        # en el contexto de la plantilla.
        datos = _instrucciones_servicio_de(recorrido)
        auxiliar1, auxiliar2 = recorrido.auxiliares
        return Manifiesto(
            auxiliar1=auxiliar1, auxiliar2=auxiliar2,
            nombre_responsable_empresa=recorrido.responsable_empresa, **datos
        ), 'PENDIENTE'
    estado = 'FIRMADA' if manifiesto.estado_firma == 'FIRMADO' else 'DILIGENCIADA'
    return manifiesto, estado


def _actas_formato(recorridos):
    """[{recorrido, acta, estado}] para embeber el acta (formato documento) en la orden."""
    resultado = []
    for recorrido in recorridos:
        acta, estado = _acta_para_vista(recorrido)
        resultado.append({'recorrido': recorrido, 'acta': acta, 'estado': estado})
    return resultado


class ActaFormatoView(NoConductorRequiredMixin, View):
    """
    Vista del acta (Orden de Servicio) en el MISMO formato del PDF final, pero en
    la plataforma y pre-llenada "hasta donde va": las instrucciones del asesor
    (definidas en la programación) más lo que el conductor haya diligenciado.
    Solo para gestión (asesor/superusuario): el CONDUCTOR NO accede al acta como
    documento ni la descarga; él solo la diligencia (asistente) y muestra el QR.
    """
    template_name = 'gestion/acta_formato.html'

    def get(self, request, pk):
        recorrido = get_object_or_404(Recorrido, pk=pk)
        acta, estado = _acta_para_vista(recorrido)
        return render(request, self.template_name, {
            'recorrido': recorrido, 'orden': recorrido.orden,
            'manifiesto': acta, 'estado_acta': estado,
        })


# Ícono de cada novedad operacional (para las tarjetas táctiles de la hoja).
NOVEDAD_ICONOS = {
    'HOROMETRO': 'bi-speedometer',
    'MONTALLANTAS': 'bi-tools',
    'STANDBY': 'bi-pause-circle',
    'VARADA': 'bi-cone-striped',
    'TANQUEO_EXTERNO': 'bi-fuel-pump',
    'CAMBIO_CONDUCTOR': 'bi-people',
    'COMPRA_REPUESTO': 'bi-bag',
    'DEMORA_DISPOSITOR': 'bi-hourglass-split',
    'DEMORA_CLIENTE': 'bi-hourglass',
    'RETEN_POLICIA': 'bi-shield-check',
    'INMOVILIZACION': 'bi-sign-stop',
    'APOYO': 'bi-life-preserver',
}


def _formularios_novedades(manifiesto, data=None):
    """
    Las 12 filas de NOVEDADES OPERACIONALES del formato, con lo ya guardado.
    Devuelve [(tipo, etiqueta, icono, form)] en el orden de la hoja.
    """
    from .forms import NovedadOperacionalForm
    guardadas = {}
    if manifiesto is not None:
        guardadas = {n.tipo: n for n in manifiesto.novedades_operacionales.all()}
    filas = []
    for tipo, etiqueta in NovedadOperacional.TIPO_CHOICES:
        n = guardadas.get(tipo)
        inicial = {
            'marcada': n is not None,
            'observacion': n.observacion if n else '',
            'hora_inicio': n.hora_inicio if n else None,
            'hora_final': n.hora_final if n else None,
        }
        filas.append((tipo, etiqueta, NOVEDAD_ICONOS.get(tipo, 'bi-flag'),
                      NovedadOperacionalForm(data, prefix=f'nov-{tipo}', initial=inicial)))
    return filas


def _formularios_acpm(manifiesto, data=None, files=None):
    """Las 3 casillas de CONTROL DE ACPM, con lo ya guardado."""
    from .forms import MedidaACPMForm
    guardadas = {}
    if manifiesto is not None:
        guardadas = {m.tipo: m for m in manifiesto.medidas_acpm.all()}
    filas = []
    for tipo, etiqueta in MedidaACPM.TIPO_CHOICES:
        m = guardadas.get(tipo)
        filas.append((tipo, etiqueta, m,
                      MedidaACPMForm(data, files, prefix=f'acpm-{tipo}',
                                     initial={'medida': m.medida if m else ''})))
    return filas


def _guardar_novedades_y_acpm(manifiesto, filas_novedades, filas_acpm):
    """
    Escribe lo marcado en la hoja: las novedades sin datos se borran (el
    conductor pudo desmarcarlas) y las fotos de ACPM solo se reemplazan si
    subió una nueva.
    """
    for tipo, _etiqueta, _icono, form in filas_novedades:
        if form.tiene_datos():
            NovedadOperacional.objects.update_or_create(
                manifiesto=manifiesto, tipo=tipo,
                defaults={
                    'observacion': form.cleaned_data['observacion'],
                    'hora_inicio': form.cleaned_data['hora_inicio'],
                    'hora_final': form.cleaned_data['hora_final'],
                },
            )
        else:
            NovedadOperacional.objects.filter(manifiesto=manifiesto, tipo=tipo).delete()

    for tipo, _etiqueta, _previa, form in filas_acpm:
        medida = form.cleaned_data['medida']
        foto = form.cleaned_data['foto']
        if not medida and not foto:
            continue
        registro, _creada = MedidaACPM.objects.get_or_create(
            manifiesto=manifiesto, tipo=tipo)
        registro.medida = medida
        if foto:
            registro.foto = foto
        registro.save()


# ============================================================
#  NOTA DE NOMENCLATURA: en el back se llama "Manifiesto" (modelo, estas
#  vistas y URLs manifiesto_*); en el front se muestra como "ACTA DE SERVICIO".
#  Es la ejecución de la orden que firma el cliente. Ver Manifiesto en models.py.
# ============================================================
class GenerarManifiestoView(LoginRequiredMixin, View):
    """
    Wizard que llena EL CONDUCTOR: solo los datos operativos (paso3 y paso4).
    La primera parte del acta (Succión/Sondeo/Lavado/Transporte) NO la llena el
    conductor: son las instrucciones que definió el asesor en la programación y se
    copian al acta al cerrarla. Al terminar se persiste el manifiesto (acta de
    servicio) y se redirige al QR; la encuesta de satisfacción y la firma las
    completa el cliente en su propio dispositivo (EncuestaPublicaView).
    """
    # El asistente son DOS pasos. Los que faltan no los llena el conductor:
    #  - Las instrucciones (Succión/Sondeo/Lavado/Transporte) las define el
    #    asesor en la programación y se copian al acta al cerrarla (ver post()).
    #  - El paso de repaso de la orden se quitó: el conductor ya viene de la
    #    orden y el checklist del asesor sale en la propia hoja (paso3).
    FORMS = [
        ("paso3", ManifiestoPaso3Form), ("paso4", ManifiestoPaso4Form),
    ]
    TEMPLATES = {
        "paso3": 'gestion/manifiesto_wizard/paso3.html',
        "paso4": 'gestion/manifiesto_wizard/paso4.html',
    }

    def get_form_step(self, step_name):
        for name, form_class in self.FORMS:
            if name == step_name:
                return form_class
        return None

    def dispatch(self, request, *args, **kwargs):
        # Control de propiedad: evita que un usuario llene el manifiesto de otro recorrido.
        if request.user.is_authenticated:
            recorrido = get_object_or_404(Recorrido, pk=kwargs.get('pk'))
            if not _puede_gestionar_manifiesto(request.user, recorrido):
                messages.error(request, "No tienes permiso para llenar esta acta de servicio.")
                return redirect('gestion:dashboard_redirect')
            # Firmada por el cliente, el CONDUCTOR ya no la toca (ni desde una
            # pestaña que quedó abierta). Gestión sí puede corregir datos
            # pendientes; el estado de la firma no se altera en ningún caso.
            manifiesto = Manifiesto.objects.filter(recorrido=recorrido).first()
            if (manifiesto is not None and manifiesto.estado_firma == 'FIRMADO'
                    and request.user.groups.filter(name='Conductores').exists()):
                messages.info(
                    request,
                    "El cliente ya firmó el acta de este servicio: quedó "
                    "cerrada. Si hay que corregir algo, avísale a la oficina."
                )
                return redirect('gestion:detalle_orden_conductor', pk=recorrido.orden_id)
        return super().dispatch(request, *args, **kwargs)

    def get(self, request, pk, step='paso3'):
        recorrido = get_object_or_404(Recorrido, pk=pk)
        manifiesto_data = request.session.get(f'manifiesto_data_{pk}', {})
        try:
            manifiesto_instance = recorrido.manifiesto
        except Manifiesto.DoesNotExist:
            manifiesto_instance = None

        FormClass = self.get_form_step(step)
        template_path = self.TEMPLATES.get(step)
        if not FormClass or not template_path:
            messages.error(request, "Paso de formulario inválido.")
            return redirect('gestion:detalle_orden', pk=recorrido.orden.pk)

        form = FormClass(initial=manifiesto_data, instance=manifiesto_instance)

        auxiliar1, auxiliar2 = recorrido.auxiliares
        contexto = {
            'responsable_empresa': recorrido.responsable_empresa,
            'recorrido': recorrido, 'form': form, 'current_step': step, 'pk': pk,
            'manifiesto_instance': manifiesto_instance,
            'instrucciones_resumen': _resumen_instrucciones_de(recorrido),
            'auxiliar1': auxiliar1, 'auxiliar2': auxiliar2,
        }
        if step == 'paso3':
            contexto.update(self._contexto_hoja(recorrido, manifiesto_instance))
        return render(request, template_path, contexto)

    def _contexto_hoja(self, recorrido, manifiesto, data=None, files=None):
        """Bloques del formato que acompañan a tiempos y kilómetros."""
        programacion = _programacion_de(recorrido)
        izquierda, derecha = (programacion.resumen_checklist() if programacion
                              else ([], []))
        return {
            'checklist_izq': izquierda,
            'checklist_der': derecha,
            'filas_novedades': _formularios_novedades(manifiesto, data),
            'filas_acpm': _formularios_acpm(manifiesto, data, files),
        }

    def post(self, request, pk, step='paso3'):
        recorrido = get_object_or_404(Recorrido, pk=pk)
        manifiesto_data = request.session.get(f'manifiesto_data_{pk}', {})
        try:
            manifiesto_instance = recorrido.manifiesto
        except Manifiesto.DoesNotExist:
            manifiesto_instance = None

        FormClass = self.get_form_step(step)
        if FormClass is None:
            messages.error(request, "Paso de formulario inválido.")
            return redirect('gestion:detalle_orden', pk=recorrido.orden.pk)

        form = FormClass(request.POST, instance=manifiesto_instance)
        # El paso de tiempos trae además las novedades operacionales y el ACPM.
        extra = {}
        if step == 'paso3':
            extra = self._contexto_hoja(recorrido, manifiesto_instance,
                                        request.POST, request.FILES)
        subformularios_ok = all(
            f.is_valid() for _t, _e, _i, f in extra.get('filas_novedades', [])
        ) and all(f.is_valid() for _t, _e, _p, f in extra.get('filas_acpm', []))

        if not form.is_valid() or not subformularios_ok:
            messages.error(request, "Por favor, corrija los errores en el formulario.")
            return render(request, self.TEMPLATES[step], {
                'recorrido': recorrido, 'form': form, 'current_step': step, 'pk': pk,
                'instrucciones_resumen': _resumen_instrucciones_de(recorrido),
                **extra,
            })

        if step == 'paso3':
            # Las novedades y el ACPM cuelgan del acta (y las fotos no caben en
            # la sesión): se persiste el acta ya mismo y se guardan de una vez.
            # Los pasos siguientes actualizan esta misma acta.
            if manifiesto_instance is None:
                auxiliar1, auxiliar2 = recorrido.auxiliares
                manifiesto_instance = Manifiesto.objects.create(
                    recorrido=recorrido,
                    **_instrucciones_servicio_de(recorrido),
                    auxiliar1=auxiliar1, auxiliar2=auxiliar2,
                    nombre_responsable_empresa=recorrido.responsable_empresa,
                    estado_firma='PENDIENTE_FIRMA',
                )
            # Los tiempos y kilómetros se escriben ya sobre esa acta (no solo
            # en la sesión): así lo guardado coincide con lo que se ve al volver.
            for campo, valor in form.cleaned_data.items():
                setattr(manifiesto_instance, campo, valor)
            manifiesto_instance.save()
            _guardar_novedades_y_acpm(
                manifiesto_instance, extra['filas_novedades'], extra['filas_acpm'])

        # Acumulamos los datos del paso en la sesión (serializando tipos no JSON).
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

        # --- Último paso del conductor: persistir el manifiesto y pasar al QR ---
        # La primera parte del acta (Succión/Sondeo/Lavado/Transporte) no la llena
        # el conductor: la definió el asesor en la programación. Se copia aquí.
        instrucciones = _instrucciones_servicio_de(recorrido)
        # Los auxiliares son los ayudantes que asignó el asesor: se copian del
        # recorrido, el conductor no los edita.
        auxiliar1, auxiliar2 = recorrido.auxiliares
        # OJO: el estado de la firma NO va en los defaults. Antes se forzaba a
        # PENDIENTE_FIRMA y eso "desfirmaba" un acta que el cliente acababa de
        # firmar (pestaña del conductor abierta mientras el cliente firmaba),
        # reviviendo el enlace público. Un acta nueva ya nace pendiente por el
        # default del modelo; una firmada, firmada se queda.
        Manifiesto.objects.update_or_create(
            recorrido=recorrido,
            defaults={
                **instrucciones, **manifiesto_data,
                'auxiliar1': auxiliar1, 'auxiliar2': auxiliar2,
                # El responsable SOLMED es el conductor: tampoco lo escribe él.
                'nombre_responsable_empresa': recorrido.responsable_empresa,
            },
        )
        if f'manifiesto_data_{pk}' in request.session:
            del request.session[f'manifiesto_data_{pk}']
        # De vuelta a la orden: las tareas son independientes y el QR del
        # cliente es otra tarea de la lista (puede ir antes o después).
        messages.success(request, "Datos del servicio guardados.")
        if recorrido.conductor_id == request.user.id:
            return redirect('gestion:detalle_orden_conductor', pk=recorrido.orden_id)
        return redirect('gestion:detalle_orden', pk=recorrido.orden_id)


def _acta_lista_para_firmar(manifiesto):
    """
    ¿El conductor ya diligenció lo suyo? Se mira lo que él llena en el
    asistente (tiempos y kilómetros): si está vacío y el cliente firma, el
    acta queda sin esos datos. Sirve para advertirlo, no para bloquear.
    """
    campos = ('tiempo_inicio_operativo', 'tiempo_final_operativo',
              'hora_salida_solmed', 'hora_llegada_solmed')
    return any(getattr(manifiesto, campo, None) not in (None, '') for campo in campos)


class ManifiestoQRView(LoginRequiredMixin, View):
    """
    QR y enlace público para que el cliente responda la encuesta y firme.
    Lo usa el conductor al cerrar el acta y también el asesor desde el
    expediente de la orden (para enviárselo al cliente por su cuenta).

    Si el acta todavía no existe, se crea aquí con lo que definió el asesor en
    la programación: así el enlace se puede generar y compartir aunque el
    conductor no haya llegado al último paso. Lo que él llena después se
    actualiza sobre la misma acta.
    """
    template_name = 'gestion/manifiesto_wizard/qr.html'

    def get(self, request, pk):
        recorrido = get_object_or_404(Recorrido, pk=pk)
        if not _puede_gestionar_manifiesto(request.user, recorrido):
            messages.error(request, "No tienes permiso para ver esta acta de servicio.")
            return redirect('gestion:dashboard_redirect')

        try:
            manifiesto = recorrido.manifiesto
        except Manifiesto.DoesNotExist:
            auxiliar1, auxiliar2 = recorrido.auxiliares
            manifiesto = Manifiesto.objects.create(
                recorrido=recorrido,
                **_instrucciones_servicio_de(recorrido),
                auxiliar1=auxiliar1, auxiliar2=auxiliar2,
                nombre_responsable_empresa=recorrido.responsable_empresa,
                estado_firma='PENDIENTE_FIRMA',
            )

        url_publica = request.build_absolute_uri(
            reverse('gestion:encuesta_publica', kwargs={'token': manifiesto.token_publico})
        )
        return render(request, self.template_name, {
            'recorrido': recorrido,
            'manifiesto': manifiesto,
            'url_publica': url_publica,
            'qr_b64': _qr_data_uri(url_publica),
            'acta_diligenciada': _acta_lista_para_firmar(manifiesto),
            # El conductor cierra su flujo aquí; el asesor vuelve a la orden.
            'es_asesor_viendo': recorrido.conductor_id != request.user.id,
        })


@login_required
def manifiesto_estado_json(request, pk):
    """Endpoint de polling para que la pantalla del QR detecte cuándo firma el cliente."""
    recorrido = get_object_or_404(Recorrido, pk=pk)
    # Solo el conductor asignado, un asesor o un superusuario (mismo criterio
    # del asistente del acta): sin esto, cualquier usuario podía sondear el
    # estado y el PDF de actas ajenas.
    if not _puede_gestionar_manifiesto(request.user, recorrido):
        return JsonResponse({'error': 'Sin permiso para consultar esta acta.'}, status=403)
    try:
        manifiesto = recorrido.manifiesto
    except Manifiesto.DoesNotExist:
        return JsonResponse({'firmado': False, 'pdf_url': None})

    try:
        recorrido.encuesta_conductor
        encuesta_pendiente = False
    except EncuestaConductor.DoesNotExist:
        encuesta_pendiente = True
    return JsonResponse({
        'firmado': manifiesto.estado_firma == 'FIRMADO',
        'encuesta_pendiente': encuesta_pendiente,
        'encuesta_url': reverse('gestion:encuesta_conductor', kwargs={'pk': pk}),
    })


class EncuestaConductorView(LoginRequiredMixin, View):
    """
    Encuesta de cierre (PESV + gestión ambiental) que llena EL CONDUCTOR tras
    firmarse el manifiesto del cliente. Diligenciarla marca el recorrido como
    COMPLETADO. Solo el conductor asignado, un Asesor o un superusuario acceden.
    """
    template_name = 'gestion/encuesta_conductor.html'

    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated:
            recorrido = get_object_or_404(Recorrido, pk=kwargs.get('pk'))
            if not _puede_gestionar_manifiesto(request.user, recorrido):
                messages.error(request, "No tienes permiso para llenar esta encuesta.")
                return redirect('gestion:dashboard_redirect')
        return super().dispatch(request, *args, **kwargs)

    def _get_instancia(self, recorrido):
        try:
            return recorrido.encuesta_conductor
        except EncuestaConductor.DoesNotExist:
            return None

    def get(self, request, pk):
        recorrido = get_object_or_404(Recorrido, pk=pk)
        instancia = self._get_instancia(recorrido)
        return render(request, self.template_name, {
            'recorrido': recorrido,
            'form': EncuestaConductorForm(instance=instancia),
            'ya_diligenciada': instancia is not None,
        })

    def post(self, request, pk):
        recorrido = get_object_or_404(Recorrido, pk=pk)
        instancia = self._get_instancia(recorrido)
        form = EncuestaConductorForm(request.POST, instance=instancia)
        if form.is_valid():
            encuesta = form.save(commit=False)
            encuesta.recorrido = recorrido
            encuesta.save()  # marca el recorrido como COMPLETADO
            messages.success(
                request,
                "Encuesta de cierre registrada. El recorrido fue marcado como completado."
            )
            return redirect('gestion:dashboard_redirect')
        messages.error(request, "Por favor, corrige los errores en la encuesta.")
        return render(request, self.template_name, {
            'recorrido': recorrido,
            'form': form,
            'ya_diligenciada': instancia is not None,
        })


class EncuestaPublicaView(View):
    """
    Página PÚBLICA (sin login) que abre el cliente al escanear el QR.
    Contiene la encuesta de satisfacción (paso5) + la firma de conformidad.
    Es de un solo uso: una vez FIRMADO, el token deja de ser utilizable.
    """
    template_name = 'gestion/manifiesto_wizard/encuesta_publica.html'
    template_gracias = 'gestion/manifiesto_wizard/encuesta_gracias.html'

    def get(self, request, token):
        manifiesto = get_object_or_404(Manifiesto, token_publico=token)
        if manifiesto.estado_firma == 'FIRMADO':
            return render(request, self.template_gracias, {
                'manifiesto': manifiesto, 'ya_firmado': True,
            })
        return render(request, self.template_name, {
            'manifiesto': manifiesto,
            'recorrido': manifiesto.recorrido,
            'orden': manifiesto.recorrido.orden,
            'form': ManifiestoPaso5Form(instance=manifiesto),
        })

    def post(self, request, token):
        manifiesto = get_object_or_404(Manifiesto, token_publico=token)
        if manifiesto.estado_firma == 'FIRMADO':
            return render(request, self.template_gracias, {
                'manifiesto': manifiesto, 'ya_firmado': True,
            })

        form = ManifiestoPaso5Form(request.POST, instance=manifiesto)
        signature_data = request.POST.get('signature_data')
        nombre_responsable_cliente = request.POST.get('nombre_responsable_cliente')

        if form.is_valid() and signature_data and nombre_responsable_cliente:
            # Todo o nada: si la imagen de la firma no se puede guardar, el
            # acta NO queda marcada como firmada (y el cliente puede volver a
            # intentarlo). El PDF ya no se genera aquí: sale al momento de
            # descargarlo, siempre con los datos vigentes.
            with transaction.atomic():
                manifiesto = form.save(commit=False)
                manifiesto.nombre_responsable_cliente = nombre_responsable_cliente
                manifiesto.estado_firma = 'FIRMADO'
                manifiesto.save()
                _guardar_firma_cliente(manifiesto, signature_data, manifiesto.recorrido.pk)

            return render(request, self.template_gracias, {
                'manifiesto': manifiesto, 'ya_firmado': False,
            })

        if not signature_data or not nombre_responsable_cliente:
            messages.error(request, 'Falta la firma o el nombre de quien recibe.')
        else:
            messages.error(request, 'Por favor, corrija los errores en la encuesta.')
        return render(request, self.template_name, {
            'manifiesto': manifiesto,
            'recorrido': manifiesto.recorrido,
            'orden': manifiesto.recorrido.orden,
            'form': form,
        })



# ============================================================
#  BORRADO DE REGISTROS "NUEVOS" (sin uso todavía)
#  Solo administradores. No se hardcodea qué relaciones bloquean: se intenta
#  borrar y, si la base lo protege (ProtectedError), se explica qué lo impide.
#  Así sigue siendo correcto aunque mañana se agreguen relaciones.
# ============================================================

def _resumen_protegido(error):
    """'2 órdenes de servicio, 1 programación' a partir de un ProtectedError."""
    from collections import Counter
    conteo = Counter(
        obj._meta.verbose_name for obj in getattr(error, 'protected_objects', [])
    )
    if not conteo:
        return "tiene registros asociados"
    partes = []
    for nombre, n in conteo.most_common(4):
        partes.append(f"{n} {nombre}{'' if n == 1 else 's'}")
    return ", ".join(partes)


def _eliminar_si_no_tiene_uso(request, objeto, etiqueta, destino):
    """
    Borra el objeto si nada lo referencia; si está en uso, no borra nada y
    explica por qué. Devuelve la redirección correspondiente.
    """
    from django.db.models import ProtectedError
    nombre = str(objeto)
    try:
        with transaction.atomic():
            objeto.delete()
    except ProtectedError as e:
        messages.error(
            request,
            f"No se puede eliminar {etiqueta} «{nombre}»: ya está en uso "
            f"({_resumen_protegido(e)}). Solo se pueden eliminar registros nuevos, "
            f"sin movimientos."
        )
    else:
        messages.success(request, f"{etiqueta.capitalize()} «{nombre}» eliminado.")
    return redirect(destino)


# --- Mixin para las vistas de administración de la plataforma ---
# Superusuario y rol 'Administradores' (usuarios, reportes). El nombre viejo
# SuperuserRequiredMixin se conserva como alias por compatibilidad.
class EliminarClienteView(AdministradorRequiredMixin, View):
    """Elimina un cliente que aún no tiene órdenes ni programaciones (solo POST)."""
    def post(self, request, pk):
        cliente = get_object_or_404(Cliente, pk=pk)
        return _eliminar_si_no_tiene_uso(request, cliente, 'el cliente', 'gestion:lista_clientes')


class EliminarVehiculoView(AdministradorRequiredMixin, View):
    """Elimina un vehículo que aún no se ha usado en recorridos ni cuadrillas."""
    def post(self, request, pk):
        vehiculo = get_object_or_404(Vehiculo, pk=pk)
        return _eliminar_si_no_tiene_uso(request, vehiculo, 'el vehículo', 'gestion:lista_vehiculos')


class EliminarDispositorView(AdministradorRequiredMixin, View):
    """Elimina un proveedor de disposición que aún no se ha usado."""
    def post(self, request, pk):
        dispositor = get_object_or_404(Dispositor, pk=pk, tipo='PROVEEDOR')
        return _eliminar_si_no_tiene_uso(
            request, dispositor, 'el proveedor', 'gestion:lista_dispositores')


class EliminarPersonaView(AdministradorRequiredMixin, View):
    """
    Elimina a una persona que todavía no ha participado en ningún servicio
    (ni como conductor, ayudante, asesor o creador de programaciones). Con su
    expediente y perfil, que son datos suyos. No se puede eliminar a un
    superusuario ni a uno mismo.
    """
    def post(self, request, pk):
        persona = get_object_or_404(User, pk=pk)
        if persona.is_superuser:
            messages.error(request, "No se puede eliminar la cuenta de un superadministrador.")
            return redirect('gestion:ficha_persona', pk=pk)
        if persona.pk == request.user.pk:
            messages.error(request, "No puedes eliminar tu propia cuenta.")
            return redirect('gestion:ficha_persona', pk=pk)
        return _eliminar_si_no_tiene_uso(request, persona, 'la persona', 'gestion:lista_personal')

# --- Vistas para Administración de Usuarios ---

class ListaUsuariosView(SuperuserRequiredMixin, PaginadoMixin, ListView):
    model = User
    template_name = 'gestion/lista_usuarios.html'
    context_object_name = 'usuarios'
    ordering = ['first_name', 'username']

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

class ActualizarUsuarioView(AdministradorRequiredMixin, SuccessMessageMixin, UpdateView):
    model = User
    form_class = ActualizarUsuarioForm
    template_name = 'gestion/form_usuario.html'
    success_url = reverse_lazy('gestion:lista_usuarios')
    success_message = "¡Usuario actualizado exitosamente!"

    def dispatch(self, request, *args, **kwargs):
        # Solo un superusuario edita a otro superusuario (ver _protege_superusuario).
        if request.user.is_authenticated and not request.user.is_superuser:
            persona = self.get_object()
            if persona.is_superuser:
                messages.error(
                    request,
                    "Solo un superadministrador puede modificar la cuenta de otro superadministrador."
                )
                return redirect('gestion:lista_usuarios')
        return super().dispatch(request, *args, **kwargs)

    def form_valid(self, form):
        # Guardamos el usuario
        response = super().form_valid(form)
        
        # Actualizamos la pertenencia al grupo
        grupo = form.cleaned_data['grupo']
        self.object.groups.clear() # Limpiamos los grupos anteriores
        self.object.groups.add(grupo) # Añadimos el nuevo grupo

        return response


ETIQUETA_FOTO_REGISTRO = 'Registro fotográfico'


def _cargar_soporte_orden(request, orden):
    """
    Guarda el soporte que venga en el POST (tiquete de báscula o fotos del
    registro fotográfico). Lo usan el conductor desde su vista y el asesor
    desde el expediente, para que gestión pueda completar lo que falte.
    Devuelve True si el POST era de un soporte (haya salido bien o mal).
    """
    if 'submit_bascula' in request.POST and orden.requiere_bascula:
        archivo = request.FILES.get('bascula_adjunto')
        if archivo:
            orden.bascula_adjunto = archivo
            orden.save(update_fields=['bascula_adjunto'])
            messages.success(request, "Soporte de báscula cargado.")
        else:
            messages.error(request, "Selecciona la foto o el archivo del tiquete de báscula.")
        return True

    if 'submit_fotos' in request.POST and orden.requiere_registro_fotografico:
        fotos = request.FILES.getlist('fotos')
        if fotos:
            # La primera foto llena el soporte de la orden (si está vacío);
            # el resto queda como documentos etiquetados con quién los cargó.
            for foto in fotos:
                if not orden.registro_fotografico_adjunto:
                    orden.registro_fotografico_adjunto = foto
                    orden.save(update_fields=['registro_fotografico_adjunto'])
                else:
                    DocumentoOrden.objects.create(
                        orden=orden, archivo=foto,
                        descripcion=f"{ETIQUETA_FOTO_REGISTRO} "
                                    f"({request.user.get_full_name() or request.user.username})",
                    )
            messages.success(
                request,
                f"{len(fotos)} foto{'s' if len(fotos) != 1 else ''} del registro "
                f"fotográfico cargada{'s' if len(fotos) != 1 else ''}."
            )
        else:
            messages.error(request, "Selecciona al menos una foto del servicio.")
        return True
    return False


class OrdenServicioDetailView(NoConductorRequiredMixin, DetailView):
    model = OrdenServicio
    template_name = 'gestion/ordenservicio_detail.html'
    context_object_name = 'orden'

    def get_queryset(self):
        # Precargamos personal y sus documentos (se usan varias veces en la plantilla).
        return super().get_queryset().prefetch_related(
            'recorridos__vehiculo',
            'recorridos__conductor__documentos_personales',
            'recorridos__ayudante__documentos_personales',
            'recorridos__ayudante2__documentos_personales',
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        # Formulario para subir documentos (los recorridos vienen de la
        # programación: aquí no se añaden).
        context['form_documento'] = DocumentoOrdenForm()
        # Vehículos operativos con documentos vencidos/por vencer (aviso al asignar).
        context['vehiculos_con_alerta'] = [
            v for v in Vehiculo.objects.filter(estado='OPERATIVO') if v.tiene_alerta_documentos
        ]

        # Personal (conductores/ayudantes) de esta orden con documentos vencidos o
        # por vencer, para avisar en el expediente. Se recorre una sola vez.
        personal_con_alerta = []
        vistos = set()
        for recorrido in self.object.recorridos.all():
            for persona in (recorrido.conductor, recorrido.ayudante, recorrido.ayudante2):
                if persona and persona.pk not in vistos:
                    vistos.add(persona.pk)
                    docs_alerta = [d for d in persona.documentos_personales.all() if d.tiene_alerta]
                    if docs_alerta:
                        personal_con_alerta.append({'persona': persona, 'documentos': docs_alerta})
        context['personal_con_alerta'] = personal_con_alerta
        # Novedades operacionales y control de ACPM que reportó el conductor:
        # es control interno (no va en el acta que firma el cliente), así que se
        # consulta desde aquí.
        hojas = []
        for recorrido in self.object.recorridos.all().order_by('fecha_recorrido'):
            manifiesto = getattr(recorrido, 'manifiesto', None)
            if manifiesto is None:
                continue
            novedades = list(manifiesto.novedades_operacionales.all())
            medidas = list(manifiesto.medidas_acpm.all())
            if novedades or medidas:
                hojas.append({'recorrido': recorrido, 'novedades': novedades,
                              'medidas': medidas})
        context['hojas_conductor'] = hojas


        # Acta(s) en formato documento (igual al PDF) para la pestaña de la orden.
        context['actas_formato'] = _actas_formato(
            self.object.recorridos.all().order_by('fecha_recorrido'))
        # Fotos adicionales del registro fotográfico que cargó el conductor.
        context['fotos_registro'] = self.object.documentos.filter(
            descripcion__startswith=OrdenConductorDetailView.ETIQUETA_FOTO
        )
        # Otros adjuntos de la orden (p. ej. el acta física de una orden
        # histórica); las fotos de registro ya se muestran como soportes.
        context['documentos_orden'] = self.object.documentos.exclude(
            descripcion__startswith=OrdenConductorDetailView.ETIQUETA_FOTO
        )
        # Evidencias que subieron los ayudantes desde su enlace, agrupadas por
        # persona (la programación de origen es la que las tiene).
        programacion = getattr(self.object, 'programacion_origen', None)
        evidencias = []
        if programacion is not None:
            for cuadrilla in programacion.cuadrillas.prefetch_related('fotos_ayudantes'):
                for slot in (1, 2):
                    persona = cuadrilla.ayudante_de(slot)
                    fotos = [f for f in cuadrilla.fotos_ayudantes.all() if f.slot == slot]
                    pedidas = cuadrilla.fotos_pedidas(slot)
                    if persona is None or not (fotos or pedidas):
                        continue
                    subidas = {f.novedad for f in fotos}
                    pendientes = [p for p in pedidas if p['codigo'] not in subidas]
                    evidencias.append({
                        'persona': persona,
                        'cuadrilla': cuadrilla,
                        'slot': slot,
                        'fotos': fotos,
                        'pendientes': pendientes,
                        'faltan': [p['etiqueta'] for p in pendientes],
                    })
        context['evidencias_ayudantes'] = evidencias
        # ¿Los soportes exigidos (báscula / fotos) ya están completos?
        orden = self.object
        context['soportes_ok'] = (
            (not orden.requiere_bascula or bool(orden.bascula_adjunto))
            and (not orden.requiere_registro_fotografico
                 or bool(orden.registro_fotografico_adjunto))
        )
        return context

    def post(self, request, *args, **kwargs):
        orden = self.get_object()

        # Soportes pendientes (báscula / fotos): el asesor puede completarlos
        # si el conductor no lo ha hecho.
        if _cargar_soporte_orden(request, orden):
            return redirect('gestion:detalle_orden', pk=orden.pk)

        # Fotos de los AYUDANTES: si alguno no subió las suyas por su enlace,
        # gestión las carga aquí (sirve aunque el enlace ya haya vencido).
        if 'submit_foto_ayudante' in request.POST:
            programacion = getattr(orden, 'programacion_origen', None)
            cuadrilla = (programacion.cuadrillas.filter(
                pk=request.POST.get('cuadrilla')).first() if programacion else None)
            slot = request.POST.get('slot')
            novedad = request.POST.get('novedad', '')
            fotos = request.FILES.getlist('fotos_ayudante')
            slot = int(slot) if slot in ('1', '2') else None
            codigos = ({f['codigo'] for f in cuadrilla.fotos_pedidas(slot)}
                       if cuadrilla and slot else set())
            if not cuadrilla or slot is None or cuadrilla.ayudante_de(slot) is None:
                messages.error(request, "Ese ayudante no corresponde a esta orden.")
            elif novedad not in codigos:
                messages.error(request, "Esa foto no corresponde al turno del ayudante.")
            elif not fotos:
                messages.error(request, "Selecciona la foto del ayudante antes de enviarla.")
            else:
                for foto in fotos:
                    FotoAyudante.objects.create(
                        cuadrilla=cuadrilla, slot=slot, novedad=novedad, archivo=foto)
                nombre = cuadrilla.ayudante_de(slot)
                messages.success(
                    request,
                    f"{len(fotos)} foto{'s' if len(fotos) != 1 else ''} cargada"
                    f"{'s' if len(fotos) != 1 else ''} por gestión para "
                    f"{nombre.get_full_name() or nombre.username}."
                )
            return redirect('gestion:detalle_orden', pk=orden.pk)

        # Reenviar al conductor su correo con el enlace a la orden.
        if 'submit_reenviar_conductor' in request.POST:
            recorrido = orden.recorridos.filter(
                pk=request.POST.get('recorrido')).select_related('conductor').first()
            cuadrilla = None
            programacion = getattr(orden, 'programacion_origen', None)
            if programacion is not None and recorrido is not None:
                # La cuadrilla aporta los datos del servicio; el destinatario
                # es el conductor del RECORRIDO (puede haber cambiado después).
                cuadrilla = programacion.cuadrillas.filter(
                    vehiculo=recorrido.vehiculo_id).first() or programacion.cuadrillas.first()
            if recorrido is None or cuadrilla is None:
                messages.error(request, "Ese recorrido no corresponde a esta orden.")
            elif recorrido.conductor_id is None:
                messages.error(request, "El recorrido no tiene conductor asignado.")
            else:
                try:
                    enviado, aviso = _correo_conductor(
                        request, cuadrilla, conductor=recorrido.conductor)
                except Exception as e:
                    messages.warning(request, f"No se pudo reenviar el correo ({e}).")
                else:
                    if enviado:
                        messages.success(
                            request,
                            f"Correo reenviado a "
                            f"{recorrido.conductor.get_full_name() or recorrido.conductor.username} "
                            f"({recorrido.conductor.email})."
                        )
                    if aviso:
                        messages.warning(request, aviso)
            return redirect('gestion:detalle_orden', pk=orden.pk)

        # Reenviar al ayudante su correo con el enlace (token) para subir fotos.
        if 'submit_reenviar_ayudante' in request.POST:
            programacion = getattr(orden, 'programacion_origen', None)
            cuadrilla = (programacion.cuadrillas.filter(
                pk=request.POST.get('cuadrilla')).first() if programacion else None)
            slot = request.POST.get('slot')
            slot = int(slot) if slot in ('1', '2') else None
            if not cuadrilla or slot is None or cuadrilla.ayudante_de(slot) is None:
                messages.error(request, "Ese ayudante no corresponde a esta orden.")
            else:
                try:
                    enviado, aviso = _correo_ayudante(request, cuadrilla, slot)
                except Exception as e:
                    messages.warning(request, f"No se pudo reenviar el correo ({e}).")
                else:
                    if enviado:
                        ayudante = cuadrilla.ayudante_de(slot)
                        messages.success(
                            request,
                            f"Correo reenviado a "
                            f"{ayudante.get_full_name() or ayudante.username} "
                            f"con su enlace para subir las fotos del servicio."
                        )
                        if not cuadrilla.acceso_vigente:
                            messages.warning(
                                request,
                                "Ojo: su enlace ya venció "
                                f"(era válido hasta el {cuadrilla.fecha_limite_acceso:%d/%m/%Y}), "
                                "así que podrá ver el servicio pero no subir fotos. "
                                "Puedes cargarlas tú desde esta página."
                            )
                    if aviso:
                        messages.warning(request, aviso)
            return redirect('gestion:detalle_orden', pk=orden.pk)

        if 'submit_documento' in request.POST:
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


class EditarRecorridoView(NoConductorRequiredMixin, UpdateView):
    """
    Corrige un recorrido que quedó mal (fecha, vehículo, conductor, ayudante).
    Es la forma de arreglar una orden sin borrarla.
    """
    model = Recorrido
    form_class = RecorridoForm
    template_name = 'gestion/form_recorrido.html'

    def form_valid(self, form):
        form.save()   # Recorrido.save recalcula el estado de la orden
        messages.success(self.request, "Recorrido actualizado.")
        return redirect('gestion:detalle_orden', pk=self.object.orden_id)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['orden'] = self.object.orden
        return context


class EliminarRecorridoView(NoConductorRequiredMixin, View):
    """
    Quita un recorrido de la orden (solo POST). Al borrarlo caen su manifiesto y
    su encuesta (CASCADE) y se recalcula el estado de la orden. La orden completa
    solo se elimina desde el admin de Django.
    """
    def post(self, request, pk):
        recorrido = get_object_or_404(Recorrido, pk=pk)
        orden = recorrido.orden
        # Con el acta firmada por el cliente, quitar el recorrido arrastraría
        # la firma y la encuesta en cascada: evidencia que no se recupera.
        manifiesto = Manifiesto.objects.filter(recorrido=recorrido).first()
        if manifiesto is not None and manifiesto.estado_firma == 'FIRMADO':
            messages.error(
                request,
                "Este recorrido tiene el acta FIRMADA por el cliente: quitarlo "
                "borraría la firma y la encuesta. Si de verdad hay que "
                "eliminarlo, es desde el admin de Django."
            )
            return redirect('gestion:detalle_orden', pk=orden.pk)
        # Como los recorridos ya no se pueden añadir, quitar el último dejaría
        # la orden vacía y sin forma de arreglarla desde la app.
        if orden.recorridos.count() <= 1:
            messages.error(
                request,
                "No puedes quitar el único recorrido de la orden: quedaría vacía y "
                "los recorridos ya no se añaden a mano. Corrígelo con «Editar "
                "recorrido», o cancela la orden."
            )
            return redirect('gestion:detalle_orden', pk=orden.pk)
        recorrido.delete()
        _recalcular_estado_orden(orden)
        messages.success(request, "Recorrido eliminado de la orden.")
        return redirect('gestion:detalle_orden', pk=orden.pk)


@login_required
def feed_calendario(request):
    user = request.user

    # Si el usuario es un conductor, filtra solo sus recorridos
    if not es_administrador(user) and user.groups.filter(name='Conductores').exists():
        recorridos = Recorrido.objects.filter(conductor=user)
    # Si es asesor o admin, muestra todos los recorridos
    else:
        recorridos = Recorrido.objects.all()

    recorridos = recorridos.exclude(
        orden__estado_orden='CANCELADA'
    ).select_related('vehiculo', 'orden')
    
    eventos = []
    colores_vehiculos = {}
    colores_disponibles = ['#007bff', '#28a745', '#dc3545', '#ffc107', '#17a2b8', '#6610f2']

    for recorrido in recorridos:
        vehiculo_id = recorrido.vehiculo.id
        if vehiculo_id not in colores_vehiculos:
            colores_vehiculos[vehiculo_id] = colores_disponibles[len(colores_vehiculos) % len(colores_disponibles)]

        evento = {
            'title': f'Orden #{recorrido.orden.numero_orden} - {recorrido.vehiculo.placa}',
            'start': recorrido.fecha_recorrido.strftime("%Y-%m-%d"),
            'url': reverse('gestion:detalle_orden', args=[recorrido.orden.pk]),
            'color': colores_vehiculos[vehiculo_id],
        }
        eventos.append(evento)
    
    return JsonResponse(eventos, safe=False)


class CalendarioView(LoginRequiredMixin, TemplateView):
    template_name = 'gestion/calendario.html'



# --- VISTA PARA REPORTES (SOLO SUPERUSUARIOS) ---

class ReportesView(SuperuserRequiredMixin, ListView):
    template_name = 'gestion/reportes.html'
    
    def get_queryset(self):
        # No usamos un queryset por defecto, lo generamos dinámicamente
        return None

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        form = ReporteFiltroForm(self.request.GET or None)
        context['form'] = form

        report_type = self.request.GET.get('report_type')
        resultados = []
        chart_labels = []
        chart_data = []
        chart_type = 'bar' # Por defecto
        total_general = 0

        if form.is_valid() and report_type:
            
            # --- REPORTE 1: FACTURACIÓN POR CLIENTE ---
            if report_type == 'facturacion_cliente' and form.cleaned_data.get('fecha_inicio'):
                fecha_inicio = form.cleaned_data['fecha_inicio']
                fecha_fin = form.cleaned_data['fecha_fin']
                
                resultados = Recorrido.objects.filter(
                    estado='COMPLETADO', fecha_recorrido__range=[fecha_inicio, fecha_fin]
                ).values('orden__cliente__nombre').annotate(
                    total_facturado=Sum('orden__valor_servicio'), numero_servicios=Count('id')
                ).order_by('-total_facturado')
                
                chart_labels = [item['orden__cliente__nombre'] for item in resultados]
                chart_data = [float(item['total_facturado']) for item in resultados]
                total_general = sum(chart_data)

            # --- REPORTE 2: RENDIMIENTO POR VEHÍCULO ---
            elif report_type == 'rendimiento_vehiculo' and form.cleaned_data.get('fecha_inicio'):
                fecha_inicio = form.cleaned_data['fecha_inicio']
                fecha_fin = form.cleaned_data['fecha_fin']
                
                resultados = Recorrido.objects.filter(
                    estado='COMPLETADO', fecha_recorrido__range=[fecha_inicio, fecha_fin]
                ).values('vehiculo__placa').annotate(
                    total_facturado=Sum('orden__valor_servicio'), numero_servicios=Count('id')
                ).order_by('-total_facturado')

                chart_labels = [item['vehiculo__placa'] for item in resultados]
                chart_data = [float(item['total_facturado']) for item in resultados]
                total_general = sum(chart_data)

            # --- REPORTE 3: TENDENCIA MENSUAL ---
            elif report_type == 'tendencia_mensual' and form.cleaned_data.get('año'):
                año = form.cleaned_data['año']
                
                resultados = Recorrido.objects.filter(
                    estado='COMPLETADO', fecha_recorrido__year=año
                ).annotate(
                    mes=TruncMonth('fecha_recorrido') # Agrupa por mes
                ).values('mes').annotate(
                    total_facturado=Sum('orden__valor_servicio')
                ).order_by('mes')

                meses = ["Ene", "Feb", "Mar", "Abr", "May", "Jun", "Jul", "Ago", "Sep", "Oct", "Nov", "Dic"]
                chart_labels = [meses[item['mes'].month - 1] for item in resultados]
                chart_data = [float(item['total_facturado']) for item in resultados]
                chart_type = 'line' # Cambiamos a gráfico de líneas
                total_general = sum(chart_data)

        context['resultados'] = resultados
        context['report_type'] = report_type
        context['chart_labels'] = json.dumps(chart_labels)
        context['chart_data'] = json.dumps(chart_data)
        context['chart_type'] = chart_type
        context['total_general'] = total_general
        
        return context



# --- Mixin de Seguridad para Conductores ---
class ConductorRequiredMixin(LoginRequiredMixin, UserPassesTestMixin):
    def test_func(self):
        return self.request.user.groups.filter(name='Conductores').exists()

# --- NUEVA VISTA: DASHBOARD DEL CONDUCTOR ---
class DashboardConductorView(ConductorRequiredMixin, TemplateView):
    template_name = 'gestion/dashboard_conductor.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        conductor = self.request.user
        hoy = timezone.localdate()

        # Recorridos para el día de hoy
        context['recorridos_hoy'] = Recorrido.objects.filter(
            conductor=conductor,
            fecha_recorrido=hoy
        ).order_by('orden__fecha_creacion')

        # Recorridos para los próximos 7 días
        proxima_semana = hoy + datetime.timedelta(days=7)
        context['recorridos_proximos'] = Recorrido.objects.filter(
            conductor=conductor,
            fecha_recorrido__gt=hoy,
            fecha_recorrido__lte=proxima_semana
        ).order_by('fecha_recorrido')
        
        return context
    

@login_required
def dashboard_redirect_view(request):
    user = request.user
    if not es_administrador(user) and user.groups.filter(name='Conductores').exists():
        return redirect('gestion:dashboard_conductor')
    else: # Asesores y Superusuarios
        return redirect('gestion:dashboard')
    


# --- VISTA PRINCIPAL PARA CONDUCTORES ---
class MisRecorridosView(ConductorRequiredMixin, PaginadoMixin, ListView):
    model = Recorrido
    template_name = 'gestion/mis_recorridos.html'
    context_object_name = 'recorridos'
    paginate_by = 10

    def get_queryset(self):
        # Solo los recorridos del conductor que siguen pendientes, por fecha.
        # Se traen de una vez la orden, el cliente, la placa y el estado del
        # acta: la tarjeta los muestra todos (si no, una consulta por fila).
        hoy = timezone.localdate()
        return (
            Recorrido.objects.filter(
                conductor=self.request.user,
                fecha_recorrido__gte=hoy,
                estado__in=['PROGRAMADO', 'EN_CURSO'],
            )
            .select_related('orden', 'orden__cliente', 'orden__programacion_origen',
                            'vehiculo', 'manifiesto', 'encuesta_conductor')
            .order_by('fecha_recorrido')
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['hoy'] = timezone.localdate()   # para destacar los de hoy
        return context


# --- HISTORIAL DEL CONDUCTOR ---
class HistorialConductorView(ConductorRequiredMixin, PaginadoMixin, ListView):
    """
    Historial de TODOS los recorridos del conductor (los más recientes primero).
    Surface también las encuestas de cierre pendientes para que pueda completarlas.
    """
    model = Recorrido
    template_name = 'gestion/historial_conductor.html'
    context_object_name = 'recorridos'
    paginate_by = 25

    def get_queryset(self):
        return Recorrido.objects.filter(
            conductor=self.request.user
        ).select_related('orden', 'orden__cliente', 'vehiculo').order_by('-fecha_recorrido')


# --- VISTA DE ORDEN PARA EL CONDUCTOR ---
def _tareas_servicio_conductor(orden, actas_formato, fotos_registro):
    """
    Las tareas del conductor para cerrar el servicio, en lenguaje simple y
    en el orden natural del día. Todas se pueden hacer cuando él quiera;
    solo la encuesta de cierre espera a la firma del cliente (firmarla
    marca el recorrido COMPLETADO, no puede ir antes).
    """
    varios = len(actas_formato) > 1
    tareas = []

    def fecha_de(item):
        # Con un solo recorrido no hace falta repetir la fecha en cada tarea.
        return (' · ' + item['recorrido'].fecha_recorrido.strftime('%d/%m/%Y')
                if varios else '')

    for item in actas_formato:
        rec, estado = item['recorrido'], item['estado']
        tareas.append({
            'titulo': 'Llena los datos del servicio' + fecha_de(item),
            'titulo_corto': 'los datos del servicio',
            'detalle': ('Datos registrados. Puedes corregirlos hasta que el cliente firme.'
                        if estado == 'DILIGENCIADA' else
                        'Datos registrados y firmados.' if estado == 'FIRMADA' else
                        'Tiempos, kilómetros, novedades del día y ACPM.'),
            'icono': 'bi-pen-fill',
            'hecha': estado != 'PENDIENTE',
            'habilitada': True,
            'url': (None if estado == 'FIRMADA' else
                    reverse('gestion:firmar_manifiesto_step',
                            kwargs={'pk': rec.pk, 'step': 'paso3'})),
            'boton': 'Corregir' if estado == 'DILIGENCIADA' else 'Llenar',
            'formulario': None,
        })

    if orden.requiere_bascula:
        tareas.append({
            'titulo': 'Sube el tiquete de báscula',
            'titulo_corto': 'el tiquete de báscula',
            'detalle': ('Tiquete cargado. Puedes reemplazarlo si quedó mal.'
                        if orden.bascula_adjunto else
                        'Tómale una foto al tiquete del pesaje.'),
            'icono': 'bi-speedometer2',
            'hecha': bool(orden.bascula_adjunto),
            'habilitada': True,
            'url': None,
            'boton': '',
            'formulario': 'bascula',
        })

    if orden.requiere_registro_fotografico:
        con_fotos = bool(orden.registro_fotografico_adjunto) or bool(fotos_registro)
        tareas.append({
            'titulo': 'Sube las fotos del servicio',
            'titulo_corto': 'las fotos del servicio',
            'detalle': ('Fotos cargadas. Puedes añadir más si hace falta.'
                        if con_fotos else
                        'El registro fotográfico del trabajo realizado.'),
            'icono': 'bi-camera-fill',
            'hecha': con_fotos,
            'habilitada': True,
            'url': None,
            'boton': '',
            'formulario': 'fotos',
        })

    for item in actas_formato:
        rec, estado = item['recorrido'], item['estado']
        tareas.append({
            'titulo': 'Pídele la firma al cliente' + fecha_de(item),
            'titulo_corto': 'la firma del cliente',
            'detalle': ('El cliente ya respondió su encuesta y firmó.'
                        if estado == 'FIRMADA' else
                        'Muéstrale el QR: él responde su encuesta y firma desde su celular.'),
            'icono': 'bi-qr-code',
            'hecha': estado == 'FIRMADA',
            'habilitada': True,
            'url': (None if estado == 'FIRMADA' else
                    reverse('gestion:manifiesto_qr', kwargs={'pk': rec.pk})),
            'boton': 'Mostrar QR',
            'formulario': None,
        })

    for item in actas_formato:
        rec, estado = item['recorrido'], item['estado']
        con_encuesta = bool(getattr(rec, 'encuesta_conductor', None))
        tareas.append({
            'titulo': 'Responde tu encuesta de cierre' + fecha_de(item),
            'titulo_corto': 'tu encuesta de cierre',
            'detalle': ('¡Listo! Con esto el servicio quedó completado.'
                        if con_encuesta else
                        'Siete preguntas rápidas sobre tu jornada.'
                        if estado == 'FIRMADA' else
                        'Se habilita cuando el cliente firme.'),
            'icono': 'bi-clipboard-check',
            'hecha': con_encuesta,
            'habilitada': estado == 'FIRMADA',
            'url': (reverse('gestion:encuesta_conductor', kwargs={'pk': rec.pk})
                    if estado == 'FIRMADA' and not con_encuesta else None),
            'boton': 'Responder',
            'formulario': None,
        })
    return tareas


# ============================================================
#  DEMOSTRACIÓN PARA GERENCIA (datos de EJEMPLO, nada real)
#  Reproduce la experiencia completa del conductor —llenar la hoja, subir
#  fotos, el QR, la encuesta— sin tocar la base de datos: los objetos se
#  arman en memoria y el avance se guarda en una COOKIE FIRMADA, no en el
#  servidor. Es público: no hay nada que proteger porque nada es real.
# ============================================================

class _DemoConductorBase(View):
    """Piezas comunes de la demo: los datos de ejemplo y el avance simulado."""
    COOKIE = 'demo_conductor'
    SAL = 'demo-conductor-avance'

    # --- Avance simulado (cookie firmada; si la manipulan, se ignora) ---
    def avance(self, request):
        from django.core import signing
        try:
            datos = signing.loads(request.COOKIES.get(self.COOKIE, ''), salt=self.SAL)
            return datos if isinstance(datos, dict) else {}
        except signing.BadSignature:
            return {}

    def marcar(self, request, respuesta, **cambios):
        from django.core import signing
        datos = self.avance(request)
        datos.update(cambios)
        respuesta.set_cookie(self.COOKIE, signing.dumps(datos, salt=self.SAL),
                             max_age=8 * 3600, samesite='Lax')
        return respuesta

    # --- Los datos de ejemplo (SIN guardar: pk=0 y nada de .save()) ---
    def escenario(self, request):
        hoy = timezone.localdate()
        avance = self.avance(request)
        conductor = User(first_name='Carlos', last_name='Ejemplo')
        ayudante = User(first_name='Andrés', last_name='Modelo')
        vehiculo = Vehiculo(pk=0, placa='WHB 123', marca='Hino', modelo='FC9J',
                            capacidad='8 m³')
        orden = OrdenServicio(
            pk=0, numero_orden=22207,
            direccion_servicio='Cra 69A No. 24 Sur - 17, Bogotá',
            descripcion=('Succión y transporte de lodos de los pozos sépticos. '
                         'Anunciarse en portería con el supervisor de turno.'),
            bascula='PESAN', registro_fotografico='SI',
        )
        recorrido = Recorrido(pk=0, orden=orden, vehiculo=vehiculo,
                              conductor=conductor, ayudante=ayudante,
                              fecha_recorrido=hoy)
        acta = Manifiesto(
            succ_pozos_septicos=True, succ_pozos_septicos_cant='6 M³',
            succ_trampas_grasa=True, succ_trampas_grasa_cant='1',
            transporte_tipo='Lodos', transporte_cantidad='6 M³',
        )
        # Lo que el conductor "ya llenó" en esta demo.
        if avance.get('datos'):
            acta.tiempo_inicio_operativo = datetime.time(7, 30)
            acta.tiempo_final_operativo = datetime.time(11, 45)
            acta.hora_salida_solmed = datetime.time(7, 10)
            acta.hora_llegada_solmed = datetime.time(12, 15)
            acta.observaciones = 'Servicio sin novedad.'
        if avance.get('firma'):
            acta.estado_firma = 'FIRMADO'
        return {
            'avance': avance, 'orden': orden, 'recorrido': recorrido, 'acta': acta,
            'estado': ('FIRMADA' if avance.get('firma')
                       else 'DILIGENCIADA' if avance.get('datos') else 'PENDIENTE'),
        }

    def contexto_pantalla(self, request):
        """Contexto de la pantalla principal con el avance ya aplicado."""
        e = self.escenario(request)
        avance, orden = e['avance'], e['orden']
        if avance.get('bascula'):
            orden.bascula_adjunto = 'demo/tiquete.jpg'
        if avance.get('fotos'):
            orden.registro_fotografico_adjunto = 'demo/foto.jpg'
        actas_formato = [{'recorrido': e['recorrido'], 'acta': e['acta'],
                          'estado': e['estado']}]
        tareas = _tareas_servicio_conductor(orden, actas_formato, [])
        # En la demo, cada tarea apunta a su propia pantalla simulada.
        destinos = {
            'bi-pen-fill': reverse('gestion:demo_conductor_datos'),
            'bi-qr-code': reverse('gestion:demo_conductor_qr'),
            'bi-clipboard-check': reverse('gestion:demo_conductor_encuesta'),
        }
        for tarea in tareas:
            if tarea['url']:
                tarea['url'] = destinos.get(tarea['icono'], tarea['url'])
            if avance.get('encuesta') and tarea['icono'] == 'bi-clipboard-check':
                tarea['hecha'], tarea['url'] = True, None
                tarea['detalle'] = '¡Listo! Con esto el servicio quedó completado.'
        hechas = sum(1 for t in tareas if t['hecha'])
        return {
            'orden': orden, 'mis_recorridos': [e['recorrido']],
            'actas_formato': actas_formato, 'fotos_registro': [], 'tareas': tareas,
            'progreso': {
                'hechas': hechas, 'total': len(tareas),
                'pct': int(hechas * 100 / len(tareas)) if tareas else 0,
                'faltan': [t['titulo_corto'] for t in tareas if not t['hecha']],
            },
            'es_demo': True,
        }


class DemoOrdenConductorView(_DemoConductorBase):
    """Pantalla principal de la demo. El POST solo simula subir fotos."""
    def get(self, request):
        return render(request, 'gestion/orden_conductor_detail.html',
                      self.contexto_pantalla(request))

    def post(self, request):
        destino = redirect('gestion:demo_orden_conductor')
        if 'submit_bascula' in request.POST:
            messages.success(request, "Tiquete de báscula cargado (simulado).")
            return self.marcar(request, destino, bascula=True)
        if 'submit_fotos' in request.POST:
            messages.success(request, "Fotos del servicio cargadas (simulado).")
            return self.marcar(request, destino, fotos=True)
        return destino


class DemoConductorDatosView(_DemoConductorBase):
    """La hoja del servicio (paso 1) con los campos reales, sin guardar nada."""
    def get(self, request):
        e = self.escenario(request)
        return render(request, 'gestion/manifiesto_wizard/paso3.html', {
            'recorrido': e['recorrido'], 'pk': 0, 'current_step': 'paso3',
            'form': ManifiestoPaso3Form(instance=e['acta']),
            'checklist_izq': [('PALEADA', 'Palea Savicol'),
                              ('BÁSCULA', 'SÍ — SUBIR FOTO (Báscula Mulera)'),
                              ('SE REALIZA DISPOSICIÓN', 'RELLENO SANITARIO DOÑA JUANA')],
            'checklist_der': [('SE REQUIERE SISO', 'SÍ'),
                              ('REGISTRO FOTOGRÁFICO', 'SÍ — SUBIR FOTOS'),
                              ('AYUDANTE CON CURSOS', 'Alturas')],
            'filas_novedades': _formularios_novedades(None),
            'filas_acpm': _formularios_acpm(None),
            'es_demo': True,
        })

    def post(self, request):
        return redirect('gestion:demo_conductor_cierre')


class DemoConductorCierreView(_DemoConductorBase):
    """El cierre (paso 2). Al 'guardar' solo marca el avance en la cookie."""
    def get(self, request):
        e = self.escenario(request)
        return render(request, 'gestion/manifiesto_wizard/paso4.html', {
            'recorrido': e['recorrido'], 'pk': 0, 'current_step': 'paso4',
            'form': ManifiestoPaso4Form(instance=e['acta']),
            'responsable_empresa': 'Carlos Ejemplo',
            'es_demo': True,
        })

    def post(self, request):
        messages.success(request, "Datos del servicio guardados (simulado).")
        return self.marcar(request, redirect('gestion:demo_orden_conductor'), datos=True)


class DemoConductorQRView(_DemoConductorBase):
    """
    La pantalla del QR. El código lleva a la encuesta del cliente de ejemplo,
    así que se puede escanear de verdad en la presentación.
    """
    def get(self, request):
        e = self.escenario(request)
        url_publica = request.build_absolute_uri(
            reverse('gestion:demo_encuesta_cliente'))
        return render(request, 'gestion/manifiesto_wizard/qr.html', {
            'recorrido': e['recorrido'], 'manifiesto': e['acta'],
            'url_publica': url_publica, 'qr_b64': _qr_data_uri(url_publica),
            'acta_diligenciada': bool(e['avance'].get('datos')),
            'es_asesor_viendo': False, 'es_demo': True,
        })

    def post(self, request):
        messages.success(request, "El cliente firmó el acta (simulado).")
        return self.marcar(request, redirect('gestion:demo_orden_conductor'), firma=True)


class DemoConductorEncuestaView(_DemoConductorBase):
    """La encuesta de cierre del conductor, sin guardar."""
    def get(self, request):
        e = self.escenario(request)
        return render(request, 'gestion/encuesta_conductor.html', {
            'recorrido': e['recorrido'], 'form': EncuestaConductorForm(),
            'ya_diligenciada': bool(e['avance'].get('encuesta')), 'es_demo': True,
        })

    def post(self, request):
        messages.success(request, "Encuesta de cierre enviada (simulado). ¡Servicio completado!")
        return self.marcar(request, redirect('gestion:demo_orden_conductor'), encuesta=True)


class DemoEncuestaClienteView(_DemoConductorBase):
    """Lo que ve el CLIENTE al escanear el QR de la demo (encuesta + firma)."""
    def get(self, request):
        e = self.escenario(request)
        return render(request, 'gestion/manifiesto_wizard/encuesta_publica.html', {
            'manifiesto': e['acta'], 'recorrido': e['recorrido'], 'orden': e['orden'],
            'form': ManifiestoPaso5Form(instance=e['acta']), 'es_demo': True,
        })

    def post(self, request):
        e = self.escenario(request)
        return render(request, 'gestion/manifiesto_wizard/encuesta_gracias.html', {
            'manifiesto': e['acta'], 'ya_firmado': False, 'es_demo': True,
        })


class DemoConductorReiniciarView(_DemoConductorBase):
    """Borra el avance simulado para volver a empezar la demostración."""
    def post(self, request):
        respuesta = redirect('gestion:demo_orden_conductor')
        respuesta.delete_cookie(self.COOKIE)
        messages.info(request, "Demostración reiniciada.")
        return respuesta



class OrdenConductorDetailView(ConductorRequiredMixin, DetailView):
    """
    Ficha de la orden pensada para el conductor. Solo deja ver órdenes en las
    que tiene algún recorrido asignado (cualquier otra devuelve 404) y no expone
    datos financieros ni de gestión. Es de solo lectura salvo los SOPORTES del
    servicio: si la programación marcó báscula o registro fotográfico, el
    conductor carga aquí la foto del tiquete y las fotos del servicio.
    """
    model = OrdenServicio
    template_name = 'gestion/orden_conductor_detail.html'
    context_object_name = 'orden'

    # Etiqueta con la que se guardan las fotos adicionales del registro
    # fotográfico como documentos de la orden (visibles en el expediente).
    ETIQUETA_FOTO = 'Registro fotográfico'

    def get_queryset(self):
        # Restringe el acceso a las órdenes propias del conductor.
        return OrdenServicio.objects.filter(
            recorridos__conductor=self.request.user
        ).distinct()

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        # Solo los recorridos de esta orden asignados a este conductor.
        mis_recorridos = self.object.recorridos.filter(
            conductor=self.request.user
        ).select_related('vehiculo').order_by('-fecha_recorrido')
        context['mis_recorridos'] = mis_recorridos
        # Acta(s) en formato documento (igual al PDF) para la pestaña del conductor.
        context['actas_formato'] = _actas_formato(mis_recorridos)
        # Fotos adicionales del registro fotográfico ya cargadas.
        context['fotos_registro'] = self.object.documentos.filter(
            descripcion__startswith=self.ETIQUETA_FOTO
        )
        # La lista de tareas del servicio y su avance (la pantalla del
        # conductor es una lista de chequeo, no un trámite).
        context['tareas'] = self._tareas_servicio(
            self.object, context['actas_formato'], context['fotos_registro'])
        hechas = sum(1 for t in context['tareas'] if t['hecha'])
        total = len(context['tareas'])
        context['progreso'] = {
            'hechas': hechas, 'total': total,
            'pct': int(hechas * 100 / total) if total else 0,
            'faltan': [t['titulo_corto'] for t in context['tareas'] if not t['hecha']],
        }
        return context

    def _tareas_servicio(self, orden, actas_formato, fotos_registro):
        return _tareas_servicio_conductor(orden, actas_formato, fotos_registro)


    def post(self, request, *args, **kwargs):
        """Carga de soportes: tiquete de báscula y fotos del registro fotográfico."""
        self.object = self.get_object()   # 404 si la orden no es suya
        if not _cargar_soporte_orden(request, self.object):
            messages.error(request, "Esta orden no tiene ese soporte habilitado.")
        return redirect('gestion:detalle_orden_conductor', pk=self.object.pk)


# --- NUEVA VISTA: TABLERO DE PLANIFICACIÓN ---
class PlanificacionView(PlanificadorRequiredMixin, TemplateView):
    template_name = 'gestion/planificacion.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        
        # 1. Obtener la fecha (igual que en el expediente del vehículo)
        fecha_str = self.request.GET.get('fecha')
        fecha_seleccionada = timezone.localdate()
        if fecha_str:
            try:
                fecha_seleccionada = datetime.datetime.strptime(fecha_str, '%Y-%m-%d').date()
            except ValueError:
                pass # Mantener la fecha de hoy si el formato es incorrecto
        
        context['fecha_seleccionada'] = fecha_seleccionada

        # 2. Obtener los recorridos del día
        recorridos_del_dia = Recorrido.objects.filter(fecha_recorrido=fecha_seleccionada).select_related('vehiculo', 'conductor', 'orden__cliente')
        context['recorridos_del_dia'] = recorridos_del_dia

        # 3. Identificar recursos OCUPADOS
        vehiculos_ocupados_ids = [r.vehiculo.id for r in recorridos_del_dia if r.vehiculo]
        conductores_ocupados_ids = [r.conductor.id for r in recorridos_del_dia if r.conductor]

        # 4. Obtener recursos DISPONIBLES (conductores activos, sin retirados)
        conductores = Group.objects.get(name='Conductores').user_set.exclude(perfil__retirado=True)

        context['vehiculos_disponibles'] = Vehiculo.objects.filter(estado='OPERATIVO').exclude(id__in=vehiculos_ocupados_ids)
        context['conductores_disponibles'] = conductores.exclude(id__in=conductores_ocupados_ids)

        return context

    def post(self, request, *args, **kwargs):
        # Esta lógica maneja la re-asignación
        recorrido_id = request.POST.get('recorrido_id')
        nuevo_vehiculo_id = request.POST.get('vehiculo')
        nuevo_conductor_id = request.POST.get('conductor')

        try:
            recorrido = Recorrido.objects.get(id=recorrido_id)
            if nuevo_vehiculo_id:
                recorrido.vehiculo_id = nuevo_vehiculo_id
            if nuevo_conductor_id:
                recorrido.conductor_id = nuevo_conductor_id
            recorrido.save()
            messages.success(request, f"Recorrido #{recorrido.id} re-asignado exitosamente.")
        except Recorrido.DoesNotExist:
            messages.error(request, "El recorrido que intentas modificar no existe.")
            
        # Redirige a la misma página de planificación con la fecha seleccionada
        fecha = request.POST.get('fecha', timezone.localdate().isoformat())
        return redirect(f"{reverse('gestion:planificacion')}?fecha={fecha}")



class RegistrarPagoView(AsesorRequiredMixin, CreateView):
    model = Pago
    form_class = PagoForm
    template_name = 'gestion/registrar_pago.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        # Obtenemos la orden desde la URL y la pasamos a la plantilla
        context['orden'] = get_object_or_404(OrdenServicio, pk=self.kwargs['orden_pk'])
        return context

    def form_valid(self, form):
        # Asignamos la orden al pago antes de guardarlo
        orden = get_object_or_404(OrdenServicio, pk=self.kwargs['orden_pk'])
        form.instance.orden = orden
        messages.success(self.request, "Pago registrado exitosamente.")
        return super().form_valid(form)

    def get_success_url(self):
        # Después de registrar el pago, volvemos al expediente de la orden
        return reverse('gestion:detalle_orden', kwargs={'pk': self.kwargs['orden_pk']})


class ConciliarOrdenView(AsesorRequiredMixin, View):
    """
    Concilia la "Transporte - Cantidad" de una orden (solo POST): el asesor la
    diligencia durante el mes, después de prestado el servicio. Guarda la
    cantidad en la programación de origen (y en el acta si ya existe — decisión
    provisional, ver OrdenServicio.conciliar_transporte) y limpia el estado
    PENDIENTE de la orden.
    """
    def post(self, request, pk):
        orden = get_object_or_404(OrdenServicio, pk=pk)
        if orden.estado_conciliacion == 'NO_APLICA':
            messages.info(request, "Esta orden no maneja conciliación (se creó sin programación).")
            return redirect('gestion:detalle_orden', pk=pk)

        cantidad = request.POST.get('transporte_cantidad', '').strip()
        if not cantidad:
            messages.error(request, "Ingresa la cantidad de transporte para conciliar la orden.")
            return redirect('gestion:detalle_orden', pk=pk)

        orden.conciliar_transporte(cantidad)
        messages.success(
            request,
            f"Orden #{orden.numero_orden} conciliada: Transporte - Cantidad = {cantidad}."
        )
        return redirect('gestion:detalle_orden', pk=pk)


# ============================================================
#  MÓDULO DE PROGRAMACIÓN (paso PREVIO a la Orden de Servicio)
#  Lo gestionan los Asesores (y superusuarios). Al confirmar una
#  programación se genera automáticamente la orden + primer recorrido.
# ============================================================

# Documentos estándar del expediente (también define el orden de presentación).
DOCUMENTOS_ESTANDAR = [
    ('CEDULA', 'Cédula de ciudadanía'),
    ('SEGURIDAD_SOCIAL', 'Seguridad social vigente'),
    ('LICENCIA', 'Licencia de conducción'),
    ('CURSO_ALTURAS', 'Certificado curso de alturas'),
    ('CURSO_CONFINADOS', 'Certificado espacios confinados'),
]


def _documentos_requeridos_por_rol(nombres_grupos):
    """
    Tipos de documento OBLIGATORIOS en el expediente según el/los rol(es).
    La seguridad social se exige a CUALQUIER persona con rol asignado (todos los
    cargos la cargan). Los conductores llevan además cédula y licencia; los
    ayudantes, cédula. Los cursos de alturas y espacios confinados no son
    obligatorios: cada programación decide si los exige (ver Programacion.exige_curso_*).
    """
    requeridos = set()
    if nombres_grupos:
        # Toda persona con un rol debe mantener su seguridad social vigente.
        requeridos.add('SEGURIDAD_SOCIAL')
    if 'Conductores' in nombres_grupos:
        requeridos |= {'CEDULA', 'LICENCIA'}
    if 'Ayudantes' in nombres_grupos:
        requeridos |= {'CEDULA'}
    return requeridos


# Roles cuyas personas NO acceden a la plataforma: se registran solo para su
# expediente y para poder asignarlas a las cuadrillas. No tienen usuario ni
# contraseña utilizables (ver PersonaSinAccesoForm).
GRUPOS_SIN_ACCESO = {'Ayudantes'}

# Documentos que llevan fecha de vigencia (se puede fijar/editar con el botón
# "Vigencia" del expediente). La seguridad social ahora se controla por vigencia
# manual (ya no por el mes calendario).
TIPOS_CON_VIGENCIA = {'SEGURIDAD_SOCIAL', 'LICENCIA', 'CURSO_ALTURAS', 'CURSO_CONFINADOS'}


def _grupo_es_sin_acceso(grupo):
    """True si el rol seleccionado no debe tener acceso al sistema."""
    return grupo is not None and grupo.name in GRUPOS_SIN_ACCESO


def _persona_sin_acceso(persona):
    """True si la persona está registrada sin acceso a la plataforma."""
    return bool(set(persona.groups.values_list('name', flat=True)) & GRUPOS_SIN_ACCESO)


def _grupo_de_post(request):
    """Grupo (rol) enviado en el POST del formulario de persona, si es válido."""
    return Group.objects.filter(pk=request.POST.get('grupo')).first()


def _ids_grupos_sin_acceso():
    """IDs de los roles sin acceso, para que el formulario reaccione en vivo."""
    return list(Group.objects.filter(name__in=GRUPOS_SIN_ACCESO).values_list('id', flat=True))


def _documentos_aplicables_por_rol(nombres_grupos):
    """
    Casillas del expediente que se muestran para ese rol (en el orden estándar).
    Los cursos solo aparecen en ayudantes y la licencia solo en conductores;
    la cédula está siempre disponible aunque no sea obligatoria.
    """
    aplicables = _documentos_requeridos_por_rol(nombres_grupos) | {'CEDULA'}
    if 'Ayudantes' in nombres_grupos:
        # Opcionales en el expediente, pero exigibles desde una programación.
        aplicables |= {'CURSO_ALTURAS', 'CURSO_CONFINADOS'}
    return [(tipo, label) for tipo, label in DOCUMENTOS_ESTANDAR if tipo in aplicables]


def _ss_vigente(docs):
    """
    Seguridad social vigente de una persona: la de mayor fecha de vencimiento
    entre las que aún no han vencido. La vigencia se fija a mano al cargarla, así
    que ya NO se usa el mes calendario. Devuelve el DocumentoPersonal o None.
    `docs` es la lista de sus documentos (ya cargada).
    """
    candidatas = [
        d for d in docs
        if d.tipo == 'SEGURIDAD_SOCIAL' and d.vigente
    ]
    if not candidatas:
        return None
    return max(candidatas, key=lambda d: d.fecha_vencimiento)


def _estado_documentos_personal():
    """
    Por cada persona con requisitos documentales, los documentos REQUERIDOS que
    le faltan y el enlace a su ficha. Se pasa a la plantilla de programación
    (JSON) para avisar en vivo cuando se asigna a alguien sin la documentación
    al día.
      - Toda persona con rol: seguridad social vigente.
      - Conductores: además cédula y licencia.
      - Ayudantes:   además cédula (los cursos se exigen desde cada programación).
    """
    tipo_label = dict(DocumentoPersonal.TIPO_CHOICES)
    mes_actual = timezone.localdate().strftime('%Y-%m')
    # Cualquier persona ACTIVA con rol asignado (los retirados no se asignan).
    usuarios = (
        User.objects.filter(groups__isnull=False)
        .exclude(perfil__retirado=True)
        .distinct()
        .prefetch_related('groups', 'documentos_personales')
    )
    data = {}
    for u in usuarios:
        nombres = set(u.groups.values_list('name', flat=True))
        requeridos = _documentos_requeridos_por_rol(nombres)
        docs = list(u.documentos_personales.all())
        subidos = {d.tipo for d in docs}
        faltan = []
        # Seguridad social: al día = existe una con vigencia y sin vencer (la
        # vigencia se pone a mano al cargarla; ya no depende del mes calendario).
        ss_doc = _ss_vigente(docs)
        for tipo, _label in DOCUMENTOS_ESTANDAR:   # orden estable de presentación
            if tipo not in requeridos:
                continue
            if tipo == 'SEGURIDAD_SOCIAL':
                if ss_doc is None:
                    faltan.append('Seguridad social vigente')
            elif tipo not in subidos:
                faltan.append(tipo_label[tipo])
        # Cursos vigentes (no obligatorios en el expediente, pero exigibles
        # desde la programación): sirven para avisar en vivo al asignar.
        cursos = {
            tipo: any(d.tipo == tipo and not d.vencido for d in docs)
            for tipo, _etiqueta in CURSOS_EXIGIBLES
        }
        data[u.id] = {
            'nombre': u.get_full_name() or u.username,
            'faltan': faltan,
            'cursos': cursos,
            'es_ayudante': 'Ayudantes' in nombres,
            'url': reverse('gestion:ficha_persona', args=[u.id]),
            'ss_al_dia': ss_doc is not None,
            'ss_vence': ss_doc.fecha_vencimiento.strftime('%d/%m/%Y') if ss_doc else '',
            'ss_url': ss_doc.archivo.url if ss_doc else '',
        }
    return data


def _validar_cursos_cuadrilla(form, cuadrilla_form):
    """
    Si la programación exige cursos, comprueba que el ayudante asignado los tenga
    vigentes. Marca el error en el campo 'ayudante' de la cuadrilla.
    Devuelve True si cumple.
    """
    exige_alturas = form.cleaned_data.get('exige_curso_alturas') == 'SI'
    exige_confinados = form.cleaned_data.get('exige_curso_confinados') == 'SI'
    if not (exige_alturas or exige_confinados):
        return True
    todo_ok = True
    for campo in ('ayudante', 'ayudante2'):
        ayudante = cuadrilla_form.cleaned_data.get(campo)
        motivos = cursos_faltantes_ayudante(ayudante, exige_alturas, exige_confinados)
        if not motivos:
            continue
        todo_ok = False
        nombre = ayudante.get_full_name() or ayudante.username
        cuadrilla_form.add_error(
            campo,
            f"{nombre} {' y '.join(motivos)}. Este servicio exige esos cursos: "
            f"carga el soporte en su expediente o asigna otro ayudante."
        )
    return todo_ok


def _tiene_ss_vigente(persona):
    """True si la persona tiene una seguridad social con vigencia sin vencer."""
    if persona is None:
        return True
    return persona.documentos_personales.filter(
        tipo='SEGURIDAD_SOCIAL',
        fecha_vencimiento__gte=timezone.localdate(),
    ).exists()


# ============================================================
#  ADJUNTOS DEL CENTRO DE CORREOS (tokens de EnvioCorreo.adjuntos)
#  Un solo resolutor: cada token nombra un documento que vive en el sistema
#  (personal, vehículo, proveedor, SOLMED o cliente) y se resuelve a
#  (archivo, nombre, línea) para armar el correo. Sin contexto: desde el
#  centro se puede adjuntar cualquier documento, exista o no programación.
# ============================================================

# Etiquetas de los documentos de la placa y del cliente (subcampos fijos).
DOCS_VEHICULO = {
    'soat': ('archivo_soat', 'SOAT'),
    'tecno': ('archivo_tecnomecanica', 'Tecnomecánica'),
    'tarjeta': ('archivo_tarjeta', 'Tarjeta de propiedad'),
}
DOCS_CLIENTE_FIJOS = {
    'rut': ('doc_rut', 'RUT'),
    'camara': ('doc_camara_comercio', 'Cámara de Comercio'),
    'cedula': ('doc_cedula_rep_legal', 'Cédula del representante legal'),
}


def _lista_correos(texto):
    """Parte un texto de correos separados por coma o punto y coma."""
    return [c.strip() for c in str(texto or '').replace(';', ',').split(',') if c.strip()]


def _reply_to():
    """
    Direcciones a las que se dirige la RESPUESTA de los correos que NO se
    redactan a mano (notificaciones al personal): el valor global del .env.
    Lista vacía = el correo responde a la cuenta del sistema, como antes.
    """
    return list(getattr(settings, 'EMAIL_REPLY_TO', []) or [])


def _resolver_adjunto_correo(token):
    """
    Resuelve un token a {'archivo', 'nombre', 'linea'} si el documento existe.
    Devuelve None si el token no existe o su archivo fue eliminado: el envío
    avisa en vez de mandar un correo incompleto.
    """
    partes = str(token).split(':')
    tipo = partes[0] if partes else ''

    def _nombre(base, etiqueta):
        ext = os.path.splitext(base)[1] or '.pdf'
        return f"{etiqueta}{ext}".replace('/', '-')

    if tipo == 'personal' and len(partes) == 2 and partes[1].isdigit():
        doc = (DocumentoPersonal.objects.select_related('usuario')
               .filter(pk=partes[1]).first())
        if not doc or not doc.archivo:
            return None
        persona = doc.usuario.get_full_name() or doc.usuario.username
        etiqueta = (doc.descripcion if doc.tipo == 'OTRO' and doc.descripcion
                    else doc.get_tipo_display())
        if doc.tipo == 'SEGURIDAD_SOCIAL' and doc.fecha_vencimiento:
            etiqueta += f" (vigente hasta {doc.fecha_vencimiento.strftime('%d/%m/%Y')})"
        return {'archivo': doc.archivo,
                'nombre': _nombre(doc.archivo.name, f"{etiqueta} - {persona}"),
                'linea': f"- {persona}: {etiqueta}"}

    if tipo == 'vehiculo' and len(partes) == 3 and partes[2] in DOCS_VEHICULO:
        vehiculo = Vehiculo.objects.filter(pk=partes[1]).first() if partes[1].isdigit() else None
        campo, etiqueta = DOCS_VEHICULO[partes[2]]
        archivo = getattr(vehiculo, campo, None) if vehiculo else None
        if not archivo:
            return None
        return {'archivo': archivo,
                'nombre': _nombre(archivo.name, f"{etiqueta} - {vehiculo.placa}"),
                'linea': f"- Vehículo {vehiculo.placa}: {etiqueta}"}

    if tipo == 'proveedor' and len(partes) == 2 and partes[1].isdigit():
        doc = (DocumentoDispositor.objects.select_related('dispositor')
               .filter(pk=partes[1]).first())
        if not doc or not doc.archivo:
            return None
        return {'archivo': doc.archivo,
                'nombre': _nombre(doc.archivo.name,
                                  f"{doc.get_tipo_display()} - {doc.dispositor.nombre}"),
                'linea': f"- Proveedor {doc.dispositor.nombre}: {doc.get_tipo_display()}"}

    if tipo == 'solmed' and len(partes) == 2 and partes[1].isdigit():
        from .models import DocumentoInterno
        doc = DocumentoInterno.objects.filter(pk=partes[1]).first()
        if not doc or not doc.archivo:
            return None
        if doc.tipo == DocumentoInterno.TIPO_ADICIONAL and doc.descripcion:
            etiqueta = doc.descripcion
        else:
            etiqueta = doc.get_tipo_display() + (f" {doc.entidad}" if doc.entidad else '')
        return {'archivo': doc.archivo,
                'nombre': _nombre(doc.archivo.name, f"{etiqueta} - SOLMED"),
                'linea': f"- SOLMED: {etiqueta}"}

    if tipo == 'cliente_fijo' and len(partes) == 3 and partes[2] in DOCS_CLIENTE_FIJOS:
        cliente = Cliente.objects.filter(pk=partes[1]).first() if partes[1].isdigit() else None
        campo, etiqueta = DOCS_CLIENTE_FIJOS[partes[2]]
        archivo = getattr(cliente, campo, None) if cliente else None
        if not archivo:
            return None
        return {'archivo': archivo,
                'nombre': _nombre(archivo.name, f"{etiqueta} - {cliente.nombre}"),
                'linea': f"- Cliente {cliente.nombre}: {etiqueta}"}

    if tipo == 'cliente_amb' and len(partes) == 2 and partes[1].isdigit():
        doc = (DocumentoAmbientalCliente.objects.select_related('cliente')
               .filter(pk=partes[1]).first())
        if not doc or not doc.archivo:
            return None
        etiqueta = doc.descripcion or os.path.basename(doc.archivo.name)
        return {'archivo': doc.archivo,
                'nombre': _nombre(doc.archivo.name, f"{etiqueta} - {doc.cliente.nombre}"),
                'linea': f"- Cliente {doc.cliente.nombre}: {etiqueta} (ambiental)"}

    if tipo == 'cliente_correo' and len(partes) == 2 and partes[1].isdigit():
        doc = (DocumentoCorreoCliente.objects.select_related('cliente')
               .filter(pk=partes[1]).first())
        if not doc or not doc.archivo:
            return None
        etiqueta = doc.descripcion or os.path.basename(doc.archivo.name)
        return {'archivo': doc.archivo,
                'nombre': _nombre(doc.archivo.name, f"{etiqueta} - {doc.cliente.nombre}"),
                'linea': f"- Cliente {doc.cliente.nombre}: {etiqueta}"}

    return None


def _validar_ss_cuadrilla(form, cuadrilla_form):
    """
    La seguridad social vigente del personal asignado (conductor y ayudante) debe
    estar cargada: es lo que se enviará al cliente. Marca el error en su campo.
    Devuelve True si ambos la tienen vigente.
    """
    todo_ok = True
    for campo in ('conductor', 'ayudante', 'ayudante2'):
        persona = cuadrilla_form.cleaned_data.get(campo)
        if persona is None or _tiene_ss_vigente(persona):
            continue
        todo_ok = False
        nombre = persona.get_full_name() or persona.username
        cuadrilla_form.add_error(
            campo,
            f"{nombre} no tiene seguridad social vigente. Se enviará al cliente, "
            f"así que debe estar al día: cárgala con su vigencia en el expediente."
        )
    return todo_ok


def _direcciones_clientes():
    """
    Mapa {id_cliente: dirección registrada} para autocompletar la dirección de
    la programación al elegir el cliente en el formulario.
    """
    return {
        str(pk): direccion or ''
        for pk, direccion in Cliente.objects.values_list('pk', 'direccion')
    }


def _sedes_por_cliente():
    """
    Mapa {id_cliente: [{id, nombre, direccion}, ...]} de las sedes activas, para
    poblar en vivo el desplegable de sede al elegir el cliente en la programación.
    """
    data = {}
    sedes = Sede.objects.filter(activa=True).values(
        'id', 'cliente_id', 'nombre', 'direccion'
    ).order_by('nombre')
    for s in sedes:
        data.setdefault(str(s['cliente_id']), []).append({
            'id': s['id'], 'nombre': s['nombre'], 'direccion': s['direccion'] or '',
        })
    return data


def _terceros_por_cliente():
    """
    Mapa {id_cliente: [{id, nombre, direccion, contacto, telefono}, ...]} de los
    terceros activos, para poblar en vivo el desplegable de tercero al elegir el
    cliente en la programación (y arrastrar su dirección y contacto).
    """
    data = {}
    terceros = Tercero.objects.filter(activo=True).values(
        'id', 'cliente_id', 'nombre', 'direccion', 'persona_contacto', 'telefono'
    ).order_by('nombre')
    for t in terceros:
        data.setdefault(str(t['cliente_id']), []).append({
            'id': t['id'], 'nombre': t['nombre'], 'direccion': t['direccion'] or '',
            'contacto': t['persona_contacto'] or '', 'telefono': t['telefono'] or '',
        })
    return data


def _vehiculos_cargados():
    """
    Mapa {id_vehiculo: detalle} de los camiones con carga PENDIENTE de
    disposición, para alertar en vivo al asignarlos en la programación.
    """
    return {
        str(pk): detalle or 'carga pendiente de disposición'
        for pk, detalle in Vehiculo.objects.filter(cargado=True)
                                            .values_list('pk', 'cargado_detalle')
    }


def _catalogo_docs_solmed():
    """[{token, label}] de la documentación interna de SOLMED."""
    from .models import DocumentoInterno
    def etiqueta(d):
        # La documentación adicional se nombra por su nombre libre.
        if d.tipo == DocumentoInterno.TIPO_ADICIONAL and d.descripcion:
            base = d.descripcion
        else:
            base = d.get_tipo_display() + (f" — {d.entidad}" if d.entidad else '')
        return base + (f" ({d.fecha.strftime('%d/%m/%Y')})" if d.fecha else '')
    return [{'token': f'solmed:{d.pk}', 'label': etiqueta(d)}
            for d in DocumentoInterno.objects.all()]


def _docs_de_persona(usuario, docs=None):
    """[{token, label}] del expediente de una persona, con su SS vigente primero."""
    tipo_label = dict(DocumentoPersonal.TIPO_CHOICES)
    if docs is None:
        docs = list(usuario.documentos_personales.all())
    out = []
    ss = _ss_vigente(docs)
    if ss is not None:
        out.append({
            'token': f'personal:{ss.pk}',
            'label': f"Seguridad social (vigente hasta "
                     f"{ss.fecha_vencimiento.strftime('%d/%m/%Y')})",
        })
    for d in docs:
        if d.tipo == 'SEGURIDAD_SOCIAL':
            continue
        etiqueta = (d.descripcion if d.tipo == 'OTRO' and d.descripcion
                    else tipo_label[d.tipo])
        out.append({'token': f'personal:{d.pk}',
                    'label': etiqueta + (' (vencido)' if d.vencido else '')})
    return out


def _docs_de_vehiculo(v):
    """[{token, label}] de los documentos presentes de una placa."""
    out = []
    for sub, (campo, etiqueta) in DOCS_VEHICULO.items():
        if not getattr(v, campo):
            continue
        vence = (v.fecha_vencimiento_soat if sub == 'soat'
                 else v.fecha_vencimiento_tecnomecanica if sub == 'tecno' else None)
        out.append({
            'token': f'vehiculo:{v.pk}:{sub}',
            'label': etiqueta + (f" (vence {vence.strftime('%d/%m/%Y')})" if vence else ''),
        })
    return out


def _docs_de_cliente(c):
    """[{token, label}] de un cliente: fijos + de cada correo + ambientales."""
    out = [{'token': f'cliente_fijo:{c.pk}:{sub}', 'label': etiqueta}
           for sub, (campo, etiqueta) in DOCS_CLIENTE_FIJOS.items()
           if getattr(c, campo)]
    for doc in c.documentos_correo.all():
        out.append({'token': f'cliente_correo:{doc.pk}',
                    'label': doc.descripcion or os.path.basename(doc.archivo.name)})
    for doc in c.documentos_ambientales.all():
        out.append({'token': f'cliente_amb:{doc.pk}',
                    'label': (doc.descripcion or os.path.basename(doc.archivo.name))
                             + ' (ambiental)'})
    return out


# ============================================================
#  CENTRO DE CORREOS
#  Envío de documentación por correo SIN depender de la programación: hay
#  clientes que piden la información varios días antes del servicio. El asesor
#  arma el correo (destinatarios, asunto, mensaje y cualquier documento del
#  sistema) y todo queda registrado en un historial consultable.
# ============================================================

# Peso máximo práctico de los adjuntos de UN correo. Los servidores de correo
# suelen aceptar mensajes de hasta ~25 MB, y los adjuntos viajan en base64
# (~33% más pesados): 18 MB de archivos reales ≈ 24 MB de mensaje. Pasarse casi
# garantiza el rechazo (también en el buzón del destinatario, p. ej. Gmail).
PESO_MAX_ADJUNTOS = 18 * 1024 * 1024
# Desde aquí el medidor del redactor pasa a ámbar: "se está llenando".
PESO_AVISO_ADJUNTOS = 15 * 1024 * 1024


def _peso_adjunto(resuelto):
    """Bytes del archivo de un token resuelto (0 si el storage no lo informa)."""
    try:
        return resuelto['archivo'].size
    except Exception:
        return 0


# Texto con el que se abre el mensaje si el asesor no escribe nada.
MENSAJE_ENVIO_POR_DEFECTO = (
    "Buen día,\n\n"
    "Adjuntamos la documentación solicitada para la prestación del servicio."
)


def _armar_correo_envio(destinatarios, asunto, mensaje, resueltos, cliente,
                        responder_a=None):
    """
    Construye el correo (texto plano + versión HTML de marca) con los adjuntos
    ya resueltos. Devuelve el EmailMultiAlternatives listo para .send().
    """
    from django.core.mail import EmailMultiAlternatives
    from django.template.loader import render_to_string

    lineas = [r['linea'] for r in resueltos]
    cuerpo = (mensaje or MENSAJE_ENVIO_POR_DEFECTO)
    if lineas:
        cuerpo += "\n\nDocumentos adjuntos:\n" + "\n".join(lineas)
    cuerpo += "\n\nCordialmente,\nSOLMED SAS"

    html = render_to_string('gestion/correo_envio.html', {
        'mensaje': mensaje or MENSAJE_ENVIO_POR_DEFECTO,
        'adjuntos': [l[2:] if l.startswith('- ') else l for l in lineas],
        'cliente': cliente,
    })
    correo = EmailMultiAlternatives(
        subject=asunto, body=cuerpo,
        from_email=settings.DEFAULT_FROM_EMAIL, to=destinatarios,
        reply_to=_lista_correos(responder_a),
    )
    correo.attach_alternative(html, 'text/html')
    for r in resueltos:
        with r['archivo'].open('rb') as fh:
            contenido = fh.read()
        tipo = mimetypes.guess_type(r['nombre'])[0] or 'application/octet-stream'
        correo.attach(r['nombre'], contenido, tipo)
    return correo


class BuscarDocsCorreoView(AsesorRequiredMixin, View):
    """
    Buscador del redactor del Centro de correos. El catálogo documental NO se
    manda entero al navegador (con cientos de personas sería impagable): se
    consulta aquí y solo viajan las entidades pedidas, cada una con sus
    documentos listos para marcar.

      ?q=<texto>        busca en todas las fuentes (mínimo 2 letras, 6 por fuente)
      ?fuente=<clave>   explora UNA categoría: sin q lista todas sus entidades,
                        con q filtra dentro de ella; pagina con ?desde=<n>
      ?cliente=<id>     trae SOLO ese cliente (para fijarlo al elegirlo arriba)

    Devuelve {'grupos': [{fuente, icono, items: [{clave, nombre, detalle,
    docs: [{token, label}]}]}], 'mas': {fuente: cuántos quedaron por fuera},
    'siguiente': desde para la página que sigue (solo al explorar una fuente)}.
    """
    LIMITE = 6            # búsqueda global: resultados por fuente
    LIMITE_EXPLORAR = 20  # exploración de una categoría: tamaño de página

    # --- Una consulta por fuente: (queryset filtrado, armador de item) ---

    def _personal(self, q):
        qs = (User.objects.filter(groups__isnull=False, is_superuser=False)
              .exclude(perfil__retirado=True).distinct()
              .prefetch_related('groups', 'documentos_personales')
              .order_by('first_name', 'last_name'))
        if q:
            qs = qs.filter(Q(first_name__icontains=q) | Q(last_name__icontains=q)
                           | Q(username__icontains=q)
                           | Q(perfil__numero_documento__icontains=q))
        return qs, lambda u: {
            'clave': f'personal-{u.pk}',
            'nombre': u.get_full_name() or u.username,
            'detalle': ', '.join(u.groups.values_list('name', flat=True)),
            'docs': _docs_de_persona(u),
        }

    def _vehiculos(self, q):
        qs = Vehiculo.objects.order_by('placa')
        if q:
            qs = qs.filter(Q(placa__icontains=q) | Q(marca__icontains=q)
                           | Q(modelo__icontains=q))
        return qs, lambda v: {
            'clave': f'vehiculo-{v.pk}', 'nombre': v.placa,
            'detalle': f"{v.marca} {v.modelo}".strip(),
            'docs': _docs_de_vehiculo(v),
        }

    def _proveedores(self, q):
        from .models import Dispositor
        qs = Dispositor.objects.prefetch_related('documentos').order_by('nombre')
        if q:
            qs = qs.filter(nombre__icontains=q)
        return qs, lambda d: {
            'clave': f'proveedor-{d.pk}', 'nombre': d.nombre,
            'detalle': d.get_tipo_display(),
            'docs': [{'token': f'proveedor:{doc.pk}',
                      'label': doc.get_tipo_display()
                               + (f" — {doc.descripcion}" if doc.descripcion else '')}
                     for doc in d.documentos.all()],
        }

    def _clientes(self, q):
        qs = (Cliente.objects
              .prefetch_related('documentos_correo', 'documentos_ambientales')
              .order_by('nombre'))
        if q:
            qs = qs.filter(Q(nombre__icontains=q) | Q(sigla__icontains=q)
                           | Q(identificacion__icontains=q))
        return qs, lambda c: {
            'clave': f'cliente-{c.pk}', 'nombre': c.nombre,
            'detalle': c.identificacion, 'docs': _docs_de_cliente(c),
        }

    # clave de la fuente -> (título, ícono, consulta). El orden es el de pintado.
    @property
    def fuentes(self):
        return {
            'personal':    ('Personal', 'person-badge', self._personal),
            'vehiculos':   ('Vehículos', 'truck', self._vehiculos),
            'proveedores': ('Proveedores', 'recycle', self._proveedores),
            'clientes':    ('Clientes', 'buildings', self._clientes),
        }

    def get(self, request):
        q = request.GET.get('q', '').strip()
        fuente = request.GET.get('fuente', '').strip()
        cliente_id = request.GET.get('cliente', '').strip()
        try:
            desde = max(0, int(request.GET.get('desde', 0)))
        except ValueError:
            desde = 0
        grupos, mas = [], {}

        # --- Un cliente puntual (al elegirlo en "Datos del correo") ---
        if cliente_id.isdigit():
            c = (Cliente.objects.filter(pk=cliente_id)
                 .prefetch_related('documentos_correo', 'documentos_ambientales').first())
            if c is not None:
                _titulo, _icono, consulta = self.fuentes['clientes']
                grupos.append({'fuente': _titulo, 'icono': _icono,
                               'items': [consulta('')[1](c)]})
            return JsonResponse({'grupos': grupos, 'mas': mas})

        # --- SOLMED: una sola "entidad" con la documentación de la empresa ---
        if fuente == 'solmed':
            docs = _catalogo_docs_solmed()
            if q:
                docs = [d for d in docs if q.lower() in d['label'].lower()]
            grupos.append({'fuente': 'SOLMED', 'icono': 'building', 'items': [{
                'clave': 'solmed', 'nombre': 'SOLMED SAS',
                'detalle': 'Documentación de la empresa', 'docs': docs,
            }]})
            return JsonResponse({'grupos': grupos, 'mas': mas})

        # --- Explorar UNA categoría: lista completa paginada (con o sin q) ---
        if fuente in self.fuentes:
            titulo, icono, consulta = self.fuentes[fuente]
            qs, item = consulta(q)
            total = qs.count()
            pagina = [item(e) for e in qs[desde:desde + self.LIMITE_EXPLORAR]]
            grupos.append({'fuente': titulo, 'icono': icono, 'items': pagina})
            faltan = total - desde - len(pagina)
            if faltan > 0:
                mas[titulo] = faltan
            return JsonResponse({'grupos': grupos, 'mas': mas,
                                 'siguiente': desde + len(pagina)})

        # --- Búsqueda global: todas las fuentes, poquitos por fuente ---
        if len(q) < 2:
            return JsonResponse({'grupos': grupos, 'mas': mas})
        for titulo, icono, consulta in self.fuentes.values():
            qs, item = consulta(q)
            total = qs.count()
            items = [item(e) for e in qs[:self.LIMITE]]
            if items:
                grupos.append({'fuente': titulo, 'icono': icono, 'items': items})
            if total > self.LIMITE:
                mas[titulo] = total - self.LIMITE
        return JsonResponse({'grupos': grupos, 'mas': mas})


class ListaEnviosCorreoView(AsesorRequiredMixin, PaginadoMixin, ListView):
    """Historial del Centro de correos, con buscador, filtro y estadísticas."""
    model = EnvioCorreo
    template_name = 'gestion/centro_correos.html'
    context_object_name = 'envios'

    def get_queryset(self):
        qs = EnvioCorreo.objects.select_related('cliente', 'enviado_por')
        q = self.request.GET.get('q', '').strip()
        estado = self.request.GET.get('estado', '')
        if q:
            qs = qs.filter(
                Q(destinatarios__icontains=q) | Q(asunto__icontains=q)
                | Q(cliente__nombre__icontains=q)
            )
        if estado in ('ENVIADO', 'FALLIDO'):
            qs = qs.filter(estado=estado)
        return qs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        inicio_mes = timezone.localdate().replace(day=1)
        todos = EnvioCorreo.objects.all()
        context['kpi'] = {
            'total': todos.count(),
            'mes': todos.filter(fecha__date__gte=inicio_mes).count(),
            'fallidos': todos.filter(estado='FALLIDO').count(),
            'ultimo': todos.first(),   # ordering = ['-fecha']
        }
        context['q'] = self.request.GET.get('q', '').strip()
        context['estado_sel'] = self.request.GET.get('estado', '')
        return context


class CrearEnvioCorreoView(AsesorRequiredMixin, View):
    """
    Redacción y envío de un correo de documentación. GET pinta el formulario
    (con ?copiar=<id> se precarga desde un envío anterior, para reenviar o
    usarlo de plantilla); POST valida, envía y registra el resultado.
    """
    template_name = 'gestion/form_envio_correo.html'

    def _render(self, request, datos, seleccionados, errores=None):
        clientes = list(Cliente.objects.order_by('nombre'))
        # La canasta de adjuntos se arma en el servidor con etiqueta legible;
        # los tokens que ya no resuelven simplemente no vuelven a la canasta.
        seleccion = []
        for t in seleccionados:
            r = _resolver_adjunto_correo(t)
            if r is not None:
                linea = r['linea']
                seleccion.append({'token': t,
                                  'label': linea[2:] if linea.startswith('- ') else linea,
                                  'peso': _peso_adjunto(r)})
        # Una caja por destinatario (siempre al menos una vacía para escribir).
        destinatarios_lista = [d.strip() for d in datos['destinatarios'].split(',')
                               if d.strip()] or ['']
        return render(request, self.template_name, {
            # El catálogo documental NO viaja con la página: el buscador
            # (BuscarDocsCorreoView) lo consulta al escribir o al explorar
            # una categoría, incluida la documentación de SOLMED.
            'destinatarios_lista': destinatarios_lista,
            'reply_to_defecto': ', '.join(getattr(settings, 'EMAIL_REPLY_TO', []) or []),
            'clientes': clientes,
            'correos_clientes': {str(c.pk): c.email for c in clientes if c.email},
            'datos': datos,
            'seleccion': seleccion,
            'errores': errores or [],
        })

    def get(self, request):
        por_defecto = ', '.join(getattr(settings, 'EMAIL_REPLY_TO', []) or [])
        datos = {
            'cliente': '',
            'destinatarios': '',
            'asunto': 'SOLMED - Documentación del servicio',
            'mensaje': MENSAJE_ENVIO_POR_DEFECTO,
            'responder_a': por_defecto,
        }
        seleccionados = []
        base = EnvioCorreo.objects.filter(pk=request.GET.get('copiar') or 0).first()
        if base is not None:
            datos = {
                'cliente': str(base.cliente_id or ''),
                'destinatarios': base.destinatarios,
                'asunto': base.asunto,
                'mensaje': base.mensaje or MENSAJE_ENVIO_POR_DEFECTO,
                'responder_a': base.responder_a or por_defecto,
            }
            seleccionados = base.adjuntos or []
        return self._render(request, datos, seleccionados)

    def post(self, request):
        from django.core.exceptions import ValidationError
        from django.core.validators import validate_email

        datos = {
            'cliente': request.POST.get('cliente', '').strip(),
            # Una caja por correo (name="destinatarios" repetido); las vacías
            # se ignoran. Se une con coma: todo lo demás sigue igual.
            'destinatarios': ', '.join(
                v.strip() for v in request.POST.getlist('destinatarios') if v.strip()),
            'asunto': request.POST.get('asunto', '').strip(),
            'mensaje': request.POST.get('mensaje', '').strip(),
            'responder_a': request.POST.get('responder_a', '').strip(),
        }
        tokens = request.POST.getlist('adjuntos')
        cliente = (Cliente.objects.filter(pk=datos['cliente']).first()
                   if datos['cliente'].isdigit() else None)

        # --- Validación ---
        errores = []
        correos = [c.strip() for c in datos['destinatarios'].replace(';', ',').split(',')
                   if c.strip()]
        if not correos:
            errores.append("Escribe al menos un correo destinatario.")
        for c in correos:
            try:
                validate_email(c)
            except ValidationError:
                errores.append(f"«{c}» no es un correo válido.")
        if len(', '.join(correos)) > 500:
            errores.append("Son demasiados destinatarios para un solo envío.")
        if not datos['asunto']:
            errores.append("Escribe el asunto del correo.")
        for c in _lista_correos(datos['responder_a']):
            try:
                validate_email(c)
            except ValidationError:
                errores.append(f"«{c}» no es un correo válido para las respuestas.")
        resueltos = []
        for t in tokens:
            r = _resolver_adjunto_correo(t)
            if r is None:
                errores.append("Uno de los documentos marcados ya no existe en el "
                               "sistema. Revisa la selección y vuelve a intentarlo.")
                break
            resueltos.append(r)
        # Con demasiado peso el servidor (o el buzón del cliente) lo va a
        # rechazar: mejor frenar aquí con una explicación que registrar un fallo.
        if not errores:
            peso_total = sum(_peso_adjunto(r) for r in resueltos)
            if peso_total > PESO_MAX_ADJUNTOS:
                errores.append(
                    f"Los documentos marcados pesan ≈ {peso_total / (1024 * 1024):.1f} MB "
                    f"y el correo casi seguro será rechazado (límite práctico: "
                    f"{PESO_MAX_ADJUNTOS // (1024 * 1024)} MB). Divide el envío en dos correos."
                )
        if errores:
            return self._render(request, datos, tokens, errores)

        # --- Envío y registro (el fallo del servidor también queda en el historial) ---
        registro = EnvioCorreo(
            cliente=cliente,
            destinatarios=', '.join(correos),
            asunto=datos['asunto'],
            mensaje=datos['mensaje'],
            adjuntos=tokens,
            adjuntos_detalle=[r['linea'][2:] if r['linea'].startswith('- ') else r['linea']
                              for r in resueltos],
            responder_a=datos['responder_a'],
            enviado_por=request.user,
        )
        try:
            _armar_correo_envio(correos, datos['asunto'], datos['mensaje'],
                                resueltos, cliente,
                                datos['responder_a']).send(fail_silently=False)
        except Exception as e:
            registro.estado = 'FALLIDO'
            registro.error = str(e)
            registro.save()
            messages.error(
                request,
                f"El servidor de correo rechazó el envío ({e}). Quedó registrado "
                "como fallido: corrígelo y reenvíalo desde el detalle."
            )
            return redirect('gestion:detalle_envio_correo', pk=registro.pk)

        registro.save()
        n = len(resueltos)
        messages.success(
            request,
            f"Correo enviado a {registro.destinatarios} con {n} "
            f"documento{'s' if n != 1 else ''} adjunto{'s' if n != 1 else ''}."
        )
        return redirect('gestion:detalle_envio_correo', pk=registro.pk)


class PesoAdjuntosCorreoView(AsesorRequiredMixin, View):
    """
    Peso en bytes de cada token pedido (?t=<token>&t=<token>…), para el medidor
    del redactor. Se consulta solo lo que está en la canasta (el JS lo cachea
    por token): así el buscador no paga el costo de preguntar tamaños al
    storage, que en producción (S3) es una petición por archivo.
    """
    def get(self, request):
        pesos = {}
        for t in request.GET.getlist('t')[:80]:
            r = _resolver_adjunto_correo(t)
            if r is not None:
                pesos[t] = _peso_adjunto(r)
        return JsonResponse({'pesos': pesos,
                             'aviso': PESO_AVISO_ADJUNTOS, 'maximo': PESO_MAX_ADJUNTOS})


class DetalleEnvioCorreoView(AsesorRequiredMixin, DetailView):
    """Copia fiel de un envío del historial (lo que se mandó y a quién)."""
    model = EnvioCorreo
    template_name = 'gestion/detalle_envio_correo.html'
    context_object_name = 'envio'


def _disposicion_meta():
    """IDs de los destinos internos especiales, para la lógica del formulario."""
    from .models import Dispositor
    nombres = {d.nombre: d.pk for d in Dispositor.objects.filter(tipo='INTERNO')}
    return {
        'dejar_cargado': nombres.get(Dispositor.DEJAR_CARRO_CARGADO),
        'trasiego_placa': nombres.get(Dispositor.TRASIEGO_PLACA),
        'sin_disposicion': nombres.get(Dispositor.SIN_DISPOSICION),
    }


def _avisar_carga_pendiente(request, programacion, orden):
    """
    Tras generar la orden: si el servicio quedó SIN disposición final, avisa
    qué quedó cargado (camiones o tanques) para que el personal lo tenga en cuenta.
    """
    from .models import Dispositor
    if programacion.requiere_disposicion_final != 'NO' or not programacion.dispositor_final_id:
        return
    destino = programacion.dispositor_final.nombre
    if destino == Dispositor.DEJAR_CARRO_CARGADO:
        placas = ", ".join(sorted({
            r.vehiculo.placa for r in orden.recorridos.all() if r.vehiculo_id
        }))
        messages.warning(
            request,
            f"OJO: sin disposición final — el/los camión(es) {placas} quedaron CARGADOS, "
            f"pendientes de disposición."
        )
    elif destino == Dispositor.TRASIEGO_PLACA and programacion.trasiego_vehiculo_id:
        messages.warning(
            request,
            f"OJO: el contenido se trasegó al camión {programacion.trasiego_vehiculo.placa}, "
            f"que quedó CARGADO pendiente de disposición."
        )
    elif destino in Dispositor.TANQUES:
        messages.warning(
            request,
            f"OJO: el contenido quedó en {destino.title()} (tanques SOLMED), "
            f"pendiente de disposición final."
        )
    # Dispositor.SIN_DISPOSICION no deja nada pendiente: no hay nada que avisar.


class ListaProgramacionesView(AsesorRequiredMixin, PaginadoMixin, ListView):
    model = Programacion
    template_name = 'gestion/lista_programaciones.html'
    context_object_name = 'programaciones'

    def get_queryset(self):
        qs = Programacion.objects.select_related(
            'cliente', 'orden'
        ).prefetch_related('cuadrillas')
        estado_filtro = self.request.GET.get('estado')
        if estado_filtro:
            qs = qs.filter(estado=estado_filtro)
        # Por el número de su orden, de mayor a menor; si alguna quedara sin
        # orden, arriba (es la más pendiente). El pk desempata para paginar.
        return qs.order_by(F('orden_id').desc(nulls_first=True), '-pk')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['estado_choices'] = Programacion.ESTADO_CHOICES
        context['current_estado'] = self.request.GET.get('estado', '')
        return context


def _contexto_programacion(context):
    """Datos compartidos por el formulario de programación (JSON para el JS)."""
    context['personal_docs'] = _estado_documentos_personal()
    context['direcciones_clientes'] = _direcciones_clientes()
    context['sedes_por_cliente'] = _sedes_por_cliente()
    context['terceros_por_cliente'] = _terceros_por_cliente()
    context['vehiculos_cargados'] = _vehiculos_cargados()
    context['disposicion_meta'] = _disposicion_meta()
    # Catálogos que se administran desde un popup del propio formulario
    # (agregar/eliminar sin salir de la programación). Solo los activos.
    context['basculas'] = [
        {'id': b.pk, 'nombre': b.nombre, 'direccion': b.direccion}
        for b in Bascula.objects.filter(activo=True)
    ]
    context['sitios_inicio'] = [
        {'id': s.pk, 'nombre': s.nombre}
        for s in SitioInicio.objects.filter(activo=True)
    ]
    context['tipos_residuo'] = [
        {'id': t.pk, 'nombre': t.nombre}
        for t in TipoResiduo.objects.filter(activo=True)
    ]

    # Instrucciones del servicio: pares (casilla, cantidad) para renderizar la
    # primera parte del acta (Succión y Sondeo) en dos columnas alineadas.
    form = context.get('form')
    if form is not None:
        context['instrucciones_succion'] = [
            (form['succ_canecas'], form['succ_canecas_cant']),
            (form['succ_pozos_inspeccion'], form['succ_pozos_inspeccion_cant']),
            (form['succ_pozos_septicos'], form['succ_pozos_septicos_cant']),
            (form['succ_tanques'], form['succ_tanques_cant']),
            (form['succ_trampas_grasa'], form['succ_trampas_grasa_cant']),
        ]
        context['instrucciones_sondeo'] = [
            (form['sond_red_aguas_lluvias'], form['sond_red_aguas_lluvias_cant']),
            (form['sond_red_aguas_negras'], form['sond_red_aguas_negras_cant']),
            (form['sond_red_acueducto'], form['sond_red_acueducto_cant']),
            (form['sond_correctivo'], form['sond_correctivo_cant']),
            (form['sond_preventivo'], form['sond_preventivo_cant']),
        ]
    return context


class CrearProgramacionView(AsesorRequiredMixin, CreateView):
    model = Programacion
    form_class = ProgramacionForm
    template_name = 'gestion/form_programacion.html'
    success_url = reverse_lazy('gestion:lista_programaciones')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        if 'cuadrilla_form' not in context:
            data = self.request.POST if self.request.method == 'POST' else None
            context['cuadrilla_form'] = ProgramacionCuadrillaForm(data, prefix='cuadrilla')
        _contexto_programacion(context)
        return context

    def form_valid(self, form):
        # Una programación = un vehículo = una orden. Una sola cuadrilla.
        cuadrilla_form = ProgramacionCuadrillaForm(self.request.POST, prefix='cuadrilla')
        if not cuadrilla_form.is_valid():
            return self.render_to_response(
                self.get_context_data(form=form, cuadrilla_form=cuadrilla_form))
        cursos_ok = _validar_cursos_cuadrilla(form, cuadrilla_form)
        ss_ok = _validar_ss_cuadrilla(form, cuadrilla_form)
        if not (cursos_ok and ss_ok):
            messages.error(
                self.request,
                "No se guardó: revisa la documentación del personal asignado "
                "(seguridad social vigente y cursos exigidos)."
            )
            return self.render_to_response(
                self.get_context_data(form=form, cuadrilla_form=cuadrilla_form))

        form.instance.creado_por = self.request.user

        # La programación, su cuadrilla y la orden nacen JUNTAS o no nace
        # ninguna: antes se guardaban por separado y un fallo al generar la
        # orden dejaba la programación colgada en borrador, invisible desde la
        # lista de órdenes y sin que el asesor se enterara.
        orden = None
        for intento in range(_INTENTOS_NUMERO_ORDEN):
            try:
                with transaction.atomic():
                    self.object = form.save()
                    cuadrilla = cuadrilla_form.save(commit=False)
                    cuadrilla.programacion = self.object
                    cuadrilla.save()
                    orden = self.object.convertir_en_orden(self.request.user)
                break
            except IntegrityError:
                # El número de orden se calcula como "el último + 1", así que
                # dos guardados a la vez (o un doble clic) pueden pedir el
                # mismo. Se descarta lo revertido y se reintenta: el segundo
                # cálculo ya ve el número que acaba de ocupar el otro.
                _olvidar_guardado(form.instance, cuadrilla_form.instance)
                if intento == _INTENTOS_NUMERO_ORDEN - 1:
                    messages.error(
                        self.request,
                        "No se pudo guardar la programación porque otro usuario "
                        "estaba generando una orden al mismo tiempo. No se creó "
                        "nada: vuelve a intentarlo."
                    )
                    return self.render_to_response(self.get_context_data(
                        form=form, cuadrilla_form=cuadrilla_form))
            except ValueError as e:
                # Motivo de negocio (cursos vencidos, cuadrilla sin vehículo):
                # no se guarda nada y el asesor corrige sobre el formulario.
                messages.error(self.request, f"No se guardó la programación: {e}")
                return self.render_to_response(self.get_context_data(
                    form=form, cuadrilla_form=cuadrilla_form))

        messages.success(
            self.request,
            f"Programación creada y Orden #{orden.numero_orden} generada."
        )
        if form.cleaned_data.get('sin_correos'):
            messages.info(
                self.request,
                "No se envió el aviso por correo al personal (lo marcaste al "
                "crear). Cuando quieras avisarles, usa los botones de reenviar "
                "en el expediente de la orden."
            )
        else:
            _avisar_correos_programacion(self.request, self.object)
        _avisar_carga_pendiente(self.request, self.object, orden)

        return HttpResponseRedirect(reverse('gestion:detalle_orden', kwargs={'pk': orden.pk}))


class ActualizarProgramacionView(AsesorRequiredMixin, UpdateView):
    model = Programacion
    form_class = ProgramacionForm
    template_name = 'gestion/form_programacion.html'
    success_url = reverse_lazy('gestion:lista_programaciones')

    def dispatch(self, request, *args, **kwargs):
        # Una programación ya convertida en orden es de solo lectura.
        self.object = self.get_object()
        if self.object.orden_id:
            messages.info(
                request,
                f"Esta programación ya generó la Orden #{self.object.orden.numero_orden}. "
                "Corrige lo que quedó mal desde la orden (datos y recorridos)."
            )
            return redirect('gestion:detalle_orden', pk=self.object.orden_id)
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        if 'cuadrilla_form' not in context:
            data = self.request.POST if self.request.method == 'POST' else None
            context['cuadrilla_form'] = ProgramacionCuadrillaForm(
                data, prefix='cuadrilla', instance=self.object.cuadrillas.first())
        _contexto_programacion(context)
        return context

    def form_valid(self, form):
        cuadrilla_form = ProgramacionCuadrillaForm(
            self.request.POST, prefix='cuadrilla', instance=self.object.cuadrillas.first())
        if not cuadrilla_form.is_valid():
            return self.render_to_response(
                self.get_context_data(form=form, cuadrilla_form=cuadrilla_form))
        cursos_ok = _validar_cursos_cuadrilla(form, cuadrilla_form)
        ss_ok = _validar_ss_cuadrilla(form, cuadrilla_form)
        if not (cursos_ok and ss_ok):
            messages.error(
                self.request,
                "No se guardó: revisa la documentación del personal asignado "
                "(seguridad social vigente y cursos exigidos)."
            )
            return self.render_to_response(
                self.get_context_data(form=form, cuadrilla_form=cuadrilla_form))
        self.object = form.save()
        cuadrilla = cuadrilla_form.save(commit=False)
        cuadrilla.programacion = self.object
        cuadrilla.save()
        messages.success(self.request, "Programación actualizada.")
        return HttpResponseRedirect(self.get_success_url())


# ============================================================
#  ACCESO DEL AYUDANTE POR TOKEN (sin usuario ni contraseña)
#  Al programarle un servicio se le envía por correo su hoja de ruta con un
#  enlace personal. Desde ahí ve lo que necesita y sube las fotos que le
#  exijan sus novedades (inicia/termina donde el cliente, parqueadero, punto
#  de encuentro). El enlace vence a los días de DIAS_VIGENCIA_ACCESO.
# ============================================================

def _datos_servicio_ayudante(cuadrilla, slot):
    """Todo lo que el ayudante necesita saber de su servicio, en un dict."""
    programacion = cuadrilla.programacion
    lugar = programacion.tercero or programacion.sede_cliente
    conductor = cuadrilla.conductor
    return {
        'ayudante': cuadrilla.ayudante_de(slot),
        'cuadrilla': cuadrilla,
        'programacion': programacion,
        'cliente': programacion.cliente,
        'lugar': lugar.nombre if lugar else '',
        'direccion': (
            (programacion.tercero.direccion if programacion.tercero_id else '')
            or (programacion.sede_cliente.direccion if programacion.sede_cliente_id else '')
            or programacion.direccion or programacion.cliente.direccion
        ),
        'contacto': programacion.nombre_contacto_recibe,
        'sitio_inicio': programacion.sitio_inicio.nombre if programacion.sitio_inicio_id else '',
        'conductor': (conductor.get_full_name() or conductor.username) if conductor else '',
        'placa': cuadrilla.vehiculo.placa if cuadrilla.vehiculo_id else '',
        'novedades': ProgramacionCuadrilla.novedades_display(
            cuadrilla.ayudante_novedad if slot == 1 else cuadrilla.ayudante2_novedad
        ),
        'fotos_pedidas': cuadrilla.fotos_pedidas(slot),
        'orden': programacion.orden,
        # Lo ÚNICO que se le muestra al ayudante (además de sus fotos): a qué
        # hora y a dónde llega. La hora de ingreso manda sobre la del servicio,
        # y el sitio de inicio sobre el lugar del cliente: es donde empieza él.
        'hora_ayudante': (programacion.hora_ingreso_bodega
                          or programacion.hora_servicio),
        # Dónde llega: el sitio de inicio manda; si no, la sede o el tercero; y
        # como último recurso la dirección del servicio. Nunca el nombre del
        # cliente: eso es a quién se le presta, no a dónde va él.
        'lugar_ayudante': (
            (programacion.sitio_inicio.nombre if programacion.sitio_inicio_id else '')
            or (lugar.nombre if lugar else '')
            or programacion.direccion
            or programacion.cliente.direccion
        ),
    }


def _lineas_correo_servicio(ctx):
    """Versión de TEXTO del correo de programación (respaldo del HTML)."""
    p = ctx['programacion']
    lineas = [
        f"Hola {ctx['nombre']},", "",
        f"Se te asignó un servicio para el {p.fecha.strftime('%d/%m/%Y')}.", "",
    ]
    for etiqueta, valor in ctx['detalles']:
        lineas.append(f"{etiqueta}: {valor}")
    # El ayudante solo recibe su hora, su lugar y sus fotos.
    if ctx['rol'] != 'ayudante':
        if ctx['novedades']:
            lineas += ["", "Tu turno:"] + [f"- {n}" for n in ctx['novedades']]
        if p.observaciones_servicio:
            lineas += ["", "Observaciones del servicio:", p.observaciones_servicio]
    if ctx['fotos_pedidas']:
        lineas += ["", "Debes subir una foto de:"]
        lineas += [f"- {f['etiqueta']}" for f in ctx['fotos_pedidas']]
    lineas += ["", ctx['url_texto'] + ":", ctx['url'], ""]
    if ctx.get('fecha_limite'):
        lineas += [f"El enlace es personal y sirve hasta el "
                   f"{ctx['fecha_limite'].strftime('%d/%m/%Y')}.", ""]
    lineas += ["Cordialmente,", "SOLMED SAS"]
    return lineas


def _enviar_correo_servicio(ctx, correo):
    """Envía el correo de programación (texto + HTML de marca) a una persona."""
    from django.core.mail import EmailMultiAlternatives
    p = ctx['programacion']
    mensaje = EmailMultiAlternatives(
        subject=f"SOLMED - Servicio del {p.fecha.strftime('%d/%m/%Y')}",
        body="\n".join(_lineas_correo_servicio(ctx)),
        from_email=settings.DEFAULT_FROM_EMAIL,
        to=[correo],
        reply_to=_reply_to(),
    )
    mensaje.attach_alternative(
        get_template('gestion/correo_programacion.html').render(ctx), 'text/html')
    mensaje.send(fail_silently=False)


def _correo_ayudante(request, cuadrilla, slot):
    """
    Arma y envía el correo del ayudante del slot con su enlace personal (token).
    Sirve para el envío inicial de la programación y para reenviarlo después.
    Devuelve (enviado, aviso); aviso explica por qué no se pudo enviar.
    """
    ayudante = cuadrilla.ayudante_de(slot)
    nombre = ayudante.get_full_name() or ayudante.username
    correo = (ayudante.email or '').strip()
    if not correo:
        return False, f"El ayudante {nombre} no tiene correo registrado: no se le pudo avisar"

    datos = _datos_servicio_ayudante(cuadrilla, slot)
    # Al ayudante NO se le manda la operación completa: solo lo suyo.
    filas = []
    if datos['hora_ayudante']:
        filas.append(('Hora', datos['hora_ayudante'].strftime('%H:%M')))
    if datos['lugar_ayudante']:
        filas.append(('Lugar', datos['lugar_ayudante']))
    ctx = {
        'nombre': nombre,
        'primer_nombre': (ayudante.first_name or nombre).split(' ')[0],
        'programacion': cuadrilla.programacion,
        'rol': 'ayudante',
        'detalles': filas,
        'novedades': datos['novedades'],
        'fotos_pedidas': datos['fotos_pedidas'],
        'url': request.build_absolute_uri(reverse(
            'gestion:acceso_ayudante', kwargs={'token': cuadrilla.token_de(slot)})),
        'url_texto': ('Entra aquí para verlo y subir las fotos '
                      '(no necesitas usuario ni contraseña)'
                      if datos['fotos_pedidas'] else
                      'Entra aquí para ver los detalles del servicio'),
        'url_boton': ('Ver mi servicio y subir fotos'
                      if datos['fotos_pedidas'] else 'Ver mi servicio'),
        'fecha_limite': cuadrilla.fecha_limite_acceso,
    }
    _enviar_correo_servicio(ctx, correo)
    return True, None


def _correo_conductor(request, cuadrilla, conductor=None):
    """
    Arma y envía el correo del conductor con el enlace a su servicio en la
    plataforma. `conductor` permite mandárselo a quien está de verdad en el
    recorrido (si lo cambiaron después de programar, la cuadrilla conserva al
    anterior). Devuelve (enviado, aviso).
    """
    conductor = conductor or cuadrilla.conductor
    if conductor is None:
        return False, "El recorrido no tiene conductor asignado: no hay a quién avisarle"
    nombre = conductor.get_full_name() or conductor.username
    correo = (conductor.email or '').strip()
    if not correo:
        return False, f"El conductor {nombre} no tiene correo registrado: no se le pudo avisar"

    programacion = cuadrilla.programacion
    datos = _datos_servicio_ayudante(cuadrilla, 1)
    if programacion.orden_id:
        url = request.build_absolute_uri(reverse(
            'gestion:detalle_orden_conductor', kwargs={'pk': programacion.orden_id}))
    else:
        url = request.build_absolute_uri(reverse('gestion:dashboard_conductor'))

    # Sin el nombre del cliente ni el de su sede (decisión de gerencia: al
    # personal solo le llega lo necesario para prestar el servicio).
    filas = []
    if datos['direccion']:
        filas.append(('Dirección', datos['direccion']))
    if programacion.hora_ingreso_bodega:
        filas.append(('Hora de ingreso', programacion.hora_ingreso_bodega.strftime('%H:%M')))
    if datos['sitio_inicio']:
        filas.append(('Sitio de inicio', datos['sitio_inicio']))
    if programacion.hora_servicio:
        filas.append(('Hora del servicio', programacion.hora_servicio.strftime('%H:%M')))
    if datos['placa']:
        filas.append(('Vehículo', datos['placa']))
    if datos['contacto']:
        filas.append(('Contacto en el sitio', datos['contacto']))
    ayudantes = [p.get_full_name() or p.username
                 for p in (cuadrilla.ayudante, cuadrilla.ayudante2) if p]
    if ayudantes:
        filas.append(('Ayudante(s)', ', '.join(ayudantes)))

    _enviar_correo_servicio({
        'nombre': nombre,
        'primer_nombre': (conductor.first_name or nombre).split(' ')[0],
        'programacion': programacion,
        'rol': 'conductor',
        'detalles': filas,
        'novedades': [],
        'fotos_pedidas': [],
        'url': url,
        'url_texto': 'Entra a la plataforma para ver tu servicio',
        'url_boton': 'Ver mi servicio',
        'fecha_limite': None,
    }, correo)
    return True, None


def _enviar_correos_programacion(programacion, request):
    """
    Notifica por correo a TODO el personal de la programación: el conductor
    recibe su servicio con enlace a la plataforma, y cada ayudante su hoja de
    ruta con el enlace personal (token) para ver el servicio y subir fotos.
    Devuelve (enviados, avisos); un fallo de correo no debe tumbar la orden.
    """
    enviados, avisos = 0, []
    for cuadrilla in programacion.cuadrillas.select_related(
            'ayudante', 'ayudante2', 'conductor', 'vehiculo'):
        # Conductor (entra a la plataforma con su usuario) y ayudantes (enlace
        # personal con token). Cada uno arma su correo en su propio helper,
        # compartido con el botón de reenviar del expediente de la orden.
        destinatarios = [(_correo_conductor, (request, cuadrilla))] if cuadrilla.conductor else []
        destinatarios += [
            (_correo_ayudante, (request, cuadrilla, slot))
            for slot in (1, 2) if cuadrilla.ayudante_de(slot) is not None
        ]
        for enviar, argumentos in destinatarios:
            enviado, aviso = enviar(*argumentos)
            if enviado:
                enviados += 1
            if aviso:
                avisos.append(aviso)
    return enviados, avisos


def _avisar_correos_programacion(request, programacion):
    """Notifica al personal (conductor y ayudantes) e informa el resultado."""
    try:
        enviados, avisos = _enviar_correos_programacion(programacion, request)
    except Exception as e:
        messages.warning(request, f"No se pudo notificar al personal por correo ({e}).")
        return
    if enviados:
        messages.success(
            request,
            f"Programación enviada por correo a {enviados} "
            f"persona{'s' if enviados != 1 else ''} (conductor y ayudantes)."
        )
    for aviso in avisos:
        messages.warning(request, aviso)


class AccesoAyudanteView(View):
    """
    Página PÚBLICA (sin login) a la que entra el ayudante con su enlace: ve su
    servicio y sube las fotos que le exigen sus novedades. El token identifica
    al ayudante y la cuadrilla; vence pasados los días de vigencia.
    """
    template_name = 'gestion/acceso_ayudante.html'

    def _buscar(self, token):
        """Devuelve (cuadrilla, slot) según cuál token coincide."""
        cuadrilla = ProgramacionCuadrilla.objects.filter(token_ayudante=token).first()
        if cuadrilla is not None:
            return cuadrilla, 1
        cuadrilla = get_object_or_404(ProgramacionCuadrilla, token_ayudante2=token)
        return cuadrilla, 2

    def _contexto(self, cuadrilla, slot):
        datos = _datos_servicio_ayudante(cuadrilla, slot)
        fotos = cuadrilla.fotos_ayudantes.filter(slot=slot)
        por_novedad = {}
        for foto in fotos:
            por_novedad.setdefault(foto.novedad, []).append(foto)
        # Cada foto pedida con las que ya subió.
        pedidas = [{
            **pedida,
            'fotos': por_novedad.get(pedida['codigo'], []),
        } for pedida in datos['fotos_pedidas']]
        datos['fotos_pedidas'] = pedidas
        datos['pendientes'] = [p for p in pedidas if not p['fotos']]
        datos['vigente'] = cuadrilla.acceso_vigente
        datos['fecha_limite'] = cuadrilla.fecha_limite_acceso
        datos['slot'] = slot
        return datos

    def get(self, request, token):
        cuadrilla, slot = self._buscar(token)
        if cuadrilla.ayudante_de(slot) is None:
            raise Http404("Este enlace ya no corresponde a un ayudante asignado.")
        return render(request, self.template_name, self._contexto(cuadrilla, slot))

    def post(self, request, token):
        cuadrilla, slot = self._buscar(token)
        if cuadrilla.ayudante_de(slot) is None:
            raise Http404("Este enlace ya no corresponde a un ayudante asignado.")

        if not cuadrilla.acceso_vigente:
            messages.error(request, "Este enlace ya venció: habla con tu coordinador.")
            return redirect('gestion:acceso_ayudante', token=token)

        novedad = request.POST.get('novedad', '')
        codigos = {f['codigo'] for f in cuadrilla.fotos_pedidas(slot)}
        fotos = request.FILES.getlist('fotos')
        if novedad not in codigos:
            messages.error(request, "Esa foto no corresponde a tu turno.")
        elif not fotos:
            messages.error(request, "Selecciona o toma la foto antes de enviarla.")
        else:
            for foto in fotos:
                FotoAyudante.objects.create(
                    cuadrilla=cuadrilla, slot=slot, novedad=novedad, archivo=foto)
            messages.success(
                request,
                f"{len(fotos)} foto{'s' if len(fotos) != 1 else ''} enviada"
                f"{'s' if len(fotos) != 1 else ''}. ¡Gracias!"
            )
        return redirect('gestion:acceso_ayudante', token=token)


class CrearItemCatalogoView(AsesorRequiredMixin, View):
    """
    Crea un registro de un catálogo desde el popup de la programación
    (báscula, sitio de inicio, residuo). Responde JSON para que el JS
    sincronice el desplegable sin recargar.

    Si el nombre ya existe no se duplica: se reutiliza y, si estaba oculto,
    se vuelve a mostrar.
    """
    modelo = None
    etiqueta = 'registro'          # cómo se nombra en los mensajes
    con_direccion = False          # solo las básculas tienen dirección

    def post(self, request):
        nombre = request.POST.get('nombre', '').strip()
        direccion = request.POST.get('direccion', '').strip()
        if not nombre:
            return JsonResponse(
                {'ok': False, 'error': f'El nombre {self.etiqueta} es obligatorio.'}, status=400)

        item = self.modelo.objects.filter(nombre__iexact=nombre).first()
        if item is None:
            datos = {'nombre': nombre}
            if self.con_direccion:
                datos['direccion'] = direccion
            item = self.modelo.objects.create(**datos)
        else:
            # Ya existía: se reactiva y, si mandaron dirección, se actualiza.
            item.activo = True
            if self.con_direccion and direccion:
                item.direccion = direccion
            item.save()
        return JsonResponse({'ok': True, 'id': item.pk, 'nombre': item.nombre,
                             'direccion': getattr(item, 'direccion', '')})


class EliminarItemCatalogoView(AsesorRequiredMixin, View):
    """
    Elimina un registro del catálogo desde el popup (POST, responde JSON). Si
    ya se usó en programaciones no se borra: se oculta del desplegable y el
    histórico queda intacto.
    """
    modelo = None
    etiqueta = 'registro'
    articulo = 'Ese'               # concordancia del mensaje: Ese / Esa

    def esta_en_uso(self, item):
        """
        Uso que la base de datos no protege sola. Las básculas y los sitios de
        inicio son llaves foráneas con PROTECT (lo detecta ProtectedError); el
        residuo se guarda como texto, así que hay que preguntarlo aquí.
        """
        return False

    def post(self, request, pk):
        from django.db.models import ProtectedError
        item = get_object_or_404(self.modelo, pk=pk)
        oculto = {
            'ok': True, 'eliminada': False,
            'mensaje': f'{self.articulo} {self.etiqueta} ya se usó en '
                       f'programaciones: se ocultó del listado.',
        }
        if self.esta_en_uso(item):
            item.activo = False
            item.save(update_fields=['activo'])
            return JsonResponse(oculto)
        try:
            item.delete()
            return JsonResponse({'ok': True, 'eliminada': True})
        except ProtectedError:
            item.activo = False
            item.save(update_fields=['activo'])
            return JsonResponse(oculto)


class CrearBasculaView(CrearItemCatalogoView):
    modelo = Bascula
    etiqueta = 'de la báscula'
    con_direccion = True


class EliminarBasculaView(EliminarItemCatalogoView):
    modelo = Bascula
    etiqueta = 'báscula'
    articulo = 'Esa'


class CrearSitioInicioView(CrearItemCatalogoView):
    modelo = SitioInicio
    etiqueta = 'del sitio de inicio'


class EliminarSitioInicioView(EliminarItemCatalogoView):
    modelo = SitioInicio
    etiqueta = 'sitio de inicio'


class CrearTipoResiduoView(CrearItemCatalogoView):
    modelo = TipoResiduo
    etiqueta = 'del residuo'


class EliminarTipoResiduoView(EliminarItemCatalogoView):
    modelo = TipoResiduo
    etiqueta = 'residuo'

    def esta_en_uso(self, item):
        # `Programacion.transporte_tipo` guarda el NOMBRE como texto, no una FK.
        return Programacion.objects.filter(transporte_tipo__iexact=item.nombre).exists()


# Cuántas veces se reintenta si el número de orden choca con otro guardado
# simultáneo. El número sale de "el último + 1" sin bloqueo de base, así que
# la colisión es posible; al reintentar se recalcula sobre el ya ocupado.
_INTENTOS_NUMERO_ORDEN = 3


def _olvidar_guardado(*instancias):
    """
    Deja las instancias como recién creadas después de una transacción
    revertida: Django les dejó la clave primaria puesta y en el reintento
    haría un UPDATE de una fila que ya no existe.
    """
    for instancia in instancias:
        instancia.pk = None
        instancia._state.adding = True


class ConvertirProgramacionView(AsesorRequiredMixin, View):
    """Genera la Orden de Servicio + un recorrido por cuadrilla (solo POST)."""
    def post(self, request, pk):
        programacion = get_object_or_404(Programacion, pk=pk)

        if programacion.orden_id:
            messages.info(request, "Esta programación ya tiene una orden generada.")
            return redirect('gestion:detalle_orden', pk=programacion.orden_id)
        if programacion.estado == 'CANCELADA':
            messages.error(request, "No puedes generar una orden desde una programación cancelada.")
            return redirect('gestion:lista_programaciones')

        orden = None
        for intento in range(_INTENTOS_NUMERO_ORDEN):
            try:
                orden = programacion.convertir_en_orden(request.user)
                break
            except IntegrityError:
                # Choque de número con otro guardado simultáneo: se reintenta.
                if intento == _INTENTOS_NUMERO_ORDEN - 1:
                    messages.error(
                        request,
                        "No se pudo generar la orden porque otro usuario estaba "
                        "generando una al mismo tiempo. No se creó nada: "
                        "vuelve a intentarlo."
                    )
                    return redirect('gestion:lista_programaciones')
            except ValueError as e:
                messages.error(request, str(e))
                return redirect('gestion:actualizar_programacion', pk=pk)

        messages.success(
            request,
            f"Orden #{orden.numero_orden} generada desde la programación "
            f"({orden.recorridos.count()} recorrido(s)). Completa el valor y los documentos que falten."
        )

        # La documentación al cliente se envía desde el Centro de correos; aquí
        # solo se notifica al personal (conductor y ayudantes).
        _avisar_correos_programacion(request, programacion)
        _avisar_carga_pendiente(request, programacion, orden)

        return redirect('gestion:detalle_orden', pk=orden.pk)


class CancelarProgramacionView(AsesorRequiredMixin, View):
    """Marca la programación como CANCELADA (solo POST). No aplica si ya generó orden."""
    def post(self, request, pk):
        programacion = get_object_or_404(Programacion, pk=pk)
        if programacion.orden_id:
            messages.error(request, "No puedes cancelar una programación que ya generó una orden.")
        else:
            programacion.estado = 'CANCELADA'
            programacion.save()
            messages.success(request, "Programación cancelada.")
        return redirect('gestion:lista_programaciones')


# ============================================================
#  MÓDULO PERSONAL (personas de la plataforma)
#  Panel dedicado a las personas: cuenta (accesos), datos personales y
#  expediente documental, todo en una sola ficha. Gestionado por Asesores
#  y superusuarios.
# ============================================================

def _protege_superusuario(request, persona):
    """
    Impide que quien NO es superusuario modifique la cuenta de un superusuario
    (editarla, cambiarle la contraseña o retirarla). Sin esto, el rol
    Administradores podría apropiarse de una cuenta con acceso al admin de
    Django, que es justo lo que no debe poder hacer. Devuelve una redirección
    si hay que frenar, o None si puede seguir.
    """
    if persona.is_superuser and not request.user.is_superuser:
        messages.error(
            request,
            "Solo un superadministrador puede modificar la cuenta de otro superadministrador."
        )
        return redirect('gestion:ficha_persona', pk=persona.pk)
    return None


def _perfil_de(persona):
    """Devuelve (creándolo si no existe) el perfil de datos de la persona."""
    perfil, _ = PerfilPersona.objects.get_or_create(usuario=persona)
    return perfil


class ListaPersonalView(AsesorRequiredMixin, PaginadoMixin, ListView):
    model = User
    template_name = 'gestion/lista_personal.html'
    context_object_name = 'usuarios'

    def get_queryset(self):
        # Los superadministradores no son personal operativo: se gestionan en
        # Sistema > Usuarios, no aquí.
        qs = (
            User.objects.exclude(is_superuser=True)
            .select_related('perfil')
            .prefetch_related('groups', 'documentos_personales')
        )
        q = self.request.GET.get('q', '').strip()
        rol = self.request.GET.get('rol', '')
        estado = self.request.GET.get('estado', '')

        if q:
            qs = qs.filter(
                Q(first_name__icontains=q) | Q(last_name__icontains=q)
                | Q(username__icontains=q) | Q(perfil__numero_documento__icontains=q)
            )
        if rol:
            qs = qs.filter(groups__name=rol)
        if estado == 'retirado':
            qs = qs.filter(perfil__retirado=True)
        elif estado == 'activo':
            qs = qs.exclude(perfil__retirado=True)

        # Los retirados van al final (trazabilidad); dentro, por nombre.
        return qs.order_by('perfil__retirado', 'first_name', 'username').distinct()

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        # Estado documental (faltantes) para conductores/ayudantes.
        docs = _estado_documentos_personal()
        for usuario in context['usuarios']:
            info = docs.get(usuario.id)
            usuario.doc_faltan = info['faltan'] if info else None
            usuario.tiene_requisitos = info is not None
            usuario.sin_acceso = _persona_sin_acceso(usuario)
            perfil = getattr(usuario, 'perfil', None)
            usuario.esta_retirado = bool(perfil and perfil.retirado)

        # Datos para la barra de filtros.
        context['roles'] = Group.objects.order_by('name')
        context['q'] = self.request.GET.get('q', '')
        context['rol_sel'] = self.request.GET.get('rol', '')
        context['estado_sel'] = self.request.GET.get('estado', '')
        return context


class CrearPersonaView(AsesorRequiredMixin, View):
    """
    Da de alta a una persona. El ROL se elige primero porque determina todo lo
    demás: los roles con acceso (conductores, asesores...) llevan usuario y
    contraseña; los ayudantes NO acceden al sistema, así que solo se registran
    sus datos y su expediente documental.
    """
    template_name = 'gestion/form_persona.html'

    def get(self, request):
        return render(request, self.template_name, {
            'form': CrearUsuarioForm(),
            'perfil_form': PerfilPersonaForm(),
            'crear': True,
            'grupos_sin_acceso_ids': json.dumps(_ids_grupos_sin_acceso()),
        })

    def post(self, request):
        grupo = _grupo_de_post(request)
        sin_acceso = _grupo_es_sin_acceso(grupo)
        # Los ayudantes no llevan usuario ni contraseña: se usa el formulario
        # reducido, que crea la cuenta inactiva y sin contraseña utilizable.
        FormClass = PersonaSinAccesoForm if sin_acceso else CrearUsuarioForm

        form = FormClass(request.POST)
        perfil_form = PerfilPersonaForm(request.POST)
        if form.is_valid() and perfil_form.is_valid():
            usuario = form.save()
            usuario.groups.add(form.cleaned_data['grupo'])
            perfil = perfil_form.save(commit=False)
            perfil.usuario = usuario
            perfil.save()
            if sin_acceso:
                messages.success(
                    request,
                    "Ayudante registrado. No tiene acceso al sistema: solo se gestiona su expediente."
                )
            else:
                messages.success(request, "Persona creada correctamente.")
            return redirect('gestion:ficha_persona', pk=usuario.pk)
        return render(request, self.template_name, {
            'form': form, 'perfil_form': perfil_form, 'crear': True,
            'sin_acceso': sin_acceso,
            'grupos_sin_acceso_ids': json.dumps(_ids_grupos_sin_acceso()),
        })


class FichaPersonaView(AsesorRequiredMixin, View):
    """Ficha completa de la persona: accesos, datos personales y expediente."""
    template_name = 'gestion/ficha_persona.html'

    def _context(self, persona):
        mes_actual = timezone.localdate().strftime('%Y-%m')
        docs = list(persona.documentos_personales.all())
        por_tipo = {}
        for d in docs:
            por_tipo.setdefault(d.tipo, []).append(d)

        grupos = set(persona.groups.values_list('name', flat=True))
        requeridos = _documentos_requeridos_por_rol(grupos)

        # Seguridad social vigente (por fecha de vencimiento, no por mes).
        ss_vigente = _ss_vigente(docs)
        ss_todos = por_tipo.get('SEGURIDAD_SOCIAL', [])
        # La más reciente cargada (para avisar cuál está vencida si no hay vigente).
        ss_ultima = max(
            ss_todos,
            key=lambda d: d.fecha_vencimiento or datetime.date.min,
            default=None,
        )

        # Una casilla por cada documento que aplica al rol, con su estado.
        # Los cursos solo aparecen en ayudantes; la licencia, solo en conductores.
        slots = []
        for tipo, label in _documentos_aplicables_por_rol(grupos):
            if tipo == 'SEGURIDAD_SOCIAL':
                # Cargada = existe una con vigencia sin vencer (manual, no por mes).
                doc = ss_vigente
            else:
                lista = por_tipo.get(tipo, [])
                doc = lista[0] if lista else None   # el más reciente (orden -fecha_subida)
            slots.append({
                'tipo': tipo, 'label': label, 'doc': doc,
                'cargado': doc is not None,
                'requerido': tipo in requeridos,
                'es_ss': tipo == 'SEGURIDAD_SOCIAL',
                'es_licencia': tipo == 'LICENCIA',
                'es_curso': tipo in ('CURSO_ALTURAS', 'CURSO_CONFINADOS'),
                'con_vigencia': tipo in TIPOS_CON_VIGENCIA,
            })

        otros = por_tipo.get('OTRO', [])
        faltan_requeridos = [s['label'] for s in slots if s['requerido'] and not s['cargado']]

        perfil = _perfil_de(persona)
        return {
            'persona': persona,
            'perfil': perfil,
            'retirado': perfil.retirado,
            'fecha_retiro': perfil.fecha_retiro,
            'mes_actual': mes_actual,
            # Tiene requisitos documentales (conductores, ayudantes y asesores).
            'es_personal': bool(requeridos),
            # Todos los que la llevan deben mantener su seguridad social vigente.
            'exige_ss': 'SEGURIDAD_SOCIAL' in requeridos,
            'sin_acceso': _persona_sin_acceso(persona),
            'dias_alerta': DocumentoPersonal.DIAS_ALERTA_VENCIMIENTO,
            'ss_al_dia': ss_vigente is not None,
            'slots': slots,
            # Hay seguridad social cargada pero ninguna vigente (todas vencidas).
            'ss_vencida': ss_vigente is None and ss_ultima is not None,
            'ss_ultima': ss_ultima,
            'ss_total': len(ss_todos),
            'otros': otros,
            'faltan_requeridos': faltan_requeridos,
        }

    def get(self, request, pk):
        persona = get_object_or_404(User, pk=pk)
        return render(request, self.template_name, self._context(persona))

    def post(self, request, pk):
        # Carga de un documento al expediente (cada casilla envía su 'tipo').
        persona = get_object_or_404(User, pk=pk)
        form = DocumentoPersonalForm(request.POST, request.FILES)
        if form.is_valid():
            documento = form.save(commit=False)
            documento.usuario = persona
            documento.save()
            messages.success(request, "Documento cargado.")
        else:
            messages.error(request, "No se pudo cargar el documento (revisa el archivo).")
        return redirect('gestion:ficha_persona', pk=pk)


class EditarCuentaPersonaView(AsesorRequiredMixin, View):
    """Edita la cuenta (usuario, nombre, correo, rol, estado) y el perfil de datos."""
    template_name = 'gestion/form_persona.html'

    def get(self, request, pk):
        persona = get_object_or_404(User, pk=pk)
        frenar = _protege_superusuario(request, persona)
        if frenar is not None:
            return frenar
        sin_acceso = _persona_sin_acceso(persona)
        FormClass = PersonaSinAccesoForm if sin_acceso else ActualizarUsuarioForm
        return render(request, self.template_name, {
            'form': FormClass(instance=persona),
            'perfil_form': PerfilPersonaForm(instance=_perfil_de(persona)),
            'persona': persona,
            'crear': False,
            'sin_acceso': sin_acceso,
            'grupos_sin_acceso_ids': json.dumps(_ids_grupos_sin_acceso()),
        })

    def post(self, request, pk):
        persona = get_object_or_404(User, pk=pk)
        frenar = _protege_superusuario(request, persona)
        if frenar is not None:
            return frenar
        grupo = _grupo_de_post(request)
        sin_acceso = _grupo_es_sin_acceso(grupo)
        FormClass = PersonaSinAccesoForm if sin_acceso else ActualizarUsuarioForm

        datos = request.POST.copy()
        # Al pasar de un rol sin acceso a uno con acceso, el formulario mostrado
        # no traía usuario ni estado: se reutiliza el identificador existente y
        # se activa la cuenta (la contraseña se define aparte).
        daba_acceso_nuevo = not sin_acceso and _persona_sin_acceso(persona)
        if daba_acceso_nuevo:
            datos.setdefault('username', persona.username)
            datos['is_active'] = 'on'

        form = FormClass(datos, instance=persona)
        perfil_form = PerfilPersonaForm(request.POST, instance=_perfil_de(persona))
        if form.is_valid() and perfil_form.is_valid():
            usuario = form.save()
            usuario.groups.clear()
            usuario.groups.add(form.cleaned_data['grupo'])
            perfil_form.save()
            messages.success(request, "Datos de la persona actualizados.")
            if daba_acceso_nuevo:
                messages.info(
                    request,
                    f"Esta persona ahora tiene acceso al sistema con el usuario "
                    f"«{usuario.username}». Asígnale una contraseña para que pueda entrar."
                )
            return redirect('gestion:ficha_persona', pk=usuario.pk)
        return render(request, self.template_name, {
            'form': form, 'perfil_form': perfil_form, 'persona': persona, 'crear': False,
            'sin_acceso': sin_acceso,
            'grupos_sin_acceso_ids': json.dumps(_ids_grupos_sin_acceso()),
        })


class CambiarPasswordPersonaView(AsesorRequiredMixin, View):
    """Cambia la contraseña de acceso de una persona (no aplica a los ayudantes)."""
    template_name = 'gestion/cambiar_password.html'

    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated:
            persona = get_object_or_404(User, pk=kwargs.get('pk'))
            frenar = _protege_superusuario(request, persona)
            if frenar is not None:
                return frenar
            if _persona_sin_acceso(persona):
                messages.info(
                    request,
                    "Los ayudantes no acceden al sistema, así que no tienen contraseña. "
                    "Cambia su rol si necesitas darle acceso."
                )
                return redirect('gestion:ficha_persona', pk=persona.pk)
        return super().dispatch(request, *args, **kwargs)

    def get(self, request, pk):
        persona = get_object_or_404(User, pk=pk)
        return render(request, self.template_name, {'form': self._form(persona), 'persona': persona})

    def post(self, request, pk):
        persona = get_object_or_404(User, pk=pk)
        form = self._form(persona, request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, "Contraseña actualizada.")
            return redirect('gestion:ficha_persona', pk=persona.pk)
        return render(request, self.template_name, {'form': form, 'persona': persona})

    def _form(self, persona, data=None):
        form = SetPasswordForm(persona, data)
        for field in form.fields.values():
            field.widget.attrs['class'] = 'form-control'
        return form


class HistorialSeguridadSocialView(AsesorRequiredMixin, View):
    """
    Historial completo de la seguridad social de una persona. Cada carga lleva su
    vigencia (fecha de vencimiento) puesta a mano: está vigente mientras no venza,
    y las vencidas quedan aquí como soporte histórico.
    """
    template_name = 'gestion/historial_seguridad_social.html'
    REGISTROS_POR_PAGINA = 12

    def _context(self, persona, pagina=None):
        documentos = list(
            persona.documentos_personales.filter(tipo='SEGURIDAD_SOCIAL')
            .order_by('-fecha_vencimiento', '-fecha_subida')
        )
        # El resumen (al día / total) se calcula sobre TODO el historial; la
        # tabla muestra solo la página pedida.
        page_obj = Paginator(documentos, self.REGISTROS_POR_PAGINA).get_page(pagina)
        registros = [{
            'doc': documento,
            'vigente': documento.vigente,
        } for documento in page_obj.object_list]

        return {
            'persona': persona,
            'perfil': _perfil_de(persona),
            'registros': registros,
            'al_dia': any(d.vigente for d in documentos),
            'total': len(documentos),
            'dias_alerta': DocumentoPersonal.DIAS_ALERTA_VENCIMIENTO,
            'page_obj': page_obj,
            'pagina_rango': rango_de_paginas(page_obj),
        }

    def get(self, request, pk):
        persona = get_object_or_404(User, pk=pk)
        return render(request, self.template_name,
                      self._context(persona, request.GET.get('page')))

    def post(self, request, pk):
        """Carga una seguridad social (con su vigencia) desde el historial."""
        persona = get_object_or_404(User, pk=pk)
        datos = request.POST.copy()
        datos['tipo'] = 'SEGURIDAD_SOCIAL'
        form = DocumentoPersonalForm(datos, request.FILES)
        if form.is_valid():
            documento = form.save(commit=False)
            documento.usuario = persona
            documento.save()
            messages.success(
                request,
                f"Seguridad social cargada (vigente hasta "
                f"{documento.fecha_vencimiento.strftime('%d/%m/%Y')})."
            )
        else:
            messages.error(request, "No se pudo cargar: revisa el archivo y la vigencia.")
        return redirect('gestion:historial_seguridad_social', pk=pk)


class ActualizarVigenciaDocumentoView(AsesorRequiredMixin, View):
    """
    Fija o edita la vigencia (fecha de vencimiento) de un documento del
    expediente desde el pop-up de la ficha. Solo POST.
    """
    def post(self, request, pk):
        documento = get_object_or_404(DocumentoPersonal, pk=pk)
        fecha = request.POST.get('fecha_vencimiento', '').strip()

        if not fecha:
            # Vaciar el campo = el documento queda sin vigencia registrada.
            documento.fecha_vencimiento = None
            documento.save(update_fields=['fecha_vencimiento'])
            messages.success(request, "Vigencia eliminada del documento.")
            return redirect('gestion:ficha_persona', pk=documento.usuario_id)

        try:
            documento.fecha_vencimiento = datetime.datetime.strptime(fecha, '%Y-%m-%d').date()
        except ValueError:
            messages.error(request, "La fecha de vigencia no es válida.")
            return redirect('gestion:ficha_persona', pk=documento.usuario_id)

        documento.save(update_fields=['fecha_vencimiento'])
        messages.success(
            request,
            f"Vigencia registrada: vence el {documento.fecha_vencimiento.strftime('%d/%m/%Y')}."
        )
        return redirect('gestion:ficha_persona', pk=documento.usuario_id)


class CambiarEstadoPersonaView(AsesorRequiredMixin, View):
    """
    Retira o reactiva a una persona (solo POST). Al retirar, deja de aparecer en
    las asignaciones (programación, recorridos, planificación) y se le bloquea el
    acceso; su ficha y expediente se conservan para trazabilidad. Al reactivar, se
    restaura el acceso salvo que sea un rol sin acceso (ayudante).
    """
    def post(self, request, pk):
        persona = get_object_or_404(User, pk=pk)
        frenar = _protege_superusuario(request, persona)
        if frenar is not None:
            return frenar
        perfil = _perfil_de(persona)
        if perfil.retirado:
            perfil.retirado = False
            perfil.fecha_retiro = None
            perfil.save(update_fields=['retirado', 'fecha_retiro'])
            if not _persona_sin_acceso(persona):
                persona.is_active = True
                persona.save(update_fields=['is_active'])
            messages.success(request, "Persona reactivada. Vuelve a estar disponible para asignaciones.")
        else:
            perfil.retirado = True
            perfil.fecha_retiro = timezone.localdate()
            perfil.save(update_fields=['retirado', 'fecha_retiro'])
            persona.is_active = False
            persona.save(update_fields=['is_active'])
            messages.success(
                request,
                "Persona marcada como retirada. Ya no aparece en las asignaciones; "
                "su expediente se conserva para trazabilidad."
            )
        return redirect('gestion:ficha_persona', pk=pk)


class EliminarDocumentoPersonalView(AsesorRequiredMixin, View):
    """Elimina un documento del expediente (solo POST)."""
    def post(self, request, pk):
        documento = get_object_or_404(DocumentoPersonal, pk=pk)
        usuario_pk = documento.usuario_id
        # Al borrar desde el historial de seguridad social se vuelve allí.
        volver_a_historial = request.POST.get('origen') == 'seguridad_social'
        documento.delete()
        messages.success(request, "Documento eliminado del expediente.")
        if volver_a_historial:
            return redirect('gestion:historial_seguridad_social', pk=usuario_pk)
        return redirect('gestion:ficha_persona', pk=usuario_pk)

# ============================================================
#  DOCUMENTACIÓN INTERNA DE SOLMED
#  Panel con los documentos de la propia empresa (RUT, cámara, certificaciones,
#  etc.), a la mano para las áreas. Gestionado por asesores y superusuarios.
# ============================================================
class DocumentacionSolmedView(AsesorRequiredMixin, View):
    template_name = 'gestion/documentacion.html'

    def _context(self):
        from .models import DocumentoInterno
        docs = list(DocumentoInterno.objects.all())
        por_tipo = {}
        for d in docs:
            por_tipo.setdefault(d.tipo, []).append(d)
        # Una tarjeta por tipo fijo, en el orden de las opciones del modelo. La
        # documentación ADICIONAL (nombre libre) va en su propia sección arriba.
        secciones = []
        for tipo, label in DocumentoInterno.TIPO_CHOICES:
            if tipo == DocumentoInterno.TIPO_ADICIONAL:
                continue
            secciones.append({
                'tipo': tipo,
                'label': label,
                'docs': por_tipo.get(tipo, []),
                'con_fecha': tipo in DocumentoInterno.TIPOS_CON_FECHA,
                'es_bancaria': tipo == DocumentoInterno.TIPO_MULTIPLE,
                'multiple': tipo == DocumentoInterno.TIPO_MULTIPLE,
            })
        adicionales = sorted(por_tipo.get(DocumentoInterno.TIPO_ADICIONAL, []),
                             key=lambda d: d.descripcion.lower())
        return {
            'secciones': secciones,
            'adicionales': adicionales,
            'entidades_bancarias': DocumentoInterno.ENTIDADES_BANCARIAS,
        }

    def get(self, request):
        return render(request, self.template_name, self._context())

    def post(self, request):
        from .forms import DocumentoInternoForm
        from .models import DocumentoInterno
        form = DocumentoInternoForm(request.POST, request.FILES)
        if not form.is_valid():
            errores = "; ".join(
                f"{form.fields.get(c).label or c}: {e[0]}" for c, e in form.errors.items()
            )
            messages.error(request, f"No se pudo cargar el documento. {errores}")
            return redirect('gestion:documentacion')

        # De cada documento hay UNO vigente: el nuevo REEMPLAZA al anterior.
        # La certificación bancaria reemplaza por cuenta/banco y la
        # documentación adicional por su nombre; el resto, por el tipo.
        nuevo = form.save(commit=False)
        if nuevo.tipo == DocumentoInterno.TIPO_MULTIPLE:
            anteriores = DocumentoInterno.objects.filter(
                tipo=nuevo.tipo, entidad__iexact=(nuevo.entidad or '').strip())
        elif nuevo.tipo == DocumentoInterno.TIPO_ADICIONAL:
            anteriores = DocumentoInterno.objects.filter(
                tipo=nuevo.tipo, descripcion__iexact=(nuevo.descripcion or '').strip())
        else:
            anteriores = DocumentoInterno.objects.filter(tipo=nuevo.tipo)
        reemplazados = anteriores.count()
        anteriores.delete()
        nuevo.save()
        messages.success(
            request,
            "Documento cargado: reemplazó al que estaba." if reemplazados
            else "Documento cargado."
        )
        return redirect('gestion:documentacion')


class EliminarDocumentoInternoView(AsesorRequiredMixin, View):
    """Elimina un documento interno de SOLMED (solo POST)."""
    def post(self, request, pk):
        from .models import DocumentoInterno
        documento = get_object_or_404(DocumentoInterno, pk=pk)
        documento.delete()
        messages.success(request, "Documento eliminado.")
        return redirect('gestion:documentacion')


# ============================================================
#  PROVEEDORES DE DISPOSICIÓN FINAL (Dispositor, tipo PROVEEDOR)
#  Panel propio para darlos de alta y llevar el expediente documental de
#  cada uno (RUT, cámara, cédula del representante, certificación bancaria
#  y documentos ambientales). Los destinos INTERNOS (trasiegos, dejar
#  cargado) se siembran por migración y siguen siendo cosa del admin.
#  Gestionado por asesores y superusuarios.
# ============================================================
from .models import Dispositor, DocumentoDispositor
from .forms import DispositorForm, DocumentoDispositorForm


class ListaDispositoresView(AsesorRequiredMixin, PaginadoMixin, ListView):
    model = Dispositor
    template_name = 'gestion/lista_dispositores.html'
    context_object_name = 'dispositores'

    def get_queryset(self):
        # Solo los proveedores externos; los inactivos van al final.
        return (
            Dispositor.objects.filter(tipo='PROVEEDOR')
            .prefetch_related('documentos')
            .order_by('-activo', 'nombre')
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        # Documentos únicos que le faltan a cada proveedor (para el aviso del listado).
        tipos = [t for t, _ in DocumentoDispositor.TIPO_CHOICES]
        etiquetas = dict(DocumentoDispositor.TIPO_CHOICES)
        for d in context['dispositores']:
            cargados = {doc.tipo for doc in d.documentos.all()}
            d.docs_faltan = [etiquetas[t] for t in tipos if t not in cargados]
            d.docs_cargados = len(cargados)
            d.docs_total = len(tipos)
        return context


class CrearDispositorView(AsesorRequiredMixin, CreateView):
    model = Dispositor
    form_class = DispositorForm
    template_name = 'gestion/form_dispositor.html'

    def form_valid(self, form):
        # El panel solo crea proveedores externos.
        form.instance.tipo = 'PROVEEDOR'
        self.object = form.save()
        messages.success(
            self.request,
            "Proveedor creado. Ahora puedes cargar los documentos de su expediente."
        )
        return HttpResponseRedirect(reverse('gestion:ficha_dispositor', kwargs={'pk': self.object.pk}))


class ActualizarDispositorView(AsesorRequiredMixin, UpdateView):
    model = Dispositor
    form_class = DispositorForm
    template_name = 'gestion/form_dispositor.html'
    queryset = Dispositor.objects.filter(tipo='PROVEEDOR')

    def form_valid(self, form):
        self.object = form.save()
        messages.success(self.request, "Proveedor actualizado.")
        return HttpResponseRedirect(reverse('gestion:ficha_dispositor', kwargs={'pk': self.object.pk}))


class FichaDispositorView(AsesorRequiredMixin, View):
    """
    Expediente documental del proveedor: una tarjeta por tipo de documento
    (RUT, cámara, cédula del representante, certificación bancaria) y los
    documentos ambientales, que admiten varios.
    """
    template_name = 'gestion/ficha_dispositor.html'

    def _context(self, dispositor):
        docs = list(dispositor.documentos.all())
        por_tipo = {}
        for d in docs:
            por_tipo.setdefault(d.tipo, []).append(d)
        secciones = []
        for tipo, label in DocumentoDispositor.TIPO_CHOICES:
            multiple = tipo in DocumentoDispositor.TIPOS_MULTIPLES
            secciones.append({
                'tipo': tipo,
                'label': label,
                # Título de la tarjeta: en plural cuando admite varios.
                'titulo': 'Documentos ambientales' if tipo == 'DOC_AMBIENTAL' else label,
                'docs': por_tipo.get(tipo, []),
                'multiple': multiple,
            })
        faltan = [s['label'] for s in secciones if not s['docs']]
        return {
            'dispositor': dispositor,
            'secciones': secciones,
            'faltan': faltan,
        }

    def get(self, request, pk):
        dispositor = get_object_or_404(Dispositor, pk=pk, tipo='PROVEEDOR')
        return render(request, self.template_name, self._context(dispositor))

    def post(self, request, pk):
        # Carga de un documento al expediente (cada tarjeta envía su 'tipo').
        dispositor = get_object_or_404(Dispositor, pk=pk, tipo='PROVEEDOR')
        form = DocumentoDispositorForm(request.POST, request.FILES)
        if form.is_valid():
            documento = form.save(commit=False)
            documento.dispositor = dispositor
            documento.save()
            messages.success(request, "Documento cargado al expediente.")
        else:
            messages.error(request, "No se pudo cargar el documento (revisa el archivo).")
        return redirect('gestion:ficha_dispositor', pk=pk)


class EliminarDocumentoDispositorView(AsesorRequiredMixin, View):
    """Elimina un documento del expediente del proveedor (solo POST)."""
    def post(self, request, pk):
        documento = get_object_or_404(DocumentoDispositor, pk=pk)
        dispositor_pk = documento.dispositor_id
        documento.delete()
        messages.success(request, "Documento eliminado del expediente.")
        return redirect('gestion:ficha_dispositor', pk=dispositor_pk)
