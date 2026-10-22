"""
Las listas de chequeo del PREOPERACIONAL, por tipo de vehículo (oct-2026).

Las mandó la SISO por correo, ya depuradas: no piden datos del vehículo ni
del conductor (el sistema los tiene) y dejan por fuera las dos últimas
preguntas de cada lista («¿Vehículo APTO?» y «Observaciones o fotos»), que
son el dictamen final y el cierre del formato, iguales para todos.

Cada ítem se responde B (bueno / apto), M (malo / deficiente) o N/A. Si la
SISO cambia una lista, se cambia AQUÍ: los preoperacionales ya guardados
conservan el texto que el conductor vio (se copia a cada ítem al guardar).
"""

ESTADO_ITEM_CHOICES = [
    ('B', 'Bueno'),
    ('M', 'Malo'),
    ('NA', 'No aplica'),
]

DICTAMEN_CHOICES = [
    ('APTO', 'Apto para operar'),
    ('NO_APTO', 'No apto para operar'),
]

# Los tipos de vehículo de la flota. El orden es el del correo de la SISO.
TIPOS_VEHICULO = [
    ('VACIO_DOBLE', 'Vehículo de vacío doble troque'),
    ('VACIO_SENCILLO', 'Vehículo de vacío sencillo'),
    ('HINO', 'Camión Hino'),
    ('VOLQUETA', 'Volqueta'),
    ('VACTOR', 'Vactor · equipo combinado'),
    ('CAMIONETA', 'Camioneta'),
]

