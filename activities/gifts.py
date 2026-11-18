"""Registro territorial de regalos, con unicidad global por campaña y RUT normalizado."""
from urllib.parse import urlencode

from django import forms
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db import IntegrityError, transaction
from django.db.models import Count, Q
from django.http import HttpResponseBadRequest
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views import View

from accounts.forms import clean_person_name, clean_phone
from accounts.models import Delegation, Role, Territory
from common.access import ProtectedViewMixin, get_scoped_object_or_404
from common.edit_concurrency import edit_conflict, edit_is_current, edit_revision
from common.exports import xlsx_response
from common.maintainer_forms import MaintainerForm
from common.maintainers import activity_queryset
from common.modal_forms import ModalFormOnlyMixin, add_form_success
from common.scopes import delegation_ids, permission_scope
from common.text import format_snapshot
from configuration.services import AuditoriaService

from .gift_models import GiftCampaign, GiftRegistration, GiftRegistrationEvent, canonical_gift_rut

VIEW = "activities.view_giftregistration"
ADD = "activities.add_giftregistration"
CHANGE = "activities.change_giftregistration"
DELIVER = "activities.deliver_giftregistration"
CANCEL = "activities.cancel_giftregistration"
VIEW_CAMPAIGN = "activities.view_giftcampaign"


def allowed_delegations(user, *permissions, active_only=True):
    rows = Delegation.objects.all()
    if active_only:
        rows = rows.filter(deleted_at__isnull=True, status="ACTIVE")
    for permission in permissions:
        scope = permission_scope(user, permission)
        if scope == Role.Scope.DELEGATION:
            rows = rows.filter(pk__in=delegation_ids(user))
        elif scope != Role.Scope.ALL:
            return rows.none()
    return rows


def campaigns_for(user, *permissions):
    delegates = allowed_delegations(user, *permissions, active_only=False)
    return GiftCampaign.objects.filter(deleted_at__isnull=True, delegations__in=delegates).distinct()


def registrations_for(user, permission=VIEW):
    return GiftRegistration.objects.filter(
        deleted_at__isnull=True, delegation__in=allowed_delegations(user, VIEW, permission, active_only=False),
    )


def editable_campaigns(user):
    ids = allowed_delegations(user, VIEW_CAMPAIGN, "activities.change_giftcampaign", active_only=False).values("pk")
    # Un delegado no puede quitar la participación de otra delegación.
    return campaigns_for(user, VIEW_CAMPAIGN).exclude(
        delegations__in=Delegation.objects.exclude(pk__in=ids),
    )


def campaign_available(campaign):
    today = timezone.localdate()
    if not campaign.is_open or not campaign.start_date <= today <= campaign.end_date:
        raise ValidationError("La campaña debe estar abierta y dentro de sus fechas para inscribir, editar o entregar.")


def delegation_option(delegation):
    status = "Archivada" if delegation.deleted_at else delegation.get_status_display()
    return f"{delegation} · {status}"


class CampaignForm(MaintainerForm):
    class Meta:
        model = GiftCampaign
        fields = ("name", "celebration", "year", "start_date", "end_date", "delegations", "is_open")

    def __init__(self, *args, actor, **kwargs):
        super().__init__(*args, actor=actor, **kwargs)
        permission = "activities.change_giftcampaign" if self.instance.pk else "activities.add_giftcampaign"
        permitted = allowed_delegations(actor, VIEW_CAMPAIGN, permission, active_only=False)
        current = self.instance.delegations.values("pk") if self.instance.pk else []
        self.fields["delegations"].queryset = permitted.filter(
            Q(status="ACTIVE", deleted_at__isnull=True) | Q(pk__in=current),
        )
        self.fields["delegations"].help_text = "Las delegaciones inactivas o archivadas ya participantes se conservan para gestionar el historial."
        self.fields["delegations"].label_from_instance = delegation_option
        self.fields["name"].widget.attrs.pop("data-field-pattern", None)
        self.fields["is_open"].widget = forms.Select(choices=((True, "Abierta"), (False, "Cerrada")), attrs={"class": "form-select"})

    def clean_delegations(self):
        delegates = self.cleaned_data["delegations"]
        if self.instance.pk:
            used = self.instance.registrations.values_list("delegation_id", flat=True)
            if set(used) - set(delegates.values_list("pk", flat=True)):
                raise ValidationError("Conserva las delegaciones que ya tienen inscripciones, incluidas las anuladas.")
        return delegates

    def clean(self):
        data = super().clean()
        if self.instance.pk and self.instance.registrations.exists():
            for field in ("celebration", "year"):
                if field in self.changed_data:
                    self.add_error(field, "Conserva la celebración y el año de una campaña con inscripciones.")
        return data


