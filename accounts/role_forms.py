"""
Mantenedor de Roles: formulario y reglas que lo mantienen coherente con el CRUD de usuarios.

- "Administrador global" es la misma regla que aplica accounts.forms al asignar roles: alcance
  ALL y al menos un permiso de privileged_permission_query(). Aquí se reutiliza esa consulta en
  is_global_administrator() (un alcance y permisos dados) y en last_global_administrator()
  (resuelta en la base de datos).
- Asignar permisos privilegiados exige accounts.change_role, igual que asignar roles
  privilegiados a un usuario.
- El sistema nunca queda sin administrador: el último rol Administrador global vigente con
  funcionarios activos no puede desactivarse, perder sus permisos privilegiados ni su alcance.
- El Administrador global no se combina con otros roles, por lo que un rol no puede pasar a
  serlo (ni reactivarse como tal) si algún funcionario lo tiene junto con otro rol vigente.
"""

import unicodedata

from django import forms
from django.contrib.auth.models import Permission
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Exists, OuterRef, Q

from accounts.forms import privileged_permission_query
from accounts.models import Official, Role

SGR_APP_LABELS = ("accounts", "activities", "agenda", "analytics", "configuration")
ACTION_LABELS = {"view": "Consultar", "add": "Crear", "change": "Editar", "delete": "Eliminar"}
ACTION_ORDER = ("view", "add", "change")
ROLE_STATUS_CHOICES = [("ACTIVE", "Activo"), ("INACTIVE", "Inactivo")]


def normalize_spaces(value):
    """Quita los espacios de los extremos y deja uno solo entre palabras."""
    return " ".join((value or "").split())


def sort_text(value):
    """Clave de orden alfabético que ignora tildes y mayúsculas."""
    return unicodedata.normalize("NFD", value).encode("ascii", "ignore").decode().lower()


def officials_phrase(count):
    return f"{count} funcionario activo" if count == 1 else f"{count} funcionarios activos"


# --- Reglas de administración global ---

def is_global_administrator(scope, permissions):
    """
    Alcance ALL y al menos un permiso privilegiado. `permissions` es un queryset de Permission:
    los guardados en el rol o los elegidos en el formulario antes de guardar.
    """
    return scope == Role.Scope.ALL and permissions.filter(privileged_permission_query()).exists()


def can_grant_privileged_permissions(actor):
    """Misma exigencia que el formulario de usuarios: superusuario o accounts.change_role."""
    return actor is None or actor.is_superuser or actor.has_perm("accounts.change_role")


def active_official_filter(prefix=""):
    """Funcionarios que hoy reciben los permisos de sus roles: habilitados y con cuenta activa."""
    return Q(
        **{
            f"{prefix}status": Official.Status.ACTIVE,
            f"{prefix}deleted_at__isnull": True,
            f"{prefix}user__is_active": True,
        }
    )


def active_officials(role):
    return role.officials.filter(active_official_filter())


def last_global_administrator():
    """El único rol vigente que da administración global a funcionarios activos, si es uno solo."""
    privileged = Permission.objects.filter(privileged_permission_query(), sgr_roles=OuterRef("pk"))
    staffed = Official.objects.filter(active_official_filter(), roles=OuterRef("pk"))
    supporting = list(
        Role.objects.filter(
            Exists(privileged),
            Exists(staffed),
            is_active=True,
            deleted_at__isnull=True,
            scope=Role.Scope.ALL,
        ).order_by("pk")[:2]
    )
    return supporting[0] if len(supporting) == 1 else None


def is_last_global_administrator(role):
    last = last_global_administrator()
    return last is not None and last.pk == role.pk


def last_global_administrator_message(role, action):
    """`action` completa la frase, p. ej. "desactivar el rol"."""
    return (
        f"No se puede {action} {role.role_name}: es el último rol Administrador global con "
        "funcionarios activos y el sistema quedaría sin administrador. Asigna primero otro "
        "rol Administrador global a un funcionario activo."
    )


def officials_combining_roles(role):
    """Funcionarios que tienen este rol junto con otro rol vigente."""
    other_roles = Role.objects.filter(is_active=True, deleted_at__isnull=True).exclude(pk=role.pk)
    return (
        Official.objects.filter(deleted_at__isnull=True, roles=role)
        .filter(roles__in=other_roles)
        .distinct()
    )


