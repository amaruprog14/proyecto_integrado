"""Datos ficticios compartidos por las semillas y su documento de referencia."""

# Ningún perfil, salvo el superusuario, elimina registros: se archivan o desactivan.
# Los permisos de los funcionarios vienen solo de sus roles SGR, de modo que desactivar un rol
# retira efectivamente lo que otorgaba.
OPERATOR_PERMISSIONS = [
    "activities.view_activity", "activities.add_activity", "activities.change_activity",
    "activities.view_socialattention", "activities.add_socialattention",
    "accounts.view_official", "configuration.view_item",
]
CONSULTA_PERMISSIONS = [
    "activities.view_activity", "accounts.view_official", "configuration.view_item",
]

# Versiones anteriores del seed daban permisos por estos grupos. Se quita a los usuarios de
# demostración de ellos (los grupos no se eliminan, por si se usan para otra cosa).
LEGACY_GROUPS = ("Funcionarios", "Consulta")

# (código, nombre, dirección, comuna, estado). Direcciones ficticias.
DELEGATIONS = [
    ("D01", "Centro", "Calle Demo 101", "La Serena", "ACTIVE"),
    ("D02", "Norte", "Calle Demo 202", "La Serena", "ACTIVE"),
    ("D03", "Sur", "Calle Demo 303", "La Serena", "ACTIVE"),
    ("D04", "Rural", "Camino Demo km 4", "La Serena", "INACTIVE"),
]

# Rol: (alcance, descripción, permisos). Los permisos del Administrador se calculan aparte.
ROLES = {
    "Administrador": (
        "ALL",
        "Configura delegaciones, usuarios, roles, catálogos y períodos.",
        None,
    ),
    "Coordinador": (
        "ALL",
        "Supervisa la operación transversal y administra ítems y períodos.",
        [
            "activities.view_activity", "activities.view_socialattention",
            "activities.view_evidence", "activities.view_evidencevalidation",
            "accounts.view_official", "accounts.view_delegation",
            "configuration.view_item", "configuration.add_item", "configuration.change_item",
            "configuration.view_period", "configuration.add_period", "configuration.change_period",
            "configuration.view_attentiontype", "configuration.view_subattentiontype",
        ],
    ),
    "Supervisor": (
        "DELEGATION",
        "Consulta la gestión de sus delegaciones autorizadas.",
        [
            "activities.view_activity", "activities.view_socialattention",
            "activities.view_evidence", "activities.view_evidencevalidation",
            "accounts.view_official", "accounts.view_delegation",
            "configuration.view_item", "configuration.view_period",
        ],
    ),
    "Operador": (
        "DELEGATION",
        "Registra actividades y atenciones de su delegación.",
        OPERATOR_PERMISSIONS,
    ),
    "Verificador": (
        "DELEGATION",
        "Revisa evidencias y registra su validación.",
        [
            "activities.view_activity", "activities.view_socialattention",
            "activities.view_evidence", "activities.view_evidencevalidation",
            "activities.add_evidencevalidation", "activities.change_evidencevalidation",
            "accounts.view_official", "configuration.view_item",
        ],
    ),
    "Consulta": (
        "DELEGATION",
        "Solo lectura sobre la información de su delegación.",
        CONSULTA_PERMISSIONS,
    ),
}

# Nombres sin dígitos: el formulario de funcionarios no los acepta en el nombre completo.
DEMO_OFFICIAL_NAMES = ["Uno", "Dos", "Tres", "Cuatro", "Cinco"]

# Contexto de Funcionario Demo Uno a Cinco: (delegación principal, roles, delegaciones autorizadas).
# Coordinador y Supervisor no registran atenciones por sí solos; funcionario3 y funcionario4 suman
# el rol Operador para conservar esa capacidad (ninguno es Administrador global, así que pueden
# combinarse).
OFFICIAL_CONTEXT = [
    ("Centro", ["Operador"], []),
    ("Norte", ["Operador", "Verificador"], []),
    ("Sur", ["Coordinador", "Operador"], []),
    ("Sur", ["Supervisor", "Operador"], ["Sur", "Norte"]),  # dos delegaciones autorizadas: prueba del selector
    ("Centro", ["Operador"], []),  # archivado y sin usuario: funcionario5 sigue sin contexto
]


