import uuid
from functools import cached_property

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.http import JsonResponse
from django.shortcuts import redirect
from django.utils import timezone
from django.views.generic import DetailView, FormView, TemplateView, View

from accounts.delegation_context import get_active_delegation
from accounts.models import Delegation, ServiceRecipient
from common.access import ProtectedViewMixin, ScopedObjectMixin, get_scoped_object_or_404
from common.list_state import positive
from common.text import normalize_spaces
from configuration.models import AttentionType, SubattentionType
from configuration.services import AuditoriaService

from .client_portal import staff_requests
from .cases import ADD_ATTENTION, assign_case, scoped_cases
from .forms import SocialAttentionForm, attention_delegations
from .invitations import invite_to_portal
from .models import AttentionCase, ClientRequest, SocialAttention, Activity
from configuration.period_services import lock_open_period, lock_period_registry
from configuration.models import Item

LAST_ATTENTION_SESSION_KEY = "last_registered_attention"


def scoped_attentions(user, permission=None):
    """
    Atenciones que el usuario puede consultar: las de sus delegaciones autorizadas y las que
    registró. El superusuario conserva el alcance total; sin funcionario no hay alcance.
    """
    queryset = SocialAttention.objects.filter(deleted_at__isnull=True).select_related(
        "recipient", "attention_type", "subattention_type", "delegation", "responsible", "case__client_request"
    )
    from common.scopes import permission_scope, current_permission, delegation_ids
    from accounts.models import Role
    scope = permission_scope(user, permission or current_permission.get() or "activities.view_socialattention")
    if scope == Role.Scope.ALL:
        return queryset
    official = getattr(user, "official", None)
    if scope == Role.Scope.OWN:
        return queryset.filter(Q(responsible=official) | Q(case__client_request__isnull=True, case__responsible=official))
    if scope == Role.Scope.DELEGATION:
        return queryset.filter(Q(delegation_id__in=delegation_ids(user)) | Q(responsible=official)).distinct()
    return queryset.none()


def registered_attention(token, official):
    """Atención ya guardada con este token de envío por el mismo responsable, si existe."""
    if not token or official is None:
        return None
    return SocialAttention.objects.filter(submission_token=token, responsible=official).first()


def requests_for_attention(user, delegations):
    appendable = scoped_cases(user, ADD_ATTENTION).exclude(client_request_id=None).values("client_request_id")
    return staff_requests(user, "activities.view_socialattention").filter(
        delegation__in=delegations, pk__in=appendable,
    ).exclude(
        status=ClientRequest.Status.RESOLVED,
    )


def attention_request_folio(queryset, folio):
    try:
        folio = SocialAttentionForm.base_fields["client_request"].clean(folio)
    except ValidationError:
        return None
    if folio and (request_id := positive(folio[4:], 0)):
        return queryset.filter(pk=request_id).first()
    return None


class AttentionRequestLookupView(ProtectedViewMixin, View):
    permission_required = ("activities.add_socialattention", "activities.view_socialattention")

    def get(self, request):
        delegations = attention_delegations(getattr(request.user, "official", None), get_active_delegation(request))
        queryset = requests_for_attention(request.user, delegations)
        origin = attention_request_folio(queryset, request.GET.get("folio", ""))
        if origin is None:
            return JsonResponse({"error": "La solicitud no está disponible para esta atención."}, status=404)
        return JsonResponse({
            "folio": origin.identifier,
            "rut": origin.recipient.national_id,
            "name": normalize_spaces(origin.recipient.full_name),
            "delegation_id": origin.delegation_id,
        })


