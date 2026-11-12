import uuid

from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Case, F, Q, Value, When
from django.db.models.functions import Coalesce
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import path, reverse, reverse_lazy
from django.utils.cache import add_never_cache_headers
from django.views.decorators.cache import never_cache
from django.views.generic import FormView, TemplateView, View

from accounts.forms import OwnOfficialProfileForm, profile_snapshot
from accounts.models import Delegation, Role, ServiceRecipient, Territory
from common.pagination import ClampedPaginationMixin
from common.access import ProtectedViewMixin, get_scoped_object_or_404
from common.exports import xlsx_response
from common.list_state import ordered, positive
from common.scopes import delegation_ids, permission_scope
from common.text import clean_description_text, describe_changes, normalize_spaces
from configuration.models import AttentionType, SubattentionType
from configuration.services import AuditoriaService
from .case_views import render_case
from .cases import case_timeline, change_request_status, record_case_event, scoped_cases
from .invitations import activate_portal
from .models import AttentionCase, ClientRequest, ClientRequestEvent


class ClientAccessMixin(LoginRequiredMixin):
    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return self.handle_no_permission()
        self.recipient = getattr(request.user, "service_recipient", None)
        if (not request.user.is_active or self.recipient is None or not self.recipient.is_enabled
                or hasattr(request.user, "official") or request.user.is_staff or request.user.is_superuser):
            raise PermissionDenied("Tu cuenta no tiene un perfil de cliente habilitado.")
        response = super().dispatch(request, *args, **kwargs)
        add_never_cache_headers(response)
        return response

    def get_context_data(self, **kwargs):
        return {**super().get_context_data(**kwargs), "client_recipient": self.recipient}

    def requests(self):
        return ClientRequest.objects.filter(recipient=self.recipient, deleted_at__isnull=True).select_related(
            "delegation", "attention_type", "subattention_type")

    def cases(self):
        return AttentionCase.objects.filter(recipient=self.recipient, deleted_at__isnull=True).filter(
            Q(client_request__isnull=True) | Q(client_request__recipient=self.recipient,
                client_request__deleted_at__isnull=True, client_request__delegation_id=F("delegation_id")),
        ).select_related("client_request", "delegation")