class RegistrationForm(MaintainerForm):
    class Meta:
        model = GiftRegistration
        fields = ("child_rut", "child_name", "guardian_rut", "guardian_name", "phone", "territory", "activity", "notes")

    def __init__(self, *args, actor, **kwargs):
        super().__init__(*args, actor=actor, **kwargs)
        permission = CHANGE if self.instance.pk else ADD
        delegates = allowed_delegations(actor, VIEW, permission)
        if self.instance.pk:
            delegates = delegates.filter(pk=self.instance.delegation_id)
        current = Q(pk__in=[])
        if self.instance.pk and allowed_delegations(actor, VIEW, permission, active_only=False).filter(pk=self.instance.delegation_id).exists():
            current = Q(pk=self.instance.territory_id)
        self.fields["territory"].queryset = Territory.objects.filter(Q(
            is_active=True, deleted_at__isnull=True, delegation__in=delegates,
            delegation__gift_campaigns=self.instance.campaign,
        ) | current)
        activities = activity_queryset(actor, "activities.view_activity")
        if not actor.has_perm("activities.view_activity"):
            activities = activities.none()
        self.fields["activity"].queryset = activities.filter(
            registration_delegation__in=delegates,
            registration_delegation__gift_campaigns=self.instance.campaign,
        ).distinct()
        self.fields["activity"].label_from_instance = lambda activity: f"{activity.code} · {activity.date:%d-%m-%Y} · {activity.subject or activity.item}"
        self.fields["activity"].help_text = "Selecciona la jornada de la misma delegación. Las evidencias se adjuntan desde esa actividad."
        self.fields["child_rut"].help_text = "Un menor puede inscribirse una sola vez por campaña, entre todas las delegaciones."

    def clean_child_rut(self):
        return canonical_gift_rut(self.cleaned_data["child_rut"])

    def clean_guardian_rut(self):
        return canonical_gift_rut(self.cleaned_data["guardian_rut"])

    def clean_phone(self):
        return clean_phone(self.cleaned_data["phone"])

    def clean_child_name(self):
        return clean_person_name(self.cleaned_data["child_name"])

    def clean_guardian_name(self):
        return clean_person_name(self.cleaned_data["guardian_name"])

    def clean(self):
        data = super().clean()
        rut = data.get("child_rut")
        if rut:
            existing = GiftRegistration.objects.filter(campaign=self.instance.campaign, child_rut=rut).exclude(
                pk=self.instance.pk).select_related("delegation").first()
            if existing:
                self.add_error("child_rut", f"RUT ya ingresado por la delegación {existing.delegation.delegation_name} en esta campaña. También se conservan las inscripciones anuladas.")
        return data


class RegistrationActionForm(forms.Form):
    observation = forms.CharField(label="Observación", required=False, max_length=500,
                                  widget=forms.Textarea(attrs={"class": "form-control", "rows": 3}))

    def __init__(self, *args, cancel=False, **kwargs):
        super().__init__(*args, **kwargs)
        if cancel:
            self.fields["observation"].required = True
            self.fields["observation"].label = "Motivo de anulación"


