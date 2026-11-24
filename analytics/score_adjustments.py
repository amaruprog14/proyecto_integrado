from django import forms
from django.contrib import messages
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views import View

from accounts.models import Official, Role
from analytics.measurement import historical_position_id, version_for
from analytics.models import ScoreAdjustment
from common.access import ProtectedViewMixin
from common.maintainer_forms import MaintainerForm
from common.scopes import permission_scope, scope_officials
from configuration.models import Period
from configuration.period_services import lock_open_period, lock_period_registry
from configuration.services import AuditoriaService

def score_officials(user, permission):
    return scope_officials(Official.objects.all(), user, permission)


OWN_REVIEW_MESSAGE = "No puedes validar un registro que ingresaste tú. Debe validarlo otra cuenta autorizada."
SUBJECT_REVIEW_MESSAGE = ("No puedes validar un reclamo o felicitación sobre ti. "
                          "Debe validarlo otra cuenta autorizada.")

class ScoreAdjustmentForm(MaintainerForm):
    class Meta:
        model = ScoreAdjustment
        fields = ("official", "occurred_on", "kind", "channel", "reason", "written_support")
        help_texts = {"written_support": "Registra el contenido escrito y la referencia que permite comprobar su origen."}

    def __init__(self, *args, actor=None, **kwargs):
        super().__init__(*args, actor=actor, **kwargs)
        self.fields["official"].queryset = score_officials(actor, ScoreAdjustment.ADD_PERMISSION).filter(
            pk__in=score_officials(actor, ScoreAdjustment.VIEW_PERMISSION).values("pk"), deleted_at__isnull=True,
        )
        self.fields["written_support"].widget.attrs.update(maxlength=4000, rows=5)

    def clean_occurred_on(self):
        occurred_on = self.cleaned_data["occurred_on"]
        if occurred_on > timezone.localdate():
            raise ValidationError("La fecha del registro no puede ser futura.")
        return occurred_on


class ScoreAdjustmentReviewForm(forms.Form):
    decision = forms.ChoiceField(label="Decisión", choices=(
        (ScoreAdjustment.Status.APPROVED, "Aprobar"),
        (ScoreAdjustment.Status.REJECTED, "Rechazar"),
    ), widget=forms.Select(attrs={"class": "form-select"}))
    note = forms.CharField(
        label="Motivo de la decisión", max_length=500, required=False,
        widget=forms.Textarea(attrs={"class": "form-control", "rows": 3, "maxlength": 500}),
        help_text="Obligatorio si rechazas el registro.",
    )

    delegate_reference = forms.CharField(label="Referencia del oficio o correo del delegado", max_length=250,
                                         required=False, widget=forms.TextInput(attrs={"class": "form-control"}),
                                         help_text="Para aprobar, indica el folio del oficio o la referencia del correo.")
    delegate_origin_confirmed = forms.BooleanField(label="Confirmo que el respaldo formal proviene del delegado",
                                                   required=False)

    def __init__(self, *args, record, **kwargs):
        super().__init__(*args, **kwargs)
        if record.kind != ScoreAdjustment.Kind.CONGRATULATION:
            del self.fields["delegate_reference"]
            del self.fields["delegate_origin_confirmed"]

    def clean(self):
        data = super().clean()
        if data.get("decision") == ScoreAdjustment.Status.APPROVED and "delegate_reference" in self.fields:
            if not data.get("delegate_reference"):
                self.add_error("delegate_reference", "Indica la referencia del oficio o correo del delegado.")
            if not data.get("delegate_origin_confirmed"):
                self.add_error("delegate_origin_confirmed", "Verifica el origen del respaldo antes de aprobar.")
        if data.get("decision") == ScoreAdjustment.Status.REJECTED and not data.get("note"):
            self.add_error("note", "Indica el motivo del rechazo.")
        return data


class ScoreAdjustmentAccess(ProtectedViewMixin):
    permission_required = (ScoreAdjustment.VIEW_PERMISSION,)

    def has_permission(self):
        if not super().has_permission():
            return False
        return all(
            permission_scope(self.request.user, permission) is not None
            for permission in self.get_permission_required()
        )

    def records(self):
        return ScoreAdjustment.objects.filter(
            official_id__in=score_officials(self.request.user, ScoreAdjustment.VIEW_PERMISSION).values("pk"),
            deleted_at__isnull=True,
        )

    def audit(self, record, action, previous="", new=""):
        AuditoriaService.register_change(
            official=getattr(self.request.user, "official", None),
            action=action, instance=record, previous_value=previous,
            new_value=f"{new}\nCuenta responsable: {self.request.user.pk}",
            origin_ip=self.request.META.get("REMOTE_ADDR") or None,
            actor=self.request.user,
        )


class ScoreAdjustmentList(ScoreAdjustmentAccess, View):
    def get(self, request):
        status = request.GET.get("estado", "")
        records = self.records().select_related("official")
        if status in ScoreAdjustment.Status.values:
            records = records.filter(status=status)
        page = Paginator(records, 25).get_page(request.GET.get("page"))
        return render(request, "analytics/score_adjustment_list.html", {
            "page_obj": page, "status": status, "statuses": ScoreAdjustment.Status.choices,
            "can_add": permission_scope(request.user, ScoreAdjustment.ADD_PERMISSION) is not None,
        })


