from django.contrib import messages
from django.core.exceptions import ValidationError
from django.db import transaction
from django.shortcuts import redirect
from django.utils import timezone
from django.views.generic import FormView, TemplateView

from accounts.delegation_context import get_active_delegation
from accounts.models import Delegation, ServiceRecipient
from common.access import ProtectedViewMixin
from configuration.models import AttentionType, SubattentionType
from configuration.services import AuditoriaService

from .forms import SocialAttentionForm
from .models import SocialAttention


class ActivityMaintainerView(ProtectedViewMixin, TemplateView):
    permission_required = 'activities.view_activity'
    template_name = 'activities/activity_list.html'
    extra_context = {
        'maintainer_title': 'Actividades',
        'maintainer_kind': 'activities',
        'columns': ['Código', 'Funcionario', 'Ítem', 'Fecha', 'Tipo de registro', 'Estado'],
        'statuses': ['Vigente', 'Archivada'],
        'records': [
            {
                'cells': ['ACT001', 'Camila Rojas', 'Atenciones realizadas', '16-10-2026', 'Registro mensual', 'Vigente'],
                'status': 'Vigente',
                'status_is_active': True,
            },
            {
                'cells': ['ACT002', 'Diego Muñoz', 'Fiscalizaciones', '15-10-2026', 'Terreno', 'Vigente'],
                'status': 'Vigente',
                'status_is_active': True,
            },
            {
                'cells': ['ACT003', 'Sofía González', 'Informes emitidos', '14-10-2026', 'Registro mensual', 'Archivada'],
                'status': 'Archivada',
                'status_is_active': False,
            },
            {
                'cells': ['ACT004', 'Matías Fuentes', 'Atenciones realizadas', '13-10-2026', 'Terreno', 'Vigente'],
                'status': 'Vigente',
                'status_is_active': True,
            },
            {
                'cells': ['ACT005', 'Valentina Pérez', 'Inspecciones', '12-10-2026', 'Registro mensual', 'Vigente'],
                'status': 'Vigente',
                'status_is_active': True,
            },
            {
                'cells': ['ACT006', 'Tomás Silva', 'Informes emitidos', '11-10-2026', 'Terreno', 'Vigente'],
                'status': 'Vigente',
                'status_is_active': True,
            },
        ],
    }


class AttentionEntryView(ProtectedViewMixin, FormView):
    permission_required = 'activities.add_socialattention'
    template_name = 'activities/attention_entry.html'
    form_class = SocialAttentionForm

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["official"] = getattr(self.request.user, "official", None)
        kwargs["active_delegation"] = get_active_delegation(self.request)
        return kwargs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["registered_at"] = timezone.localtime()
        return context

    def form_valid(self, form):
        try:
            with transaction.atomic():
                recipient = form.get_or_create_recipient()
                recipient = ServiceRecipient.objects.select_for_update().get(pk=recipient.pk)
                if (
                    recipient.status != ServiceRecipient.Status.ACTIVE
                    or recipient.deleted_at is not None
                ):
                    raise ValidationError(
                        {
                            "recipient_national_id": (
                                "La persona asociada a este identificador no está activa."
                            )
                        }
                    )
                try:
                    attention_type = AttentionType.objects.select_for_update().get(
                        pk=form.cleaned_data["attention_type"].pk,
                        is_active=True,
                        deleted_at__isnull=True,
                    )
                except AttentionType.DoesNotExist as error:
                    raise ValidationError(
                        {"attention_type": "El Tipo de Atención dejó de estar vigente."}
                    ) from error
                try:
                    subattention_type = SubattentionType.objects.select_for_update().get(
                        pk=form.cleaned_data["subattention_type"].pk,
                        attention_type=attention_type,
                        is_active=True,
                        deleted_at__isnull=True,
                    )
                except SubattentionType.DoesNotExist as error:
                    raise ValidationError(
                        {
                            "subattention_type": (
                                "La Sub Atención dejó de estar vigente o no corresponde al tipo elegido."
                            )
                        }
                    ) from error
                try:
                    delegation = form.official.get_authorized_delegations().select_for_update().get(
                        pk=form.cleaned_data["delegation"].pk,
                        deleted_at__isnull=True,
                    )
                except Delegation.DoesNotExist as error:
                    raise ValidationError(
                        {"delegation": "La delegación ya no está autorizada para tu perfil."}
                    ) from error
                attention = SocialAttention(
                    recipient=recipient,
                    attention_type=attention_type,
                    subattention_type=subattention_type,
                    description=form.cleaned_data["description"],
                    delegation=delegation,
                    responsible=form.official,
                )
                attention.full_clean()
                attention.save()
                AuditoriaService.register_change(
                    official=form.official,
                    action="Creación de atención",
                    instance=attention,
                    new_value=(
                        f"Identificador: {attention.identifier}; "
                        f"Solicitante ID interno: {recipient.pk}; "
                        f"Tipo: {attention.attention_type}; "
                        f"Sub Atención: {attention.subattention_type}; "
                        f"Delegación: {attention.delegation}"
                    ),
                    origin_ip=self.request.META.get("REMOTE_ADDR") or None,
                )
        except ValidationError as error:
            for field, errors in getattr(error, "message_dict", {}).items():
                form_field = "recipient_national_id" if field == "recipient" else field
                if form_field in form.fields:
                    for message in errors:
                        form.add_error(form_field, message)
                else:
                    for message in errors:
                        form.add_error(None, message)
            if not getattr(error, "message_dict", None):
                for message in error.messages:
                    form.add_error(None, message)
            return self.form_invalid(form)

        messages.success(
            self.request,
            f"La atención {attention.identifier} se registró correctamente.",
        )
        return redirect("attention_entry")

    def form_invalid(self, form):
        messages.error(
            self.request,
            "No se pudo registrar la atención. Revisa los datos ingresados.",
        )
        return super().form_invalid(form)