class AttentionEntryView(ProtectedViewMixin, FormView):
    permission_required = 'activities.add_socialattention'
    template_name = 'activities/attention_entry.html'
    form_class = SocialAttentionForm

    @cached_property
    def target_case(self):
        if "caso" not in self.request.GET:
            return None
        return get_scoped_object_or_404(self.request, scoped_cases(self.request.user),
                                        pk=positive(self.request.GET.get("caso"), 0))

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["official"] = getattr(self.request.user, "official", None)
        kwargs["active_delegation"] = get_active_delegation(self.request)
        kwargs["can_link_request"] = self.request.user.has_perm("activities.view_socialattention")
        kwargs["case"] = self.target_case
        return kwargs

    def get_initial(self):
        initial = super().get_initial()
        initial["submission_token"] = uuid.uuid4().hex
        return initial

    def get_form(self, form_class=None):
        form = super().get_form(form_class)
        folio = self.request.GET.get("folio", "").strip()
        if form.is_bound or not folio or "client_request" not in form.fields:
            return form
        form.initial["origin"] = form.LINKED
        origin = attention_request_folio(
            requests_for_attention(self.request.user, form.fields["delegation"].queryset), folio,
        )
        if origin:
            form.initial.update(
                client_request=origin.identifier,
                delegation=origin.delegation_id,
                recipient_national_id=origin.recipient.national_id,
                recipient_full_name=normalize_spaces(origin.recipient.full_name),
            )
        return form

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        form = context["form"]
        if "client_request" in form.fields:
            requests = requests_for_attention(self.request.user, form.fields["delegation"].queryset)
            requests = requests.select_related(None).select_related("recipient").only("subject", "recipient__full_name")
            choices = [
                (item.identifier, f"{item.identifier} · {item.recipient.full_name} · {item.subject}")
                for item in requests
            ]
            placeholder = "Selecciona una solicitud" if choices else "No hay solicitudes disponibles"
            form.fields["client_request"].widget.choices = [("", placeholder), *choices]
        context["registered_at"] = timezone.localtime()
        context["target_case"] = self.target_case
        if self.target_case:
            context["case_unavailable"] = self.target_case.is_closed or not self.can_append(form, self.target_case)
        elif self.request.GET.get("folio") and not form.is_bound and not form.initial.get("client_request"):
            context["folio_unavailable"] = True
        if self.request.method == "GET":
            # Tras guardar se vuelve a un formulario limpio que muestra la atención registrada.
            last_pk = self.request.session.pop(LAST_ATTENTION_SESSION_KEY, None)
            if last_pk is not None:
                context["last_attention"] = scoped_attentions(self.request.user).filter(pk=last_pk).first()
                if context["last_attention"]:
                    context["last_case"] = scoped_cases(self.request.user).filter(pk=context["last_attention"].case_id).first()
        return context

    def can_append(self, form, case):
        return (form.fields["delegation"].queryset.filter(pk=case.delegation_id).exists()
                and scoped_cases(self.request.user, ADD_ATTENTION).filter(pk=case.pk).exists())

    def already_registered(self, attention):
        """Doble envío del mismo formulario: no se crea otra atención y se informa la existente."""
        self.request.session[LAST_ATTENTION_SESSION_KEY] = attention.pk
        messages.info(
            self.request,
            f"La atención {attention.identifier} ya estaba registrada; el envío repetido no creó un duplicado.",
        )
        return self.success_destination(attention)

    def success_destination(self, attention):
        if self.target_case:
            return redirect("attention_case_detail", pk=attention.case_id)
        return redirect("attention_entry")

    def form_valid(self, form):
        token = form.cleaned_data.get("submission_token") or None
        duplicate = registered_attention(token, form.official)
        if duplicate is not None:
            return self.already_registered(duplicate)
        try:
            with transaction.atomic():
                lock_period_registry()
                effective_date = form.cleaned_data["effective_date"]
                lock_open_period(effective_date)
                request_id = form.cleaned_data.get("client_request")
                case = self.target_case
                if request_id:
                    origin = requests_for_attention(self.request.user, form.fields["delegation"].queryset).filter(pk=request_id).first()
                    if origin is None or (
                        origin.recipient.national_id.casefold() != form.cleaned_data["recipient_national_id"].casefold()
                        or origin.delegation_id != form.cleaned_data["delegation"].pk
                    ):
                        raise ValidationError({"client_request": "No hay una solicitud disponible con ese folio para este solicitante y delegación."})
                    case = origin.attention_case
                if case:
                    case = AttentionCase.objects.select_for_update().get(pk=case.pk)
                    if case.is_closed:
                        raise ValidationError("El caso está cerrado.")
                    if not self.can_append(form, case):
                        raise ValidationError({"delegation": "Tu perfil y delegación activa deben permitir registrar en este caso."})
                recipient = case.recipient if case else form.get_or_create_recipient()
                recipient = ServiceRecipient.objects.select_for_update().get(pk=recipient.pk)
                if (
                    recipient.status != ServiceRecipient.Status.ACTIVE
                    or recipient.deleted_at is not None
                ):
                    raise ValidationError(
                        {
                            "recipient_national_id": (
                                "La persona asociada a este RUT no está activa."
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
                if case is None:
                    case = AttentionCase.objects.create(recipient=recipient, delegation=delegation,
                        responsible=form.official, subject=normalize_spaces(form.cleaned_data.get("case_subject")) or attention_type.name[:100])
                attention = SocialAttention(
                    case=case,
                    recipient=recipient,
                    attention_type=attention_type,
                    subattention_type=subattention_type,
                    description=form.cleaned_data["description"],
                    result=form.cleaned_data["result"],
                    date=effective_date,
                    delegation=delegation,
                    responsible=form.official,
                    submission_token=token,
                )
                # La unicidad del token la resuelve la base (IntegrityError), también entre envíos simultáneos.
                attention.full_clean(exclude=["submission_token"])
                try:
                    item = Item.objects.select_for_update().get(pk=attention_type.activity_item_id,
                        is_active=True, deleted_at__isnull=True)
                except Item.DoesNotExist as error:
                    raise ValidationError("Configura un ítem vigente en el Tipo de Atención antes de registrar.") from error
                activity = Activity.objects.create(official=form.official, item=item, date=attention.date,
                    record_type=Activity.RecordType.ATTENTION, action_description=attention.description)
                attention.activity = activity
                attention.save()
                assign_case(case, form.official)
                case.save(update_fields=["responsible", "direct_status", "updated_at"])
                AuditoriaService.register_change(official=form.official, action="Creación de actividad automática",
                    instance=activity, new_value=f"Atención: {attention.identifier}; Ítem: {item}",
                    origin_ip=self.request.META.get("REMOTE_ADDR") or None)
                AuditoriaService.register_change(
                    official=form.official,
                    action="Creación de atención",
                    instance=attention,
                    new_value=(
                        f"Identificador: {attention.identifier}; "
                        f"Solicitante ID interno: {recipient.pk}; "
                        f"Tipo: {attention.attention_type}; "
                        f"Sub Atención: {attention.subattention_type}; "
                        f"Delegación: {attention.delegation}; Caso: {case.identifier}"
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
        except IntegrityError:
            duplicate = registered_attention(token, form.official)
            if duplicate is None:
                raise
            return self.already_registered(duplicate)

        self.request.session[LAST_ATTENTION_SESSION_KEY] = attention.pk
        messages.success(
            self.request,
            f"La atención {attention.identifier} se registró correctamente.",
        )
        if form.cleaned_data.get("invite_to_portal"):
            try:
                invite_to_portal(self.request, recipient.pk, form.cleaned_data["invitation_email"])
            except ValidationError as error:
                messages.warning(self.request, " ".join(error.messages))
        return self.success_destination(attention)

    def form_invalid(self, form):
        messages.error(
            self.request,
            "No se pudo registrar la atención. Revisa los datos ingresados.",
        )
        return super().form_invalid(form)


class AttentionDetailView(ScopedObjectMixin, ProtectedViewMixin, DetailView):
    """Consulta de una atención registrada, limitada a las delegaciones autorizadas del usuario."""

    permission_required = 'activities.view_socialattention'
    template_name = 'activities/attention_detail.html'
    context_object_name = 'attention'

    def get_queryset(self):
        return scoped_attentions(self.request.user)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        if scoped_cases(self.request.user).filter(pk=self.object.case_id).exists():
            context["attention_case"] = self.object.case
        if self.object.client_request_id:
            context["origin_request"] = staff_requests(
                self.request.user, self.permission_required,
            ).filter(pk=self.object.client_request_id).first()
        return context
