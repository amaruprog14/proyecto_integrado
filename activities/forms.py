import re

from django import forms
from django.core.exceptions import ValidationError

from accounts.models import Delegation, ServiceRecipient
from common.chilean_rut import normalize_chilean_rut
from common.text import clean_description_text, normalize_spaces
from configuration.models import AttentionType, SubattentionType


DESCRIPTION_MAX_LENGTH = 5000


class CatalogChoiceField(forms.ModelChoiceField):
    def label_from_instance(self, obj):
        return f"{obj.code} · {obj.name}"


class SubattentionSelect(forms.Select):
    def create_option(self, name, value, label, selected, index, subindex=None, attrs=None):
        option = super().create_option(
            name, value, label, selected, index, subindex=subindex, attrs=attrs
        )
        instance = getattr(value, "instance", None)
        if instance is not None:
            option["attrs"]["data-attention-type"] = str(instance.attention_type_id)
        return option


class SocialAttentionForm(forms.Form):
    recipient_national_id = forms.CharField(
        label="RUT o RUN chileno",
        max_length=20,
        widget=forms.TextInput(
            attrs={
                "class": "form-control",
                "autocomplete": "off",
                "inputmode": "text",
                "data-chilean-rut": "true",
            }
        ),
    )
    recipient_full_name = forms.CharField(
        label="Nombre completo del solicitante",
        max_length=200,
        required=False,
        widget=forms.TextInput(
            attrs={"class": "form-control", "autocomplete": "name"}
        ),
    )
    delegation = forms.ModelChoiceField(
        label="Delegación de atención",
        queryset=Delegation.objects.none(),
        widget=forms.Select(attrs={"class": "form-select"}),
    )
    attention_type = CatalogChoiceField(
        label="Tipo de Atención",
        queryset=AttentionType.objects.none(),
        widget=forms.Select(attrs={"class": "form-select"}),
    )
    subattention_type = CatalogChoiceField(
        label="Sub Atención",
        queryset=SubattentionType.objects.none(),
        widget=SubattentionSelect(attrs={"class": "form-select"}),
    )
    # Token de un solo uso que emite la vista al abrir el formulario (ver SocialAttention).
    submission_token = forms.CharField(required=False, max_length=32, widget=forms.HiddenInput)
    # Sin max_length en el campo: Django contaría cada salto "\r\n" como 2 caracteres y
    # rechazaría textos que el maxlength del navegador acepta. El límite lo aplica clean_description.
    description = forms.CharField(
        label="Descripción de la atención",
        widget=forms.Textarea(
            attrs={
                "class": "form-control",
                "rows": 3,
                "maxlength": DESCRIPTION_MAX_LENGTH,
                "placeholder": "Describa la solicitud y los antecedentes necesarios.",
            }
        ),
    )

    def __init__(self, *args, official=None, active_delegation=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.official = official
        self.recipient_record = None

        if official is not None and official.is_enabled:
            delegations = official.get_authorized_delegations().filter(
                deleted_at__isnull=True
            )
            if active_delegation is not None:
                delegations = delegations.filter(pk=active_delegation.pk)
            self.fields["delegation"].queryset = delegations
            if active_delegation is not None and delegations.filter(
                pk=active_delegation.pk
            ).exists():
                self.fields["delegation"].initial = active_delegation.pk
            elif official.delegation_id and delegations.filter(pk=official.delegation_id).exists():
                self.fields["delegation"].initial = official.delegation_id
            elif delegations.count() == 1:
                self.fields["delegation"].initial = delegations.get().pk

        self.fields["attention_type"].queryset = AttentionType.objects.filter(
            is_active=True, deleted_at__isnull=True
        ).order_by("name")
        self.fields["subattention_type"].queryset = (
            SubattentionType.objects.filter(
                is_active=True,
                deleted_at__isnull=True,
                attention_type__is_active=True,
                attention_type__deleted_at__isnull=True,
            )
            .select_related("attention_type")
            .order_by("attention_type__name", "name")
        )

    def clean_submission_token(self):
        """Un token con otro formato se ignora: la atención se guarda sin control de doble envío."""
        token = (self.cleaned_data.get("submission_token") or "").strip().lower()
        return token if re.fullmatch(r"[0-9a-f]{32}", token) else ""

    def clean_recipient_national_id(self):
        return normalize_chilean_rut(self.cleaned_data["recipient_national_id"])

    def clean_recipient_full_name(self):
        return normalize_spaces(self.cleaned_data.get("recipient_full_name"))

    def clean_description(self):
        return clean_description_text(self.cleaned_data.get("description"), DESCRIPTION_MAX_LENGTH)

    def clean(self):
        cleaned_data = super().clean()
        national_id = cleaned_data.get("recipient_national_id")
        full_name = cleaned_data.get("recipient_full_name")
        attention_type = cleaned_data.get("attention_type")
        subattention_type = cleaned_data.get("subattention_type")

        if national_id:
            recipient = ServiceRecipient.objects.filter(
                national_id__iexact=national_id
            ).first()
            if recipient is not None:
                if recipient.deleted_at is not None:
                    self.add_error(
                        "recipient_national_id",
                        "Este RUT pertenece a una persona archivada; solicita su revisión antes de registrar otra atención.",
                    )
                elif recipient.status != ServiceRecipient.Status.ACTIVE:
                    self.add_error(
                        "recipient_national_id",
                        "La persona asociada a este RUT está inactiva.",
                    )
                elif full_name and normalize_spaces(recipient.full_name).casefold() != full_name.casefold():
                    self.add_error(
                        "recipient_full_name",
                        "El RUT ya está asociado a otro nombre. Verifica los datos de la persona.",
                    )
                else:
                    self.recipient_record = recipient
                    cleaned_data["recipient_full_name"] = recipient.full_name
            elif not full_name:
                self.add_error(
                    "recipient_full_name",
                    "Ingresa el nombre completo para registrar a una persona con este RUT.",
                )

        if (
            attention_type is not None
            and subattention_type is not None
            and subattention_type.attention_type_id != attention_type.pk
        ):
            self.add_error(
                "subattention_type",
                "Selecciona una Sub Atención asociada al Tipo de Atención elegido.",
            )

        return cleaned_data

    def get_or_create_recipient(self):
        if self.recipient_record is not None:
            return self.recipient_record
        recipient, _ = ServiceRecipient.objects.get_or_create(
            national_id=self.cleaned_data["recipient_national_id"],
            defaults={
                "full_name": self.cleaned_data["recipient_full_name"],
                "status": ServiceRecipient.Status.ACTIVE,
            },
        )
        if recipient.status != ServiceRecipient.Status.ACTIVE or recipient.deleted_at is not None:
            raise ValidationError(
                {
                    "recipient_national_id": (
                        "La persona asociada a este RUT no está activa."
                    )
                }
            )
        return recipient
