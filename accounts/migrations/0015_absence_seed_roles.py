"""Permisos de Ausencias para los roles de demostración ya desplegados (mismo patrón que
analytics/0008_score_adjustment_roles). Solo toca roles creados por la semilla (MARKER)."""
from django.db import migrations

MANAGE = ("view_officialabsence", "manage_absence")
SEED_ROLES = (
    ("Administrador", "ALL", MANAGE),
    ("Coordinador del sistema", "ALL", MANAGE),
    ("Delegado", "DELEGATION", MANAGE),
)
NAMES = {"view_officialabsence": "Can view Ausencia", "manage_absence": "Puede gestionar ausencias"}


def grant_roles(apps, schema_editor):
    db = schema_editor.connection.alias
    Role = apps.get_model("accounts", "Role")
    Permission = apps.get_model("auth", "Permission")
    ContentType = apps.get_model("contenttypes", "ContentType")
    content_type, _ = ContentType.objects.using(db).get_or_create(app_label="accounts", model="officialabsence")
    permissions = {}
    for codename, name in NAMES.items():
        rows = Permission.objects.using(db)
        permissions[codename], _ = rows.get_or_create(
            content_type=content_type, codename=codename, defaults={"name": name},
        )
    for role_name, scope, codenames in SEED_ROLES:
        roles = Role.objects.using(db).filter(role_name=role_name, scope=scope, deleted_at__isnull=True,
                                              description__startswith="[SGR seed v1]")
        for role in roles:
            selected = [permissions[code] for code in codenames if code in permissions]
            role.permissions.add(*selected)


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0014_measurement_rules"),
    ]

    # No se conoce la procedencia de las asignaciones previas o posteriores a esta migración.
    # La reversión conserva los permisos; su retirada se realiza explícitamente desde Roles.
    operations = [migrations.RunPython(grant_roles, migrations.RunPython.noop)]
