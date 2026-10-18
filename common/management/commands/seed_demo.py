from datetime import timedelta

from django.contrib.auth.models import Group, Permission, User
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from accounts.models import Area, Delegation, Official, Position, Role
from activities.models import Activity
from configuration.models import Item, Period

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
    ("D01", "Centro", "Calle Demo 101", "La Serena", Delegation.Status.ACTIVE),
    ("D02", "Norte", "Calle Demo 202", "La Serena", Delegation.Status.ACTIVE),
    ("D03", "Sur", "Calle Demo 303", "La Serena", Delegation.Status.ACTIVE),
    ("D04", "Rural", "Camino Demo km 4", "La Serena", Delegation.Status.INACTIVE),
]

# Rol: (alcance, descripción, permisos). Los permisos del Administrador se calculan aparte.
ROLES = {
    "Administrador": (
        Role.Scope.ALL,
        "Configura delegaciones, usuarios, roles, catálogos y períodos.",
        None,
    ),
    "Coordinador": (
        Role.Scope.ALL,
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
        Role.Scope.DELEGATION,
        "Consulta la gestión de sus delegaciones autorizadas.",
        [
            "activities.view_activity", "activities.view_socialattention",
            "activities.view_evidence", "activities.view_evidencevalidation",
            "accounts.view_official", "accounts.view_delegation",
            "configuration.view_item", "configuration.view_period",
        ],
    ),
    "Operador": (
        Role.Scope.DELEGATION,
        "Registra actividades y atenciones de su delegación.",
        OPERATOR_PERMISSIONS,
    ),
    "Verificador": (
        Role.Scope.DELEGATION,
        "Revisa evidencias y registra su validación.",
        [
            "activities.view_activity", "activities.view_socialattention",
            "activities.view_evidence", "activities.view_evidencevalidation",
            "activities.add_evidencevalidation", "activities.change_evidencevalidation",
            "accounts.view_official", "configuration.view_item",
        ],
    ),
    "Consulta": (
        Role.Scope.DELEGATION,
        "Solo lectura sobre la información de su delegación.",
        CONSULTA_PERMISSIONS,
    ),
}

# Contexto de Funcionario Demo 1 a 5: (delegación principal, roles, delegaciones autorizadas).
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


def get_permissions(names):
    """Permisos a partir de "app_label.codename"; falla si alguno no existe."""
    query = Q()
    for name in names:
        app_label, codename = name.split(".")
        query |= Q(content_type__app_label=app_label, codename=codename)
    permissions = Permission.objects.filter(query).select_related("content_type")
    missing = set(names) - {f"{p.content_type.app_label}.{p.codename}" for p in permissions}
    if missing:
        raise CommandError(f"Permisos inexistentes: {', '.join(sorted(missing))}")
    return permissions


def get_administrator_permissions():
    """Ver, crear y modificar todo el dominio y las cuentas; la auditoría solo se consulta."""
    return (
        Permission.objects.filter(
            Q(content_type__app_label__in=["accounts", "activities", "configuration"])
            | Q(content_type__app_label="auth", content_type__model__in=["user", "group"])
        )
        .exclude(codename__startswith="delete_")
        .exclude(codename__in=["add_auditlog", "change_auditlog"])
    )


def sync_fields(instance, **fields):
    """Guarda solo los campos que cambiaron, para no alterar updated_at en cada seed."""
    changed = [name for name, value in fields.items() if getattr(instance, name) != value]
    if changed:
        for name in changed:
            setattr(instance, name, fields[name])
        instance.save(update_fields=[*changed, "updated_at"])


def assign_context(official, delegation, roles, authorized_delegations=()):
    sync_fields(official, delegation=delegation)
    official.roles.set(roles)
    official.authorized_delegations.set(authorized_delegations)


