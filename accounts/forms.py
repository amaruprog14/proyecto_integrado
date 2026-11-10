import re

from django import forms
from django.contrib.auth.forms import AuthenticationForm
from django.contrib.auth.models import Permission
from django.contrib.auth.validators import UnicodeUsernameValidator
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Prefetch, Q

from accounts.models import Area, Delegation, Official, Position, Role
from common.chilean_rut import normalize_chilean_rut
from common.field_validation import (
    ACCOUNT_TEXT_LIMITS, DEFAULT_COMMUNE, PHONE_PATTERN, LimitedTextFieldsMixin,
    clean_address, clean_catalog_name, configure_text_widgets,
)
from common.scopes import delegation_ids, permission_scope
from common.text import normalize_spaces

GENERIC_LOGIN_ERROR = "Usuario, correo o contraseña incorrectos."
# Mismo validador que auth.User.username: estos formularios no son ModelForm y guardan sin
# full_clean(), así que sin él se aceptarían espacios u otros caracteres no permitidos.
username_validator = UnicodeUsernameValidator(
    message="Usa solo letras, números y los caracteres @ . + - _ (sin espacios)."
)

PRIVILEGED_ROLE_PERMISSIONS = frozenset(
    {
        "auth.add_group",
        "auth.change_group",
        "auth.add_user",
        "auth.change_user",
        "accounts.add_delegation",
        "accounts.change_delegation",
        "accounts.add_role",
        "accounts.change_role",
        "accounts.archive_official",
        "activities.archive_activity",
    }
)


def privileged_permission_query():
    query = Q()
    for permission in PRIVILEGED_ROLE_PERMISSIONS:
        app_label, codename = permission.split(".", 1)
        query |= Q(content_type__app_label=app_label, codename=codename)
    return query


class RoleCheckboxSelectMultiple(forms.CheckboxSelectMultiple):
    """
    Checkboxes with metadata used by the role-selection behavior.

    `locked_ids` are privileged roles the actor cannot assign: they render disabled, and those in
    `kept_ids` (already assigned) stay checked even after a submission with errors.
    """

    locked_ids = frozenset()
    kept_ids = frozenset()

    def create_option(self, name, value, label, selected, index, subindex=None, attrs=None):
        option = super().create_option(name, value, label, selected, index, subindex, attrs)
        role = value.instance if hasattr(value, "instance") else None
        if role is not None:
            option["attrs"]["data-role-scope"] = role.scope
            option["attrs"]["data-role-global-administrator"] = str(
                role.permissions.filter(privileged_permission_query()).exists()
                and role.scope == Role.Scope.ALL
            ).lower()
            if role.pk in self.locked_ids:
                option["attrs"]["disabled"] = True
                option["attrs"]["data-role-locked"] = "true"
                option["selected"] = role.pk in self.kept_ids
                option["attrs"].pop("checked", None)
                if option["selected"]:
                    option["attrs"]["checked"] = True
        return option


class RoleMultipleChoiceField(forms.ModelMultipleChoiceField):
    def label_from_instance(self, obj):
        return f"{obj.role_name} — {obj.description}" if obj.description else obj.role_name


class SGRAuthenticationForm(AuthenticationForm):
    """
    Login con usuario o correo. El error es genérico para no revelar qué dato falló. Durante un
    bloqueo temporal (accounts.login_security) se informa que hay que esperar; el mensaje es el
    mismo exista o no la cuenta.
    """

    error_messages = {
        "invalid_login": GENERIC_LOGIN_ERROR,
        "inactive": GENERIC_LOGIN_ERROR,
    }

    def __init__(self, request=None, *args, **kwargs):
        super().__init__(request, *args, **kwargs)
        username = self.fields["username"]
        username.label = "Usuario o correo"
        username.max_length = 254
        username.widget.attrs.update({"maxlength": 254, "autocomplete": "username"})

    def get_invalid_login_error(self):
        from accounts import login_security

        if getattr(self.request, login_security.LOCKED_REQUEST_FLAG, False):
            return ValidationError(login_security.locked_message(), code="locked")
        return super().get_invalid_login_error()


class RecoveryRequestForm(forms.Form):
    email = forms.EmailField(
        label="Correo electrónico",
        max_length=191,
        error_messages={
            "required": "Ingresa un correo electrónico válido para continuar.",
            "invalid": "Ingresa un correo electrónico válido para continuar.",
        },
    )


# --- Mantenedores: Delegaciones y Usuarios ---
#
# Las validaciones se ejecutan en el servidor; los formularios de usuario limitan las
# delegaciones ofrecidas al ámbito del actor, de modo que un identificador fuera de ese
# ámbito no valida aunque se envíe desde el navegador.


def get_user_model_class():
    from django.contrib.auth import get_user_model

    return get_user_model()


def assigned_roles_not_offered(official, offered_roles):
    """
    Roles asignados al funcionario que el formulario no ofrece (inactivos o archivados). Se
    muestran bloqueados y se conservan al guardar, para no quitarlos sin que nadie lo decida.
    """
    if official is None or not official.pk:
        return []
    return list(official.roles.exclude(pk__in=offered_roles.values("pk")).order_by("role_name"))


