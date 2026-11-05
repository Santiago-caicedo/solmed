"""
TABLERO DE GERENCIA (nov-2026, pedido de Santiago; reemplaza el módulo
«Reportes», que sumaba un `valor_servicio` que nadie llena).

Junta en una sola pantalla, por periodo y comparado con el periodo anterior:
facturación (preliquidado, con factura electrónica, enviado), ventas por mes,
facturación por vehículo, clientes que más facturan, asesoras comerciales,
el proceso de facturación, servicios, movimiento del personal (horas,
servicios por persona, ingresos y retiros), lo que dicen los números en
palabras y los clientes mes a mes.

V2 (4-nov-2026, Santiago): se quitaron las correlaciones estadísticas («a
alguien de gerencia no le interesa ciencia de datos») y el diseño aparte; el
tablero vive dentro del sistema, con la sidebar. En su lugar van lecturas en
lenguaje de negocio y la matriz cliente × mes.

Decisiones de Santiago (nov-2026):
- La cifra de facturación es lo PRELIQUIDADO (todas las preliquidaciones,
  por su fecha de emisión), y al lado cuánto de eso ya tiene factura
  electrónica y cuánto ya se envió.
- Solo administradores y superadministradores, sin casilla en «Gestionar
  accesos».
- Diseño propio, corporativo; el resto del sistema no cambia.

Reglas de cálculo (para que las cifras cuadren con Facturación):
- El valor de una orden en una preliquidación es su `subtotal` (global +
  conceptos). Los PDF aparte son facturas propias y cuentan por su fecha.
- Por VEHÍCULO, el valor de una orden se reparte en partes iguales entre las
  placas de sus recorridos (una orden con dos camiones da mitad a cada uno).
- Por PERSONA y por ASESORA el valor NO se reparte: es «la facturación de
  los servicios en que participó» / «de su cartera», y no se suma entre ellas.
- Servicios = recorridos COMPLETADOS en el periodo (sin órdenes canceladas).
- Horas = la misma fuente del centro de control (_datos_centro_control).
"""
import calendar
import datetime
import json
import math
from collections import defaultdict
from decimal import Decimal

from django.contrib.auth.models import User
from django.db.models import Count, Min, Q
from django.shortcuts import render
from django.utils import timezone
from django.views import View

from .models import Factura, PerfilPersona, Recorrido
from .views import AdministradorRequiredMixin, MESES_CORTOS

MESES = ['enero', 'febrero', 'marzo', 'abril', 'mayo', 'junio', 'julio',
         'agosto', 'septiembre', 'octubre', 'noviembre', 'diciembre']

# Los cargos del personal operativo (los que tienen servicios y horas).
CARGOS_OPERATIVOS = ('Conductores', 'Ayudantes', 'Conductor - Ayudante')

PERIODOS = [
    ('mes', 'Este mes'),
    ('trimestre', 'Este trimestre'),
    ('anio', 'Este año'),
    ('12m', 'Últimos 12 meses'),
    ('personalizado', 'Personalizado'),
]


# ============================================================
#  El periodo
# ============================================================

def _sumar_meses(fecha, n):
    mes = fecha.month - 1 + n
    anio = fecha.year + mes // 12
    mes = mes % 12 + 1
    return datetime.date(anio, mes, min(fecha.day, calendar.monthrange(anio, mes)[1]))


