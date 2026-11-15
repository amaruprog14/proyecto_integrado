"""Catálogos transcritos del caso SGR (sin datos personales del Excel).

Procedencia: matriz SGR trimestral, descriptor de funciones y guía del proyecto.
Distribución y ejecución segura: README.md. No se lee Excel al cargar.
Los cargos son funciones laborales; los roles Django controlan el acceso.
"""

GEOGRAPHY = {
    "Las Compañías": ("Latorre", "Rukalaf", "Toqui", "Zorrilla"),
    "Antena": ("Alfalfares", "Antena", "Ceres", "La Florida"),
}

# Cargo: (área funcional derivada del descriptor, resumen de funciones).
POSITIONS = {
    "Delegado": ("Delegación municipal", "Representar a la alcaldía, administrar la delegación y coordinar servicios municipales y organizaciones vecinales."),
    "Gestor social": ("Gestión social", "Evaluar, diagnosticar, intervenir y derivar casos sociales; realizar visitas y coordinar recursos y programas."),
    "Apoyo administrativo": ("Apoyo administrativo", "Gestionar agenda, atención y derivación ciudadana, seguimiento telefónico, inventarios e informes administrativos."),
    "Organizaciones comunitarias": ("Organizaciones comunitarias", "Asesorar la constitución y funcionamiento de organizaciones, convocar talleres y coordinar necesidades territoriales."),
    "Gestor de compras y proyectos": ("Compras y proyectos", "Planificar y controlar compras, preparar requerimientos y especificaciones y colaborar en la evaluación de proveedores."),
    "Gestión y planificación": ("Gestión y planificación", "Coordinar el equipo, elaborar diagnósticos, mantener la matriz SGR y preparar informes y reuniones periódicas."),
    "Coordinador de servicios comunitarios": ("Servicios comunitarios", "Coordinar operaciones de aseo, ornato y medioambiente, cuadrillas y requerimientos técnicos de la comunidad."),
}

PERCENTAGE_ITEM = "Soluciones de ingresos al tubo"

# Ítems de las tablas de indicadores del Excel trimestral: (ítem, ponderador %, meta del trimestre).
# Sin totales, filas vacías ni datos personales. La variante «SOLUCIONES AL INGRESO AL TUBO» se
# unifica con «SOLUCIONES DE INGRESOS AL TUBO», cuya meta es porcentual (80 % de compromisos
# realizados). «Emergencia» tiene meta variable en el Excel; aquí se usa meta 1 (README, supuestos).
# En «Organizaciones comunitarias», la fila «Atención de usuario» reutiliza el ítem de atención
# telefónica y presencial, que es la misma actividad descrita en el descriptor de funciones.
POSITION_PLANS = {
    "Gestor social": (
        ("Atención social a usuario presencial", "25", 90), ("Visita terreno", "20", 12),
        ("Entrega informe", "20", 40), ("Entrega beneficio", "20", 8), ("Emergencia", "5", 1),
        (PERCENTAGE_ITEM, "10", 80),
    ),
    "Apoyo administrativo": (
        ("Atención de usuario teléfono y presencial", "20", 240), ("Llamadas preventivas a usuarios", "30", 90),
        ("Informe de inventarios", "25", 1), ("Informe a comunicaciones", "20", 12), ("Emergencia", "5", 1),
    ),
    "Organizaciones comunitarias": (
        ("Atención de usuario teléfono y presencial", "15", 60), ("Visitas y reuniones con organizaciones", "15", 24),
        ("Conformación de organizaciones", "25", 1), ("Gestión de talleres y actividades", "15", 6),
        ("Emergencia", "5", 1), (PERCENTAGE_ITEM, "25", 80),
    ),
    "Coordinador de servicios comunitarios": (
        ("Informes personal", "10", 3), ("Informe trabajo", "10", 12), ("Operativo delegación", "15", 24),
        ("Operativo Diserco", "10", 12), ("Talleres", "10", 12), ("Terreno", "10", 24),
        ("Atención requerimiento usuario", "15", 24), ("Emergencia", "5", 1), (PERCENTAGE_ITEM, "15", 80),
    ),
    # El Excel suma 85 % (falta una fila): se normaliza proporcionalmente a 100 %.
    "Gestión y planificación": (
        ("Reunión semanal con el equipo", "17.65", 12), ("Solución de problemas a usuarios particulares", "35.29", 8),
        ("Emergencia", "5.88", 1), (PERCENTAGE_ITEM, "41.18", 80),
    ),
}
# No se inventan indicadores de compras o de delegado: el delegado usa la tabla de gestión y
# planificación; para compras el Excel no trae hoja y se asume reunión semanal e informe de trabajo.
POSITION_PLANS["Delegado"] = POSITION_PLANS["Gestión y planificación"]
POSITION_PLANS["Gestor de compras y proyectos"] = (("Reunión semanal con el equipo", "50", 12), ("Informe trabajo", "50", 12))

POSITION_ITEMS = {name: tuple(item for item, _, _ in lines) for name, lines in POSITION_PLANS.items()}

# LISTA!B2:C8: las siete parejas válidas. No importar #N/A de DATO MENU.
ATTENTION_CATALOG = {
    "Informes sociales": ("Informe aporte económico", "Informe aporte material", "Informe institución"),
    "Gestión de subsidios": ("IPS", "PGU", "SUF", "SAP"),
}

FIRST_NAMES = ("Camila", "Diego", "Valentina", "Matías", "Catalina", "Tomás", "Daniela", "Javier", "Antonia", "Felipe")
LAST_NAMES = ("Rojas", "Muñoz", "Soto", "Pérez", "González", "Contreras", "Silva", "Torres", "Fuentes", "Vargas")


def fictional_name(index):
    # Sin números: satisface las mismas restricciones que el formulario.
    from common.demo_data import batch_letters
    return f"{FIRST_NAMES[index % 10]} {LAST_NAMES[(index // 10) % 10]} Simulado {batch_letters(index // 100)}"