def sole_global_administrator_errors(official, status, roles):
    """
    Errores por campo si el cambio dejaría al sistema sin Administrador global: el funcionario
    es el único titular activo del último rol de ese tipo (misma regla que el mantenedor de Roles).
    """
    # Importación local: accounts.role_forms importa este módulo.
    from accounts.role_forms import sole_global_administrator_message, sole_global_administrator_role

    if official is not None and official.user_id and status and status != Official.Status.ACTIVE:
        from common.maintainer_forms import protect_last_group_administrator
        for group in official.user.groups.all():
            profile = getattr(group, "sgr_profile", None)
            if profile:
                try:
                    protect_last_group_administrator(group, profile.scope, group.permissions.all(),
                        group.user_set.exclude(pk=official.user_id), profile.is_active)
                except ValidationError as error:
                    return {"status": error.messages[0]}
    role = sole_global_administrator_role(official)
    if role is None:
        return {}
    errors = {}
    if status and status != Official.Status.ACTIVE:
        errors["status"] = sole_global_administrator_message(official, role, "desactivar ni suspender a")
    if roles is not None and role not in roles:
        errors["roles"] = sole_global_administrator_message(official, role, f"quitar el rol {role.role_name} a")
    return errors


def clean_person_name(value):
    name = normalize_spaces(value)
    if name and not all(word.isalpha() for word in name.split(" ")):
        raise ValidationError("Usa solo letras, tildes y espacios.")
    return name


def clean_phone(value):
    phone = value or ""
    if phone and (not re.fullmatch(PHONE_PATTERN, phone) or not 8 <= len(phone) <= 15):
        raise ValidationError("Ingresa un teléfono válido de 8 a 15 dígitos, sin espacios ni signos.")
    return phone


class AccountTextFieldsMixin(LimitedTextFieldsMixin):
    text_limits = ACCOUNT_TEXT_LIMITS

    def clean_person_field(self, name):
        if self.keeps_original_text(name):
            return self.initial[name]
        return clean_person_name(self.cleaned_data.get(name))

    def clean_phone(self):
        if self.keeps_original_text("phone"):
            return self.initial["phone"]
        return clean_phone(self.data.get(self.add_prefix("phone")))


def can_assign_privileged_roles(actor):
    """La asignación sin restricciones requiere administración global de roles."""
    return actor is None or permission_scope(actor, "accounts.change_role") == Role.Scope.ALL


def is_privileged_role(role):
    return role.permissions.filter(privileged_permission_query()).exists()


class RoleAssignmentMixin:
    """
    Reglas de asignación de roles comunes a OfficialUserForm y OfficialForm.

    - Solo se ofrecen roles vigentes; los inactivos ya asignados se conservan (kept_roles).
    - Un editor solo puede delegar permisos que ejerce por delegación o globalmente.
    - Los roles globales, privilegiados o que exceden sus permisos se bloquean. Si el
      funcionario ya tiene uno de esos roles, se conserva al editar los demás campos.
    - El Administrador global no se combina con otros roles vigentes.
    """

    def setup_roles(self, actor, official):
        field = self.fields["roles"]
        field.queryset = Role.objects.filter(is_active=True, deleted_at__isnull=True).order_by("role_name")
        self.kept_roles = assigned_roles_not_offered(official, field.queryset)
        self.locked_roles = []
        self.denied_roles = []
        self.unrestricted_role_assignment = can_assign_privileged_roles(actor)
        if self.unrestricted_role_assignment:
            return
        actor_permissions = actor.get_all_permissions()
        actor_scopes = {}
        roles = field.queryset.prefetch_related(
            Prefetch("permissions", queryset=Permission.objects.select_related("content_type"))
        )
        locked_ids = set()
        for role in roles:
            permissions = {f"{p.content_type.app_label}.{p.codename}" for p in role.permissions.all()}
            if (role.scope == Role.Scope.ALL or permissions & PRIVILEGED_ROLE_PERMISSIONS
                    or not permissions <= actor_permissions):
                locked_ids.add(role.pk)
                continue
            for permission in permissions - actor_scopes.keys():
                actor_scopes[permission] = permission_scope(actor, permission)
            # OWN autoriza al actor sobre sus registros, no sobre los de otro titular.
            if any(actor_scopes[p] not in (Role.Scope.DELEGATION, Role.Scope.ALL) for p in permissions):
                locked_ids.add(role.pk)
        field.widget.locked_ids = frozenset(locked_ids)
        if official is not None and official.pk:
            self.locked_roles = list(official.roles.filter(pk__in=field.widget.locked_ids))
        field.widget.kept_ids = frozenset(role.pk for role in self.locked_roles)
        field.help_text += (
            " Puedes asignar roles locales con permisos que ya ejerces en tu ámbito."
            " Los roles bloqueados que ya están asignados se conservan."
        )

    def final_roles(self, roles):
        """Roles que quedarán asignados: los elegidos más los conservados, sin repetir."""
        merged = {role.pk: role for role in [*(roles or []), *self.locked_roles, *self.kept_roles]}
        return list(merged.values())

    def clean_roles(self):
        roles = self.cleaned_data.get("roles")
        selected = list(roles or [])
        assigned_ids = {role.pk for role in self.locked_roles}
        self.denied_roles = [
            role
            for role in selected
            if role.pk in self.fields["roles"].widget.locked_ids and role.pk not in assigned_ids
        ]
        if self.denied_roles:
            raise ValidationError("No tienes autorización para asignar los roles seleccionados.")
        current = {role.pk: role for role in [*selected, *self.locked_roles]}.values()
        if len(current) > 1 and any(role.scope == Role.Scope.ALL and is_privileged_role(role) for role in current):
            raise ValidationError("El rol Administrador global no puede combinarse con otros roles.")
        return roles

    def clean(self):
        data = super().clean()
        if self.unrestricted_role_assignment or not data.get("roles"):
            return data
        target_ids = {delegation.pk for delegation in data.get("authorized_delegations") or []}
        principal = data.get("delegation")
        if principal is not None:
            target_ids.add(principal.pk)
        if target_ids - delegation_ids(self.actor):
            self.denied_roles = list(data["roles"])
            self.add_error("roles", "Solo puedes asignar roles dentro de tus delegaciones autorizadas.")
        return data


