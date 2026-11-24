from datetime import timedelta

from django import forms
from django.contrib import messages
from django.core.exceptions import ValidationError
from django.db import transaction
from django.shortcuts import redirect, render
from django.views import View

from accounts.models import Delegation, Role
from common.access import ProtectedViewMixin
from .models import RegistrationWeek
from .period_services import lock_period_registry
from .services import AuditoriaService


def week_start(day):
    return day - timedelta(days=day.weekday())


def check_registration_week(day, delegation_id):
    if RegistrationWeek.objects.filter(delegation_id=delegation_id, monday=week_start(day), closed=True).exists():
        raise ValidationError("La semana de registro está cerrada para esta delegación.")


def can_manage_weeks(user):
    official = getattr(user, "official", None)
    return user.is_superuser or bool(official and official.is_enabled and official.roles.filter(
        role_name__in=("Administrador", "Coordinador del sistema"), scope=Role.Scope.ALL,
        is_active=True, deleted_at__isnull=True).exists())


class WeekForm(forms.Form):
    delegation = forms.ModelChoiceField(label="Delegación", queryset=Delegation.objects.filter(deleted_at__isnull=True))
    day = forms.DateField(label="Fecha de la semana (lunes a domingo)", widget=forms.DateInput(attrs={"type": "date"}))
    action = forms.ChoiceField(label="Acción", choices=(("close", "Cerrar semana"), ("open", "Reabrir semana")))
    reason = forms.CharField(label="Motivo", max_length=500)


class WeekView(ProtectedViewMixin, View):
    permission_required = "agenda.view_commitment"

    def has_permission(self):
        return super().has_permission() and can_manage_weeks(self.request.user)

    def show(self, form):
        return render(self.request, "agenda/registration_weeks.html", {
            "form": form, "weeks": RegistrationWeek.objects.filter(closed=True).select_related("delegation").order_by("-monday"),
        })

    def get(self, request):
        return self.show(WeekForm())

    def post(self, request):
        form = WeekForm(request.POST)
        if form.is_valid():
            data = form.cleaned_data
            with transaction.atomic():
                lock_period_registry()
                monday = week_start(data["day"])
                week = RegistrationWeek.objects.filter(monday=monday, delegation=data["delegation"]).first()
                closed = data["action"] == "close"
                if bool(week and week.closed) == closed:
                    form.add_error(None, "La semana ya tiene el estado solicitado.")
                    return self.show(form)
                week = week or RegistrationWeek(monday=monday, delegation=data["delegation"])
                week.closed = closed
                week.save()
                AuditoriaService.register_change(official=getattr(request.user, "official", None), actor=request.user,
                    action="Cierre semanal" if closed else "Reapertura semanal", instance=week,
                    previous_value="Abierta" if closed else "Cerrada",
                    new_value=f"{week.delegation} · {monday} · {data['reason']}")
            messages.success(request, "Estado de la semana actualizado.")
            return redirect("registration_weeks")
        return self.show(form)