# tipo -> [(sección, [ítems])]. Los números del correo se conservan.
LISTAS = {
    'VACIO_DOBLE': [
        ('Mecanismos de acceso y prevención de caídas', [
            'Estribos de acceso a cabina (limpios, fijos y con superficie antideslizante).',
            'Escalerilla lateral/trasera de acceso a tanque (peldaños firmes y antideslizantes).',
            'Pasamanos, agarraderas y plataforma superior (fijación, limpios de grasa y antideslizantes).',
        ]),
        ('Mecánica, frenos y rodamiento', [
            'Niveles de fluidos (aceite de motor, refrigerante, líquido hidráulico y de frenos).',
            'Estado de llantas delanteras y de doble tracción (presión, pernos ajustados, labrado > 2.5 mm).',
            'Sistema de frenos de aire (presión en manómetros, sin fugas y purga de tanques realizada).',
            'Suspensión y chasis (hojas de resorte sin fisuras ni platinas rotas).',
        ]),
        ('Módulo operativo de vacío (toma de fuerza, compresor y bomba)', [
            'Toma de fuerza (PTO): engranaje/acople suave, sin ruidos extraños, fugas de aceite ni vibración excesiva.',
            'Compresor Bético: nivel de aceite, lubricación, correas/cardán y funcionamiento sin ruidos anómalos.',
            'Bomba de vacío y vacuómetro/manómetro de presión (carátula visible y funcional).',
            'Válvulas de alivio, sobrepresión y de retención (libres de obstrucciones).',
            'Hermeticidad del tanque, compuerta trasera, empaques y gatos hidráulicos.',
            'Estado de las mangueras de succión/descarga, los acoples rápidos y las abrazaderas.',
        ]),
        ('Luces, equipos de emergencia y cierre', [
            'Luces operativas (altas/bajas, direccionales, freno, reversa y luz intermitente/baliza).',
            'Espejos retrovisores, parabrisas y pito o alarma de reversa.',
            'Extintor vigente, botiquín, kit de carretera y kit para control de derrames.',
        ]),
    ],
    'VACIO_SENCILLO': [
        ('Mecanismos de acceso y prevención de caídas', [
            'Estribos de acceso a cabina y pasarelas (limpios, firmes y antideslizantes).',
            'Escalerilla y pasamanos de inspección del tanque.',
        ]),
        ('Mecánica, frenos y rodamiento', [
            'Niveles de fluidos (aceite de motor, refrigerante, hidráulico).',
            'Estado de las llantas (direccionales y tracción trasera: labrado, presión y pernos).',
            'Sistema de frenos y purga del tanque de aire.',
        ]),
        ('Módulo operativo de vacío (toma de fuerza, compresor y tanque)', [
            'Toma de fuerza (PTO): activación/desacople adecuado y ausencia de fugas o ruidos.',
            'Compresor Bético / bomba de vacío: nivel de aceite, estado de acoples y vacuómetro.',
            'Hermeticidad del tanque, la compuerta y los empaques de sellado.',
            'Mangueras de succión, acoples rápidos y válvulas de descarga.',
        ]),
        ('Luces, emergencia y cierre', [
            'Luces (direccionales, freno, reversa, baliza) y alarma de reversa.',
            'Espejos, parabrisas y limpiaparabrisas.',
            'Extintor vigente, botiquín, kit de carretera y kit de derrames.',
        ]),
    ],
    'HINO': [
        ('Mecanismos de acceso y estribos', [
            'Estribos y pasamanos de ascenso/descenso a la cabina (antideslizantes y bien anclados).',
            'Estado de la estructura de la carrocería, furgón o platón.',
        ]),
        ('Mecánica, frenos y rodamiento', [
            'Niveles de fluidos (aceite, refrigerante, frenos, dirección).',
            'Estado de las llantas (delanteras, traseras y repuesto: labrado y presión).',
            'Pedal de freno, embrague y freno de parqueo.',
            'Batería (bornes limpios y soporte ajustado).',
        ]),
        ('Luces, emergencia y cierre', [
            'Luces completas (altas, bajas, direccionales, freno y reversa) y claxon.',
            'Espejos retrovisores y panorámico (limpios y sin fisuras).',
            'Extintor vigente, botiquín y kit de carretera completo.',
        ]),
    ],
    'VOLQUETA': [
        ('Mecanismos de acceso y prevención de caídas', [
            'Estribos de cabina (superficie antideslizante sin desgaste).',
            'Escalerilla de ascenso al volco y pasamanos superiores (peldaños limpios y sin deformación).',
        ]),
        ('Sistema hidráulico del volco', [
            'Cilindro/gato hidráulico de levante y toma de fuerza (ausencia de fugas de aceite hidráulico).',
            'Pasadores de seguridad, carpa/cubierta de material y traba de compuerta trasera.',
        ]),
        ('Mecánica, frenos y rodamiento', [
            'Niveles de fluidos (aceite de motor, refrigerante, hidráulico).',
            'Llantas (direccionales y las del doble troque: labrado, pernos y presión).',
            'Frenos de aire, purga de tanques y freno de ahogo.',
        ]),
        ('Luces, emergencia y cierre', [
            'Luces generales, baliza de señalización y alarma sonora de reversa.',
            'Espejos retrovisores, parabrisas y pito.',
            'Extintor vigente, botiquín, kit de carretera y tacos.',
        ]),
    ],
    'VACTOR': [
        ('Mecanismos de acceso y prevención de caídas', [
            'Escalerilla metálica de acceso a la parte superior (peldaños antideslizantes).',
            'Pasamanos, pasarelas y plataformas de maniobra (antideslizantes y limpios de grasa).',
        ]),
        ('Sistema de vacío, compresor / bomba y alta presión', [
            'Toma de fuerza (PTO) y transferencia: acople y funcionamiento sin fugas ni vibraciones.',
            'Bomba de vacío / compresor y bomba de agua de alta presión (niveles de aceite y presión).',
            'Carrete, manguera de alta presión y boquillas de lavado.',
            'Manguerote de succión, pluma articulada y bloqueos de seguridad.',
            'Manómetros, válvulas de alivio, purga y tanques de agua limpia/lodos.',
        ]),
        ('Mecánica, luces y emergencia', [
            'Niveles de fluidos del motor del vehículo y motor auxiliar (si aplica).',
            'Estado de llantas, frenos de aire y purga de tanques.',
            'Faros de trabajo nocturno, licuadora/baliza y pito de reversa.',
            'Extintor, botiquín, kit de carretera y kit de derrames.',
        ]),
    ],
    'CAMIONETA': [
        ('Mecanismos de acceso y prevención de caídas', [
            'Estribos laterales (fijación y goma/superficie antideslizante).',
            'Manijas de puertas internas y externas.',
        ]),
        ('Mecánica y seguridad pasiva', [
            'Niveles de fluidos (aceite de motor, refrigerante, frenos, limpiaparabrisas).',
            'Cinturones de seguridad en todas las plazas (retractores y hebillas).',
            'Estado de las llantas (incluyendo repuesto, labrado y pernos).',
        ]),
        ('Luces, visibilidad y emergencia', [
            'Luces (altas, bajas, direccionales, freno, reversa) y pito.',
            'Espejos retrovisores, panorámico y plumillas limpiaparabrisas.',
            'Extintor vigente, botiquín, kit de carretera, gato y cruceta.',
        ]),
    ],
}


def items_de(tipo):
    """
    Los ítems de un tipo, numerados de corrido como en el correo:
    [{'numero', 'seccion', 'texto'}]. Lista vacía si el tipo no tiene lista.
    """
    items, numero = [], 0
    for seccion, textos in LISTAS.get(tipo, []):
        for texto in textos:
            numero += 1
            items.append({'numero': numero, 'seccion': seccion, 'texto': texto})
    return items


def nombre_tipo(tipo):
    return dict(TIPOS_VEHICULO).get(tipo, '')
