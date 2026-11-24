from datetime import timedelta

from django.conf import settings
from django.contrib import messages
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Count, F, Q
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.dateparse import parse_date
from django.views import View

from accounts.delegation_context import get_active_delegation
from accounts.models import Delegation, Official, Territory
from activities.cases import VIEW_CASE, scoped_cases
from common.access import ProtectedViewMixin, get_scoped_object_or_404
from common.maintainers import activity_queryset
from configuration.period_services import lock_period_registry
from configuration.models import AuditLog
from configuration.services import AuditoriaService
from configuration.weeks import can_manage_weeks

from .commitments import ADD, ASSIGN, CHANGE, VIEW, deadline_labels, scoped_commitments, scoped_delegations, validate_commitment_date
from .comments import comments_context
from .forms import CommitmentAssignForm, CommitmentForm, CommitmentStatusForm
from .models import Commitment


def visible_origin(user, case_id, activity_id):
    if case_id is not None:
        cases = scoped_cases(user) if user.has_perm(VIEW_CASE) else scoped_cases(user).none()
        return get_object_or_404(cases, pk=case_id), None
    if activity_id is not None:
        activities = activity_queryset(user, "activities.view_activity")
        if not user.has_perm("activities.view_activity"):
            activities = activities.none()
        return None, get_object_or_404(activities, pk=activity_id)
    return None, None


def summary_counts():
    return {
        "total": Count("pk"),
        "done": Count("pk", filter=Q(current_status=Commitment.Status.DONE)),
        "entered": Count("pk", filter=Q(current_status=Commitment.Status.ENTERED)),
        "pending": Count("pk", filter=Q(current_status=Commitment.Status.PENDING)),
        "in_progress": Count("pk", filter=Q(current_status=Commitment.Status.IN_PROGRESS)),
    }


def add_percentages(row):
    row["done_pct"] = 100 * row["done"] / row["total"] if row["total"] else None
    row["open_pct"] = 100 - row["done_pct"] if row["total"] else None
    return row



class CommitmentListView(ProtectedViewMixin, View):
    permission_required = VIEW

    def get(self, request):
        records = scoped_commitments(request.user)
        delegation_options = Delegation.objects.filter(pk__in=records.values("delegation_id")).order_by("delegation_name")
        responsible_options = Official.objects.filter(pk__in=records.values("responsible_id"))
        territory_options = Territory.objects.filter(pk__in=records.values("territory_ref_id"))
        params = request.GET
        for param, field in (("delegacion", "delegation_id"), ("responsable", "responsible_id"), ("territorio", "territory_ref_id")):
            value = params.get(param, "")
            if value.isascii() and value.isdecimal() and len(value) <= 18:
                records = records.filter(**{field: value})
        for param, lookup in (("desde", "committed_date__gte"), ("hasta", "committed_date__lte")):
            try:
                date = parse_date(params.get(param, ""))
            except ValueError:
                date = None
            if date is not None:
                records = records.filter(**{lookup: date})
        status = params.get("estado")
        if status in Commitment.Status.values:
            records = records.filter(current_status=status)

        today = timezone.localdate()
        open_records = ~Q(current_status__in=Commitment.CLOSED_STATUSES)
        summary = add_percentages(records.aggregate(
            **summary_counts(),
            overdue=Count("pk", filter=open_records & Q(committed_date__lt=today)),
            soon=Count("pk", filter=open_records & Q(committed_date__range=(
                today, today + timedelta(days=settings.COMMITMENT_DUE_WARNING_DAYS),
            ))),
            late=Count("pk", filter=Q(current_status=Commitment.Status.DONE, completed_on__gt=F("committed_date"))),
        ))
        by_responsible = [
            add_percentages(row) for row in records.values("responsible_id", "responsible__full_name")
            .annotate(**summary_counts()).order_by("responsible__full_name", "responsible_id")
        ]
        page = Paginator(records.select_related("delegation", "responsible"), 15).get_page(params.get("page"))
        for record in page:
            record.deadline_label = deadline_labels(record, today)
        page_params = params.copy()
        page_params.pop("page", None)
        return render(request, "agenda/commitment_list.html", {
            "page_obj": page, "summary": summary, "by_responsible": by_responsible, "can_manage_weeks": can_manage_weeks(request.user),
            "delegations": delegation_options, "responsibles": responsible_options, "territories": territory_options,
            "statuses": Commitment.Status.choices, "can_add": request.user.has_perm(ADD),
            "querystring": page_params.urlencode(),
        })


