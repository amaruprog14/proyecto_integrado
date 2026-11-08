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

# Ítems de las tablas de indicadores, sin totales, ponderadores ni filas vacías.
# La variante «SOLUCIONES AL INGRESO AL TUBO» se unifica con «SOLUCIONES DE INGRESOS AL TUBO».
POSITION_ITEMS = {
    "Apoyo administrativo": ("Atención de usuario teléfono y presencial", "Llamadas preventivas a usuarios", "Informe de inventarios", "Informe a comunicaciones", "Emergencia"),
    "Coordinador de servicios comunitarios": ("Informes personal", "Informe trabajo", "Operativo delegación", "Operativo Diserco", "Talleres", "Terreno", "Atención requerimiento usuario", "Emergencia", "Soluciones de ingresos al tubo"),
    "Organizaciones comunitarias": ("Atención de usuario teléfono y presencial", "Visitas y reuniones con organizaciones", "Conformación de organizaciones", "Gestión de talleres y actividades", "Emergencia", "Soluciones de ingresos al tubo"),
    "Gestor social": ("Atención social a usuario presencial", "Visita terreno", "Entrega informe", "Entrega beneficio", "Emergencia", "Soluciones de ingresos al tubo"),
    "Gestión y planificación": ("Reunión semanal con el equipo", "Solución de problemas a usuarios particulares", "Emergencia", "Soluciones de ingresos al tubo"),
}
# No se inventan indicadores de compras o de delegado: sus actividades se asignan
# a los ítems de coordinación/gestión que efectivamente describe el caso.
POSITION_ITEMS["Delegado"] = POSITION_ITEMS["Gestión y planificación"]
POSITION_ITEMS["Gestor de compras y proyectos"] = ("Reunión semanal con el equipo", "Informe trabajo")

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
