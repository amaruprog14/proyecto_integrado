from django.db import migrations


REGISTER = ("view_scoreadjustment", "add_scoreadjustment")
REVIEW = (*REGISTER, "review_scoreadjustment")
SEED_ROLES = (
    ("Administrador", "ALL", REVIEW),
    ("Coordinador del sistema", "ALL", REVIEW),
    ("Funcionario", "DELEGATION", REGISTER),
    ("Delegado", "DELEGATION", REGISTER),
)


def grant_roles(apps, schema_editor):
    db = schema_editor.connection.alias
    Role = apps.get_model("accounts", "Role")
    Permission = apps.get_model("auth", "Permission")
    ContentType = apps.get_model("contenttypes", "ContentType")
    content_type, _ = ContentType.objects.using(db).get_or_create(app_label="analytics", model="scoreadjustment")
    permissions = {}
    names = {
        "view_scoreadjustment": "Can view reclamo o felicitación",
        "add_scoreadjustment": "Can add reclamo o felicitación",
        "review_scoreadjustment": "Puede validar reclamos y felicitaciones",
    }
    for codename, name in names.items():
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
        ("analytics", "0007_score_adjustments"),
    ]

    # Conservar las asignaciones evita revocar permisos otorgados manualmente.
    operations = [migrations.RunPython(grant_roles, migrations.RunPython.noop)]
