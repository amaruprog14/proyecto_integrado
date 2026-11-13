from django import forms
from django.core.exceptions import ValidationError
from django.db.models import Q

from accounts.models import Official, Position
from analytics.models import MeasurementAdjustment, MeasurementItem, MeasurementVersion
from common.maintainer_forms import MaintainerForm
from configuration.models import Item


class NewPlanForm(forms.Form):
    position = forms.ModelChoiceField(
        label="Cargo", queryset=Position.objects.none(), widget=forms.Select(attrs={"class": "form-select"}),
    )

    def __init__(self, *args, period, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["position"].queryset = Position.objects.filter(
            is_active=True, deleted_at__isnull=True,
        ).exclude(pk__in=period.measurement_plans.values("position_id"))


class RevisionForm(forms.Form):
    effective_from = forms.DateField(
        label="Vigente desde", widget=forms.DateInput(attrs={"type": "date", "class": "form-control"}),
    )

    def __init__(self, *args, previous, **kwargs):
        super().__init__(*args, **kwargs)
        self.previous = previous

    def clean_effective_from(self):
        date = self.cleaned_data["effective_from"]
        if not self.previous.effective_from < date <= self.previous.plan.period.end_date:
            raise ValidationError("Elige una fecha posterior a la última vigencia y dentro del período.")
        return date


class VersionForm(MaintainerForm):
    class Meta:
        model = MeasurementVersion
        fields = ("effective_from", "max_computable", "amber_threshold", "green_threshold", "collective_threshold")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance.number == 1:
            self.initial["effective_from"] = self.instance.plan.period.start_date
            self.fields["effective_from"].disabled = True

    def clean(self):
        data = super().clean()
        if "amber_threshold" in data and "green_threshold" in data and data["amber_threshold"] >= data["green_threshold"]:
            self.add_error("amber_threshold", "El umbral naranjo debe ser menor que el verde.")
        if self.instance.number > 1 and (date := data.get("effective_from")):
            previous = self.instance.plan.versions.filter(published_at__isnull=False).first()
            if not previous.effective_from < date <= self.instance.plan.period.end_date:
                self.add_error("effective_from", "Elige una fecha posterior a la última vigencia y dentro del período.")
        return data


def check_percentage_goal(form, goal_type):
    goal = form.cleaned_data.get("goal")
    if goal_type == MeasurementItem.GoalType.PERCENTAGE and goal is not None and goal > 100:
        form.add_error("goal", "La meta porcentual debe ser como máximo 100 %.")


class MeasurementItemForm(MaintainerForm):
    class Meta:
        model = MeasurementItem
        fields = ("function", "item", "goal_type", "goal", "weight")

    def __init__(self, *args, version, **kwargs):
        super().__init__(*args, **kwargs)
        position = version.plan.position
        self.fields["function"].queryset = position.functions.filter(
            Q(is_active=True, deleted_at__isnull=True) | Q(pk=self.instance.function_id),
        )
        used = version.items.exclude(pk=self.instance.pk).values("item_id")
        self.fields["item"].queryset = Item.objects.filter(
            Q(is_active=True, deleted_at__isnull=True) | Q(pk=self.instance.item_id),
        ).exclude(pk__in=used)

    def clean(self):
        data = super().clean()
        check_percentage_goal(self, data.get("goal_type"))
        if data.get("goal_type") == MeasurementItem.GoalType.PERCENTAGE and self.instance.pk and self.instance.adjustments.filter(goal__gt=100).exists():
            self.add_error("goal_type", "Corrige las metas individuales que superan el 100 %.")
        return data


class MeasurementAdjustmentForm(MaintainerForm):
    class Meta:
        model = MeasurementAdjustment
        fields = ("official", "goal", "weight")

    def __init__(self, *args, line, **kwargs):
        super().__init__(*args, **kwargs)
        self.line = line
        self.fields["official"].queryset = Official.objects.filter(
            Q(position=line.version.plan.position, status=Official.Status.ACTIVE, deleted_at__isnull=True)
            | Q(pk=self.instance.official_id),
        ).exclude(pk__in=line.adjustments.exclude(pk=self.instance.pk).values("official_id"))
        self.fields["goal"].help_text = "Deja en blanco para usar la meta del cargo."
        self.fields["weight"].help_text = "Deja en blanco para usar el ponderador del cargo."

    def clean(self):
        data = super().clean()
        if data.get("goal") is None and data.get("weight") is None:
            self.add_error(None, "Ingresa una meta individual, un ponderador individual o ambos.")
        check_percentage_goal(self, self.line.goal_type)
        return data