class CommitmentCreateView(ProtectedViewMixin, View):
    permission_required = (VIEW, ADD)

    def get(self, request, case_id=None, activity_id=None):
        return self.form_response(request, case_id, activity_id)

    def post(self, request, case_id=None, activity_id=None):
        return self.form_response(request, case_id, activity_id)

    def form_response(self, request, case_id, activity_id):
        from .alerts import update_commitment_alerts

        user = request.user
        actor = getattr(user, "official", None)
        if actor is None or not actor.is_enabled:
            return self.handle_no_permission()
        origin_case, origin_activity = visible_origin(user, case_id, activity_id)
        attention = getattr(origin_activity, "social_attentions", None)
        origin_delegation = (origin_case.delegation if origin_case else attention.delegation if attention else
                             origin_activity.official.delegation if origin_activity else None)
        allowed = scoped_delegations(user)
        chosen_id = request.GET.get("delegacion")
        if origin_case or origin_activity:
            delegation = get_scoped_object_or_404(request, allowed, pk=origin_delegation.pk if origin_delegation else None)
        elif chosen_id and chosen_id.isascii() and chosen_id.isdecimal() and len(chosen_id) <= 18:
            delegation = get_scoped_object_or_404(request, allowed, pk=chosen_id)
        elif chosen_id:
            raise Http404
        else:
            delegation = get_active_delegation(request, allowed) or allowed.first()
        case_for_form = origin_case
        if attention and user.has_perm(VIEW_CASE):
            case_for_form = scoped_cases(user).filter(pk=attention.case_id).first()
        form = CommitmentForm(request.POST if request.method == "POST" else None, user=user, delegation=delegation,
                              origin_case=case_for_form)
        if origin_activity and not attention:
            form.initial["description"] = origin_activity.action_description
        if delegation and request.method == "POST" and form.is_valid():
            data = form.cleaned_data
            try:
                with transaction.atomic():
                    lock_period_registry()
                    validate_commitment_date(data["committed_date"])
                    record, created = Commitment.objects.get_or_create(submission_token=data["submission_token"], defaults={
                        "delegation": delegation, "origin_case": origin_case, "origin_activity": origin_activity,
                        "requester": data["requester"], "territory_ref": data["territory_ref"], "territory": str(data["territory_ref"]),
                        "responsible": data["responsible"], "support_area": str(data["support_area"] or ""),
                        "committed_date": data["committed_date"], "description": data["description"],
                    })
                    if created:
                        AuditoriaService.register_change(actor, "Compromiso creado", record, new_value=record.identifier)
                        update_commitment_alerts(record)
                    else:
                        record = get_scoped_object_or_404(request, scoped_commitments(user), pk=record.pk)
            except ValidationError as error:
                form.add_error("committed_date", error)
            else:
                messages.success(request, "Compromiso registrado.")
                return redirect("commitment_detail", pk=record.pk)
        return render(request, "agenda/commitment_form.html", {
            "form": form, "delegation": delegation, "delegations": allowed,
            "origin_case": origin_case, "origin_activity": origin_activity,
        })


def render_commitment(request, record, *, errors=None):
    user = request.user
    forms = {}
    if record.next_statuses:
        if user.has_perm(CHANGE) and scoped_commitments(user, CHANGE).filter(pk=record.pk).exists():
            forms["status_form"] = CommitmentStatusForm(commitment=record)
        if user.has_perm(ASSIGN) and scoped_commitments(user, ASSIGN).filter(pk=record.pk).exists():
            forms["assign_form"] = CommitmentAssignForm(user=user, commitment=record)
    origin_url = None
    if record.origin_case_id and user.has_perm(VIEW_CASE) and scoped_cases(user).filter(pk=record.origin_case_id).exists():
        origin_url = reverse("attention_case_detail", args=[record.origin_case_id])
    elif record.origin_activity_id and user.has_perm("activities.view_activity") and activity_queryset(
        user, "activities.view_activity",
    ).filter(pk=record.origin_activity_id).exists():
        origin_url = reverse("activity_detail", args=[record.origin_activity_id])
    context = {
        "record": record, "deadline": deadline_labels(record), "origin_url": origin_url,
        "history": record.status_history.filter(deleted_at__isnull=True).select_related("author").order_by("date", "pk"),
        "reassignments": AuditLog.objects.filter(
            affected_table=Commitment._meta.db_table, affected_record_id=record.pk, action="Compromiso reasignado",
        ).select_related("official").order_by("pk"),
        **forms, **comments_context(user, record, "commitment"), **(errors or {}),
    }
    return render(request, "agenda/commitment_detail.html", context)


class CommitmentDetailView(ProtectedViewMixin, View):
    permission_required = VIEW

    def get(self, request, pk):
        records = scoped_commitments(request.user).select_related("responsible", "delegation")
        return render_commitment(request, get_scoped_object_or_404(request, records, pk=pk))


class CommitmentUpdateView(ProtectedViewMixin, View):
    operation = None
    http_method_names = ["post"]

    def get_permission_required(self):
        return (VIEW, ASSIGN if self.operation == "assign" else CHANGE)

    def post(self, request, pk):
        from .alerts import update_commitment_alerts

        user = request.user
        actor = getattr(user, "official", None)
        if actor is None or not actor.is_enabled:
            return self.handle_no_permission()
        writable = scoped_commitments(user, self.get_permission_required()[1]).filter(
            pk__in=scoped_commitments(user).order_by().values("pk"),
        )
        with transaction.atomic():
            lock_period_registry()
            record = get_scoped_object_or_404(request, Commitment.objects.select_for_update().filter(
                pk__in=writable.order_by().values("pk"),
            ), pk=pk)
            if self.operation == "assign":
                form = CommitmentAssignForm(request.POST, user=user, commitment=record)
                key = "assign_form"
            else:
                form = CommitmentStatusForm(request.POST, commitment=record)
                key = "status_form"
            if not form.is_valid():
                return render_commitment(request, record, errors={key: form})
            try:
                if not record.next_statuses:
                    raise ValidationError("El compromiso ya está realizado.")
                data = form.cleaned_data
                if self.operation == "assign":
                    previous = record.responsible
                    record.reassign_responsible(data["responsible"])
                    AuditoriaService.register_change(actor, "Compromiso reasignado", record,
                        previous_value=f"{previous.pk} · {previous.full_name}",
                        new_value=f"{record.responsible_id} · {record.responsible.full_name} · {data['reason']}")
                else:
                    previous = record.get_current_status_display()
                    record.change_status(data["status"], actor, data["observation"])
                    AuditoriaService.register_change(actor, "Estado de compromiso actualizado", record,
                        previous_value=previous, new_value=f"{record.get_current_status_display()} · {data['observation']}")
            except ValidationError as error:
                form.add_error(None, error)
                return render_commitment(request, record, errors={key: form})
            update_commitment_alerts(record)
        messages.success(request, "Compromiso actualizado.")
        return redirect("commitment_detail", pk=pk)
