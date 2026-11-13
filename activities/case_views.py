from django import forms
from django.contrib import messages
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Q
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.generic import TemplateView, View

from accounts.delegation_context import get_active_delegation
from accounts.models import Official
from common.access import ProtectedViewMixin, get_scoped_object_or_404
from common.chilean_rut import normalize_chilean_rut
from common.list_state import positive
from common.pagination import ClampedPaginationMixin
from common.text import clean_description_text, normalize_spaces

from .cases import (ADD_ATTENTION, CHANGE_CASE, VIEW_CASE, assign_case, case_timeline,
                    change_request_status, record_case_event, scoped_cases)
from .invitations import invite_to_portal
from .evidence import VIEW_ACTIVITY, VIEW_EVIDENCE, evidence_activities
from .models import AttentionCase, ClientRequest, PortalInvitation, SocialAttention


class CaseAssignmentForm(forms.Form):
    responsible = forms.ModelChoiceField(label="Funcionario responsable", queryset=Official.objects.none(),
        widget=forms.Select(attrs={"class": "form-select"}))

    def __init__(self, *args, case, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["responsible"].queryset = Official.objects.filter(
            status=Official.Status.ACTIVE, deleted_at__isnull=True, user__is_active=True,
        ).filter(Q(delegation=case.delegation) | Q(authorized_delegations=case.delegation)).distinct()


class CaseNextStepForm(forms.Form):
    next_step = forms.CharField(label="Próximo paso interno", max_length=200,
        widget=forms.TextInput(attrs={"class": "form-control"}))
    next_step_date = forms.DateField(label="Fecha prevista", widget=forms.DateInput(
        format="%Y-%m-%d", attrs={"class": "form-control", "type": "date"}))
    public_next_step = forms.CharField(label="Mensaje para la persona (opcional)", max_length=200, required=False,
        widget=forms.TextInput(attrs={"class": "form-control"}))

    def clean_next_step_date(self):
        date = self.cleaned_data["next_step_date"]
        if date < timezone.localdate():
            raise ValidationError("Selecciona la fecha de hoy o una posterior.")
        return date


class CaseCloseForm(forms.Form):
    response = forms.CharField(label="Respuesta para la persona", max_length=500,
        widget=forms.Textarea(attrs={"class": "form-control", "rows": 3}))

    def clean_response(self):
        value = clean_description_text(self.cleaned_data["response"])
        if not value:
            raise ValidationError("Ingresa una respuesta antes de cerrar el caso.")
        return value


class PortalInvitationForm(forms.Form):
    email = forms.EmailField(label="Correo para la invitación", max_length=191,
        widget=forms.EmailInput(attrs={"class": "form-control", "autocomplete": "email"}))
    identity_verified = forms.BooleanField(label="Verifiqué la identidad presencialmente",
        widget=forms.CheckboxInput(attrs={"class": "form-check-input"}))


class CaseListView(ClampedPaginationMixin, ProtectedViewMixin, TemplateView):
    permission_required = VIEW_CASE
    template_name = "activities/case_list.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        cases = scoped_cases(self.request.user)
        query = normalize_spaces(self.request.GET.get("q"))[:200]
        if query:
            match = Q(subject__icontains=query) | Q(recipient__full_name__icontains=query)
            prefix, _, number = query.upper().partition("-")
            identifier = positive(number, 0)
            if prefix == "CAS" and identifier:
                match |= Q(pk=identifier, client_request__isnull=True)
            if prefix == "SOL" and identifier:
                match |= Q(client_request_id=identifier)
            try:
                national_id = normalize_chilean_rut(query)
            except ValidationError:
                pass
            else:
                match |= Q(recipient__national_id__iexact=national_id)
            cases = cases.filter(match)
        status = self.request.GET.get("status")
        if status in ClientRequest.Status.values or status in AttentionCase.DirectStatus.values:
            cases = cases.filter(Q(client_request__status=status) |
                                 Q(client_request__isnull=True, direct_status=status))
        page = self.clamp_page(cases)
        params = self.request.GET.copy()
        params.pop("page", None)
        return {**context, "page_obj": page, "query": query, "selected_status": status,
                "querystring": params.urlencode()}


def render_case(request, case, *, request_list_url=None, errors=None):
    user = request.user
    official = getattr(user, "official", None)
    can_manage = official is not None and user.has_perm(CHANGE_CASE) and scoped_cases(user, CHANGE_CASE).filter(pk=case.pk).exists()
    authorized_delegation = official is not None and official.get_authorized_delegations().filter(pk=case.delegation_id).exists()
    active = get_active_delegation(request)
    can_append = user.has_perm(ADD_ATTENTION) and scoped_cases(user, ADD_ATTENTION).filter(pk=case.pk).exists()
    can_register = authorized_delegation and can_append and not case.is_closed
    at_limit = case.attentions.count() >= SocialAttention.MAX_ATTENTIONS_PER_CASE
    can_invite = authorized_delegation and can_append and not case.client_request_id and not case.recipient.user_id
    invitation = PortalInvitation.objects.filter(recipient=case.recipient).first() if can_invite else None
    timeline = case_timeline(case)
    if user.has_perms((VIEW_ACTIVITY, VIEW_EVIDENCE)):
        activities_by_attention = {
            attention_id: (activity_id, code)
            for attention_id, activity_id, code in evidence_activities(user, VIEW_EVIDENCE)
                .filter(social_attentions__case=case, social_attentions__deleted_at__isnull=True)
                .values_list("social_attentions__pk", "pk", "code")
        }
        for entry in timeline:
            activity = activities_by_attention.get(entry.get("attention_id"))
            if activity:
                activity_id, code = activity
                entry["evidence_url"] = reverse("activity_detail", args=[activity_id], fragment="activity-evidence-title")
                entry["activity_code"] = code
    context = {
        "case": case, "timeline": timeline, "request_list_url": request_list_url,
        "active_menu": "staff_client_request_detail" if request_list_url == reverse("staff_client_requests") else "attention_cases",
        "can_manage": can_manage and not case.is_closed, "can_register": can_register and not at_limit,
        "at_limit": at_limit, "needs_delegation_switch": can_register and not at_limit and active != case.delegation,
        "can_invite": can_invite, "invitation": invitation,
        "assignment_form": CaseAssignmentForm(case=case, initial={"responsible": case.responsible_id}),
        "next_step_form": CaseNextStepForm(initial={"next_step": case.next_step,
            "next_step_date": case.next_step_date, "public_next_step": case.public_next_step}),
        "close_form": CaseCloseForm(),
        "invitation_form": PortalInvitationForm(initial={"email": invitation.email if invitation else case.recipient.email}),
    }
    if errors:
        context.update(errors)
    return render(request, "activities/case_detail.html", context)


class CaseDetailView(ProtectedViewMixin, View):
    permission_required = VIEW_CASE

    def get(self, request, pk):
        return render_case(request, get_scoped_object_or_404(request, scoped_cases(request.user), pk=pk))


class CaseActionView(ProtectedViewMixin, View):
    http_method_names = ["post"]

    def get_permission_required(self):
        permission = ADD_ATTENTION if self.kwargs["action"] == "invitar" else CHANGE_CASE
        return (VIEW_CASE, permission)

    def post(self, request, pk, action):
        case = get_scoped_object_or_404(request, scoped_cases(request.user), pk=pk)
        actor = getattr(request.user, "official", None)
        if actor is None:
            return self.handle_no_permission()
        if action == "invitar":
            if (case.client_request_id or not scoped_cases(request.user, ADD_ATTENTION).filter(pk=case.pk).exists()
                    or not actor.get_authorized_delegations().filter(pk=case.delegation_id).exists()):
                return self.handle_no_permission()
            form = PortalInvitationForm(request.POST)
            if form.is_valid():
                try:
                    invite_to_portal(request, case.recipient_id, form.cleaned_data["email"])
                except ValidationError as error:
                    form.add_error(None, error)
                else:
                    return redirect("attention_case_detail", pk=pk)
            return render_case(request, case, errors={"invitation_form": form})

        with transaction.atomic():
            authorized = scoped_cases(request.user, CHANGE_CASE).values("pk")
            case = get_scoped_object_or_404(request, AttentionCase.objects.select_for_update().filter(pk__in=authorized), pk=pk)
            if case.is_closed:
                messages.error(request, "El caso está cerrado.")
                return redirect("attention_case_detail", pk=pk)
            if action == "tomar" and case.responsible_id is None:
                if not actor.get_authorized_delegations().filter(pk=case.delegation_id).exists():
                    return self.handle_no_permission()
                assign_case(case, actor)
                public_text = "" if case.client_request_id else "El caso está en curso."
                record_case_event(case, actor, "Caso asignado", actor.full_name, public_text)
            elif action == "asignar":
                form = CaseAssignmentForm(request.POST, case=case)
                if not form.is_valid():
                    return render_case(request, case, errors={"assignment_form": form})
                previous = case.responsible
                responsible = form.cleaned_data["responsible"]
                if previous == responsible:
                    return redirect("attention_case_detail", pk=pk)
                case.responsible = responsible
                assign_case(case, actor)
                record_case_event(case, actor, "Responsable actualizado", f"De {previous or 'sin asignar'} a {responsible}.")
            elif action == "proximo-paso":
                form = CaseNextStepForm(request.POST)
                if not form.is_valid():
                    return render_case(request, case, errors={"next_step_form": form})
                if (case.next_step, case.next_step_date, case.public_next_step) == (
                    form.cleaned_data["next_step"], form.cleaned_data["next_step_date"], form.cleaned_data["public_next_step"],
                ):
                    return redirect("attention_case_detail", pk=pk)
                case.next_step = form.cleaned_data["next_step"]
                case.next_step_date = form.cleaned_data["next_step_date"]
                case.public_next_step = form.cleaned_data["public_next_step"]
                public_text = ""
                if case.public_next_step:
                    public_text = f"{case.public_next_step} · {case.next_step_date:%d/%m/%Y}"
                record_case_event(case, actor, "Próximo paso actualizado", f"{case.next_step} · {case.next_step_date:%d/%m/%Y}", public_text)
            elif action in ("completar-paso", "cancelar-paso") and case.next_step:
                title = "Próximo paso completado" if action == "completar-paso" else "Próximo paso cancelado"
                record_case_event(case, actor, title, case.next_step, title if case.public_next_step else "")
                case.next_step, case.next_step_date, case.public_next_step = "", None, ""
            elif action == "cerrar":
                form = CaseCloseForm(request.POST)
                valid = form.is_valid()
                if case.next_step:
                    form.add_error(None, "Completa o cancela el próximo paso antes de cerrar el caso.")
                if not valid or case.next_step:
                    return render_case(request, case, errors={"close_form": form})
                response = form.cleaned_data["response"]
                if case.client_request_id:
                    change_request_status(case, ClientRequest.Status.RESOLVED, actor, response)
                    record_case_event(case, actor, "Caso cerrado y solicitud resuelta")
                else:
                    case.direct_status = AttentionCase.DirectStatus.RESOLVED
                    case.public_response = response
                    record_case_event(case, actor, "Caso cerrado", response, "El caso está cerrado.")
            else:
                messages.info(request, "El caso ya se actualizó. Revisa su estado y vuelve a intentar.")
                return redirect("attention_case_detail", pk=pk)
            case.save()
        messages.success(request, "Seguimiento actualizado correctamente.")
        return redirect("attention_case_detail", pk=pk)
