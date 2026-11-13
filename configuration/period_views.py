from django import forms
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views import View

from accounts.models import Role
from common.access import ProtectedViewMixin
from common.modal_forms import ModalFormOnlyMixin, add_form_success
from common.scopes import permission_scope
from common.text import normalize_spaces
from configuration.models import Period
from configuration.period_services import lock_period_registry
from configuration.services import AuditoriaService


class PeriodReopenForm(forms.Form):
    reason = forms.CharField(
        label="Motivo de reapertura", max_length=500, widget=forms.Textarea(
            attrs={"class": "form-control", "rows": 3, "maxlength": 500},
        ),
    )

    def clean_reason(self):
        reason = normalize_spaces(self.cleaned_data["reason"])
        if not reason:
            raise forms.ValidationError("Indica el motivo de la reapertura.")
        return reason


class PeriodReopenView(ProtectedViewMixin, ModalFormOnlyMixin, View):
    permission_required = ("configuration.reopen_period", "configuration.view_period")

    def has_permission(self):
        return permission_scope(self.request.user, "configuration.reopen_period") == Role.Scope.ALL and super().has_permission()

    def render_form(self, period, form):
        return render(self.request, "maintainers/form.html", {
            "form": form, "form_title": "Reabrir período", "maintainer_title": "Períodos",
            "maintainer_kind": "periods", "list_url": reverse("period_detail", args=[period.pk]),
            "submit_label": "Reabrir período",
            "form_description": f"El período {period} volverá a admitir registros y correcciones autorizados.",
        })

    def get(self, request, period_id):
        period = get_object_or_404(Period, pk=period_id, status=Period.Status.CLOSED, deleted_at__isnull=True)
        return self.render_form(period, PeriodReopenForm())

    def post(self, request, period_id):
        with transaction.atomic():
            lock_period_registry()
            period = get_object_or_404(
                Period.objects.select_for_update(), pk=period_id, status=Period.Status.CLOSED, deleted_at__isnull=True,
            )
            form = PeriodReopenForm(request.POST)
            if not form.is_valid():
                return self.render_form(period, form)
            period.status = Period.Status.OPEN
            period.first_closed_at = period.first_closed_at or period.updated_at
            period.save(update_fields=["status", "first_closed_at", "updated_at"])
            AuditoriaService.register_change(
                official=getattr(request.user, "official", None), action="Reapertura de período",
                instance=period, previous_value="Cerrado",
                new_value=(f"Abierto. Motivo: {form.cleaned_data['reason']}\n"
                           f"Cuenta {request.user.pk} ({request.user.get_username()})"),
                origin_ip=request.META.get("REMOTE_ADDR") or None,
            )
        add_form_success(request, "Período reabierto correctamente.")
        return redirect("period_detail", pk=period.pk)
