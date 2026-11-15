from uuid import uuid4

from django import forms
from django.utils import timezone

from accounts.models import Area, Official, Territory
from common.text import clean_description_text

from .commitments import available_responsibles
from .models import Commitment


class CommitmentForm(forms.Form):
    submission_token = forms.UUIDField(widget=forms.HiddenInput, initial=uuid4)
    requester = forms.CharField(label="Solicitante", max_length=200)
    territory_ref = forms.ModelChoiceField(label="Territorio", queryset=Territory.objects.none())
    responsible = forms.ModelChoiceField(label="Funcionario responsable", queryset=Official.objects.none())
    support_area = forms.ModelChoiceField(label="Área de apoyo", queryset=Area.objects.none(), required=False)
    committed_date = forms.DateField(label="Fecha comprometida", widget=forms.DateInput(attrs={"type": "date"}))
    description = forms.CharField(
        label="Descripción del compromiso", max_length=500, widget=forms.Textarea(attrs={"rows": 3}),
    )

    def __init__(self, *args, user, delegation, origin_case=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["territory_ref"].queryset = Territory.objects.filter(
            delegation=delegation, is_active=True, deleted_at__isnull=True,
        )
        self.fields["responsible"].queryset = available_responsibles(user, delegation)
        self.fields["support_area"].queryset = Area.objects.filter(is_active=True, deleted_at__isnull=True)
        if origin_case:
            self.fields["requester"].disabled = True
            self.initial["requester"] = origin_case.recipient.full_name
            territory = origin_case.client_request.territory_id if origin_case.client_request_id else origin_case.recipient.territory_id
            self.initial["territory_ref"] = territory
            self.initial["description"] = origin_case.subject
        self.initial["responsible"] = getattr(getattr(user, "official", None), "pk", None)

    def clean_committed_date(self):
        value = self.cleaned_data["committed_date"]
        if value < timezone.localdate():
            raise forms.ValidationError("La fecha comprometida debe ser hoy o posterior.")
        return value


class CommitmentStatusForm(forms.Form):
    status = forms.ChoiceField(label="Nuevo estado")
    observation = forms.CharField(label="Observación", max_length=500, widget=forms.Textarea(attrs={"rows": 2}))

    def __init__(self, *args, commitment, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["status"].choices = [
            ("", "Selecciona un estado"),
            *((status, label) for status, label in Commitment.Status.choices if status in commitment.next_statuses),
        ]

    def clean_observation(self):
        return clean_description_text(self.cleaned_data["observation"])


class CommitmentAssignForm(forms.Form):
    responsible = forms.ModelChoiceField(label="Nuevo responsable", queryset=Official.objects.none())
    reason = forms.CharField(label="Motivo de la reasignación", max_length=500, widget=forms.Textarea(attrs={"rows": 2}))

    def __init__(self, *args, user, commitment, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["responsible"].queryset = available_responsibles(user, commitment.delegation).exclude(pk=commitment.responsible_id)

    def clean_reason(self):
        return clean_description_text(self.cleaned_data["reason"])
