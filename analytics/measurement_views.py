from django import forms
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import OuterRef, Subquery
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views import View

from accounts.models import Role
from analytics.measurement import ADD_PLAN, CHANGE_PLAN, PUBLISH_PLAN, VIEW_PLAN, create_revision, publish_version
from analytics.measurement_forms import MeasurementAdjustmentForm, MeasurementItemForm, NewPlanForm, RevisionForm, VersionForm
from analytics.models import MeasurementAdjustment, MeasurementItem, MeasurementVersion
from common.access import ProtectedViewMixin
from common.exports import xlsx_response
from common.list_state import ordered, query_params
from common.modal_forms import ModalFormOnlyMixin, add_form_success, is_modal_request
from common.pagination import ClampedPaginationMixin
from common.scopes import permission_scope
from configuration.models import Period
from configuration.period_services import lock_period_registry
from configuration.services import AuditoriaService


class MeasurementAccess(ProtectedViewMixin):
    permission_required = (VIEW_PLAN,)

    def has_permission(self):
        return all(permission_scope(self.request.user, perm) == Role.Scope.ALL
                   for perm in self.get_permission_required()) and super().has_permission()

    def load_period(self, period_id, *, lock=False):
        periods = Period.objects.filter(deleted_at__isnull=True)
        if lock:
            periods = periods.select_for_update()
        return get_object_or_404(periods, pk=period_id)


class MeasurementPlanList(ClampedPaginationMixin, MeasurementAccess, View):
    export = False

    def get(self, request, period_id):
        period = self.load_period(period_id)
        state = self.prepare_list_state()
        latest = MeasurementVersion.objects.filter(plan_id=OuterRef("pk")).order_by("-number")
        plans = period.measurement_plans.filter(deleted_at__isnull=True).select_related("position").annotate(
            version_number=Subquery(latest.values("number")[:1]),
            version_published=Subquery(latest.values("published_at")[:1]),
        )
        if state["q"]:
            plans = plans.filter(position__position_name__icontains=state["q"])
        if state["status"]:
            plans = plans.filter(version_published__isnull=state["status"] == "DRAFT")
        plans = ordered(plans, "measurement_plan", state)
        headers = ["Cargo", "Última versión", "Estado"]
        if self.export:
            return xlsx_response("measurement_plan", headers, (
                (str(plan.position), plan.version_number, "Publicada" if plan.version_published else "Borrador")
                for plan in plans
            ), sheet_title="Planes de medición")
        page = self.clamp_page(plans, already_ordered=True)
        rows = [
            {"display_cells": (str(plan.position), plan.version_number), "is_active": bool(plan.version_published),
             "status_code": "PUBLISHED" if plan.version_published else "DRAFT",
             "status_label": "Publicada" if plan.version_published else "Borrador",
             "detail": reverse("measurement_plan_detail", args=[period.pk, plan.pk])}
            for plan in page
        ]
        response = render(request, "maintainers/list.html", {
            **self.list_pagination_context(), "maintainer_kind": "periods",
            "maintainer_title": "Configuración de medición", "list_parent": str(period),
            "list_parent_url": reverse("period_detail", args=[period.pk]),
            "can_add": period.status == Period.Status.OPEN and permission_scope(request.user, ADD_PLAN) == Role.Scope.ALL,
            "create_url": reverse("measurement_plan_create", args=[period.pk]), "create_label": "+ Nuevo plan",
            "export_url": reverse("measurement_plan_export", args=[period.pk]),
            "query": state["q"], "selected_status": state["status"],
            "statuses": (("DRAFT", "Borrador"), ("PUBLISHED", "Publicada")),
            "headers": headers, "rows": rows, "page_obj": page, "total": page.paginator.count,
        })
        response["X-List-URL"] = request.path + "?" + query_params(state).urlencode()
        return response


class MeasurementPlanDetail(MeasurementAccess, View):
    def get(self, request, period_id, plan_id, version_id=None):
        period = self.load_period(period_id)
        plan = get_object_or_404(period.measurement_plans.select_related("position"), pk=plan_id, deleted_at__isnull=True)
        versions = list(plan.versions.all())
        version = get_object_or_404(plan.versions, pk=version_id) if version_id else versions[0]
        can_change = period.status == Period.Status.OPEN and permission_scope(request.user, CHANGE_PLAN) == Role.Scope.ALL
        lines = list(version.items.select_related("item", "function").prefetch_related("adjustments__official"))
        return render(request, "analytics/measurement_detail.html", {
            "period": period, "plan": plan, "versions": versions, "version": version,
            "lines": lines, "total_weight": sum(line.weight or 0 for line in lines),
            "can_edit": can_change and not version.is_published,
            "can_revise": can_change and versions[0].is_published and versions[0].effective_from < period.end_date,
            "can_publish": period.status == Period.Status.OPEN and not version.is_published
            and permission_scope(request.user, PUBLISH_PLAN) == Role.Scope.ALL,
        })