class DelegationForm(LimitedTextFieldsMixin, forms.ModelForm):
    """Alta y edición de delegaciones. El código se genera automáticamente."""

    text_limits = {"delegation_name": 50, "address": 50}

    class Meta:
        model = Delegation
        fields = ["delegation_name", "address", "commune", "status"]
        widgets = {
            "delegation_name": forms.TextInput(
                attrs={"class": "form-control", "maxlength": 100, "autocomplete": "off"}
            ),
            "address": forms.TextInput(
                attrs={"class": "form-control", "maxlength": 100, "autocomplete": "off"}
            ),
            "commune": forms.TextInput(
                attrs={"class": "form-control", "maxlength": 60, "autocomplete": "off"}
            ),
            "status": forms.Select(attrs={"class": "form-select"}),
        }
        labels = {
            "delegation_name": "Nombre de la delegación",
            "address": "Dirección",
            "commune": "Comuna",
            "status": "Estado",
        }
        error_messages = {
            "delegation_name": {
                "required": "Ingresa el nombre de la delegación.",
                "unique": "Ya existe una delegación con este nombre.",
            },
            "address": {"required": "Ingresa la dirección."},
            "commune": {"required": "Ingresa la comuna."},
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        configure_text_widgets(self)
        self.fields["commune"].initial = DEFAULT_COMMUNE
        self.fields["commune"].disabled = True
        self.initial["commune"] = DEFAULT_COMMUNE

    def clean_delegation_name(self):
        name = clean_catalog_name(self.cleaned_data.get("delegation_name"))
        duplicates = Delegation.objects.filter(delegation_name__iexact=name)
        if self.instance.pk:
            duplicates = duplicates.exclude(pk=self.instance.pk)
        if duplicates.exists():
            raise ValidationError("Ya existe una delegación con este nombre.")
        return name

    def clean_address(self):
        return clean_address(self.cleaned_data.get("address"))

    def clean_commune(self):
        return DEFAULT_COMMUNE


class OfficialUserForm(RoleAssignmentMixin, AccountTextFieldsMixin, forms.Form):
    """
    Administra la relación entre auth.User y accounts.Official.

    - Un usuario puede existir sin perfil Official (cuenta administrativa): la casilla
      «Registrar perfil de funcionario/a» decide si se crea o mantiene el perfil.
    - El correo se guarda en User y en Official para que el ingreso por correo sea inequívoco.
    - El estado se sincroniza: User.is_active es verdadero solo con estado Activo.
    - Al editar, una contraseña vacía conserva la contraseña actual.
    """

    username = forms.CharField(
        label="Nombre de usuario",
        max_length=150,
        validators=[username_validator],
        widget=forms.TextInput(attrs={"class": "form-control", "maxlength": 150, "autocomplete": "off"}),
        error_messages={"required": "Ingresa el nombre de usuario."},
    )
    first_name = forms.CharField(
        label="Nombres",
        max_length=150,
        required=False,
        widget=forms.TextInput(attrs={"class": "form-control", "maxlength": 150}),
    )
    last_name = forms.CharField(
        label="Apellidos",
        max_length=150,
        required=False,
        widget=forms.TextInput(attrs={"class": "form-control", "maxlength": 150}),
    )
    email = forms.EmailField(
        label="Correo electrónico",
        max_length=191,
        widget=forms.EmailInput(attrs={"class": "form-control", "maxlength": 191, "autocomplete": "off"}),
        error_messages={
            "required": "Ingresa el correo electrónico.",
            "invalid": "Ingresa un correo electrónico válido.",
        },
    )
    password1 = forms.CharField(
        label="Contraseña",
        required=False,
        strip=False,
        widget=forms.PasswordInput(attrs={"class": "form-control", "autocomplete": "new-password"}),
        help_text="Al editar, deja el campo vacío para conservar la contraseña actual.",
    )
    password2 = forms.CharField(
        label="Confirmar contraseña",
        required=False,
        strip=False,
        widget=forms.PasswordInput(attrs={"class": "form-control", "autocomplete": "new-password"}),
    )
    is_staff = forms.BooleanField(
        label="Acceso al panel de administración de Django",
        required=False,
        widget=forms.CheckboxInput(attrs={"class": "form-check-input"}),
    )
    has_official = forms.BooleanField(
        label="Registrar perfil de funcionario/a",
        required=False,
        widget=forms.CheckboxInput(attrs={"class": "form-check-input"}),
        help_text="Crea o mantiene el perfil Official con los datos de funcionario/a.",
    )
    full_name = forms.CharField(
        label="Nombre completo",
        max_length=200,
        required=False,
        widget=forms.TextInput(attrs={"class": "form-control", "maxlength": 200}),
    )
    national_id = forms.CharField(
        label="RUT o RUN chileno",
        max_length=20,
        required=False,
        widget=forms.TextInput(
            attrs={
                "class": "form-control",
                "maxlength": 20,
                "inputmode": "text",
                "data-chilean-rut": "true",
            }
        ),
        help_text="Escribe el RUT o RUN; se validará su dígito verificador.",
    )
    phone = forms.CharField(
        label="Teléfono",
        max_length=30,
        required=False,
        widget=forms.TextInput(attrs={"class": "form-control", "maxlength": 30}),
    )
    area = forms.ModelChoiceField(
        label="Área",
        queryset=Area.objects.all(),
        required=False,
        widget=forms.Select(attrs={"class": "form-select"}),
        empty_label="Sin área",
    )
    position = forms.ModelChoiceField(
        label="Cargo",
        queryset=Position.objects.all(),
        required=False,
        widget=forms.Select(attrs={"class": "form-select"}),
        empty_label="Sin cargo",
    )
    delegation = forms.ModelChoiceField(
        label="Delegación principal",
        queryset=Delegation.objects.none(),
        required=False,
        widget=forms.Select(attrs={"class": "form-select"}),
        empty_label="Sin delegación principal",
    )
    authorized_delegations = forms.ModelMultipleChoiceField(
        label="Delegaciones autorizadas",
        queryset=Delegation.objects.none(),
        required=False,
        widget=forms.CheckboxSelectMultiple(),
        help_text="Selecciona las delegaciones adicionales a las que podrá acceder.",
    )
    roles = RoleMultipleChoiceField(
        label="Roles SGR",
        queryset=Role.objects.none(),
        required=False,
        widget=RoleCheckboxSelectMultiple(),
        help_text="Selecciona uno o más roles vigentes.",
    )
    status = forms.ChoiceField(
        label="Estado",
        choices=Official.Status.choices,
        widget=forms.Select(attrs={"class": "form-select"}),
    )

    def __init__(
        self,
        *args,
        actor=None,
        instance=None,
        delegation_queryset=None,
        active_delegation=None,
        **kwargs,
    ):
        super().__init__(*args, **kwargs)
        self.actor = actor
        self.instance = instance
        self.official_instance = (
            getattr(instance, "official", None) if instance is not None and instance.pk else None
        )

        if delegation_queryset is not None:
            self.fields["delegation"].queryset = delegation_queryset
            self.fields["authorized_delegations"].queryset = delegation_queryset
        if active_delegation is not None and self.official_instance is None:
            self.fields["delegation"].queryset = self.fields["delegation"].queryset.filter(
                pk=active_delegation.pk
            )
            self.initial.setdefault("delegation", active_delegation.pk)
        self.setup_roles(actor, self.official_instance)
        current_official = getattr(self, "official_instance", instance)
        self.fields["area"].queryset = Area.objects.filter(
            Q(is_active=True, deleted_at__isnull=True) | Q(pk=getattr(current_official, "area_id", None))
        ).order_by("area_name")
        self.fields["position"].queryset = Position.objects.filter(
            Q(is_active=True, deleted_at__isnull=True) | Q(pk=getattr(current_official, "position_id", None))
        ).order_by("position_name")

        # Un perfil existente no se elimina desde el formulario.
        if self.official_instance is not None:
            self.fields.pop("has_official", None)

        if instance is not None and instance.pk:
            self.initial.setdefault("username", instance.username)
            self.initial.setdefault("first_name", instance.first_name)
            self.initial.setdefault("last_name", instance.last_name)
            self.initial.setdefault(
                "email",
                instance.email or (self.official_instance.email if self.official_instance else ""),
            )
            self.initial.setdefault("is_staff", instance.is_staff)
            if self.official_instance is not None:
                official = self.official_instance
                self.initial.setdefault("full_name", official.full_name)
                self.initial.setdefault("national_id", official.national_id)
                self.initial.setdefault("phone", official.phone)
                self.initial.setdefault("area", official.area_id)
                self.initial.setdefault("position", official.position_id)
                self.initial.setdefault("delegation", official.delegation_id)
                self.initial.setdefault(
                    "authorized_delegations",
                    list(official.authorized_delegations.values_list("pk", flat=True)),
                )
                self.initial.setdefault("roles", list(official.roles.values_list("pk", flat=True)))
                self.initial.setdefault("status", official.status)
            else:
                self.initial.setdefault(
                    "status",
                    Official.Status.ACTIVE if instance.is_active else Official.Status.INACTIVE,
                )
        configure_text_widgets(self)

    def clean_first_name(self):
        return self.clean_person_field("first_name")

    def clean_last_name(self):
        return self.clean_person_field("last_name")

    def clean_username(self):
        username = (self.cleaned_data.get("username") or "").strip()
        duplicates = get_user_model_class().objects.filter(username__iexact=username)
        if self.instance is not None and self.instance.pk:
            duplicates = duplicates.exclude(pk=self.instance.pk)
        if duplicates.exists():
            raise ValidationError("Ya existe una cuenta con este nombre de usuario.")
        return username

    def clean_national_id(self):
        value = (self.cleaned_data.get("national_id") or "").strip()
        return normalize_chilean_rut(value) if value else value

    def clean_full_name(self):
        return self.clean_person_field("full_name")

    def clean(self):
        cleaned = super().clean()
        instance = self.instance
        official = self.official_instance
        if official is not None and self.data.get("account_type") not in (None, "", "OFFICIAL"):
            self.add_error(None, "El tipo de cuenta no puede cambiarse.")
        has_official = official is not None or bool(cleaned.get("has_official"))

        email = cleaned.get("email")
        if email:
            users = get_user_model_class().objects.filter(email__iexact=email)
            officials = Official.objects.filter(email__iexact=email)
            if instance is not None and instance.pk:
                users = users.exclude(pk=instance.pk)
            if official is not None:
                officials = officials.exclude(pk=official.pk)
            if users.exists() or officials.exists():
                self.add_error("email", "Ya existe una cuenta con este correo electrónico.")

        if has_official:
            if not (cleaned.get("full_name") or "").strip():
                self.add_error("full_name", "Ingresa el nombre completo del funcionario/a.")
            national_id = (cleaned.get("national_id") or "").strip()
            if not national_id:
                if "national_id" not in self.errors:
                    self.add_error("national_id", "Ingresa el RUT o RUN chileno.")
            else:
                duplicates = Official.objects.filter(national_id__iexact=national_id)
                if official is not None:
                    duplicates = duplicates.exclude(pk=official.pk)
                if duplicates.exists():
                    self.add_error("national_id", "Ya existe un funcionario con este RUT o RUN.")

        password1 = cleaned.get("password1")
        password2 = cleaned.get("password2")
        creating = instance is None or not instance.pk
        if creating and not password1:
            self.add_error("password1", "Ingresa una contraseña para la nueva cuenta.")
        if password1 or password2:
            if password1 != password2:
                self.add_error("password2", "Las contraseñas no coinciden.")
            elif password1:
                reference = (
                    instance
                    if instance is not None and instance.pk
                    else get_user_model_class()(
                        username=cleaned.get("username"),
                        email=email,
                        first_name=cleaned.get("first_name") or "",
                        last_name=cleaned.get("last_name") or "",
                    )
                )
                try:
                    validate_password(password1, reference)
                except ValidationError as error:
                    self.add_error("password1", error)

        if (
            instance is not None
            and instance.pk
            and self.actor is not None
            and instance.pk == getattr(self.actor, "pk", None)
            and cleaned.get("status")
            and cleaned["status"] != Official.Status.ACTIVE
        ):
            self.add_error("status", "No puedes desactivar tu propia cuenta.")

        if (
            instance is not None
            and instance.pk
            and self.actor is not None
            and instance.pk == getattr(self.actor, "pk", None)
        ):
            protected_changes = []
            if cleaned.get("username") != instance.username:
                protected_changes.append("username")
            if cleaned.get("email") != instance.email:
                protected_changes.append("email")
            if cleaned.get("first_name") != instance.first_name:
                protected_changes.append("first_name")
            if cleaned.get("last_name") != instance.last_name:
                protected_changes.append("last_name")
            if bool(cleaned.get("is_staff")) != bool(instance.is_staff):
                protected_changes.append("is_staff")
            if cleaned.get("password1"):
                protected_changes.append("password1")
            if official is None and cleaned.get("has_official"):
                protected_changes.append("has_official")
            if official is not None:
                if cleaned.get("full_name") != official.full_name:
                    protected_changes.append("full_name")
                if cleaned.get("national_id") != official.national_id:
                    protected_changes.append("national_id")
                if cleaned.get("phone") != official.phone:
                    protected_changes.append("phone")
                if cleaned.get("area") != official.area:
                    protected_changes.append("area")
                if cleaned.get("position") != official.position:
                    protected_changes.append("position")
                if cleaned.get("delegation") != official.delegation:
                    protected_changes.append("delegation")
                if cleaned.get("status") != official.status:
                    protected_changes.append("status")
                if set(self.final_roles(cleaned.get("roles"))) != set(official.roles.all()):
                    protected_changes.append("roles")
                if set(cleaned.get("authorized_delegations") or []) != set(
                    official.authorized_delegations.all()
                ):
                    protected_changes.append("authorized_delegations")
            if protected_changes:
                if "status" in protected_changes and cleaned.get("status") != Official.Status.ACTIVE:
                    self.add_error("status", "No puedes desactivar tu propia cuenta.")
                else:
                    self.add_error(
                        None,
                        "La administración de tu propia cuenta debe realizarse mediante el perfil personal.",
                    )

        if official is not None:
            roles = cleaned.get("roles")
            for field, message in sole_global_administrator_errors(
                official, cleaned.get("status"), None if roles is None else self.final_roles(roles)
            ).items():
                self.add_error(field, message)

        return cleaned

    def clean_authorized_delegations(self):
        delegations = self.cleaned_data.get("authorized_delegations")
        principal = self.cleaned_data.get("delegation")
        if principal is not None and delegations and principal in delegations:
            delegations = delegations.exclude(pk=principal.pk)
        return delegations

    def save(self):
        cleaned = self.cleaned_data
        instance = self.instance
        official = self.official_instance
        has_official = official is not None or bool(cleaned.get("has_official"))
        status = cleaned["status"]

        with transaction.atomic():
            user = instance if instance is not None and instance.pk else get_user_model_class()()
            user.username = cleaned["username"]
            user.first_name = cleaned.get("first_name") or ""
            user.last_name = cleaned.get("last_name") or ""
            user.email = cleaned.get("email") or ""
            user.is_staff = bool(cleaned.get("is_staff"))
            user.is_active = status == Official.Status.ACTIVE
            if cleaned.get("password1"):
                user.set_password(cleaned["password1"])
            user.save()

            if has_official:
                official = official or Official()
                official.user = user
                official.full_name = (cleaned.get("full_name") or "").strip()
                official.national_id = (cleaned.get("national_id") or "").strip()
                official.phone = (cleaned.get("phone") or "").strip()
                official.email = user.email
                official.area = cleaned.get("area")
                official.position = cleaned.get("position")
                official.delegation = cleaned.get("delegation")
                official.status = status
                official.save()
                official.roles.set(self.final_roles(cleaned.get("roles")))
                official.authorized_delegations.set(cleaned.get("authorized_delegations") or [])

            return user


class OfficialForm(RoleAssignmentMixin, AccountTextFieldsMixin, forms.ModelForm):
    """Administra el perfil Official y, opcionalmente, crea su cuenta de acceso."""

    full_name = forms.CharField(
        label="Nombre completo",
        max_length=200,
        widget=forms.TextInput(attrs={"class": "form-control", "maxlength": 200}),
    )
    national_id = forms.CharField(
        label="RUT o RUN chileno",
        max_length=20,
        widget=forms.TextInput(
            attrs={
                "class": "form-control",
                "maxlength": 20,
                "inputmode": "text",
                "data-chilean-rut": "true",
            }
        ),
        help_text="Escribe el RUT o RUN; se validará su dígito verificador.",
    )
    email = forms.EmailField(
        label="Correo electrónico de contacto",
        max_length=191,
        widget=forms.EmailInput(attrs={"class": "form-control", "maxlength": 191}),
    )
    phone = forms.CharField(
        label="Teléfono",
        max_length=30,
        required=False,
        widget=forms.TextInput(attrs={"class": "form-control", "maxlength": 30}),
    )
    area = forms.ModelChoiceField(
        label="Área",
        queryset=Area.objects.none(),
        required=False,
        widget=forms.Select(attrs={"class": "form-select"}),
        empty_label="Sin área",
    )
    position = forms.ModelChoiceField(
        label="Cargo",
        queryset=Position.objects.none(),
        required=False,
        widget=forms.Select(attrs={"class": "form-select"}),
        empty_label="Sin cargo",
    )
    delegation = forms.ModelChoiceField(
        label="Delegación principal",
        queryset=Delegation.objects.none(),
        required=False,
        widget=forms.Select(attrs={"class": "form-select"}),
        empty_label="Sin delegación principal",
    )
    authorized_delegations = forms.ModelMultipleChoiceField(
        label="Delegaciones autorizadas",
        queryset=Delegation.objects.none(),
        required=False,
        widget=forms.CheckboxSelectMultiple(),
        help_text="Selecciona delegaciones adicionales; la principal se excluye automáticamente.",
    )
    roles = RoleMultipleChoiceField(
        label="Roles SGR",
        queryset=Role.objects.none(),
        required=False,
        widget=RoleCheckboxSelectMultiple(),
        help_text="Los roles determinan las acciones y el alcance dentro del SGR.",
    )
    status = forms.ChoiceField(
        label="Estado del funcionario",
        choices=Official.Status.choices,
        widget=forms.Select(attrs={"class": "form-select"}),
    )
    create_account = forms.BooleanField(
        label="Crear también una cuenta de usuario para acceder al SGR",
        required=False,
        widget=forms.CheckboxInput(attrs={"class": "form-check-input"}),
    )
    username = forms.CharField(
        label="Nombre de usuario",
        max_length=150,
        required=False,
        validators=[username_validator],
        widget=forms.TextInput(attrs={"class": "form-control", "maxlength": 150}),
    )
    first_name = forms.CharField(
        label="Nombres para la cuenta",
        max_length=150,
        required=False,
        widget=forms.TextInput(attrs={"class": "form-control", "maxlength": 150}),
    )
    last_name = forms.CharField(
        label="Apellidos para la cuenta",
        max_length=150,
        required=False,
        widget=forms.TextInput(attrs={"class": "form-control", "maxlength": 150}),
    )
    password1 = forms.CharField(
        label="Contraseña inicial",
        required=False,
        strip=False,
        widget=forms.PasswordInput(attrs={"class": "form-control", "autocomplete": "new-password"}),
    )
    password2 = forms.CharField(
        label="Confirmar contraseña inicial",
        required=False,
        strip=False,
        widget=forms.PasswordInput(attrs={"class": "form-control", "autocomplete": "new-password"}),
    )

    class Meta:
        model = Official
        fields = ("full_name", "national_id", "email", "phone", "area", "position",
                  "delegation", "authorized_delegations", "status")

    def __init__(
        self,
        *args,
        actor=None,
        instance=None,
        delegation_queryset=None,
        active_delegation=None,
        **kwargs,
    ):
        super().__init__(*args, instance=instance, **kwargs)
        self.actor = actor
        self.creating_official = not self.instance.pk
        self.fields["status"].initial = Official.Status.ACTIVE
        current_official = getattr(self, "official_instance", instance)
        self.fields["area"].queryset = Area.objects.filter(
            Q(is_active=True, deleted_at__isnull=True) | Q(pk=getattr(current_official, "area_id", None))
        ).order_by("area_name")
        self.fields["position"].queryset = Position.objects.filter(
            Q(is_active=True, deleted_at__isnull=True) | Q(pk=getattr(current_official, "position_id", None))
        ).order_by("position_name")
        self.setup_roles(actor, instance)
        if delegation_queryset is not None:
            self.fields["delegation"].queryset = delegation_queryset
            self.fields["authorized_delegations"].queryset = delegation_queryset
        if active_delegation is not None and (instance is None or not instance.pk):
            self.fields["delegation"].queryset = self.fields["delegation"].queryset.filter(
                pk=active_delegation.pk
            )
            self.initial.setdefault("delegation", active_delegation.pk)

        if instance is not None and instance.pk:
            self.initial.update(
                full_name=instance.full_name,
                national_id=instance.national_id,
                email=instance.email,
                phone=instance.phone,
                area=instance.area_id,
                position=instance.position_id,
                delegation=instance.delegation_id,
                authorized_delegations=list(
                    instance.authorized_delegations.values_list("pk", flat=True)
                ),
                roles=list(instance.roles.values_list("pk", flat=True)),
                status=instance.status,
            )
            self.fields["create_account"].disabled = True
            if instance.user_id:
                self.fields["create_account"].help_text = (
                    f"Este funcionario ya está vinculado a la cuenta «{instance.user.username}»."
                )
        configure_text_widgets(self)

    def clean_national_id(self):
        value = normalize_chilean_rut(self.cleaned_data.get("national_id"))
        duplicates = Official.objects.filter(national_id__iexact=value)
        if self.instance is not None and self.instance.pk:
            duplicates = duplicates.exclude(pk=self.instance.pk)
        if duplicates.exists():
            raise ValidationError("Ya existe un funcionario con este RUT o RUN.")
        return value

    def clean_email(self):
        value = (self.cleaned_data.get("email") or "").strip()
        duplicates = Official.objects.filter(email__iexact=value)
        if self.instance is not None and self.instance.pk:
            duplicates = duplicates.exclude(pk=self.instance.pk)
        if duplicates.exists():
            raise ValidationError("Ya existe un funcionario con este correo electrónico.")
        # Mismo criterio que OfficialUserForm: el correo identifica el ingreso, así que tampoco
        # puede repetirse en otra cuenta de usuario (se excluye la cuenta vinculada al funcionario).
        users = get_user_model_class().objects.filter(email__iexact=value)
        if self.instance is not None and self.instance.user_id:
            users = users.exclude(pk=self.instance.user_id)
        if users.exists():
            raise ValidationError("Este correo ya está asociado a otra cuenta de acceso.")
        return value

    def clean_full_name(self):
        return self.clean_person_field("full_name")

    def clean_first_name(self):
        return self.clean_person_field("first_name")

    def clean_last_name(self):
        return self.clean_person_field("last_name")

    def clean_username(self):
        value = (self.cleaned_data.get("username") or "").strip()
        if value and get_user_model_class().objects.filter(username__iexact=value).exists():
            raise ValidationError("Ya existe una cuenta con este nombre de usuario.")
        return value

    def clean_authorized_delegations(self):
        delegations = self.cleaned_data.get("authorized_delegations")
        principal = self.cleaned_data.get("delegation")
        if principal is not None and delegations:
            return delegations.exclude(pk=principal.pk)
        return delegations

    def clean(self):
        cleaned = super().clean()
        if (
            self.instance is not None
            and self.instance.pk
            and self.instance.user_id
            and self.actor is not None
            and self.instance.user_id == getattr(self.actor, "pk", None)
        ):
            self.add_error(
                None,
                "No puedes administrar tu propio perfil desde el mantenedor de funcionarios.",
            )
        if self.instance is not None and self.instance.pk:
            roles = cleaned.get("roles")
            for field, message in sole_global_administrator_errors(
                self.instance, cleaned.get("status"), None if roles is None else self.final_roles(roles)
            ).items():
                self.add_error(field, message)
        if not cleaned.get("create_account") or (self.instance is not None and self.instance.pk):
            return cleaned
        username = cleaned.get("username")
        password1 = cleaned.get("password1")
        password2 = cleaned.get("password2")
        if not username:
            self.add_error("username", "Ingresa el nombre de usuario de la nueva cuenta.")
        if not password1:
            self.add_error("password1", "Ingresa una contraseña para la nueva cuenta.")
        if password1 or password2:
            if password1 != password2:
                self.add_error("password2", "Las contraseñas no coinciden.")
            elif password1:
                try:
                    validate_password(
                        password1,
                        get_user_model_class()(
                            username=username,
                            email=cleaned.get("email"),
                            first_name=cleaned.get("first_name") or "",
                            last_name=cleaned.get("last_name") or "",
                        ),
                    )
                except ValidationError as error:
                    self.add_error("password1", error)
        return cleaned

    def _save_m2m(self):
        with transaction.atomic():
            official = self.instance
            if self.creating_official and self.cleaned_data.get("create_account") and not official.user_id:
                user = get_user_model_class()(
                    username=self.cleaned_data["username"], email=official.email,
                    first_name=(self.cleaned_data.get("first_name") or "").strip(),
                    last_name=(self.cleaned_data.get("last_name") or "").strip(),
                    is_active=official.status == Official.Status.ACTIVE,
                )
                user.set_password(self.cleaned_data["password1"])
                user.save()
                official.user = user
                official.save(update_fields=["user", "updated_at"])
            super()._save_m2m()
            official.roles.set(self.final_roles(self.cleaned_data.get("roles")))

    def save(self, commit=True):
        with transaction.atomic():
            return super().save(commit=commit)


FULL_NAME_MAX_LENGTH = 200


def profile_snapshot(profile):
    """Valores auditables del perfil propio (funcionario o cliente)."""
    return {"Nombre": profile.full_name, "Correo": profile.email or "—", "Teléfono": profile.phone or "—"}


class OwnOfficialProfileForm(AccountTextFieldsMixin, forms.ModelForm):
    """
    Campos personales permitidos al funcionario sobre su propio perfil (ClientProfileForm lo
    reutiliza para el cliente). Nombres y apellidos se guardan en el User y forman el nombre
    completo del perfil ("nombres apellidos"); el correo también se copia al User, para que
    nombre y correo sean los mismos en la cuenta y en el perfil.
    """

    first_name = forms.CharField(
        label="Nombres",
        max_length=150,
        widget=forms.TextInput(attrs={"class": "form-control", "maxlength": 150, "autocomplete": "given-name"}),
        error_messages={"required": "Ingresa tus nombres."},
    )
    last_name = forms.CharField(
        label="Apellidos",
        max_length=150,
        widget=forms.TextInput(attrs={"class": "form-control", "maxlength": 150, "autocomplete": "family-name"}),
        error_messages={"required": "Ingresa tus apellidos."},
    )
    photo = forms.ImageField(required=False, label="Foto de perfil", widget=forms.FileInput(
        attrs={"accept": "image/jpeg,image/png", "class": "form-control"}))
    photo_crop = forms.CharField(required=False, widget=forms.HiddenInput)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        user = self.instance.user
        self.initial.setdefault("first_name", user.first_name)
        self.initial.setdefault("last_name", user.last_name)
        self.previous_snapshot = profile_snapshot(self.instance)
        self.order_fields(["first_name", "last_name", "email", "phone", "photo", "photo_crop"])
        configure_text_widgets(self)

    def clean_first_name(self):
        return self.clean_person_field("first_name")

    def clean_last_name(self):
        return self.clean_person_field("last_name")

    def full_name(self):
        return f"{self.cleaned_data['first_name']} {self.cleaned_data['last_name']}"

    class Meta:
        model = Official
        fields = ["email", "phone", "photo"]
        widgets = {
            "email": forms.EmailInput(
                attrs={"class": "form-control", "maxlength": 191, "autocomplete": "email"}
            ),
            "phone": forms.TextInput(
                attrs={"class": "form-control", "maxlength": 30, "autocomplete": "tel"}
            ),
        }
        labels = {
            "email": "Correo de contacto",
            "phone": "Teléfono",
        }

    def clean_email(self):
        value = (self.cleaned_data.get("email") or "").strip()
        duplicates = Official.objects.filter(email__iexact=value).exclude(pk=self.instance.pk)
        if duplicates.exists():
            raise ValidationError("Ya existe otro funcionario con este correo de contacto.")
        user_duplicates = get_user_model_class().objects.filter(
            email__iexact=value
        ).exclude(pk=self.instance.user_id)
        if user_duplicates.exists():
            raise ValidationError("Este correo ya está asociado a otra cuenta de acceso.")
        return value

    def clean_photo(self):
        photo = self.cleaned_data.get("photo")
        if self.files.get("photo"):
            if photo.size > 2 * 1024 * 1024:
                raise ValidationError("La imagen no puede superar los 2 MiB.")
            if photo.image.format not in ("JPEG", "PNG"):
                raise ValidationError("Selecciona una imagen JPEG o PNG válida.")
        return photo

    def clean(self):
        data = super().clean()
        if data.get("first_name") and data.get("last_name") and len(self.full_name()) > FULL_NAME_MAX_LENGTH and not (
            self.keeps_original_text("first_name") and self.keeps_original_text("last_name")
        ):
            self.add_error(
                "last_name",
                f"Nombres y apellidos no pueden superar en total los {FULL_NAME_MAX_LENGTH} caracteres.",
            )
        if not self.files.get("photo") or "photo" not in data:
            return data
        import json
        import warnings
        from io import BytesIO
        from PIL import Image, ImageOps
        from django.core.files.uploadedfile import SimpleUploadedFile
        try:
            rect = json.loads(data.get("photo_crop") or "null")
            values = [rect[key] for key in ("x", "y", "width", "height")]
            if any(type(value) is not int for value in values):
                raise ValueError
            x, y, width, height = values
            with warnings.catch_warnings():
                warnings.simplefilter("error", Image.DecompressionBombWarning)
                data["photo"].seek(0)
                with Image.open(data["photo"]) as original:
                    image = ImageOps.exif_transpose(original)
                    if (x < 0 or y < 0 or width < 1 or height < 1 or width != height or
                            x + width > image.width or y + height > image.height):
                        raise ValueError
                    # Almacenar el recorte real, sin los metadatos del archivo original.
                    image = image.crop((x, y, x + width, y + height)).convert("RGBA")
                    background = Image.new("RGB", image.size, "white")
                    background.paste(image, mask=image.getchannel("A"))
                    image = background
                    image.thumbnail((512, 512))
                    output = BytesIO()
                    image.save(output, format="JPEG", quality=90)
            data["photo"] = SimpleUploadedFile("perfil.jpg", output.getvalue(), content_type="image/jpeg")
        except (ValueError, TypeError, KeyError, OSError,
                Image.DecompressionBombError, Image.DecompressionBombWarning):
            self.add_error("photo", "Selecciona una imagen válida y confirma un recorte dentro de sus límites.")
        return data

    def save(self, commit=True):
        profile = super().save(commit=False)
        full_name = self.full_name()
        if len(full_name) <= FULL_NAME_MAX_LENGTH:
            profile.full_name = full_name
        if commit:
            with transaction.atomic():
                profile.save(update_fields=["full_name", "email", "phone", "photo", "updated_at"])
                user = profile.user
                user.first_name = self.cleaned_data["first_name"]
                user.last_name = self.cleaned_data["last_name"]
                user.email = profile.email
                user.save(update_fields=["first_name", "last_name", "email"])
        return profile
