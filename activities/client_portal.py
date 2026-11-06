import uuid

from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.db import transaction
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import path, reverse_lazy
from django.utils.cache import add_never_cache_headers
from django.views.decorators.cache import never_cache
from django.views.generic import FormView, TemplateView

from accounts.forms import OwnOfficialProfileForm
from accounts.models import Delegation, Role, ServiceRecipient, Territory
from common.pagination import ClampedPaginationMixin
from common.access import ProtectedViewMixin
from common.scopes import delegation_ids, permission_scope
from common.text import clean_description_text, normalize_spaces
from configuration.models import AttentionType, SubattentionType
from configuration.services import AuditoriaService
from .models import ClientRequest, ClientRequestEvent


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
        qs = self.requests()
        query = normalize_spaces(self.request.GET.get("q"))[:200]
        status = self.request.GET.get("status", "")
        if query:
            from django.db.models import Q
            match = Q(subject__icontains=query)
            if query.upper().startswith("SOL-") and query[4:].isdigit():
                match |= Q(pk=int(query[4:]))
            qs = qs.filter(match)
        if status in ClientRequest.Status.values:
            qs = qs.filter(status=status)
        else:
            status = ""
        page = self.clamp_page(qs)
        from django.http import QueryDict
        params = QueryDict(mutable=True)
        params.update({key: value for key, value in self.request.GET.items() if key != "page"})
        context.update(page_obj=page, query=query, selected_status=status,
                       statuses=ClientRequest.Status.choices, querystring=params.urlencode())
        return context


class ClientDetailView(ClientAccessMixin, TemplateView):
    template_name = "client/detail.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["attention_request"] = get_object_or_404(self.requests(), pk=self.kwargs["pk"])
        return context


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
        form.save()
        AuditoriaService.register_change(None, "Actualización del perfil de cliente", self.recipient,
                                        new_value=f"Cuenta {self.request.user.pk}")
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


class StaffRequestListView(ClampedPaginationMixin, ProtectedViewMixin, TemplateView):
    permission_required = "activities.view_socialattention"
    template_name = "client/staff_list.html"

    def get_context_data(self, **kwargs):
        return {**super().get_context_data(**kwargs), "page_obj": self.clamp_page(
            staff_requests(self.request.user, self.permission_required))}


class StaffRequestReviewView(ProtectedViewMixin, FormView):
    permission_required = "activities.change_socialattention"
    template_name = "client/staff_review.html"
    form_class = RequestReviewForm
    success_url = reverse_lazy("staff_client_requests")

    def get_form_kwargs(self):
        item = get_object_or_404(staff_requests(self.request.user, self.permission_required), pk=self.kwargs["pk"])
        return {**super().get_form_kwargs(), "instance": item}

    def form_valid(self, form):
        with transaction.atomic():
            item = get_object_or_404(staff_requests(self.request.user, self.permission_required).select_for_update(), pk=self.kwargs["pk"])
            if item.status != form.cleaned_data["status"] or item.response != form.cleaned_data["response"]:
                previous = item.status
                item.status, item.response = form.cleaned_data["status"], form.cleaned_data["response"]
                item.save(update_fields=["status", "response", "updated_at"])
                ClientRequestEvent.objects.create(request=item, status=item.status, response=item.response)
                AuditoriaService.register_change(getattr(self.request.user, "official", None),
                    "Respuesta a solicitud ciudadana", item, previous_value=previous, new_value=item.status)
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
    path("perfil/", ClientProfileView.as_view(), name="client_profile"),
    path("perfil/foto/", ClientPhotoView.as_view(), name="client_profile_photo"),
    path("gestion/", StaffRequestListView.as_view(), name="staff_client_requests"),
    path("gestion/<int:pk>/", StaffRequestReviewView.as_view(), name="staff_client_request_review"),
]
