from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.exceptions import ValidationError
from django.db.models import Q
from accounts.models import Area, Position, GroupProfile, Role, Official
from accounts.role_forms import assignable_permissions, can_grant_privileged_permissions
from accounts.forms import privileged_permission_query
from common.text import normalize_spaces, clean_description_text
from common.scopes import scope_officials
from configuration.models import Period, Item
from activities.models import Activity


class MaintainerForm(forms.ModelForm):
    name_field = None

    def __init__(self, *args, actor=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.actor = actor
        if self.instance.pk and "is_active" in self.fields:
            self.fields.pop("is_active")
        for field in self.fields.values():
            if isinstance(field, forms.BooleanField):
                field.widget = forms.Select(choices=((True, "Vigente"), (False, "No vigente")))
            field.widget.attrs["class"] = "form-select" if isinstance(field.widget, forms.Select) else "form-control"
            if isinstance(field.widget, forms.Textarea):
                field.widget.attrs.update(rows=3, maxlength=500)
            if isinstance(field, forms.DateField):
                field.widget = forms.DateInput(format="%Y-%m-%d", attrs={"type": "date", "class": "form-control"})

    def clean(self):
        data = super().clean()
        if self.name_field and data.get(self.name_field):
            name = normalize_spaces(data[self.name_field])
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
    name_field = "position_name"
    class Meta:
        model = Position
        fields = ("position_name", "description", "is_active")


class AreaForm(MaintainerForm):
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
    class Meta:
        model = Activity
        fields = ("official", "item", "date", "record_type", "action_description")

    def __init__(self, *args, actor=None, **kwargs):
        super().__init__(*args, actor=actor, **kwargs)
        perm = "activities.change_activity" if self.instance.pk else "activities.add_activity"
        self.fields["official"].queryset = scope_officials(
            Official.objects.filter(status=Official.Status.ACTIVE, deleted_at__isnull=True), actor, perm)
        self.fields["item"].queryset = Item.objects.filter(is_active=True, deleted_at__isnull=True)
        if self.instance.pk:
            self.fields["item"].queryset = Item.objects.filter(
                Q(is_active=True, deleted_at__isnull=True) | Q(pk=self.instance.item_id))
        self.fields["record_type"].choices = Activity.RecordType.choices[:2]


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
    name_field = "name"
    description = forms.CharField(label="Descripción", required=False, widget=forms.Textarea)
    scope = forms.ChoiceField(label="Alcance", choices=Role.Scope.choices)
    is_active = forms.BooleanField(label="Vigente", required=False, initial=True)
    members = forms.ModelMultipleChoiceField(label="Miembros", queryset=get_user_model().objects.none(), required=False)

    class Meta:
        model = Group
        fields = ("name", "permissions")

    def __init__(self, *args, actor=None, **kwargs):
        super().__init__(*args, actor=actor, **kwargs)
        self.fields["permissions"].queryset = assignable_permissions()
        perm = "auth.change_group" if self.instance.pk else "auth.add_group"
        officials = scope_officials(Official.objects.filter(deleted_at__isnull=True), actor, perm)
        self.fields["members"].queryset = get_user_model().objects.filter(official__in=officials)
        if self.instance.pk:
            profile = getattr(self.instance, "sgr_profile", None)
            if profile:
                self.initial.update(description=profile.description, scope=profile.scope)
            self.initial["members"] = self.instance.user_set.filter(pk__in=self.fields["members"].queryset)

    def clean(self):
        data = super().clean()
        permissions = data.get("permissions")
        members = data.get("members")
        if permissions is not None and permissions.filter(privileged_permission_query()).exists():
            if not can_grant_privileged_permissions(self.actor):
                self.add_error("permissions", "Se requiere administrar Roles para otorgar permisos privilegiados.")
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
                protect_last_group_administrator(self.instance, data.get("scope"), permissions, final_members,
                    getattr(getattr(self.instance, "sgr_profile", None), "is_active", True))
            except ValidationError as error:
                self.add_error(None, error)
        return data

    def save(self, commit=True):
        group = super().save(commit=commit)
        if commit:
            GroupProfile.objects.update_or_create(group=group, defaults={
                "description": self.cleaned_data["description"], "scope": self.cleaned_data["scope"],
                **({"is_active": self.cleaned_data["is_active"]} if "is_active" in self.fields else {})})
            allowed = self.fields["members"].queryset
            group.user_set.remove(*group.user_set.filter(pk__in=allowed).exclude(pk__in=self.cleaned_data["members"]))
            group.user_set.add(*self.cleaned_data["members"])
        return group