class ScoreAdjustmentCreate(ScoreAdjustmentAccess, View):
    permission_required = (ScoreAdjustment.VIEW_PERMISSION, ScoreAdjustment.ADD_PERMISSION)

    def render_form(self, form):
        return render(self.request, "maintainers/form.html", {
            "form": form, "form_title": "Registrar reclamo o felicitación",
            "maintainer_title": "Reclamos y felicitaciones", "maintainer_kind": "score_adjustments",
            "list_url": reverse("score_adjustment_list"), "submit_label": "Enviar a validación",
        })

    def get(self, request):
        return self.render_form(ScoreAdjustmentForm(actor=request.user))

    def post(self, request):
        form = ScoreAdjustmentForm(request.POST, actor=request.user)
        if not form.is_valid():
            return self.render_form(form)
        try:
            with transaction.atomic():
                lock_period_registry()
                record = form.save(commit=False)
                record.period = lock_open_period(record.occurred_on)
                record.recorded_by = request.user
                record.save()
                self.audit(record, "Registro de reclamo o felicitación",
                           new=f"{record.get_kind_display()} · Funcionario {record.official_id} · Pendiente")
        except ValidationError as error:
            form.add_error("occurred_on", error)
            return self.render_form(form)
        messages.success(request, "Registro ingresado. Quedó pendiente de validación.")
        return redirect("score_adjustment_detail", pk=record.pk)


class ScoreAdjustmentDetail(ScoreAdjustmentAccess, View):
    def get_permission_required(self):
        if self.request.method == "POST":
            return (*self.permission_required, ScoreAdjustment.REVIEW_PERMISSION)
        return self.permission_required

    def can_review(self):
        return permission_scope(self.request.user, ScoreAdjustment.REVIEW_PERMISSION) == Role.Scope.ALL

    def has_permission(self):
        return super().has_permission() and (self.request.method != "POST" or self.can_review())

    def review_conflict(self, record):
        """Segregación de funciones, por cuenta de usuario: no valida quien registró ni el
        funcionario afectado (aunque lo haya registrado otra persona). Devuelve el motivo o None."""
        user_id = self.request.user.pk
        if record.recorded_by_id == user_id:
            return "own"
        if record.official.user_id is not None and record.official.user_id == user_id:
            return "subject"
        return None

    def render_detail(self, record, form=None, status=200):
        conflict = self.review_conflict(record)
        if form is None and not conflict and self.can_review() and record.status == ScoreAdjustment.Status.PENDING:
            if record.period.status == Period.Status.OPEN and record.period.deleted_at is None:
                form = ScoreAdjustmentReviewForm(record=record)
        blocked = conflict if record.status == ScoreAdjustment.Status.PENDING and self.can_review() else None
        return render(self.request, "analytics/score_adjustment_detail.html", {
            "record": record, "form": form, "own_pending": blocked == "own", "subject_pending": blocked == "subject",
        }, status=status)

    def get(self, request, pk):
        record = get_object_or_404(self.records().select_related(
            "official", "period", "recorded_by__official", "reviewed_by__official", "version__plan__position",
        ), pk=pk)
        return self.render_detail(record)

    def post(self, request, pk):
        record = get_object_or_404(self.records().select_related("official", "period"), pk=pk)
        if conflict := self.review_conflict(record):
            # No cambia el estado: el intento queda en la bitácora y se informa el motivo.
            if conflict == "own":
                action, reason, message = ("Intento de validar un registro propio",
                                           "quien registra no puede validar su propio registro", OWN_REVIEW_MESSAGE)
            else:
                action, reason, message = ("Intento de validar un registro sobre sí mismo",
                                           "el funcionario afectado no puede validar su propio reclamo o felicitación",
                                           SUBJECT_REVIEW_MESSAGE)
            self.audit(record, action, previous=f"Estado: {record.get_status_display()}",
                       new=f"Estado: {record.get_status_display()}\nRechazado: {reason}")
            messages.error(request, message)
            return self.render_detail(record, status=403)
        form = ScoreAdjustmentReviewForm(request.POST, record=record)
        if not form.is_valid():
            return self.render_detail(record, form)
        try:
            with transaction.atomic():
                lock_period_registry()
                period = lock_open_period(record.occurred_on)
                if period.pk != record.period_id:
                    raise ValidationError("El registro ya no pertenece al período abierto de su fecha.")
                record = get_object_or_404(ScoreAdjustment.objects.select_for_update(), pk=record.pk)
                if record.status != ScoreAdjustment.Status.PENDING:
                    raise ValidationError("Este registro ya fue revisado.")
                self.review(record, period, form.cleaned_data)
        except ValidationError as error:
            form.add_error(None, error)
            return self.render_detail(record, form)
        messages.success(request, f"Registro {record.get_status_display().lower()}.")
        return redirect("score_adjustment_detail", pk=record.pk)

    def review(self, record, period, data):
        if data["decision"] == ScoreAdjustment.Status.APPROVED:
            position_id = historical_position_id(record.official_id, record.occurred_on) or record.official.position_id
            version = version_for(position_id, record.occurred_on, period)
            if version is None:
                raise ValidationError("Para aprobar necesitas un plan publicado para el cargo en la fecha del registro.")
            if record.kind == ScoreAdjustment.Kind.CONGRATULATION:
                record.delegate_reference = data["delegate_reference"]
                record.delegate_origin_confirmed = data["delegate_origin_confirmed"]
            record.version = version
            record.points = (version.congratulation_points if record.kind == ScoreAdjustment.Kind.CONGRATULATION
                             else -version.complaint_points)
        record.status = data["decision"]
        record.review_note = data["note"]
        record.reviewed_by = self.request.user
        record.reviewed_at = timezone.now()
        record.save(update_fields=["status", "review_note", "reviewed_at", "reviewed_by", "version", "points", "delegate_reference",
                                   "delegate_origin_confirmed", "updated_at"])
        self.audit(record, "Validación de reclamo o felicitación", previous="Pendiente",
                   new=f"Estado: {record.get_status_display()}\nPuntos autorizados: {record.points or 0:+f}")