class MeasurementEdit(MeasurementAccess, ModalFormOnlyMixin, View):
    operation = ""
    titles = {
        "plan": "Nuevo plan de medición", "revision": "Nueva versión", "version": "Editar vigencia y umbrales",
        "publish": "Publicar versión", "item": "Configurar ítem", "adjustment": "Configurar ajuste individual",
        "remove_item": "Quitar ítem", "remove_adjustment": "Quitar ajuste individual",
    }

    def get_permission_required(self):
        permission = {"plan": ADD_PLAN, "publish": PUBLISH_PLAN}.get(self.operation, CHANGE_PLAN)
        return (VIEW_PLAN, permission)

    def load(self, period_id, plan_id=None, version_id=None, line_id=None, adjustment_id=None, *, lock=False):
        self.period = self.load_period(period_id, lock=lock)
        self.plan = self.version = self.line = self.adjustment = None
        if self.period.status != Period.Status.OPEN:
            raise PermissionDenied("El período está cerrado.")
        if plan_id is not None:
            self.plan = get_object_or_404(self.period.measurement_plans, pk=plan_id, deleted_at__isnull=True)
        if version_id is not None:
            self.version = get_object_or_404(self.plan.versions, pk=version_id, published_at__isnull=True)
        if line_id is not None:
            self.line = get_object_or_404(self.version.items, pk=line_id)
        if adjustment_id is not None:
            self.adjustment = get_object_or_404(self.line.adjustments, pk=adjustment_id)

    def form(self, data=None):
        if self.operation == "plan":
            return NewPlanForm(data, period=self.period)
        if self.operation == "revision":
            return RevisionForm(data, previous=self.plan.versions.filter(published_at__isnull=False).first())
        if self.operation == "version":
            return VersionForm(data, instance=self.version)
        if self.operation == "item":
            line = self.line or MeasurementItem(version=self.version)
            return MeasurementItemForm(data, instance=line, version=self.version)
        if self.operation == "adjustment":
            adjustment = self.adjustment or MeasurementAdjustment(line=self.line)
            return MeasurementAdjustmentForm(data, instance=adjustment, line=self.line)
        return forms.Form(data)

    def detail_url(self):
        if self.version:
            return reverse("measurement_version_detail", args=[self.period.pk, self.plan.pk, self.version.pk])
        if self.plan:
            return reverse("measurement_plan_detail", args=[self.period.pk, self.plan.pk])
        return reverse("measurement_plan_list", args=[self.period.pk])

    def render_form(self, form):
        notes = {
            "publish": "La versión publicada conservará sus valores. Cualquier corrección se registrará en una nueva versión.",
            "remove_item": "Se quitará el ítem y sus ajustes individuales de este borrador.",
            "remove_adjustment": "El funcionario volverá a usar la configuración del cargo para este ítem.",
        }
        labels = {"publish": "Publicar versión", "remove_item": "Quitar ítem", "remove_adjustment": "Quitar ajuste"}
        return render(self.request, "maintainers/form.html", {
            "form": form, "form_title": self.titles[self.operation], "entity_label": "configuración",
            "maintainer_title": "Configuración de medición", "maintainer_kind": "periods",
            "list_url": self.detail_url(), "form_description": notes.get(self.operation),
            "submit_label": labels.get(self.operation, "Guardar configuración"),
        })

    def get(self, request, **kwargs):
        self.load(**kwargs)
        if self.operation == "revision" and not self.plan.versions.first().is_published:
            raise PermissionDenied("Ya existe un borrador para este plan.")
        return self.render_form(self.form())

    def post(self, request, **kwargs):
        with transaction.atomic():
            lock_period_registry()
            self.load(**kwargs, lock=True)
            if self.operation == "revision" and not self.plan.versions.first().is_published:
                raise PermissionDenied("Ya existe un borrador para este plan.")
            form = self.form(request.POST)
            if not form.is_valid():
                return self.render_form(form)
            try:
                self.save(form)
            except ValidationError as error:
                for field, errors in getattr(error, "message_dict", {}).items():
                    form.add_error(field if field in form.fields else None, errors)
                if not hasattr(error, "message_dict"):
                    form.add_error(None, error)
                return self.render_form(form)
        add_form_success(request, "Registro guardado correctamente.")
        return HttpResponse(status=204) if is_modal_request(request) else redirect(self.detail_url())

    def save(self, form):
        action = self.operation
        if action == "plan":
            self.plan = self.period.measurement_plans.create(position=form.cleaned_data["position"])
            self.version = self.plan.versions.create(number=1, effective_from=self.period.start_date)
        elif action == "revision":
            self.version = create_revision(self.plan, form.cleaned_data["effective_from"])
        elif action == "publish":
            if self.version.number == 1:
                self.version.effective_from = self.period.start_date
            publish_version(self.version)
            self.plan.save(update_fields=["updated_at"])
        elif action == "remove_item":
            self.line.delete()
        elif action == "remove_adjustment":
            self.adjustment.delete()
        else:
            form.save()
        if action in ("plan", "revision"):
            self.plan.save(update_fields=["updated_at"])
        if action == "publish":
            previous = self.plan.versions.filter(number__lt=self.version.number, published_at__isnull=False).first()
            AuditoriaService.register_change(
                official=getattr(self.request.user, "official", None),
                action="Publicación de plan de medición", instance=self.version,
                previous_value=f"Versión {previous.number} ({previous.effective_from:%d-%m-%Y})" if previous else "",
                new_value=(
                    f"{self.plan.position} · Versión {self.version.number} · Vigente desde {self.version.effective_from:%d-%m-%Y}\n"
                    f"Cuenta {self.request.user.pk} ({self.request.user.get_username()})"
                ),
                origin_ip=self.request.META.get("REMOTE_ADDR") or None,
            )