def audit(request, obj, action, previous, current):
    labels = {field.name: str(field.verbose_name) for field in obj._meta.concrete_fields}
    labels.update(status="Estado", campaign="Campaña", delegation="Delegación", activity="Actividad",
                  delivered_at="Fecha de entrega", delivered_by="Responsable", delegations="Delegaciones")
    AuditoriaService.register_change(
        getattr(request.user, "official", None), action, obj,
        previous_value=format_snapshot({labels.get(key, key): value for key, value in previous.items()}),
        new_value=format_snapshot({labels.get(key, key): value for key, value in current.items()}),
        origin_ip=request.META.get("REMOTE_ADDR") or None, actor=request.user,
    )


def snapshot(obj):
    return {field.name: str(getattr(obj, field.attname)) for field in obj._meta.concrete_fields}


class CampaignList(ProtectedViewMixin, View):
    permission_required = VIEW_CAMPAIGN

    def get(self, request):
        rows = campaigns_for(request.user, VIEW_CAMPAIGN).prefetch_related("delegations")
        return render(request, "activities/gift_campaigns.html", {
            "page_obj": Paginator(rows, 15).get_page(request.GET.get("page")),
            "can_add": request.user.has_perm("activities.add_giftcampaign"),
            "editable_ids": set(editable_campaigns(request.user).values_list("pk", flat=True)),
        })


class CampaignEdit(ProtectedViewMixin, ModalFormOnlyMixin, View):
    def get_permission_required(self):
        return (VIEW_CAMPAIGN, "activities.change_giftcampaign" if self.kwargs.get("pk") else "activities.add_giftcampaign")

    def display(self, request, obj, form, revision=None):
        return render(request, "analytics/operation_form.html", {"form": form,
            "maintainer_title": "Editar campaña de regalos" if obj.pk else "Nueva campaña de regalos",
            "back_url": reverse("gift_campaign_list"), "sidebar_active": "gifts", "edit_revision": revision})

    def get(self, request, pk=None):
        obj = get_scoped_object_or_404(request, editable_campaigns(request.user), pk=pk) if pk else GiftCampaign(year=timezone.localdate().year)
        revision = edit_revision(obj, memberships=[obj.delegations.values_list("pk", flat=True)]) if pk else None
        return self.display(request, obj, CampaignForm(instance=obj, actor=request.user), revision)

    def post(self, request, pk=None):
        with transaction.atomic():
            obj = get_scoped_object_or_404(request, GiftCampaign.objects.select_for_update().filter(
                pk__in=editable_campaigns(request.user).values("pk")), pk=pk) if pk else GiftCampaign()
            if pk and not edit_is_current(request, edit_revision(obj, memberships=[obj.delegations.values_list("pk", flat=True)])):
                return edit_conflict()
            previous = snapshot(obj) if pk else {}
            if pk:
                previous["delegations"] = list(obj.delegations.values_list("pk", flat=True))
            form = CampaignForm(request.POST, instance=obj, actor=request.user)
            if form.is_valid():
                try:
                    with transaction.atomic():
                        obj = form.save()
                except IntegrityError:
                    form.add_error(None, "Ya existe una campaña para esta celebración y año. Actualiza el listado.")
                else:
                    current = snapshot(obj)
                    current["delegations"] = list(obj.delegations.values_list("pk", flat=True))
                    audit(request, obj, "Campaña de regalos guardada", previous, current)
                    add_form_success(request, "Campaña guardada correctamente.")
                    return redirect("gift_campaign_list")
            return self.display(request, obj, form, request.POST.get("edit_revision"))


