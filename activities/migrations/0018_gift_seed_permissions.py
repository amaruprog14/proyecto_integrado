"""Habilita regalos solo en los tres roles administradores identificados por la semilla."""
from django.db import migrations

ROLES = (("Administrador", "ALL"), ("Coordinador del sistema", "ALL"), ("Delegado", "DELEGATION"))
MODELS = {
    "giftcampaign": ("view", "add", "change"),
    "giftregistration": ("view", "add", "change", "deliver", "cancel"),
}


def grant(apps, schema_editor):
    db = schema_editor.connection.alias
    ContentType = apps.get_model("contenttypes", "ContentType")
    Permission = apps.get_model("auth", "Permission")
    Role = apps.get_model("accounts", "Role")
    permissions = []
    verbs = {"view": "Consultar", "add": "Crear", "change": "Editar", "deliver": "Confirmar entrega de", "cancel": "Anular"}
    for model, actions in MODELS.items():
        content_type, _ = ContentType.objects.using(db).get_or_create(app_label="activities", model=model)
        for action in actions:
            permission, _ = Permission.objects.using(db).get_or_create(content_type=content_type,
                codename=f"{action}_{model}", defaults={"name": f"{verbs[action]} {'campañas' if model == 'giftcampaign' else 'inscripciones'} de regalos"})
            permissions.append(permission)
    for name, scope in ROLES:
        for role in Role.objects.using(db).filter(role_name=name, scope=scope, deleted_at__isnull=True,
                                                 description__startswith="[SGR seed v1]"):
            role.permissions.add(*permissions)


def revoke(apps, schema_editor):
    db = schema_editor.connection.alias
    Role = apps.get_model("accounts", "Role")
    Permission = apps.get_model("auth", "Permission")
    codes = [f"{action}_{model}" for model, actions in MODELS.items() for action in actions]
    permissions = list(Permission.objects.using(db).filter(content_type__app_label="activities", codename__in=codes))
    for name, scope in ROLES:
        for role in Role.objects.using(db).filter(role_name=name, scope=scope, description__startswith="[SGR seed v1]"):
            role.permissions.remove(*permissions)


class Migration(migrations.Migration):
    dependencies = [("activities", "0017_gift_campaigns"), ("accounts", "0015_absence_seed_roles")]
    operations = [migrations.RunPython(grant, revoke)]