def periodo_de(request):
    """
    (clave, desde, hasta) del periodo pedido. Por defecto, el año en curso.
    `hasta` nunca pasa de hoy: lo que no ha pasado no se mide.
    """
    from django.utils.dateparse import parse_date
    hoy = timezone.localdate()
    clave = request.GET.get('periodo') or 'anio'
    if clave not in dict(PERIODOS):
        clave = 'anio'
    if clave == 'mes':
        desde = hoy.replace(day=1)
    elif clave == 'trimestre':
        desde = datetime.date(hoy.year, (hoy.month - 1) // 3 * 3 + 1, 1)
    elif clave == '12m':
        desde = _sumar_meses(hoy.replace(day=1), -11)
    elif clave == 'personalizado':
        try:
            desde = parse_date(request.GET.get('desde') or '')
            hasta = parse_date(request.GET.get('hasta') or '')
        except ValueError:
            desde = hasta = None
        if desde and hasta and desde <= hasta:
            return clave, desde, min(hasta, hoy) if desde <= hoy else hasta
        clave = 'anio'
        desde = datetime.date(hoy.year, 1, 1)
    else:
        desde = datetime.date(hoy.year, 1, 1)
    return clave, desde, hoy


def periodo_anterior(desde, hasta, clave=None):
    """
    El periodo con el que se compara: el año corrido se compara con el mismo
    tramo del año anterior (enero a la misma fecha); el mes, el trimestre y
    los últimos 12 meses, con el tramo igual inmediatamente antes; un rango
    personalizado, con el de la misma duración justo antes.
    """
    if clave == 'anio':
        return datetime.date(desde.year - 1, 1, 1), _sumar_meses(hasta, -12)
    if clave in ('mes', 'trimestre', '12m'):
        meses = {'mes': 1, 'trimestre': 3, '12m': 12}[clave]
        return _sumar_meses(desde, -meses), _sumar_meses(hasta, -meses)
    dias = (hasta - desde).days + 1
    fin = desde - datetime.timedelta(days=1)
    return fin - datetime.timedelta(days=dias - 1), fin


def nombre_periodo(desde, hasta):
    """El periodo dicho como se habla: «noviembre de 2026», «enero a noviembre de 2026»."""
    if desde.day == 1 and desde.year == hasta.year and desde.month == hasta.month:
        return f"{MESES[desde.month - 1]} de {desde.year}"
    if desde.day == 1 and desde.year == hasta.year:
        return f"{MESES[desde.month - 1]} a {MESES[hasta.month - 1]} de {desde.year}"
    if desde.day == 1:
        return f"{MESES[desde.month - 1]} de {desde.year} a {MESES[hasta.month - 1]} de {hasta.year}"
    return f"del {desde:%d/%m/%Y} al {hasta:%d/%m/%Y}"


def frase_periodo(clave, desde, hasta):
    """El arranque de la frase principal del tablero."""
    return {
        'mes': f"En {MESES[hasta.month - 1]} de {hasta.year}",
        'trimestre': "En este trimestre",
        'anio': f"En lo corrido de {hasta.year}",
        '12m': "En los últimos doce meses",
    }.get(clave, f"Del {desde:%d/%m/%Y} al {hasta:%d/%m/%Y}")


# ============================================================
#  Cálculos
# ============================================================

def _facturas(desde, hasta):
    return list(
        Factura.objects.filter(fecha_emision__range=(desde, hasta))
        .select_related('cliente')
        .prefetch_related('lineas__conceptos', 'lineas__orden__recorridos__vehiculo',
                          'lineas__orden__recorridos__conductor',
                          'lineas__orden__recorridos__ayudante',
                          'lineas__orden__recorridos__ayudante2',
                          'cliente__asesoras'))


def _total(factura):
    return sum((l.subtotal for l in factura.lineas.all()), Decimal('0'))


def _resumen_facturacion(facturas):
    pre = fev = enviado = Decimal('0')
    for f in facturas:
        t = _total(f)
        pre += t
        if f.fe_realizada_en:
            fev += t
        if f.estado == 'ENVIADA':
            enviado += t
    return {'preliquidado': pre, 'fev': fev, 'enviado': enviado}


def _servicios(desde, hasta):
    return (Recorrido.objects.filter(estado='COMPLETADO', fecha_recorrido__range=(desde, hasta))
            .exclude(orden__estado_orden='CANCELADA'))


def _delta(actual, anterior):
    """Variación porcentual (None si no hay base para comparar)."""
    actual, anterior = float(actual or 0), float(anterior or 0)
    if anterior == 0:
        return None
    return round((actual - anterior) / anterior * 100, 1)


def _por_mes(desde_trend, hasta):
    """Los 12 meses que terminan en el mes de `hasta`: preliquidado (con y sin FEV) y servicios."""
    meses = []
    cursor = desde_trend
    while cursor <= hasta:
        meses.append((cursor.year, cursor.month))
        cursor = _sumar_meses(cursor, 1)
    datos = {m: {'fev': Decimal('0'), 'sin_fev': Decimal('0'), 'servicios': 0} for m in meses}
    for f in _facturas(desde_trend, hasta):
        clave = (f.fecha_emision.year, f.fecha_emision.month)
        if clave in datos:
            datos[clave]['fev' if f.fe_realizada_en else 'sin_fev'] += _total(f)
    for fila in (_servicios(desde_trend, hasta)
                 .values_list('fecha_recorrido__year', 'fecha_recorrido__month')):
        if fila in datos:
            datos[fila]['servicios'] += 1
    return [{'etiqueta': f"{MESES_CORTOS[m - 1]} {str(a)[2:]}", 'mes': f"{MESES[m - 1].capitalize()} {a}",
             'anio': a, 'num': m,
             'fev': float(d['fev']), 'sin_fev': float(d['sin_fev']),
             'total': float(d['fev'] + d['sin_fev']), 'servicios': d['servicios']}
            for (a, m), d in datos.items()]


def _por_vehiculo(facturas, servicios):
    """Facturación (repartida entre las placas de cada orden) y servicios por vehículo."""
    valor = defaultdict(Decimal)
    for f in facturas:
        for l in f.lineas.all():
            placas = sorted({r.vehiculo.placa for r in l.orden.recorridos.all() if r.vehiculo_id})
            if not placas:
                valor['Sin vehículo'] += l.subtotal
                continue
            parte = l.subtotal / len(placas)
            for p in placas:
                valor[p] += parte
    conteo = dict(servicios.exclude(vehiculo=None).values_list('vehiculo__placa').annotate(n=Count('pk')))
    placas = set(valor) | set(conteo)
    filas = []
    for p in placas:
        v, n = float(valor.get(p, 0)), conteo.get(p, 0)
        filas.append({'nombre': p, 'valor': v, 'servicios': n, 'ticket': v / n if n else None})
    filas.sort(key=lambda x: (-x['valor'], -x['servicios'], x['nombre']))
    return filas


def _por_cliente(facturas, servicios, total):
    valor = defaultdict(Decimal)
    nombres = {}
    for f in facturas:
        valor[f.cliente_id] += _total(f)
        nombres[f.cliente_id] = f.cliente.nombre
    conteo = dict(servicios.values_list('orden__cliente_id').annotate(n=Count('pk')))
    filas = [{'id': c, 'nombre': nombres[c], 'valor': float(v), 'servicios': conteo.get(c, 0),
              'participacion': float(v / total * 100) if total else 0}
             for c, v in valor.items()]
    filas.sort(key=lambda x: (-x['valor'], x['nombre']))
    acumulado = 0
    for x in filas:
        acumulado += x['participacion']
        x['acumulado'] = acumulado
    return filas


def _clientes_mes(desde_trend, hasta, ids):
    """
    La matriz de los clientes `ids` (en ese orden) por cada uno de los 12
    meses que terminan en `hasta`: cuánto preliquidó cada uno cada mes.
    """
    meses = []
    cursor = desde_trend
    while cursor <= hasta:
        meses.append((cursor.year, cursor.month))
        cursor = _sumar_meses(cursor, 1)
    valor = defaultdict(Decimal)
    for f in _facturas(desde_trend, hasta):
        if f.cliente_id in ids:
            valor[(f.cliente_id, f.fecha_emision.year, f.fecha_emision.month)] += _total(f)
    return {
        'meses': [{'etiqueta': MESES_CORTOS[m - 1], 'mes': f"{MESES[m - 1].capitalize()} {a}"} for a, m in meses],
        'filas': [{'id': c, 'valores': [float(valor[(c, a, m)]) for a, m in meses]} for c in ids],
    }


def _lecturas(k, meses, clientes, clientes_ant, vehiculos):
    """
    Lo que dicen los números, en frases de negocio (no estadística). Cada una
    con su tono: 'bien' (buena noticia), 'ojo' (algo para atender) o ''.
    """
    lecturas = []
    con_ventas = [m for m in meses if m['total']]
    if con_ventas:
        mejor = max(con_ventas, key=lambda m: m['total'])
        lecturas.append({'tono': '', 'texto': f"{mejor['mes']} fue el mes de mayor facturación de los últimos doce: "
                                              f"{_pesos(mejor['total'])}."})
    if k['preliquidado_delta'] is not None:
        sube = k['preliquidado_delta'] >= 0
        lecturas.append({'tono': 'bien' if sube else 'ojo',
                         'texto': f"Lo preliquidado {'subió' if sube else 'bajó'} "
                                  f"{_porcentaje(abs(k['preliquidado_delta']))} frente al periodo anterior."})
    if clientes:
        primero = clientes[0]
        lecturas.append({'tono': 'ojo' if primero['participacion'] >= 50 else '',
                         'texto': f"{primero['nombre']} aporta el {_porcentaje(primero['participacion'])} de lo facturado"
                                  + (f"; los cinco primeros clientes suman el {_porcentaje(k['top5'])}." if len(clientes) > 5
                                     else ".")})
    antes = {c['id']: c['valor'] for c in clientes_ant}
    crecen = [(c['valor'] - antes[c['id']], c) for c in clientes if antes.get(c['id'])]
    crecen = [x for x in crecen if x[0] > 0]
    if crecen:
        diferencia, c = max(crecen, key=lambda x: x[0])
        lecturas.append({'tono': 'bien', 'texto': f"El cliente que más creció es {c['nombre']}: "
                                                  f"{_pesos(diferencia)} más que en el periodo anterior."})
    nuevos = [c for c in clientes if c['id'] not in antes]
    if nuevos and antes:
        lecturas.append({'tono': 'bien', 'texto': f"{len(nuevos)} cliente{'s' if len(nuevos) != 1 else ''} "
                                                  f"facturó en este periodo y no en el anterior."})
    con_placa = [v for v in vehiculos if v['nombre'] != 'Sin vehículo' and v['valor']]
    if con_placa:
        v = con_placa[0]
        lecturas.append({'tono': '', 'texto': f"{v['nombre']} es el vehículo que más factura: {_pesos(v['valor'])} "
                                              f"en {v['servicios']} servicio{'s' if v['servicios'] != 1 else ''}."})
    pendiente_fev = k['preliquidado'] - k['fev']
    if pendiente_fev > 0:
        lecturas.append({'tono': 'ojo', 'texto': f"{_pesos(pendiente_fev)} preliquidado aún no tiene factura electrónica."})
    if k['por_preliquidar']:
        n = k['por_preliquidar']
        lecturas.append({'tono': 'ojo', 'texto': (f"{n} órdenes esperan" if n != 1 else "1 orden espera")
                                                 + " preliquidación"
                                                 + (f"; la más antigua lleva {k['por_preliquidar_dias']} días."
                                                    if k['por_preliquidar_dias'] is not None else ".")})
    return lecturas


def _pesos(valor):
    return '$' + f"{round(valor):,}".replace(',', '.')


def _porcentaje(valor):
    return f"{valor:.0f}%" if abs(valor - round(valor)) < 0.05 else f"{valor:.1f}%".replace('.', ',')


def _por_asesora(facturas):
    """La facturación de la cartera de cada asesora (un cliente con dos asesoras cuenta para las dos)."""
    valor = defaultdict(Decimal)
    clientes = defaultdict(set)
    nombres = {}
    for f in facturas:
        asesoras = list(f.cliente.asesoras.all())
        if not asesoras:
            valor[None] += _total(f)
            clientes[None].add(f.cliente_id)
            continue
        for a in asesoras:
            valor[a.pk] += _total(f)
            clientes[a.pk].add(f.cliente_id)
            nombres[a.pk] = a.get_full_name() or a.username
    filas = [{'nombre': nombres.get(k, 'Sin asesora asignada'), 'valor': float(v),
              'clientes': len(clientes[k]), 'sin_asignar': k is None}
             for k, v in valor.items()]
    filas.sort(key=lambda x: (x['sin_asignar'], -x['valor']))
    return filas


def _proceso():
    """En qué etapa del proceso de facturación está la plata HOY (no depende del periodo)."""
    facturas = Factura.objects.prefetch_related('lineas__conceptos')
    por_estado = defaultdict(lambda: {'n': 0, 'valor': Decimal('0')})
    for f in facturas:
        por_estado[f.estado]['n'] += 1
        por_estado[f.estado]['valor'] += _total(f)
    return [{'clave': clave, 'nombre': nombre, 'quien': quien,
             'n': por_estado[clave]['n'], 'valor': float(por_estado[clave]['valor'])}
            for clave, nombre, quien, _que in Factura.ETAPAS]


def _personal(desde, hasta, facturas, servicios):
    """Horas, servicios y facturación de los servicios por persona; ingresos y retiros."""
    from planes.views import _cargo_de as _cargo_de_persona
    from .views import _datos_centro_control, _texto_horas
    hoy = timezone.localdate()
    corte = min(hasta, hoy)
    personas = list(User.objects.filter(groups__name__in=CARGOS_OPERATIVOS, is_superuser=False)
                    .filter(Q(perfil__retirado=False) | Q(perfil__fecha_retiro__gte=desde))
                    .select_related('perfil').prefetch_related('groups').distinct())
    # Servicios por persona (conduciendo o de ayudante).
    n_servicios = defaultdict(int)
    for c, a1, a2 in servicios.values_list('conductor_id', 'ayudante_id', 'ayudante2_id'):
        for pk in {c, a1, a2} - {None}:
            n_servicios[pk] += 1
    # La facturación de los servicios en que participó (no se reparte).
    valor = defaultdict(Decimal)
    for f in facturas:
        for l in f.lineas.all():
            gente = set()
            for r in l.orden.recorridos.all():
                gente |= {r.conductor_id, r.ayudante_id, r.ayudante2_id}
            for pk in gente - {None}:
                valor[pk] += l.subtotal
    filas = []
    for p in personas:
        minutos = 0
        if corte >= desde:
            minutos = sum(_datos_centro_control(p, desde, corte)['horas']['por_dia'].values())
        n = n_servicios.get(p.pk, 0)
        if not (minutos or n or valor.get(p.pk)):
            continue
        filas.append({
            'nombre': p.get_full_name() or p.username,
            'cargo': _cargo_de_persona(p),
            'horas': round(minutos / 60, 1), 'horas_txt': _texto_horas(minutos),
            'servicios': n, 'valor': float(valor.get(p.pk, 0)),
            'horas_por_servicio': round(minutos / 60 / n, 1) if n else None,
            'retirado': bool(getattr(p, 'perfil', None) and p.perfil.retirado),
        })
    filas.sort(key=lambda x: (-x['horas'], -x['servicios'], x['nombre'].lower()))

    perfiles = PerfilPersona.objects.select_related('usuario')
    activos = (User.objects.filter(is_superuser=False).exclude(perfil__retirado=True)
               .exclude(groups__isnull=True).distinct())
    por_cargo = defaultdict(int)
    for u in activos.prefetch_related('groups'):
        por_cargo[_cargo_de_persona(u)] += 1
    ingresos = list(perfiles.filter(fecha_ingreso__range=(desde, hasta)).order_by('fecha_ingreso'))
    retiros = list(perfiles.filter(retirado=True, fecha_retiro__range=(desde, hasta)).order_by('fecha_retiro'))
    def gente(lista, campo):
        return [{'nombre': x.usuario.get_full_name() or x.usuario.username,
                 'cargo': _cargo_de_persona(x.usuario), 'fecha': getattr(x, campo)} for x in lista]
    return {
        'filas': filas,
        'activos': sum(por_cargo.values()),
        'por_cargo': sorted(por_cargo.items(), key=lambda kv: -kv[1]),
        'ingresos': gente(ingresos, 'fecha_ingreso'),
        'retiros': gente(retiros, 'fecha_retiro'),
        'horas_total': round(sum(x['horas'] for x in filas)),
    }


def tablero_gerencia(desde, hasta, clave=None):
    """Todos los datos del tablero para el periodo, con la comparación contra el anterior."""
    facturas = _facturas(desde, hasta)
    servicios = _servicios(desde, hasta)
    resumen = _resumen_facturacion(facturas)
    a_desde, a_hasta = periodo_anterior(desde, hasta, clave)
    facturas_ant = _facturas(a_desde, a_hasta)
    anterior = _resumen_facturacion(facturas_ant)
    n_servicios = servicios.count()
    n_servicios_ant = _servicios(a_desde, a_hasta).count()
    clientes = _por_cliente(facturas, servicios, resumen['preliquidado'])
    vehiculos = _por_vehiculo(facturas, servicios)
    personal = _personal(desde, hasta, facturas, servicios)
    # Ticket: lo preliquidado por cada servicio realizado del periodo.
    ticket = float(resumen['preliquidado']) / n_servicios if n_servicios else None
    ticket_ant = float(anterior['preliquidado']) / n_servicios_ant if n_servicios_ant else None
    from .views import _ordenes_por_preliquidar
    pendientes = _ordenes_por_preliquidar().aggregate(n=Count('pk', distinct=True), mas_vieja=Min('servicio'))
    hoy = timezone.localdate()

    top5 = sum(c['participacion'] for c in clientes[:5])
    trend_desde = _sumar_meses(hasta.replace(day=1), -11)
    meses = _por_mes(trend_desde, hasta)
    # Los meses que caen dentro del periodo elegido se resaltan en el gráfico.
    for m in meses:
        m['en_periodo'] = (desde.year, desde.month) <= (m['anio'], m['num']) <= (hasta.year, hasta.month)
    matriz = _clientes_mes(trend_desde, hasta, [c['id'] for c in clientes[:8]])
    nombres = {c['id']: c['nombre'] for c in clientes}
    for f in matriz['filas']:
        f['nombre'] = nombres[f['id']]
        f['total'] = sum(f['valores'])
    kpis = {
        'preliquidado': float(resumen['preliquidado']),
        'preliquidado_delta': _delta(resumen['preliquidado'], anterior['preliquidado']),
        'fev': float(resumen['fev']),
        'fev_pct': (float(resumen['fev'] / resumen['preliquidado'] * 100)
                    if resumen['preliquidado'] else None),
        'fev_delta': _delta(resumen['fev'], anterior['fev']),
        'enviado': float(resumen['enviado']),
        'enviado_pct': (float(resumen['enviado'] / resumen['preliquidado'] * 100)
                       if resumen['preliquidado'] else None),
        'servicios': n_servicios,
        'servicios_delta': _delta(n_servicios, n_servicios_ant),
        'ticket': ticket,
        'ticket_delta': _delta(ticket, ticket_ant) if ticket and ticket_ant else None,
        'clientes': len(clientes),
        'por_preliquidar': pendientes['n'] or 0,
        'por_preliquidar_dias': (hoy - pendientes['mas_vieja']).days if pendientes['mas_vieja'] else None,
        'top5': top5,
    }
    clientes_ant = _por_cliente(facturas_ant, _servicios(a_desde, a_hasta), anterior['preliquidado'])
    return {
        'kpis': kpis,
        'anterior': {'desde': a_desde, 'hasta': a_hasta},
        'meses': meses,
        'clientes_mes': matriz,
        'lecturas': _lecturas(kpis, meses, clientes, clientes_ant, vehiculos),
        'vehiculos': vehiculos,
        'clientes': clientes,
        'asesoras': _por_asesora(facturas),
        'proceso': _proceso(),
        'personal': personal,
    }


# ============================================================
#  La vista
# ============================================================

class GerenciaView(AdministradorRequiredMixin, View):
    """
    El tablero de gerencia. Sin `acceso`: SOLO administradores y
    superadministradores (decisión de Santiago, nov-2026: no se abre por casilla).
    """
    template_name = 'gestion/gerencia.html'

    def get(self, request):
        clave, desde, hasta = periodo_de(request)
        datos = tablero_gerencia(desde, hasta, clave)
        graficos = {
            'meses': datos['meses'],
            'vehiculos': datos['vehiculos'][:15],
            'clientes': datos['clientes'][:10],
            'asesoras': datos['asesoras'],
            'proceso': datos['proceso'],
            'personal': datos['personal']['filas'][:15],
            'clientes_mes': datos['clientes_mes'],
        }
        return render(request, self.template_name, {
            'd': datos,
            'graficos': graficos,
            'periodos': PERIODOS,
            'periodo': clave,
            'desde': desde, 'hasta': hasta,
            'nombre_periodo': nombre_periodo(desde, hasta),
            'frase_periodo': frase_periodo(clave, desde, hasta),
            'nombre_anterior': nombre_periodo(datos['anterior']['desde'], datos['anterior']['hasta']),
            'generado': timezone.localtime(),
        })
