"""Cuenta reproducible de evaluación, sin ampliar el administrador global."""
from django.contrib.auth.models import Permission, User
from django.core.management.base import CommandError
from django.db import transaction

from accounts.models import Official, Role
from common.demo_data import DEMO_PASSWORD, OPERATOR_PERMISSIONS, demo_rut

USERNAME = "adminEvalA"
ROLE_NAME = "Administrador evaluación A"
PERMISSIONS = (
    "accounts.view_official", "accounts.add_official", "accounts.change_official",
    "accounts.archive_official", "activities.view_activity", "activities.add_activity",
    "activities.change_activity", "activities.archive_activity", "configuration.view_item",
)


@transaction.atomic
def provision_evaluation_admin(*, reset_password=False):
    """Reutiliza solo el funcionario 006 intacto de la semilla; rechaza colisiones."""
    official = Official.objects.select_for_update().filter(national_id=demo_rut(70000006)).first()
    if (official is None or not official.is_enabled
            or official.email != "official006@sgr.example.invalid"
            or official.delegation is None or official.delegation.delegation_name != "Las Compañías"
            or official.delegation.deleted_at or official.delegation.status != "ACTIVE"
            or official.authorized_delegations.exists()):
        raise CommandError("No está disponible el funcionario 006 de la semilla en Las Compañías. No se modifica la base.")
    permissions = list(Permission.objects.filter(
        content_type__app_label__in=["accounts", "activities", "configuration"]).select_related("content_type"))
    by_name = {f"{p.content_type.app_label}.{p.codename}": p for p in permissions}
    if set(PERMISSIONS) - by_name.keys():
        raise CommandError("Faltan permisos del CRUD. Ejecuta las migraciones antes de preparar la cuenta.")
    role, role_created = Role.objects.get_or_create(role_name=ROLE_NAME, defaults={
        "scope": Role.Scope.DELEGATION,
        "description": "Evaluación TI3041: ambos CRUD de Las Compañías; sin administración de roles ni acceso global.",
    })
    expected = {by_name[name].pk for name in PERMISSIONS}
    if role_created:
        role.permissions.set(expected)
    elif (role.scope != Role.Scope.DELEGATION or not role.is_active or role.deleted_at
            or set(role.permissions.values_list("pk", flat=True)) != expected):
        raise CommandError("El rol de evaluación existente tiene otra configuración; no se reemplaza.")
    # Permite actualizar únicamente el perfil sin cuenta de la semilla anterior.
    existing_roles = list(official.roles.all())
    legacy_permissions = set(OPERATOR_PERMISSIONS + ["accounts.add_official", "accounts.change_official"])
    legacy = (official.user_id is None and len(existing_roles) == 1
              and existing_roles[0].role_name == "Funcionario"
              and existing_roles[0].scope == Role.Scope.DELEGATION
              and existing_roles[0].is_active and not existing_roles[0].deleted_at
              and {f"{p.content_type.app_label}.{p.codename}" for p in existing_roles[0].permissions.select_related("content_type")} == legacy_permissions)
    if existing_roles and {r.pk for r in existing_roles} != {role.pk} and not legacy:
        raise CommandError("El funcionario de evaluación tiene otros roles; no se reemplazan.")
    email = "adminevala@sgr.example.invalid"
    user = User.objects.filter(username=USERNAME).first()
    user_created = user is None
    if user is None:
        if official.user_id or User.objects.filter(email__iexact=email).exists():
            raise CommandError("La cuenta o el correo de evaluación está ocupado; no se reutiliza.")
        first, _, last = official.full_name.partition(" ")
        user = User.objects.create_user(USERNAME, email, DEMO_PASSWORD, first_name=first, last_name=last)
    elif (official.user_id != user.pk or user.email != email or not user.is_active
            or user.is_staff or user.is_superuser or user.groups.exists()
            or user.user_permissions.exists() or hasattr(user, "service_recipient")):
        raise CommandError("La cuenta de evaluación existente tiene otra configuración; no se modifica.")
    if reset_password and not user.check_password(DEMO_PASSWORD):
        user.set_password(DEMO_PASSWORD)
        user.save(update_fields=["password"])
    if official.user_id != user.pk:
        official.user = user
        official.save(update_fields=["user", "updated_at"])
    official.roles.set([role])
    return user, user_created, role_created