class ClientRequestForm(forms.ModelForm):
    submission_token = forms.UUIDField(widget=forms.HiddenInput)

    class Meta:
        model = ClientRequest
        fields = ["attention_type", "subattention_type", "subject", "description"]
        labels = {"attention_type": "Tipo de atención", "subattention_type": "Sub atención", "delegation": "Delegación"}
        widgets = {"description": forms.Textarea(attrs={"rows": 5, "maxlength": 500})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["attention_type"].queryset = AttentionType.objects.filter(is_active=True, deleted_at__isnull=True)
        self.fields["subattention_type"].queryset = SubattentionType.objects.filter(
            is_active=True, deleted_at__isnull=True, attention_type__is_active=True,
            attention_type__deleted_at__isnull=True).select_related("attention_type")
        for field in self.fields.values():
            field.widget.attrs["class"] = "form-select" if isinstance(field.widget, forms.Select) else "form-control"

    def clean_subject(self):
        value = normalize_spaces(self.cleaned_data["subject"])
        if not value:
            raise ValidationError("Indica el motivo de tu solicitud.")
        return value

    def clean_description(self):
        return clean_description_text(self.cleaned_data["description"])

    def clean(self):
        data = super().clean()
        parent, child = data.get("attention_type"), data.get("subattention_type")
        if parent and child and child.attention_type_id != parent.pk:
            self.add_error("subattention_type", "La sub atención no pertenece al tipo elegido.")
        return data


class ClientListView(ClampedPaginationMixin, ClientAccessMixin, TemplateView):
    template_name = "client/list.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        qs = self.cases()
        query = normalize_spaces(self.request.GET.get("q"))[:200]
        status = self.request.GET.get("status", "")
        if query:
            match = Q(subject__icontains=query)
            prefix, _, number = query.upper().partition("-")
            identifier = positive(number, 0)
            if prefix == "SOL" and identifier:
                match |= Q(client_request_id=identifier)
            if prefix == "CAS" and identifier:
                match |= Q(pk=identifier, client_request__isnull=True)
            qs = qs.filter(match)
        if status:
            qs = qs.filter(Q(client_request__status=status) | Q(client_request__isnull=True, direct_status=status))
        source = self.request.GET.get("record_source", "")
        if source:
            qs = qs.filter(client_request__isnull=source == "presential")
        sort = self.request.GET.get("sort")
        field = {"subject": "subject", "delegation": "delegation__delegation_name"}.get(sort, "created_at")
        prefix = "" if self.request.GET.get("direction") == "asc" else "-"
        if sort == "code":
            qs = qs.annotate(code_source=Case(When(client_request__isnull=True, then=Value(0)), default=Value(1)),
                             code_number=Coalesce("client_request_id", "pk"))
            qs = qs.order_by(f"{prefix}code_source", f"{prefix}code_number", "-pk")
        else:
            qs = qs.order_by(f"{prefix}{field}", "-pk")
        page = self.clamp_page(qs, already_ordered=True)
        from django.http import QueryDict
        params = QueryDict(mutable=True)
        params.update({key: value for key, value in self.request.GET.items() if key != "page"})
        context.update(page_obj=page, query=query, selected_status=status, selected_source=source,
                       statuses=[("RECEIVED", "Recibida"), ("REVIEW", "En revisión / En curso"),
                                 ("RESOLVED", "Resuelta / Cerrada"), ("RECORDED", "Gestión registrada")],
                       querystring=params.urlencode())
        return context


class ClientDetailView(ClientAccessMixin, TemplateView):
    template_name = "client/detail.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        origin = get_object_or_404(self.requests(), pk=self.kwargs["pk"])
        case = get_object_or_404(self.cases(), client_request=origin)
        return {**context, "attention_request": origin, **public_case_context(case)}


def public_case_context(case):
    timeline = case_timeline(case, public=True)
    return {
        "tracking": {"code": case.identifier, "subject": case.subject, "delegation": case.delegation,
                     "status": case.get_status_display(), "status_code": case.status,
                     "created": case.created_at, "last_movement": timeline[0]["when"] if timeline else case.created_at,
                     "next_step": case.public_next_step,
                     "next_step_date": case.next_step_date if case.public_next_step else None,
                     "response": case.response},
        "public_timeline": timeline,
    }


class ClientPresentialCaseView(ClientAccessMixin, TemplateView):
    template_name = "client/detail.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        case = get_object_or_404(self.cases(), pk=self.kwargs["pk"], client_request__isnull=True)
        return {**context, **public_case_context(case)}


class ClientCreateView(ClientAccessMixin, FormView):
    form_class = ClientRequestForm
    template_name = "client/form.html"
    success_url = reverse_lazy("client_requests")

    def get_initial(self):
        return {"submission_token": uuid.uuid4()}

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["location_ready"] = self.recipient.location_ready
        context["subattention_options"] = list(SubattentionType.objects.filter(is_active=True,
            deleted_at__isnull=True, attention_type__is_active=True,
            attention_type__deleted_at__isnull=True).values("id", "attention_type_id", "name"))
        return context

    def form_valid(self, form):
        with transaction.atomic():
            # Serializa envíos del mismo cliente y vuelve a comprobar su vigencia.
            recipient = ServiceRecipient.objects.select_for_update().get(pk=self.recipient.pk)
            if not recipient.is_enabled:
                raise PermissionDenied
            if not recipient.territory_id or not recipient.address.strip():
                form.add_error(None, "Tu ubicación está incompleta. Solicita a un administrador que registre delegación, territorio y dirección.")
                return self.form_invalid(form)
            territory = Territory.objects.select_for_update().get(pk=recipient.territory_id)
            delegation = Delegation.objects.select_for_update().get(pk=territory.delegation_id)
            if not territory.is_active or territory.deleted_at or delegation.status != "ACTIVE" or delegation.deleted_at:
                form.add_error(None, "Tu ubicación no está vigente. Contacta al administrador.")
                return self.form_invalid(form)
            token = form.cleaned_data["submission_token"]
            existing = ClientRequest.objects.filter(submission_token=token).first()
            if existing:
                if existing.recipient_id != recipient.pk:
                    form.add_error(None, "El formulario venció. Abre un nuevo ingreso.")
                    return self.form_invalid(form)
                messages.info(self.request, "La solicitud ya estaba registrada; no se creó un duplicado.")
                return redirect(self.success_url)
            # Catálogos bloqueados hasta confirmar la escritura.
            data = form.cleaned_data
            parent = AttentionType.objects.select_for_update().filter(pk=data["attention_type"].pk,
                is_active=True, deleted_at__isnull=True).first()
            child = SubattentionType.objects.select_for_update().filter(pk=data["subattention_type"].pk,
                attention_type=parent, is_active=True, deleted_at__isnull=True).first()
            if not parent or not child:
                form.add_error(None, "Una opción dejó de estar vigente. Revisa los datos e intenta nuevamente.")
                return self.form_invalid(form)
            item = ClientRequest.objects.create(recipient=recipient, delegation=delegation, territory=territory, address_snapshot=recipient.address,
                attention_type=parent, subattention_type=child, subject=data["subject"],
                description=data["description"], submission_token=token)
            ClientRequestEvent.objects.create(request=item, status=item.status)
            AuditoriaService.register_change(None, "Ingreso de solicitud ciudadana", item,
                new_value=f"Cuenta {self.request.user.pk}; {item.identifier}")
        messages.success(self.request, "La solicitud se registró correctamente.")
        return redirect(self.success_url)

    def form_invalid(self, form):
        messages.error(self.request, "No se pudo registrar la solicitud. Revisa los datos ingresados.")
        return super().form_invalid(form)


class ClientProfileForm(OwnOfficialProfileForm):
    class Meta(OwnOfficialProfileForm.Meta):
        model = ServiceRecipient

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['email'].required = True

    def clean_email(self):
        value = self.cleaned_data["email"].strip()
        from django.contrib.auth import get_user_model
        if value and (ServiceRecipient.objects.filter(email__iexact=value).exclude(pk=self.instance.pk).exists()
                      or get_user_model().objects.filter(email__iexact=value).exclude(pk=self.instance.user_id).exists()):
            raise ValidationError("Este correo ya está asociado a otra cuenta.")
        return value


class ClientProfileView(ClientAccessMixin, FormView):
    template_name = "client/profile.html"
    form_class = ClientProfileForm
    success_url = reverse_lazy("client_profile")

    def get_form_kwargs(self):
        return {**super().get_form_kwargs(), "instance": self.recipient}

    def get_context_data(self, **kwargs):
        return {**super().get_context_data(**kwargs), "profile_official": self.recipient, "client_portal": True}

    def form_valid(self, form):
        recipient = form.save()
        previous, new = describe_changes(form.previous_snapshot, profile_snapshot(recipient))
        AuditoriaService.register_change(None, "Actualización del perfil de cliente", recipient,
                                        previous_value=previous,
                                        new_value=f"Cuenta {self.request.user.pk}\n{new}")
        messages.success(self.request, "Tus datos personales fueron actualizados correctamente.")
        return redirect(self.success_url)

    def form_invalid(self, form):
        messages.error(self.request, "No se pudo actualizar tu perfil. Revisa los datos ingresados.")
        return super().form_invalid(form)


class ClientPhotoView(ClientAccessMixin, TemplateView):
    def get(self, request, *args, **kwargs):
        if not self.recipient.photo:
            raise Http404
        try:
            response = FileResponse(self.recipient.photo.open("rb"), content_type="image/jpeg")
        except FileNotFoundError:
            raise Http404
        response["X-Content-Type-Options"] = "nosniff"
        response["Cache-Control"] = "private, no-store"
        return response


def staff_requests(user, permission):
    qs = ClientRequest.objects.filter(deleted_at__isnull=True).select_related("recipient", "delegation")
    scope = permission_scope(user, permission)
    if scope == Role.Scope.ALL:
        return qs
    if scope == Role.Scope.DELEGATION:
        return qs.filter(delegation_id__in=delegation_ids(user))
    return qs.none()


class RequestReviewForm(forms.ModelForm):
    class Meta:
        model = ClientRequest
        fields = ["status", "response"]
        labels = {"status": "Estado"}
        widgets = {"status": forms.Select(attrs={"class": "form-select"}),
                   "response": forms.Textarea(attrs={"class": "form-control", "rows": 5, "maxlength": 500})}

    def clean_response(self):
        return clean_description_text(self.cleaned_data["response"])

    def clean(self):
        data = super().clean()
        if data.get("status") == ClientRequest.Status.RESOLVED and not data.get("response"):
            self.add_error("response", "Publica una respuesta antes de marcar la solicitud como resuelta.")
        return data


class StaffRequestQueryMixin:
    permission_required = "activities.view_socialattention"

    def filtered_requests(self):
        queryset = staff_requests(self.request.user, self.permission_required)
        status = self.request.GET.get("status")
        if status in ClientRequest.Status.values:
            queryset = queryset.filter(status=status)
        return search_staff_requests(queryset, self.request.GET.get("q"))


def search_staff_requests(queryset, query):
    if not query:
        return queryset
    match = (Q(recipient__full_name__icontains=query) | Q(subject__icontains=query)
             | Q(delegation__delegation_name__icontains=query))
    if query.upper().startswith("SOL-") and query[4:].isascii() and query[4:].isdigit():
        folio = positive(query[4:], 0)
        if folio:
            match |= Q(pk=folio)
    return queryset.filter(match)


class StaffRequestListView(StaffRequestQueryMixin, ClampedPaginationMixin, ProtectedViewMixin, TemplateView):
    template_name = "client/staff_list.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        page = self.clamp_page(self.filtered_requests())
        return {**context, "page_obj": page, "total": page.paginator.count,
                "query": self.request.GET["q"], "selected_status": self.request.GET["status"],
                "statuses": ClientRequest.Status.choices, "export_url": reverse("staff_client_requests_export")}


class StaffRequestExportView(StaffRequestQueryMixin, ProtectedViewMixin, View):
    def get(self, request):
        queryset = ordered(self.filtered_requests(), "staff_request", request.GET)
        rows = ((item.identifier, str(item.recipient), item.subject, str(item.delegation),
                 item.get_status_display()) for item in queryset.iterator())
        return xlsx_response("solicitudes-ciudadanas", ("Folio", "Solicitante", "Motivo", "Delegación", "Estado"),
                             rows, sheet_title="Solicitudes ciudadanas")


class StaffRequestDetailMixin:
    def request_context(self, item):
        from .views import scoped_attentions

        user = self.request.user
        can_view = user.has_perm("activities.view_socialattention")
        return {
            "citizen_request": item,
            "request_list_url": reverse("activity_maintainer" if self.request.GET.get("desde") == "actividades"
                and user.has_perm("activities.view_activity") else "staff_client_requests"),
            "linked_attentions": scoped_attentions(user, "activities.view_socialattention")
                .filter(case__client_request=item).order_by("-registered_at") if can_view else (),
            "can_review_request": staff_requests(user, "activities.change_socialattention")
                .filter(pk=item.pk).exists() if user.has_perm("activities.change_socialattention") else False,
            "can_register_attention": can_view and user.has_perm("activities.add_socialattention"),
        }


class StaffRequestDetailView(ProtectedViewMixin, View):
    permission_required = "activities.view_socialattention"

    def get(self, request, pk):
        case = get_scoped_object_or_404(request, scoped_cases(request.user), client_request_id=pk)
        list_name = "staff_client_requests"
        if request.GET.get("desde") == "actividades" and request.user.has_perm("activities.view_activity"):
            list_name = "activity_maintainer"
        return render_case(request, case, request_list_url=reverse(list_name))


class StaffRequestReviewView(StaffRequestDetailMixin, ProtectedViewMixin, FormView):
    permission_required = "activities.change_socialattention"
    template_name = "client/staff_review.html"
    form_class = RequestReviewForm
    success_url = reverse_lazy("staff_client_requests")

    def get_form_kwargs(self):
        item = get_object_or_404(staff_requests(self.request.user, self.permission_required), pk=self.kwargs["pk"])
        return {**super().get_form_kwargs(), "instance": item}

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        return {**context, **self.request_context(context["form"].instance)}

    def form_valid(self, form):
        with transaction.atomic():
            allowed = scoped_cases(self.request.user, self.permission_required).values("pk")
            case = get_scoped_object_or_404(self.request, AttentionCase.objects.select_for_update().filter(pk__in=allowed),
                                            client_request_id=self.kwargs["pk"])
            status, response = form.cleaned_data["status"], form.cleaned_data["response"]
            actor = getattr(self.request.user, "official", None)
            if actor is None:
                return self.handle_no_permission()
            if case.is_closed:
                form.add_error(None, "El caso está cerrado.")
                return self.form_invalid(form)
            if status == ClientRequest.Status.RESOLVED and case.next_step:
                form.add_error(None, "Completa o cancela el próximo paso antes de cerrar el caso.")
                return self.form_invalid(form)
            if status == ClientRequest.Status.RECEIVED and case.status != status:
                form.add_error("status", "Una solicitud en revisión no puede volver a Recibida.")
                return self.form_invalid(form)
            if case.status != status or case.response != response:
                if status == ClientRequest.Status.REVIEW and case.responsible_id is None:
                    case.responsible = actor
                change_request_status(case, status, actor, response)
                record_case_event(case, actor, "Respuesta a solicitud ciudadana", case.identifier)
                case.save(update_fields=["responsible", "updated_at"])
        messages.success(self.request, "Registro guardado correctamente.")
        return redirect(self.success_url)

    def form_invalid(self, form):
        messages.error(self.request, "No se pudo guardar la respuesta. Revisa los datos ingresados.")
        return super().form_invalid(form)


@login_required
@never_cache
def home(request):
    if getattr(request.user, "service_recipient", None) is not None and not request.user.is_superuser:
        return redirect("client_requests")
    response = render(request, "base.html")
    add_never_cache_headers(response)
    return response


urlpatterns = [
    path("", ClientListView.as_view(), name="client_requests"),
    path("nueva/", ClientCreateView.as_view(), name="client_request_create"),
    path("<int:pk>/", ClientDetailView.as_view(), name="client_request_detail"),
    path("atenciones/<int:pk>/", ClientPresentialCaseView.as_view(), name="client_presential_case"),
    path("activar/", activate_portal, name="portal_invitation_activate"),
    path("activar/<str:token>/", activate_portal, name="portal_invitation_token"),
    path("perfil/", ClientProfileView.as_view(), name="client_profile"),
    path("perfil/foto/", ClientPhotoView.as_view(), name="client_profile_photo"),
    path("gestion/", StaffRequestListView.as_view(), name="staff_client_requests"),
    path("gestion/exportar/", StaffRequestExportView.as_view(), name="staff_client_requests_export"),
    path("gestion/<int:pk>/detalle/", StaffRequestDetailView.as_view(), name="staff_client_request_detail"),
    path("gestion/<int:pk>/", StaffRequestReviewView.as_view(), name="staff_client_request_review"),
]