class Command(BaseCommand):
    help = (
        "Carga datos de prueba: áreas, cargos, delegaciones, roles y funcionarios con su contexto, "
        "para demostrar el scoping y el acceso por perfil."
    )

    @transaction.atomic
    def handle(self, *args, **options):
        today = timezone.now().date()
        legacy_groups = list(Group.objects.filter(name__in=LEGACY_GROUPS))

        # ---------- 5 Áreas ----------
        area_names = ["Área Norte", "Área Sur", "Área Centro", "Área Cordillera", "Área Costa"]
        areas = [Area.objects.get_or_create(area_name=n)[0] for n in area_names]

        # ---------- 5 Cargos ----------
        position_names = ["Analista", "Coordinador", "Administrativo", "Supervisor", "Encargado de Terreno"]
        positions = [Position.objects.get_or_create(position_name=n)[0] for n in position_names]

        # ---------- 4 Delegaciones: 3 activas y 1 inactiva ----------
        delegations = {}
        for code, name, address, commune, status in DELEGATIONS:
            delegations[name], _ = Delegation.objects.get_or_create(
                delegation_name=name,
                defaults=dict(code=code, address=address, commune=commune, status=status),
            )

        # ---------- 6 Roles SGR con sus permisos y alcance ----------
        roles = {}
        for role_name, (scope, description, permission_names) in ROLES.items():
            role, _ = Role.objects.get_or_create(
                role_name=role_name, defaults=dict(scope=scope, description=description)
            )
            sync_fields(role, scope=scope, is_active=True)
            role.permissions.set(
                get_administrator_permissions() if permission_names is None
                else get_permissions(permission_names)
            )
            roles[role_name] = role

        # ---------- Superusuario técnico, con funcionario Administrador (alcance ALL) ----------
        admin_user = User.objects.filter(username="admin_demo").first()
        if admin_user is None:
            admin_user = User.objects.create_superuser("admin_demo", "admin@demo.cl", "demo1234")
        admin_official, _ = Official.objects.get_or_create(
            national_id="10000098-8",
            defaults=dict(full_name="Administrador Demo", email="admin@demo.cl", user=admin_user),
        )
        sync_fields(admin_official, user=admin_user)
        assign_context(admin_official, delegations["Centro"], [roles["Administrador"]])

        # ---------- 5 Usuarios de Django (funcionario1-4 se vinculan a un Official; funcionario5 queda SIN contexto) ----------
        users = []
        for i in range(5):
            username = f"funcionario{i+1}"
            user, created = User.objects.get_or_create(username=username, defaults={"is_staff": True})
            if created:
                user.set_password("demo1234")
                user.save()
            user.groups.remove(*legacy_groups)
            users.append(user)

        # ---------- 5 Funcionarios: 1-2 en Norte, 3-4 en Sur, 5 en Centro (archivado) ----------
        officials = []
        for i in range(5):
            official, _ = Official.objects.get_or_create(
                national_id=f"{10000000 + i}-{i}",
                defaults=dict(
                    full_name=f"Funcionario Demo {i+1}",
                    email=f"funcionario{i+1}@demo.cl",
                    position=positions[i],
                ),
            )
            # Vincular área y usuario
            sync_fields(
                official,
                area=areas[[0, 0, 1, 1, 2][i]],
                user=users[i] if i < 4 else None,
            )
            delegation_name, role_names, authorized_names = OFFICIAL_CONTEXT[i]
            assign_context(
                official,
                delegations[delegation_name],
                [roles[name] for name in role_names],
                [delegations[name] for name in authorized_names],
            )
            officials.append(official)

        # ---------- Usuario de consulta (solo lectura) en Área Norte ----------
        consulta_user, created = User.objects.get_or_create(username="consulta_norte", defaults={"is_staff": True})
        if created:
            consulta_user.set_password("demo1234")
            consulta_user.save()
        consulta_user.groups.remove(*legacy_groups)
        consulta_official, _ = Official.objects.get_or_create(
            national_id="10000099-9",
            defaults=dict(full_name="Consulta Demo Norte", email="consulta_norte@demo.cl",
                          position=positions[0], area=areas[0], user=consulta_user),
        )
        assign_context(consulta_official, delegations["Norte"], [roles["Consulta"]])

        # ---------- Evidencia de borrado lógico (deleted_at) ----------
        last_official = officials[4]
        if last_official.deleted_at is None:
            last_official.deleted_at = timezone.now()
            last_official.save(update_fields=["deleted_at", "updated_at"])

        # ---------- 5 Ítems ----------
        item_names = ["Atención ciudadana", "Terreno", "Reunión de coordinación",
                      "Levantamiento de datos", "Seguimiento de caso"]
        items = [Item.objects.get_or_create(item_name=n)[0] for n in item_names]

        # ---------- 5 Períodos (no se crea uno que se solape con otro existente) ----------
        for i in range(5):
            start = today.replace(day=1) - timedelta(days=30 * i)
            end = start + timedelta(days=29)
            if not Period.objects.filter(start_date__lte=end, end_date__gte=start).exists():
                Period.objects.create(
                    start_date=start, end_date=end,
                    status=Period.Status.OPEN if i == 0 else Period.Status.CLOSED,
                )

        # ---------- 10 Actividades (2 por funcionario, para ver datos en ambas áreas) ----------
        # Se identifican por funcionario, ítem y descripción (no por fecha) para no duplicarlas
        # al ejecutar el seed otro día.
        for i, official in enumerate(officials):
            for j in range(2):
                item = items[(i + j) % 5]
                description = f"Actividad de prueba - {official.full_name} - {official.area.area_name}"
                if not Activity.objects.filter(official=official, item=item, action_description=description).exists():
                    Activity.objects.create(
                        official=official, item=item, date=today,
                        record_type="Registro", action_description=description,
                    )

        self.stdout.write(self.style.SUCCESS(
            "Seed cargado: 5 áreas, 5 cargos, 4 delegaciones (3 activas), 6 roles, 7 usuarios Django, "
            "7 funcionarios con delegación y rol, 5 ítems, 5 períodos y 10 actividades."
        ))
