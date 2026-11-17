from datetime import date, datetime, time, timedelta

from django import forms
from django.db.models import OuterRef, Q, Subquery
from django.utils import timezone

from common.text import clean_description_text

from .models import AttentionCase, SocialAttention


MILESTONES = ("scheduled_visit_on", "visited_on", "report_delivered_on", "benefit_delivered_on")


def active_attentions(case):
    return case.attentions.filter(deleted_at__isnull=True).order_by("date", "pk")


def with_first_attention_date(cases):
    first_attention = SocialAttention.objects.filter(
        case_id=OuterRef("pk"), deleted_at__isnull=True).order_by("date", "pk")
    return cases.annotate(first_attention_date=Subquery(first_attention.values("date")[:1]))


def entry_date(case, first_attention_date=None):
    if case.client_request_id:
        return timezone.localtime(case.client_request.created_at).date()
    return first_attention_date or timezone.localtime(case.created_at).date()


def entry_date_boundary(day, *, upper=False):
    if upper and day == date.max:
        return Q()
    comparison = "gte"
    if upper:
        day += timedelta(days=1)
        comparison = "lt"
    # Convertir los límites en Django evita depender de las tablas de zonas horarias de MySQL.
    instant = timezone.make_aware(datetime.combine(day, time.min))
    direct = Q(client_request__isnull=True)
    return (Q(**{f"client_request__created_at__{comparison}": instant}) |
            (direct & Q(**{f"first_attention_date__{comparison}": day})) |
            (direct & Q(first_attention_date__isnull=True, **{f"created_at__{comparison}": instant})))


class CaseFollowUpForm(forms.ModelForm):
    requires_visit = forms.NullBooleanField(label="Requiere visita", widget=forms.Select(
        attrs={"class": "form-select"}, choices=(("unknown", "Sin registrar"), ("true", "Sí"), ("false", "No"))))
    observation = forms.CharField(label="Observación interna", required=False, max_length=500,
                                  widget=forms.Textarea(attrs={"class": "form-control", "rows": 3}))

    class Meta:
        model = AttentionCase
        fields = ("requires_visit", *MILESTONES)
        widgets = {field: forms.DateInput(format="%Y-%m-%d", attrs={"type": "date", "class": "form-control"})
                   for field in MILESTONES}

    def __init__(self, *args, case_entry_date, **kwargs):
        super().__init__(*args, **kwargs)
        self.case_entry_date = case_entry_date
        self.initial["requires_visit"] = {None: "unknown", True: "true", False: "false"}[self.instance.requires_visit]

    def clean_observation(self):
        return clean_description_text(self.cleaned_data["observation"])

    def clean(self):
        data = super().clean()
        scheduled = data.get("scheduled_visit_on")
        if scheduled and scheduled < self.case_entry_date:
            self.add_error("scheduled_visit_on", "La visita programada debe ser igual o posterior al ingreso.")
        previous = self.case_entry_date
        for name in MILESTONES[1:]:
            date = data.get(name)
            if date is None:
                continue
            if date < previous:
                self.add_error(name, "La fecha debe ser igual o posterior al ingreso y al hito previo registrado.")
            elif date > timezone.localdate():
                self.add_error(name, "La fecha de un hito realizado no puede quedar en el futuro.")
            else:
                previous = date
        return data


class CaseFollowUpFilters(forms.Form):
    entry_start = forms.DateField(label="Ingreso desde", required=False, widget=forms.DateInput(
        format="%Y-%m-%d", attrs={"type": "date", "class": "form-control"}))
    entry_end = forms.DateField(label="Ingreso hasta", required=False, widget=forms.DateInput(
        format="%Y-%m-%d", attrs={"type": "date", "class": "form-control"}))
    responsible = forms.ModelChoiceField(label="Responsable", queryset=None, required=False,
        empty_label="Todos los responsables", widget=forms.Select(attrs={"class": "form-select"}))
    visit = forms.ChoiceField(label="Requiere visita", required=False,
        choices=(("", "Todos"), ("yes", "Sí"), ("no", "No"), ("unknown", "Sin registrar")),
        widget=forms.Select(attrs={"class": "form-select"}))

    def __init__(self, *args, responsibles, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["responsible"].queryset = responsibles

    def clean(self):
        data = super().clean()
        start, end = data.get("entry_start"), data.get("entry_end")
        if start and end and start > end:
            self.add_error("entry_end", "La fecha hasta debe ser igual o posterior a la fecha desde.")
        return data

    def filter(self, cases):
        data = self.cleaned_data
        if start := data["entry_start"]:
            cases = cases.filter(entry_date_boundary(start))
        if end := data["entry_end"]:
            cases = cases.filter(entry_date_boundary(end, upper=True))
        if responsible := data["responsible"]:
            cases = cases.filter(responsible=responsible)
        if visit := data["visit"]:
            cases = cases.filter(requires_visit={"yes": True, "no": False, "unknown": None}[visit])
        return cases


def case_intervals(case, entered):
    intervals = (
        ("Ingreso a visita programada", entered, case.scheduled_visit_on, 10),
        ("Visita programada a visita realizada", case.scheduled_visit_on, case.visited_on, 0),
        ("Visita a entrega de informe", case.visited_on, case.report_delivered_on, 4),
        ("Informe a entrega de beneficio", case.report_delivered_on, case.benefit_delivered_on, 4),
        ("Ingreso a entrega de beneficio", entered, case.benefit_delivered_on, 20),
    )
    for label, start, end, limit in intervals:
        days = (end - start).days if start and end else None
        reference = f"Hasta {limit} días" if limit else "Sin diferencia (0 días)"
        result = "Sin fechas suficientes"
        if days is not None:
            if limit:
                result = "En plazo" if days <= limit else "Fuera de plazo"
            else:
                result = "Adelantada" if days < 0 else "Atrasada" if days > 0 else "En la fecha programada"
        yield {"label": label, "days": days, "reference": reference, "result": result}
