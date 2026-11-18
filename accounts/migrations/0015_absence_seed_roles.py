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


def update_roles(apps, schema_editor, *, grant):
    db = schema_editor.connection.alias
    Role = apps.get_model("accounts", "Role")
    Permission = apps.get_model("auth", "Permission")
    ContentType = apps.get_model("contenttypes", "ContentType")
    content_type = ContentType.objects.using(db).filter(app_label="accounts", model="officialabsence").first()
    if content_type is None:
        if not grant:
            return
        content_type = ContentType.objects.using(db).create(app_label="accounts", model="officialabsence")
    permissions = {}
    for codename, name in NAMES.items():
        rows = Permission.objects.using(db)
        if grant:
            permissions[codename], _ = rows.get_or_create(
                content_type=content_type, codename=codename, defaults={"name": name},
            )
        elif permission := rows.filter(content_type=content_type, codename=codename).first():
            permissions[codename] = permission
    for role_name, scope, codenames in SEED_ROLES:
        roles = Role.objects.using(db).filter(role_name=role_name, scope=scope, deleted_at__isnull=True,
                                              description__startswith="[SGR seed v1]")
        for role in roles:
            selected = [permissions[code] for code in codenames if code in permissions]
            if grant:
                role.permissions.add(*selected)
            elif role_name != "Administrador":
                # El Administrador ya los tenía por sus permisos de cuentas: no se le quitan.
                role.permissions.remove(*selected)


def grant_roles(apps, schema_editor):
    update_roles(apps, schema_editor, grant=True)


def revoke_roles(apps, schema_editor):
    update_roles(apps, schema_editor, grant=False)


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0014_measurement_rules"),
    ]

    operations = [migrations.RunPython(grant_roles, revoke_roles)]