def combined_roles_message(role, count):
    noun = "funcionario lo tiene" if count == 1 else "funcionarios lo tienen"
    return (
        f"Como Administrador global, el rol {role.role_name} no puede combinarse con otros roles "
        f"y {count} {noun} junto con otro rol vigente. Ajusta primero sus roles desde el "
        "mantenedor de usuarios."
    )


# --- Catálogo y presentación de permisos ---

def assignable_permissions():
    """
    Permisos que un rol SGR puede otorgar: los de las apps del SGR y las cuentas de usuario,
    sin borrado físico (los registros se desactivan), sin editar la auditoría y sin los
    códigos internos de recuperación de contraseña.
    """
    return (
        Permission.objects.filter(
            Q(content_type__app_label__in=SGR_APP_LABELS)
            | Q(content_type__app_label="auth", content_type__model__in=["user", "group"])
        )
        .exclude(codename__startswith="delete_")
        .exclude(content_type__app_label="configuration", codename__in=["add_auditlog", "change_auditlog"])
        .exclude(content_type__app_label="accounts", content_type__model="passwordresetcode")
        .select_related("content_type")
    )


def permission_group_label(permission):
    model = permission.content_type.model_class()
    if model is None:
        return permission.content_type.name
    return str(model._meta.verbose_name_plural).capitalize()


def permission_action(permission):
    return ACTION_LABELS.get(permission.codename.split("_", 1)[0], permission.name)


def permission_label(permission):
    return f"{permission_group_label(permission)}: {permission_action(permission)}"


def group_permissions(items, permission_of=lambda item: item):
    """[(tabla, [elementos])] ordenado por tabla y, dentro de ella, Consultar, Crear y Editar."""

    def action_key(item):
        permission = permission_of(item)
        action = permission.codename.split("_", 1)[0]
        order = ACTION_ORDER.index(action) if action in ACTION_ORDER else len(ACTION_ORDER)
        return order, permission.codename

    groups = {}
    for item in items:
        groups.setdefault(permission_group_label(permission_of(item)), []).append(item)
    return [
        (label, sorted(members, key=action_key))
        for label, members in sorted(groups.items(), key=lambda group: sort_text(group[0]))
    ]


def role_snapshot(role):
    """Valores auditables del rol; los permisos como app_label.codename, ordenados."""
    permissions = sorted(
        f"{permission.content_type.app_label}.{permission.codename}"
        for permission in role.permissions.select_related("content_type")
    )
    return {
        "Nombre": role.role_name,
        "Descripción": role.description or "—",
        "Alcance": role.get_scope_display(),
        "Estado": "Activo" if role.is_active else "Inactivo",
        "Permisos": ", ".join(permissions) or "Sin permisos",
    }


def format_snapshot(snapshot, keys=None):
    return "\n".join(
        f"{key}: {value}" for key, value in snapshot.items() if keys is None or key in keys
    )


class PermissionCheckboxSelectMultiple(forms.CheckboxSelectMultiple):
    """Casillas de permisos: marca los privilegiados y los bloquea si el actor no puede otorgarlos."""

    privileged_ids = frozenset()
    lock_privileged = False

    def create_option(self, name, value, label, selected, index, subindex=None, attrs=None):
        option = super().create_option(name, value, label, selected, index, subindex, attrs)
        permission = getattr(value, "instance", None)
        if permission is not None and permission.pk in self.privileged_ids:
            option["attrs"]["data-privileged"] = "true"
            if self.lock_privileged:
                option["attrs"]["disabled"] = True
        return option


class PermissionMultipleChoiceField(forms.ModelMultipleChoiceField):
    privileged_ids = frozenset()

    def label_from_instance(self, obj):
        label = permission_action(obj)
        return f"{label} (privilegiado)" if obj.pk in self.privileged_ids else label


