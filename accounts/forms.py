from django import forms
from django.contrib.auth.forms import AuthenticationForm
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Q

from accounts.models import Area, Delegation, Official, Position, Role

GENERIC_LOGIN_ERROR = "Usuario, correo o contraseña incorrectos."

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


class RecoveryCodeForm(forms.Form):
    code = forms.RegexField(
        regex=r"^\d{6}$",
        error_messages={
            "required": "Ingresa los seis dígitos para continuar.",
            "invalid": "Ingresa los seis dígitos para continuar.",
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

    role = sole_global_administrator_role(official)
    if role is None:
        return {}
    errors = {}
    if status and status != Official.Status.ACTIVE:
        errors["status"] = sole_global_administrator_message(official, role, "desactivar ni suspender a")
    if roles is not None and role not in roles:
        errors["roles"] = sole_global_administrator_message(official, role, f"quitar el rol {role.role_name} a")
    return errors


def can_assign_privileged_roles(actor):
    """Asignar o quitar roles privilegiados exige accounts.change_role, igual que en Roles."""
    return actor is None or actor.is_superuser or actor.has_perm("accounts.change_role")


def is_privileged_role(role):
    return role.permissions.filter(privileged_permission_query()).exists()


class RoleAssignmentMixin:
    """
    Reglas de asignación de roles comunes a OfficialUserForm y OfficialForm.

    - Solo se ofrecen roles vigentes; los inactivos ya asignados se conservan (kept_roles).
    - Sin accounts.change_role, los roles privilegiados se muestran bloqueados: los que el
      funcionario ya tiene se conservan (locked_roles) y pedir uno nuevo queda en
      denied_privileged_roles para que la vista responda 403 con auditoría.
    - El Administrador global no se combina con otros roles vigentes.
    """

    def setup_roles(self, actor, official):
        field = self.fields["roles"]
        field.queryset = Role.objects.filter(is_active=True, deleted_at__isnull=True).order_by("role_name")
        self.kept_roles = assigned_roles_not_offered(official, field.queryset)
        self.locked_roles = []
        self.denied_privileged_roles = []
        if can_assign_privileged_roles(actor):
            return
        field.widget.locked_ids = frozenset(role.pk for role in field.queryset if is_privileged_role(role))
        if official is not None and official.pk:
            self.locked_roles = list(official.roles.filter(pk__in=field.widget.locked_ids))
        field.widget.kept_ids = frozenset(role.pk for role in self.locked_roles)
        field.help_text += (
            " Los roles privilegiados aparecen bloqueados: asignarlos o quitarlos requiere el permiso"
            " para administrar roles."
        )

    def final_roles(self, roles):
        """Roles que quedarán asignados: los elegidos más los conservados, sin repetir."""
        merged = {role.pk: role for role in [*(roles or []), *self.locked_roles, *self.kept_roles]}
        return list(merged.values())

    def clean_roles(self):
        roles = self.cleaned_data.get("roles")
        selected = list(roles or [])
        assigned_ids = {role.pk for role in self.locked_roles}
        self.denied_privileged_roles = [
            role
            for role in selected
            if role.pk in self.fields["roles"].widget.locked_ids and role.pk not in assigned_ids
        ]
        current = {role.pk: role for role in [*selected, *self.locked_roles]}.values()
        if len(current) > 1 and any(role.scope == Role.Scope.ALL and is_privileged_role(role) for role in current):
            raise ValidationError("El rol Administrador global no puede combinarse con otros roles.")
        return roles


class DelegationForm(forms.ModelForm):
    """Alta y edición de delegaciones. El código se genera automáticamente."""

    class Meta:
        model = Delegation
        fields = ["delegation_name", "address", "commune", "status"]
        widgets = {
            "delegation_name": forms.TextInput(
                attrs={"class": "form-control", "maxlength": 150, "autocomplete": "off"}
            ),
            "address": forms.TextInput(
                attrs={"class": "form-control", "maxlength": 255, "autocomplete": "off"}
            ),
            "commune": forms.TextInput(
                attrs={"class": "form-control", "maxlength": 100, "autocomplete": "off"}
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

    def clean_delegation_name(self):
        name = (self.cleaned_data.get("delegation_name") or "").strip()
        duplicates = Delegation.objects.filter(delegation_name__iexact=name)
        if self.instance.pk:
            duplicates = duplicates.exclude(pk=self.instance.pk)
        if duplicates.exists():
            raise ValidationError("Ya existe una delegación con este nombre.")
        return name

    def clean_address(self):
        return (self.cleaned_data.get("address") or "").strip()

    def clean_commune(self):
        return (self.cleaned_data.get("commune") or "").strip()


class OfficialUserForm(RoleAssignmentMixin, forms.Form):
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
        widget=forms.PasswordInput(attrs={"class": "form-control", "autocomplete": "new-password"}),
        help_text="Al editar, deja el campo vacío para conservar la contraseña actual.",
    )
    password2 = forms.CharField(
        label="Confirmar contraseña",
        required=False,
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
        label="RUT / identificador",
        max_length=20,
        required=False,
        widget=forms.TextInput(attrs={"class": "form-control", "maxlength": 20}),
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
        self.fields["area"].queryset = Area.objects.order_by("area_name")
        self.fields["position"].queryset = Position.objects.order_by("position_name")

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

    def clean_username(self):
        username = (self.cleaned_data.get("username") or "").strip()
        duplicates = get_user_model_class().objects.filter(username__iexact=username)
        if self.instance is not None and self.instance.pk:
            duplicates = duplicates.exclude(pk=self.instance.pk)
        if duplicates.exists():
            raise ValidationError("Ya existe una cuenta con este nombre de usuario.")
        return username

    def clean(self):
        cleaned = super().clean()
        instance = self.instance
        official = self.official_instance
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
                self.add_error("national_id", "Ingresa el RUT o identificador.")
            else:
                duplicates = Official.objects.filter(national_id__iexact=national_id)
                if official is not None:
                    duplicates = duplicates.exclude(pk=official.pk)
                if duplicates.exists():
                    self.add_error("national_id", "Ya existe un funcionario con este RUT o identificador.")

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


class OfficialForm(RoleAssignmentMixin, forms.Form):
    """Administra el perfil Official y, opcionalmente, crea su cuenta de acceso."""

    full_name = forms.CharField(
        label="Nombre completo",
        max_length=200,
        widget=forms.TextInput(attrs={"class": "form-control", "maxlength": 200}),
    )
    national_id = forms.CharField(
        label="RUT / identificador",
        max_length=20,
        widget=forms.TextInput(attrs={"class": "form-control", "maxlength": 20}),
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
        widget=forms.PasswordInput(attrs={"class": "form-control", "autocomplete": "new-password"}),
    )
    password2 = forms.CharField(
        label="Confirmar contraseña inicial",
        required=False,
        widget=forms.PasswordInput(attrs={"class": "form-control", "autocomplete": "new-password"}),
    )

    def __init__(
        self,
        *args,
        actor=None,
        instance=None,
        delegation_queryset=None,
        active_delegation=None,
        existing_usernames=None,
        **kwargs,
    ):
        super().__init__(*args, **kwargs)
        self.actor = actor
        self.instance = instance
        self.existing_usernames = set(existing_usernames or [])
        self.fields["status"].initial = Official.Status.ACTIVE
        self.fields["area"].queryset = Area.objects.order_by("area_name")
        self.fields["position"].queryset = Position.objects.order_by("position_name")
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

    def clean_national_id(self):
        value = (self.cleaned_data.get("national_id") or "").strip()
        duplicates = Official.objects.filter(national_id__iexact=value)
        if self.instance is not None and self.instance.pk:
            duplicates = duplicates.exclude(pk=self.instance.pk)
        if duplicates.exists():
            raise ValidationError("Ya existe un funcionario con este RUT o identificador.")
        return value

    def clean_email(self):
        value = (self.cleaned_data.get("email") or "").strip()
        duplicates = Official.objects.filter(email__iexact=value)
        if self.instance is not None and self.instance.pk:
            duplicates = duplicates.exclude(pk=self.instance.pk)
        if duplicates.exists():
            raise ValidationError("Ya existe un funcionario con este correo electrónico.")
        return value

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

    def save(self):
        cleaned = self.cleaned_data
        with transaction.atomic():
            official = self.instance or Official()
            official.full_name = cleaned["full_name"].strip()
            official.national_id = cleaned["national_id"]
            official.email = cleaned["email"]
            official.phone = (cleaned.get("phone") or "").strip()
            official.area = cleaned.get("area")
            official.position = cleaned.get("position")
            official.delegation = cleaned.get("delegation")
            official.status = cleaned["status"]

            if (
                not official.pk
                and cleaned.get("create_account")
            ):
                user = get_user_model_class()(
                    username=cleaned["username"],
                    email=official.email,
                    first_name=(cleaned.get("first_name") or "").strip(),
                    last_name=(cleaned.get("last_name") or "").strip(),
                    is_active=official.status == Official.Status.ACTIVE,
                )
                user.set_password(cleaned["password1"])
                user.save()
                official.user = user
            official.save()
            official.roles.set(self.final_roles(cleaned.get("roles")))
            official.authorized_delegations.set(cleaned.get("authorized_delegations") or [])
            return official


class OwnOfficialProfileForm(forms.ModelForm):
    """Campos personales permitidos al funcionario sobre su propio perfil."""

    class Meta:
        model = Official
        fields = ["email", "phone"]
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

    def save(self, commit=True):
        official = super().save(commit=False)
        if commit:
            official.save(update_fields=["email", "phone", "updated_at"])
        return official
