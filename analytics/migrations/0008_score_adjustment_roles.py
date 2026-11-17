from django.db import migrations


REGISTER = ("view_scoreadjustment", "add_scoreadjustment")
REVIEW = (*REGISTER, "review_scoreadjustment")
SEED_ROLES = (
    ("Administrador", "ALL", REVIEW),
    ("Coordinador del sistema", "ALL", REVIEW),
    ("Funcionario", "DELEGATION", REGISTER),
    ("Delegado", "DELEGATION", REGISTER),
)


def update_roles(apps, schema_editor, *, grant):
    db = schema_editor.connection.alias
    Role = apps.get_model("accounts", "Role")
    Permission = apps.get_model("auth", "Permission")
    ContentType = apps.get_model("contenttypes", "ContentType")
    content_type = ContentType.objects.using(db).filter(app_label="analytics", model="scoreadjustment").first()
    if content_type is None:
        if not grant:
            return
        content_type = ContentType.objects.using(db).create(app_label="analytics", model="scoreadjustment")
    permissions = {}
    names = {
        "view_scoreadjustment": "Can view reclamo o felicitación",
        "add_scoreadjustment": "Can add reclamo o felicitación",
        "review_scoreadjustment": "Puede validar reclamos y felicitaciones",
    }
    for codename, name in names.items():
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
            else:
                role.permissions.remove(*selected)


def grant_roles(apps, schema_editor):
    update_roles(apps, schema_editor, grant=True)


def revoke_roles(apps, schema_editor):
    update_roles(apps, schema_editor, grant=False)


class Migration(migrations.Migration):
    dependencies = [
        ("analytics", "0007_score_adjustments"),
    ]

    operations = [migrations.RunPython(grant_roles, revoke_roles)]
