import re

from django import forms
from django.utils import timezone
from django.core.exceptions import ValidationError

from accounts.forms import clean_person_name
from common.field_validation import configure_text_widgets, text_length
from accounts.models import Delegation, ServiceRecipient
from common.chilean_rut import normalize_chilean_rut
from common.list_state import positive
from common.text import clean_description_text, normalize_spaces
from configuration.models import AttentionType, SubattentionType


DESCRIPTION_MAX_LENGTH = 300


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


def attention_delegations(official, active_delegation):
    if official is None or not official.is_enabled:
        return Delegation.objects.none()
    delegations = official.get_authorized_delegations().filter(deleted_at__isnull=True)
    if active_delegation is not None:
        return delegations.filter(pk=active_delegation.pk)
    return delegations


class SocialAttentionForm(forms.Form):
    text_limits = {"recipient_full_name": 100}
    DIRECT = "direct"
    LINKED = "linked"

    origin = forms.ChoiceField(
        label="Origen de la atención",
        choices=((DIRECT, "Atención directa"), (LINKED, "Vincular a una solicitud ciudadana")),
        initial=DIRECT,
        required=False,
        widget=forms.Select(attrs={"class": "form-select"}),
    )
    client_request = forms.RegexField(
        regex=r"(?i)\ASOL-[0-9]+\Z",
        max_length=23,
        required=False,
        label="Solicitud ciudadana",
        widget=forms.Select(attrs={"class": "form-select"}),
        error_messages={"invalid": "Selecciona una solicitud válida."},
    )
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
    case_subject = forms.CharField(label="Asunto del caso presencial (visible en el portal)", max_length=100, required=False,
        widget=forms.TextInput(attrs={"class": "form-control"}))
    effective_date = forms.DateField(label="Fecha de la gestión", initial=timezone.localdate, required=False,
        widget=forms.DateInput(format="%Y-%m-%d", attrs={"class": "form-control", "type": "date"}))
    result = forms.CharField(label="Resultado de la gestión", max_length=300,
        widget=forms.TextInput(attrs={"class": "form-control"}))
    invite_to_portal = forms.BooleanField(label="La persona desea recibir una invitación al portal", required=False,
        widget=forms.CheckboxInput(attrs={"class": "form-check-input"}))
    invitation_email = forms.EmailField(label="Correo para la invitación", max_length=191, required=False,
        widget=forms.EmailInput(attrs={"class": "form-control", "autocomplete": "email"}))
    identity_verified = forms.BooleanField(label="Verifiqué la identidad presencialmente", required=False,
        widget=forms.CheckboxInput(attrs={"class": "form-check-input"}))
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

    def __init__(self, *args, official=None, active_delegation=None, can_link_request=False, case=None, **kwargs):
        super().__init__(*args, **kwargs)
        if not can_link_request:
            self.fields.pop("client_request")
            self.fields["origin"].choices = ((self.DIRECT, "Atención directa"),)
        configure_text_widgets(self)
        self.official = official
        self.case = case
        self.recipient_record = None

        delegations = attention_delegations(official, active_delegation)
        self.fields["delegation"].queryset = delegations
        if case:
            self.fields.pop("origin")
            self.fields.pop("client_request", None)
            self.fields.pop("case_subject")
            self.initial.update(recipient_national_id=case.recipient.national_id,
                recipient_full_name=case.recipient.full_name, delegation=case.delegation_id)
            for name in ("recipient_national_id", "recipient_full_name", "delegation"):
                self.fields[name].disabled = True
            if case.client_request_id or case.recipient.user_id:
                for name in ("invite_to_portal", "invitation_email", "identity_verified"):
                    self.fields.pop(name)
        if official is not None and official.is_enabled:
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
        if self.case:
            return self.case.recipient.national_id
        return normalize_chilean_rut(self.cleaned_data["recipient_national_id"])

    def clean_description(self):
        value = self.cleaned_data.get("description")
        raw = self.data.get(self.add_prefix("description"), "")
        if text_length(raw) > DESCRIPTION_MAX_LENGTH:
            raise ValidationError(f"La descripción no puede superar los {DESCRIPTION_MAX_LENGTH} caracteres.")
        return clean_description_text(value, DESCRIPTION_MAX_LENGTH)

    def clean_effective_date(self):
        date = self.cleaned_data["effective_date"] or timezone.localdate()
        if date > timezone.localdate():
            raise ValidationError("La fecha de la gestión no puede estar en el futuro.")
        return date

    def clean_result(self):
        value = clean_description_text(self.cleaned_data["result"], 300)
        if not value:
            raise ValidationError("Ingresa el resultado de la gestión.")
        return value

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
                elif full_name and normalize_spaces(recipient.full_name).casefold() != normalize_spaces(full_name).casefold():
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

        if full_name and self.recipient_record is None and "recipient_full_name" in cleaned_data:
            try:
                if text_length(self.data.get(self.add_prefix("recipient_full_name"), "")) > 100:
                    raise ValidationError("El nombre no puede superar los 100 caracteres.")
                cleaned_data["recipient_full_name"] = clean_person_name(full_name)
            except ValidationError as error:
                self.add_error("recipient_full_name", error)

        if (
            attention_type is not None
            and subattention_type is not None
            and subattention_type.attention_type_id != attention_type.pk
        ):
            self.add_error(
                "subattention_type",
                "Selecciona una Sub Atención asociada al Tipo de Atención elegido.",
            )

        folio = cleaned_data.get("client_request")
        # Los formularios anteriores al selector enviaban solo el folio.
        origin = cleaned_data.get("origin") or (self.LINKED if folio else self.DIRECT)
        if "client_request" not in self.fields and self.data.get(self.add_prefix("client_request")):
            self.add_error(None, "Tu perfil no puede vincular solicitudes ciudadanas.")
        elif origin == self.LINKED and not folio and "client_request" not in self.errors:
            self.add_error("client_request", "Selecciona una solicitud ciudadana.")
        elif origin == self.DIRECT and folio:
            self.add_error("client_request", "Para usar este folio, elige vincular a una solicitud ciudadana.")
        elif folio:
            request_id = positive(folio[4:], 0)
            if not request_id:
                self.add_error("client_request", "Ingresa un folio válido.")
            else:
                cleaned_data["client_request"] = request_id

        if cleaned_data.get("invite_to_portal"):
            if origin == self.LINKED:
                self.add_error("invite_to_portal", "La solicitud ya pertenece a una cuenta del portal.")
            if not cleaned_data.get("invitation_email") and "invitation_email" not in self.errors:
                self.add_error("invitation_email", "Ingresa el correo de la persona.")
            if not cleaned_data.get("identity_verified"):
                self.add_error("identity_verified", "Confirma que verificaste su identidad presencialmente.")

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
