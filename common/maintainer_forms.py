from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.core.exceptions import ValidationError
from django.db.models import Q
from django.urls import reverse
from accounts.models import Area, Function, Position, GroupProfile, Role, Official, Territory, Delegation
from accounts.role_forms import (
    PermissionCheckboxSelectMultiple, PermissionMultipleChoiceField,
    assignable_permissions, can_grant_privileged_permissions, group_permissions,
)
from accounts.forms import privileged_permission_query
from common.text import normalize_spaces, clean_description_text
from common.field_validation import LimitedTextFieldsMixin, clean_catalog_name, configure_text_widgets
from common.scopes import scope_officials
from configuration.models import Period, Item
from activities.models import Activity
from analytics.measurement import eligible_items


class MaintainerForm(LimitedTextFieldsMixin, forms.ModelForm):
    name_field = None

    def __init__(self, *args, actor=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.actor = actor
        configure_text_widgets(self)
        if self.instance.pk and "is_active" in self.fields:
            self.fields.pop("is_active")
        for field in self.fields.values():
            if isinstance(field, forms.BooleanField):
                field.widget = forms.Select(choices=((True, "Vigente"), (False, "No vigente")))
            field.widget.attrs["class"] = "form-select" if isinstance(field.widget, forms.Select) else "form-control"
            if isinstance(field.widget, forms.Textarea):
                field.widget.attrs.setdefault("maxlength", 500)
                field.widget.attrs["rows"] = 3
            if isinstance(field, forms.DateField):
                field.widget = forms.DateInput(format="%Y-%m-%d", attrs={"type": "date", "class": "form-control"})

    def clean(self):
        data = super().clean()
        if self.name_field and data.get(self.name_field):
            try:
                name = clean_catalog_name(data[self.name_field])
            except ValidationError as error:
                self.add_error(self.name_field, error)
                return data
            data[self.name_field] = name
            for pk, existing in self._meta.model.objects.exclude(pk=self.instance.pk).values_list("pk", self.name_field):
                if normalize_spaces(existing).casefold() == name.casefold():
                    self.add_error(self.name_field, "Ya existe un registro con este nombre.")
                    break
        for field in ("description", "action_description"):
            if field in data:
                try:
                    data[field] = clean_description_text(data[field])
                except ValidationError as error:
                    self.add_error(field, error)
        return data


class PositionForm(MaintainerForm):
    text_limits = {"position_name": 50, "description": 200}

    name_field = "position_name"
    class Meta:
        model = Position
        fields = ("position_name", "description", "is_active")


class FunctionForm(MaintainerForm):
    name_field = "function_name"
    text_limits = {"function_name": 100, "description": 200}

    class Meta:
        model = Function
        fields = ("function_name", "description", "positions", "is_active")
        widgets = {"positions": forms.CheckboxSelectMultiple}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        existing = self.instance.positions.all() if self.instance.pk else Position.objects.none()
        self.fields["positions"].queryset = Position.objects.filter(
            Q(is_active=True, deleted_at__isnull=True) | Q(pk__in=existing),
        )
        self.fields["positions"].widget.attrs["class"] = "form-check-input"


class TerritoryForm(MaintainerForm):
    text_limits = {"territory_name": 50, "description": 200}

    class Meta:
        model = Territory
        fields = ("territory_name", "delegation", "description", "is_active")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from accounts.views import scoped_delegations
        self.fields["delegation"].queryset = scoped_delegations(self.actor).filter(status="ACTIVE", deleted_at__isnull=True)

    def clean_territory_name(self):
        return clean_catalog_name(self.cleaned_data["territory_name"])

    def clean(self):
        data = super().clean()
        if data.get("territory_name") and data.get("delegation"):
            if Territory.objects.filter(delegation=data["delegation"],
                    name_key=data["territory_name"].casefold()).exclude(pk=self.instance.pk).exists():
                self.add_error("territory_name", "Ya existe un territorio con este nombre en la delegación.")
        return data


class AreaForm(MaintainerForm):
    text_limits = {"area_name": 50}

    name_field = "area_name"
    class Meta:
        model = Area
        fields = ("area_name", "is_active")


class PeriodForm(MaintainerForm):
    def clean(self):
        data = super().clean()
        if self.instance.pk and data.get("start_date") and data.get("end_date"):
            from activities.models import SocialAttention
            original = Period.objects.get(pk=self.instance.pk)
            dates_changed = (original.start_date, original.end_date) != (data["start_date"], data["end_date"])
            if dates_changed and (original.first_closed_at or original.measurement_plans.filter(
                versions__published_at__isnull=False,
            ).exists()):
                self.add_error(None, "Las fechas quedan fijas desde la primera publicación o el primer cierre.")
                return data
            for model in (Activity, SocialAttention):
                stranded = model.objects.filter(date__gte=original.start_date, date__lte=original.end_date).exclude(
                    date__gte=data["start_date"], date__lte=data["end_date"])
                if stranded.exists():
                    self.add_error(None, "No puedes dejar registros existentes fuera del período.")
                    break
        return data

    class Meta:
        model = Period
        fields = ("start_date", "end_date")


class ActivityForm(MaintainerForm):
    text_limits = {"action_description": 200}

    class Meta:
        model = Activity
        fields = ("official", "item", "date", "record_type", "action_description")

    def __init__(self, *args, actor=None, **kwargs):
        super().__init__(*args, actor=actor, **kwargs)
        perm = "activities.change_activity" if self.instance.pk else "activities.add_activity"
        self.fields["official"].queryset = scope_officials(
            Official.objects.filter(status=Official.Status.ACTIVE, deleted_at__isnull=True), actor, perm)
        official_id = self.data.get(self.add_prefix("official")) if self.is_bound else self.instance.official_id
        try:
            official_id = int(official_id)
            official = self.fields["official"].queryset.filter(pk=official_id).first() if 0 < official_id < 2**63 else None
        except (ValueError, TypeError):
            official = None
        raw_date = self.data.get(self.add_prefix("date"), "") if self.is_bound else self.instance.date
        try:
            date = self.fields["date"].clean(raw_date)
        except ValidationError:
            date = None
        self.fields["item"].queryset = activity_item_choices(official, date, self.instance)
        self.fields["item"].error_messages["invalid_choice"] = "Elige un ítem disponible para el funcionario y la fecha."
        self.fields["item"].widget.attrs["data-eligible-items"] = reverse("activity_eligible_items")
        if self.instance.pk:
            self.fields["item"].widget.attrs["data-activity-id"] = self.instance.pk
        self.fields["record_type"].choices = Activity.RecordType.choices[:2]

    def clean(self):
        data = super().clean()
        official, date, item = (data.get(field) for field in ("official", "date", "item"))
        if official and date and item and not activity_item_choices(official, date, self.instance).filter(pk=item.pk).exists():
            self.add_error("item", self.fields["item"].error_messages["invalid_choice"])
        return data

    def save(self, commit=True):
        previous_official = self.initial.get("official")
        if previous_official != self.instance.official_id:
            self.instance.registration_position_id = self.instance.official.position_id
            self.instance.registration_position_captured = True
        return super().save(commit=commit)


def activity_item_choices(official, date, activity):
    same_official = official is not None and official.pk == activity.official_id
    position_id = official.position_id if official else None
    if same_official and activity.registration_position_captured:
        position_id = activity.registration_position_id
    items = eligible_items(position_id, date)
    if activity.pk and same_official and date == activity.date:
        items = Item.objects.filter(Q(pk__in=items.values("pk")) | Q(pk=activity.item_id))
    return items


def protect_last_group_administrator(group, scope, permissions, members, is_active):
    from accounts.role_forms import last_global_administrator
    if not group.pk or last_global_administrator() is not None:
        return
    profile = getattr(group, "sgr_profile", None)
    if not profile or not profile.is_active or profile.scope != Role.Scope.ALL:
        return
    eligible = dict(is_active=True, official__status=Official.Status.ACTIVE, official__deleted_at__isnull=True)
    if not group.permissions.filter(privileged_permission_query()).exists() or not group.user_set.filter(**eligible).exists():
        return
    other = Group.objects.exclude(pk=group.pk).filter(sgr_profile__is_active=True,
        sgr_profile__deleted_at__isnull=True, sgr_profile__scope=Role.Scope.ALL,
        user__is_active=True, user__official__status=Official.Status.ACTIVE, user__official__deleted_at__isnull=True)
    if any(g.permissions.filter(privileged_permission_query()).exists() for g in other):
        return
    if not (is_active and scope == Role.Scope.ALL and permissions.filter(privileged_permission_query()).exists()
            and members.filter(**eligible).exists()):
        raise ValidationError("El sistema no puede quedar sin un grupo o rol administrador global con miembros activos.")


class GroupForm(MaintainerForm):
    text_limits = {"name": 50, "description": 200}

    name_field = "name"
    description = forms.CharField(label="Descripción", required=False, widget=forms.Textarea)
    scope = forms.ChoiceField(label="Alcance", choices=Role.Scope.choices)
    is_active = forms.BooleanField(label="Vigente", required=False, initial=True)
    permissions = PermissionMultipleChoiceField(
        label="Permisos", queryset=Permission.objects.none(), required=False,
        widget=PermissionCheckboxSelectMultiple(),
    )
    members = forms.ModelMultipleChoiceField(
        label="Miembros", queryset=get_user_model().objects.none(), required=False,
        widget=forms.CheckboxSelectMultiple,
    )

    class Meta:
        model = Group
        fields = ("name", "permissions")

    def __init__(self, *args, actor=None, **kwargs):
        super().__init__(*args, actor=actor, **kwargs)
        field = self.fields["permissions"]
        field.queryset = assignable_permissions()
        privileged_ids = frozenset(Permission.objects.filter(
            privileged_permission_query(for_assignment=True),
        ).values_list("pk", flat=True))
        field.privileged_ids = field.widget.privileged_ids = privileged_ids
        self.privileged_locked = not can_grant_privileged_permissions(actor)
        field.widget.lock_privileged = self.privileged_locked
        field.widget.attrs.pop("class", None)
        perm = "auth.change_group" if self.instance.pk else "auth.add_group"
        officials = scope_officials(Official.objects.filter(deleted_at__isnull=True), actor, perm)
        members = self.fields["members"]
        members.widget.attrs["class"] = "form-check-input"
        members.queryset = get_user_model().objects.filter(official__in=officials).select_related("official").order_by("username")
        members.label_from_instance = lambda user: f"{user.official.full_name} ({user.username})"
        self.kept_permissions = Permission.objects.none()
        if self.instance.pk:
            profile = getattr(self.instance, "sgr_profile", None)
            if profile:
                self.initial.update(description=profile.description, scope=profile.scope)
            self.initial["members"] = self.instance.user_set.filter(pk__in=self.fields["members"].queryset)
            kept_ids = list(self.instance.permissions.exclude(pk__in=field.queryset).values_list("pk", flat=True))
            self.kept_permissions = Permission.objects.filter(pk__in=kept_ids)
        configure_text_widgets(self)

    def permission_groups(self):
        return group_permissions(self["permissions"], lambda checkbox: checkbox.data["value"].instance)

    def clean(self):
        data = super().clean()
        permissions = data.get("permissions")
        members = data.get("members")
        if self.privileged_locked and (
            (permissions is not None and permissions.filter(privileged_permission_query(for_assignment=True)).exists())
            or (self.instance.pk and self.instance.permissions.filter(privileged_permission_query(for_assignment=True)).exists())
        ):
            self.add_error("permissions", "Se requiere administrar Roles para modificar un grupo con permisos privilegiados.")
        if not self.actor.is_superuser:
            from common.scopes import permission_scope
            actor_scope = permission_scope(self.actor, "auth.change_group" if self.instance.pk else "auth.add_group")
            rank = {None: -1, Role.Scope.OWN: 0, Role.Scope.DELEGATION: 1, Role.Scope.ALL: 2}
            if rank.get(data.get("scope"), -1) > rank[actor_scope]:
                self.add_error("scope", "No puedes otorgar un alcance superior al autorizado para administrar grupos.")
            if (self.instance.pk and self.instance.user_set.filter(pk=self.actor.pk).exists()) or (members is not None and members.filter(pk=self.actor.pk).exists()):
                self.add_error(None, "No puedes administrar tu propia pertenencia ni los permisos de tu grupo.")
        if self.instance.pk and permissions is not None and members is not None:
            hidden_members = self.instance.user_set.exclude(pk__in=self.fields["members"].queryset)
            final_members = get_user_model().objects.filter(Q(pk__in=hidden_members) | Q(pk__in=members))
            try:
                protect_last_group_administrator(self.instance, data.get("scope"), permissions | self.kept_permissions, final_members,
                    getattr(getattr(self.instance, "sgr_profile", None), "is_active", True))
            except ValidationError as error:
                self.add_error(None, error)
        return data

    def save(self, commit=True):
        group = super().save(commit=commit)
        if commit:
            group.permissions.add(*self.kept_permissions)
            GroupProfile.objects.update_or_create(group=group, defaults={
                "description": self.cleaned_data["description"], "scope": self.cleaned_data["scope"],
                **({"is_active": self.cleaned_data["is_active"]} if "is_active" in self.fields else {})})
            allowed = self.fields["members"].queryset
            group.user_set.remove(*group.user_set.filter(pk__in=allowed).exclude(pk__in=self.cleaned_data["members"]))
            group.user_set.add(*self.cleaned_data["members"])
        return group