class RegistrationList(ProtectedViewMixin, View):
    permission_required = (VIEW_CAMPAIGN, VIEW)

    def get(self, request, campaign_id):
        campaign = get_scoped_object_or_404(request, campaigns_for(request.user, VIEW_CAMPAIGN), pk=campaign_id)
        rows = registrations_for(request.user).filter(campaign=campaign).select_related("territory", "delegation")
        q = request.GET.get("q", "").strip()[:150]
        status = request.GET.get("status", "")
        delegation = request.GET.get("delegation", "")
        if q:
            search_rut = q.replace(".", "").upper()
            rows = rows.filter(Q(child_name__icontains=q) | Q(child_rut__icontains=search_rut)
                               | Q(guardian_name__icontains=q) | Q(guardian_rut__icontains=search_rut))
        if status in GiftRegistration.Status.values:
            rows = rows.filter(status=status)
        else:
            status = ""
        if delegation.isascii() and delegation.isdecimal() and len(delegation) <= 19:
            rows = rows.filter(delegation_id=delegation)
        else:
            delegation = ""
        filters = {"q": q, "status": status, "delegation": delegation}
        if request.GET.get("export") == "xlsx":
            return xlsx_response(f"regalos-campana-{campaign.pk}",
                ["Código", "Campaña", "RUT menor", "Menor", "RUT adulto", "Adulto responsable", "Teléfono", "Territorio", "Delegación", "Estado", "Fecha entrega", "Actividad", "Observaciones", "Motivo anulación"],
                ((str(row), str(campaign), row.child_rut, row.child_name, row.guardian_rut, row.guardian_name,
                  row.phone, row.territory.territory_name, row.delegation.delegation_name, row.get_status_display(),
                  timezone.localtime(row.delivered_at).strftime("%d-%m-%Y %H:%M") if row.delivered_at else "",
                  row.activity.code if row.activity else "", row.notes, row.cancellation_reason)
                 for row in rows.select_related("activity")), sheet_title="Regalos")
        counts = dict(rows.order_by().values("status").annotate(total=Count("pk")).values_list("status", "total"))
        return render(request, "activities/gift_registrations.html", {
            "campaign": campaign, "page_obj": Paginator(rows, 15).get_page(request.GET.get("page")),
            "counts": [(label, counts.get(value, 0)) for value, label in GiftRegistration.Status.choices],
            "total": sum(counts.values()), "filters": filters, "filter_query": urlencode(filters),
            "status_choices": GiftRegistration.Status.choices,
            "delegations": campaign.delegations.filter(pk__in=allowed_delegations(request.user, VIEW, active_only=False).values("pk")),
            "can_add": request.user.has_perm(ADD),
        })


class RegistrationDetail(ProtectedViewMixin, View):
    permission_required = (VIEW_CAMPAIGN, VIEW)

    def get(self, request, pk):
        obj = get_scoped_object_or_404(request, registrations_for(request.user).select_related(
            "campaign", "territory", "delegation", "activity", "registered_by", "delivered_by"), pk=pk)
        can_act = obj.status == GiftRegistration.Status.REGISTERED
        visible_activity = obj.activity_id and request.user.has_perm("activities.view_activity") and activity_queryset(
            request.user, "activities.view_activity").filter(pk=obj.activity_id).exists()
        return render(request, "activities/gift_detail.html", {"record": obj,
            "events": obj.events.select_related("actor"), "visible_activity": visible_activity,
            "can_edit": can_act and registrations_for(request.user, CHANGE).filter(pk=pk).exists(),
            "can_deliver": can_act and registrations_for(request.user, DELIVER).filter(pk=pk).exists(),
            "can_cancel": can_act and registrations_for(request.user, CANCEL).filter(pk=pk).exists(),
        })