DEMO_PASSWORD = "demo1234"
AREA_NAMES = ["Área Norte", "Área Sur", "Área Centro", "Área Cordillera", "Área Costa"]
POSITION_NAMES = ["Analista", "Coordinador", "Administrativo", "Supervisor", "Encargado de Terreno"]
ITEM_NAMES = ["Atención ciudadana", "Terreno", "Reunión de coordinación", "Levantamiento de datos", "Seguimiento de caso"]
# (actividad, servicio, atención, subatención), una cadena por cada área.
CATALOG_CHAINS = [
    ("Orientación social", "Apoyo social", "Asistencia social", "Evaluación social"),
    ("Gestión territorial", "Apoyo territorial", "Orientación territorial", "Visita domiciliaria"),
    ("Participación ciudadana", "Apoyo comunitario", "Orientación comunitaria", "Reunión vecinal"),
    ("Desarrollo rural", "Apoyo rural", "Orientación rural", "Evaluación rural"),
    ("Desarrollo local", "Apoyo local", "Orientación local", "Seguimiento local"),
]
DEMO_GROUPS = ["Demostración municipal", "Demostración consulta"]


def demo_rut(number):
    total = sum(int(d) * (i % 6 + 2) for i, d in enumerate(reversed(str(number))))
    digit = 11 - total % 11
    return f"{number}-{'0' if digit == 11 else 'K' if digit == 10 else digit}"


def demo_accounts(batch=0):
    records = [dict(username="admin_demo", email="admin@demo.cl", full_name="Administrador Demo",
                    national_id=demo_rut(10000098), delegation="Centro", roles=["Administrador"],
                    area=AREA_NAMES[2], position=POSITION_NAMES[3], phone="+56 9 6000 0098")]
    for i, word in enumerate(DEMO_OFFICIAL_NAMES):
        delegation, roles, authorized = OFFICIAL_CONTEXT[i]
        records.append(dict(username=f"funcionario{i+1}", email=f"funcionario{i+1}@demo.cl",
                            full_name=f"Funcionario Demo {word}", national_id=demo_rut(10000000+i),
                            delegation=delegation, roles=roles, authorized=authorized,
                            area=AREA_NAMES[[0, 0, 1, 1, 2][i]], position=POSITION_NAMES[i],
                            phone=f"+56 9 6000 000{i+1}"))
    records.append(dict(username="consulta_norte", email="consulta_norte@demo.cl", full_name="Consulta Demo Norte",
                        national_id=demo_rut(10000099), delegation="Norte", roles=["Consulta"],
                        area=AREA_NAMES[0], position=POSITION_NAMES[0], phone="+56 9 6000 0099"))
    if batch:
        for record in records:
            record["username"] += f"_lote_{batch_letters(batch).lower()}"
            local, domain = record["email"].split("@")
            record["email"] = f"{local}.lote.{batch_letters(batch).lower()}@{domain}"
            record["national_id"] = demo_rut(int(record["national_id"].split("-")[0]) + batch * 100)
            record["full_name"] = batch_name(record["full_name"], batch)
    return records


def batch_letters(batch):
    """A, B, ..., Z, AA; los nombres de catálogo no admiten dígitos."""
    value = batch + 1
    letters = ""
    while value:
        value, remainder = divmod(value - 1, 26)
        letters = chr(65 + remainder) + letters
    return letters


def batch_name(name, batch):
    return f"{name} Lote {batch_letters(batch)}" if batch else name


def batch_code(code, batch):
    return f"{code}-{batch_letters(batch)}" if batch else code