class RoleForm(forms.ModelForm):
    """
    Alta y edición de roles. El estado solo se elige al crear; después se cambia con
    Desactivar/Reactivar, que muestran a cuántos funcionarios afecta.
    """

    is_active = forms.TypedChoiceField(
        label="Estado",
        choices=[("True", "Activo"), ("False", "Inactivo")],
        coerce=lambda value: value == "True",
        widget=forms.Select(attrs={"class": "form-select"}),
    )
    permissions = PermissionMultipleChoiceField(
        label="Permisos",
        queryset=Permission.objects.none(),
        widget=PermissionCheckboxSelectMultiple(),
        error_messages={
            "required": "Selecciona al menos un permiso.",
            "invalid_choice": "Uno de los permisos seleccionados no está disponible.",
            "invalid_pk_value": "Uno de los permisos seleccionados no está disponible.",
        },
    )

    class Meta:
        model = Role
        fields = ["role_name", "description", "scope", "permissions", "is_active"]
        widgets = {
            "role_name": forms.TextInput(
                attrs={"class": "form-control", "maxlength": 100, "autocomplete": "off"}
            ),
            "description": forms.Textarea(attrs={"class": "form-control", "rows": 3}),
            "scope": forms.Select(attrs={"class": "form-select"}),
        }
        labels = {
            "role_name": "Nombre del rol",
            "description": "Descripción",
            "scope": "Alcance",
        }
        error_messages = {
            "role_name": {
                "required": "Ingresa el nombre del rol.",
                "unique": "Ya existe un rol con este nombre.",
            },
            "scope": {"required": "Selecciona el alcance del rol."},
        }

    def __init__(self, *args, actor=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.actor = actor
        catalog = assignable_permissions()
        privileged_ids = frozenset(
            Permission.objects.filter(privileged_permission_query()).values_list("pk", flat=True)
        )
        field = self.fields["permissions"]
        field.queryset = catalog
        field.privileged_ids = privileged_ids
        field.widget.privileged_ids = privileged_ids
        self.privileged_locked = not can_grant_privileged_permissions(actor)
        field.widget.lock_privileged = self.privileged_locked

        if self.instance.pk:
            self.fields.pop("is_active")
            self.previous_snapshot = role_snapshot(self.instance)
            self.was_global_administrator = is_global_administrator(
                self.instance.scope, self.instance.permissions.all()
            )
            # Permisos fuera del catálogo (p. ej. asignados desde el Admin): se conservan.
            self.kept_permissions = list(self.instance.permissions.exclude(pk__in=catalog.values("pk")))
        else:
            self.previous_snapshot = None
            self.was_global_administrator = False
            self.kept_permissions = []

    def permission_groups(self):
        """Casillas de permisos agrupadas por tabla, para el template."""
        return group_permissions(self["permissions"], lambda checkbox: checkbox.data["value"].instance)

    def clean_role_name(self):
        name = normalize_spaces(self.cleaned_data.get("role_name"))
        duplicates = Role.objects.filter(role_name__iexact=name)
        if self.instance.pk:
            duplicates = duplicates.exclude(pk=self.instance.pk)
        if duplicates.exists():
            raise ValidationError("Ya existe un rol con este nombre.")
        return name

    def clean_description(self):
        return (self.cleaned_data.get("description") or "").strip()

    def clean(self):
        cleaned = super().clean()
        scope = cleaned.get("scope")
        permissions = cleaned.get("permissions")
        if not self.instance.pk or not scope or permissions is None:
            return cleaned

        if is_global_administrator(scope, permissions):
            if not self.was_global_administrator and self.instance.is_active:
                conflicts = officials_combining_roles(self.instance).count()
                if conflicts:
                    raise ValidationError(combined_roles_message(self.instance, conflicts))
        elif self.was_global_administrator and is_last_global_administrator(self.instance):
            raise ValidationError(
                last_global_administrator_message(
                    self.instance, "quitar los permisos privilegiados ni cambiar el alcance del rol"
                )
            )
        return cleaned

    def grants_privileged_permissions(self):
        permissions = self.cleaned_data.get("permissions")
        return permissions is not None and permissions.filter(privileged_permission_query()).exists()

    def save(self):
        with transaction.atomic():
            role = super().save(commit=False)
            role.save()
            role.permissions.set([*self.cleaned_data["permissions"], *self.kept_permissions])
        return role