class RegistrationEdit(ProtectedViewMixin, ModalFormOnlyMixin, View):
    operation = "edit"

    def get_permission_required(self):
        permission = {"deliver": DELIVER, "cancel": CANCEL}.get(self.operation, CHANGE if self.kwargs.get("pk") else ADD)
        return (VIEW_CAMPAIGN, VIEW, permission)

    def load(self, request, pk, campaign_id, lock=False):
        if pk:
            permission = self.get_permission_required()[-1]
            obj = get_scoped_object_or_404(request, registrations_for(request.user, permission), pk=pk)
            campaign_id = obj.campaign_id
        campaigns = campaigns_for(request.user, VIEW_CAMPAIGN)
        # Todas las escrituras de inscripciones se serializan por campaña antes de leer la versión.
        if lock:
            campaigns = GiftCampaign.objects.select_for_update().filter(pk__in=campaigns.values("pk"))
        campaign = get_scoped_object_or_404(request, campaigns, pk=campaign_id)
        if pk:
            return get_scoped_object_or_404(request, registrations_for(request.user, permission), pk=pk)
        return GiftRegistration(campaign=campaign, registered_by=request.user)

    def form(self, request, obj, data=None):
        if self.operation != "edit":
            return RegistrationActionForm(data, cancel=self.operation == "cancel")
        return RegistrationForm(data, instance=obj, actor=request.user)

    def display(self, request, obj, form, revision=None):
        title = {"deliver": "Confirmar entrega de regalo", "cancel": "Anular inscripción"}.get(self.operation, "Editar inscripción" if obj.pk else "Inscribir beneficiario")
        return render(request, "analytics/operation_form.html", {"form": form,
            "maintainer_title": f"{title} · {obj.campaign}", "sidebar_active": "gifts", "edit_revision": revision,
            "operation_summary": f"{obj} · {obj.child_name} · {obj.child_rut}" if obj.pk else "La inscripción reserva el RUT del menor en esta campaña, incluso si se anula posteriormente.",
            "back_url": reverse("gift_registration_detail", args=[obj.pk]) if obj.pk else reverse("gift_registration_list", args=[obj.campaign_id])})

    def get(self, request, pk=None, campaign_id=None):
        obj = self.load(request, pk, campaign_id)
        return self.display(request, obj, self.form(request, obj), edit_revision(obj) if pk else None)

    def post(self, request, pk=None, campaign_id=None):
        if self.operation not in ("edit", "deliver", "cancel"):
            return HttpResponseBadRequest()
        with transaction.atomic():
            obj = self.load(request, pk, campaign_id, lock=True)
            if pk and not edit_is_current(request, edit_revision(obj)):
                return edit_conflict()
            previous = snapshot(obj) if pk else {}
            form = self.form(request, obj, request.POST)
            valid = form.is_valid()
            if obj.status != GiftRegistration.Status.REGISTERED:
                form.add_error(None, "Solo se pueden modificar inscripciones en estado Inscrito.")
            if self.operation != "cancel":
                try:
                    campaign_available(obj.campaign)
                except ValidationError as error:
                    form.add_error(None, error)
            if valid and not form.errors:
                observation = form.cleaned_data.get("observation", "")
                if self.operation == "deliver":
                    obj.status = GiftRegistration.Status.DELIVERED
                    obj.delivered_at = timezone.now()
                    obj.delivered_by = request.user
                elif self.operation == "cancel":
                    obj.status = GiftRegistration.Status.CANCELLED
                    obj.cancellation_reason = observation
                try:
                    with transaction.atomic():
                        obj.full_clean()
                        if not obj.campaign.delegations.filter(pk=obj.delegation_id).exists():
                            raise ValidationError("La delegación debe participar en la campaña.")
                        obj.save()
                except ValidationError as error:
                    form.add_error(None, error.messages)
                except IntegrityError:
                    form.add_error(None, "No se pudo guardar. Comprueba los datos y si el RUT ya está inscrito en la campaña.")
                else:
                    action = {"deliver": "Regalo entregado", "cancel": "Inscripción de regalo anulada"}.get(self.operation, "Inscripción de regalo editada" if pk else "Inscripción de regalo creada")
                    current = snapshot(obj)
                    GiftRegistrationEvent.objects.create(registration=obj, actor=request.user, action=action,
                        observation=observation, previous=previous, current=current)
                    audit(request, obj, action, previous, current)
                    add_form_success(request, "Registro guardado correctamente.")
                    return redirect("gift_registration_detail", pk=obj.pk)
            return self.display(request, obj, form, request.POST.get("edit_revision"))
