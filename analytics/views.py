"""Panel «Mi desempeño» (RF-008, RF-027, RF-028, RF-038, HU-06, HU-16, HU-17).

Un funcionario ve solo su propio resultado. Con `analytics.view_team_performance` se puede elegir
otro funcionario dentro del alcance del rol (delegación o global). Un período cerrado se muestra
siempre desde los snapshots congelados al cerrarlo (RN-013), nunca recalculado.

Alcance cruzado: el desempeño es del funcionario completo (todas sus actividades, aunque se
registren en otra delegación). El enlace a las actividades de origen queda limitado al alcance de
quien consulta y la fila avisa cuántas actividades contadas no puede ver.
"""
from collections import defaultdict
from decimal import Decimal
from urllib.parse import urlencode

from django.conf import settings
from django.db.models import Count, Exists, Max, OuterRef, Q
from django.http import Http404
from django.shortcuts import render
from django.urls import reverse
from django.utils import timezone
from django.views import View

from accounts.delegation_context import get_active_delegation
from accounts.models import Delegation, Official, Role
from activities.models import Activity, EvidenceBatch, EvidenceValidation
from agenda.models import Commitment
from analytics.models import MeasurementItem
from analytics.queries import (
    TEAM_PERFORMANCE, VIEW_PERFORMANCE, available_periods, performance_delegations,
    select_period, summarize_team, team_results,
)
from analytics.services import CalculadorDesempenoService, computable_activities, computable_days
from common.access import ProtectedViewMixin, get_scoped_object_or_404
from common.maintainers import activity_queryset
from common.scopes import permission_scope, scope_officials
from configuration.models import Period

VIEW_ACTIVITY = "activities.view_activity"


def period_selection(request, today):
    periods = list(available_periods())
    return periods, select_period(periods, today, request.GET.get("period"))


def activity_list_link(official, item, period, until):
    return reverse("activity_maintainer") + "?" + urlencode({
        "record_source": "activity", "official": official.pk, "item": item.pk,
        "evidence": "counted", "status": "", "q": "", "record_type": "",
        "date_from": period.start_date.isoformat(), "date_to": until.isoformat(),
    })


def evidence_counts(official, period):
    """Lotes de evidencia del funcionario en el período, por estado de revisión."""
    batches = EvidenceBatch.objects.filter(
        deleted_at__isnull=True, activity__official=official, activity__deleted_at__isnull=True,
        activity__date__range=(period.start_date, period.end_date), images__deleted_at__isnull=True,
    ).distinct()
    reviews = EvidenceValidation.objects.filter(
        evidence__batch=OuterRef("pk"), evidence__deleted_at__isnull=True, deleted_at__isnull=True,
    )
    return {
        "pending": batches.filter(~Exists(reviews)).count(),
        "rejected": batches.filter(Exists(reviews.filter(status=EvidenceValidation.Status.REJECTED))).count(),
        "correction": batches.filter(Exists(reviews.filter(
            status=EvidenceValidation.Status.CORRECTION_REQUESTED))).count(),
    }


def commitment_counts(official, period, today):
    """Compromisos del funcionario con fecha comprometida en el período; vencido = abierto y con
    fecha anterior a hoy."""
    open_commitments = ~Q(current_status=Commitment.Status.DONE)
    return Commitment.objects.filter(
        responsible=official, deleted_at__isnull=True, committed_date__range=(period.start_date, period.end_date),
    ).aggregate(
        open=Count("pk", filter=open_commitments),
        overdue=Count("pk", filter=open_commitments & Q(committed_date__lt=today)),
        done=Count("pk", filter=Q(current_status=Commitment.Status.DONE)),
    )


def recent_activity(official_ids, period, today, activities):
    """RF-030: última actividad computable hasta el corte y frecuencia en el período elegido."""
    reference = min(today, period.end_date)
    days = computable_days(period, until=reference, include_start_day=True)
    recorded = {}
    if days:
        qualifying = computable_activities(activities.filter(
            official_id__in=official_ids, date__lte=reference, deleted_at__isnull=True,
        ))
        recorded = {row["official_id"]: row for row in qualifying.order_by().values("official_id").annotate(
            last_date=Max("date"),
            count=Count("pk", distinct=True, filter=Q(date__gte=period.start_date)),
        )}
    threshold = settings.PERFORMANCE_INACTIVITY_DAYS
    stats = {}
    for official_id in official_ids:
        row = recorded.get(official_id, {})
        last = row.get("last_date")
        count = row.get("count", 0)
        days_without = (reference - last).days if last else None
        elapsed = days_without if days_without is not None else days - 1
        stats[official_id] = {
            "last_date": last, "days_without": days_without, "count": count,
            "daily_average": Decimal(count) / days if days else None,
            "attention": days > 0 and threshold > 0 and elapsed >= threshold,
        }
    return stats


def hidden_activity_counts(user, official, period, until):
    """Por ítem, actividades que cuentan en el avance pero quedan fuera del alcance de
    `user` en el listado de actividades (p. ej., atenciones en otra delegación)."""
    if permission_scope(user, VIEW_ACTIVITY) == Role.Scope.ALL:
        return {}
    visible = activity_queryset(user, VIEW_ACTIVITY).filter(official=official).values("pk")
    activities = Activity.objects.filter(
        official=official, deleted_at__isnull=True, date__range=(period.start_date, min(until, period.end_date)),
    ).exclude(pk__in=visible)
    rows = computable_activities(activities).order_by().values("item_id").annotate(total=Count("pk"))
    return {row["item_id"]: row["total"] for row in rows}


class MyPerformanceView(ProtectedViewMixin, View):
    permission_required = (VIEW_PERFORMANCE,)

    def officials(self):
        """Funcionarios elegibles: el propio y, con permiso de equipo, los de su alcance."""
        user = self.request.user
        own = getattr(user, "official", None)
        selectable = Q(pk=own.pk) if own else Q(pk__in=[])
        if user.has_perm(TEAM_PERFORMANCE):
            scoped = scope_officials(Official.objects.all(), user, TEAM_PERFORMANCE)
            selectable |= Q(pk__in=scoped.values("pk"))
        return (Official.objects.filter(selectable, deleted_at__isnull=True)
                .select_related("position", "delegation").prefetch_related("authorized_delegations"))

    def get(self, request):
        today = timezone.localdate()
        periods, period = period_selection(request, today)

        officials = self.officials()
        own = getattr(request.user, "official", None)
        official_id = request.GET.get("official", "")
        if official_id:
            if not official_id.isdigit():
                raise Http404("No se encontró el funcionario solicitado.")
            subject = get_scoped_object_or_404(request, officials, pk=official_id)
        else:
            subject = own
        can_choose = request.user.has_perm(TEAM_PERFORMANCE)
        team_scope = permission_scope(request.user, TEAM_PERFORMANCE) if can_choose else None

        context = {
            "periods": periods, "period": period, "subject": subject, "can_choose": can_choose,
            "can_view_delegation": team_scope in (Role.Scope.ALL, Role.Scope.DELEGATION),
            "authorized_delegations": [d for d in subject.authorized_delegations.all() if d.pk != subject.delegation_id]
            if subject is not None else [],
            "officials": officials.order_by("full_name") if can_choose else [], "today": today,
        }
        if period is not None and subject is not None:
            result = CalculadorDesempenoService.result_for(subject, period, today)
            show_links = request.user.has_perm(VIEW_ACTIVITY)
            # Mismo corte que el avance: hasta hoy en un período abierto, hasta el término si está cerrado.
            until = period.end_date if result.frozen else min(max(today, period.start_date), period.end_date)
            hidden = hidden_activity_counts(request.user, subject, period, until) if show_links else {}
            rows = []
            for row in result.items:
                link = None
                if show_links and not row.is_percentage:
                    link = activity_list_link(subject, row.item, period, until)
                rows.append({"row": row, "link": link, "hidden": 0 if row.is_percentage else hidden.get(row.item.pk, 0)})
            total_light = result.total_traffic_light
            activity_scope = (Activity.objects.all() if subject.user_id == request.user.pk
                              else activity_queryset(request.user, TEAM_PERFORMANCE))
            context.update(
                result=result, rows=rows, total_light=total_light,
                evidence=evidence_counts(subject, period), commitments=commitment_counts(subject, period, today),
                recent=recent_activity([subject.pk], period, today, activity_scope)[subject.pk],
                activity_cutoff=min(today, period.end_date),
            )
        return render(request, "analytics/my_performance.html", context)


class TeamPerformanceView(ProtectedViewMixin, View):
    permission_required = (VIEW_PERFORMANCE, TEAM_PERFORMANCE)

    def has_permission(self):
        return super().has_permission() and permission_scope(self.request.user, TEAM_PERFORMANCE) in (
            Role.Scope.ALL, Role.Scope.DELEGATION,
        )

    def delegations(self):
        return performance_delegations(self.request.user)

    def requested_delegation(self, delegation_options):
        delegation_id = self.request.GET.get("delegation")
        if not delegation_id:
            return None
        if not delegation_id.isascii() or not delegation_id.isdecimal() or len(delegation_id) > 19:
            raise Http404("No se encontró la delegación solicitada.")
        return get_scoped_object_or_404(self.request, delegation_options, pk=delegation_id)


class DelegationPerformanceView(TeamPerformanceView):
    def get(self, request):
        today = timezone.localdate()
        periods, period = period_selection(request, today)
        delegation_options = self.delegations()
        delegation = self.requested_delegation(delegation_options)
        if delegation is None:
            active_options = list(delegation_options.filter(status=Delegation.Status.ACTIVE))
            delegation = get_active_delegation(request, active_options) or delegation_options.first()

        context = {
            "periods": periods, "period": period, "delegations": delegation_options, "delegation": delegation,
            "can_view_delegation": True, "performance_tab": "delegation",
        }
        if period is None or delegation is None:
            return render(request, "analytics/delegation_performance.html", context)

        closed = period.status == Period.Status.CLOSED
        results = team_results(period, today, delegation_options.filter(pk=delegation.pk).order_by())

        rows = []
        for result in results:
            light = result.total_traffic_light
            rows.append({
                "result": result, "light": light,
                "position": result.position,
                "activity_count": result.activity_count,
            })

        selected_id = request.GET.get("official")
        if selected_id:
            selected = next((row for row in rows if str(row["result"].official.pk) == selected_id), None)
            if selected is None:
                raise Http404("No se encontró el funcionario en el período y delegación seleccionados.")
            self.add_drilldown(context, selected, period, today)

        commitments = None
        if not closed:
            commitments = Commitment.objects.filter(
                responsible_id__in=[result.official.pk for result in results], deleted_at__isnull=True,
                committed_date__range=(period.start_date, period.end_date),
            ).aggregate(
                total=Count("pk"),
                done=Count("pk", filter=Q(current_status=Commitment.Status.DONE)),
                overdue=Count("pk", filter=~Q(current_status=Commitment.Status.DONE) & Q(committed_date__lt=today)),
            )
        context.update(
            rows=rows, commitments=commitments, closed=closed, **summarize_team(results),
        )
        return render(request, "analytics/delegation_performance.html", context)

    def add_drilldown(self, context, selected, period, today):
        user = self.request.user
        result = selected["result"]
        official = result.official
        can_open_personal = official.deleted_at is None and (
            official.user_id == user.pk
            or scope_officials(Official.objects.filter(pk=official.pk), user, TEAM_PERFORMANCE).exists()
        )
        cutoff = min(today, period.end_date)
        can_open_activities = not result.frozen and cutoff >= period.start_date and user.has_perm(VIEW_ACTIVITY)
        hidden = hidden_activity_counts(user, official, period, cutoff) if can_open_activities else {}
        context.update(
            selected=selected, can_open_personal=can_open_personal,
            selected_items=[
                {
                    "item": item,
                    "activity_link": activity_list_link(official, item.item, period, cutoff)
                    if can_open_activities and item.goal_type == MeasurementItem.GoalType.QUANTITY and item.progress else None,
                    "hidden": hidden.get(item.item.pk, 0),
                }
                for item in result.items
            ],
        )


def position_item_totals(results):
    lines_by_item = defaultdict(list)
    for result in results:
        for line in result.items:
            lines_by_item[line.item.pk, line.goal_type].append(line)
    totals = []
    for lines in lines_by_item.values():
        first = lines[0]
        goals = [line.goal for line in lines if line.goal is not None and line.goal > 0]
        progress = [line.progress for line in lines if line.progress is not None]
        goal_total = sum(goals) if goals else None
        progress_total = sum(progress) if progress else None
        if first.is_percentage:
            if goals:
                goal_total /= len(goals)
            if progress:
                progress_total /= len(progress)
        totals.append({
            "item": first.item, "is_percentage": first.is_percentage,
            "goal": goal_total, "progress": progress_total,
        })
    return sorted(totals, key=lambda row: (row["item"].item_name.casefold(), row["is_percentage"]))


class PositionPerformanceView(TeamPerformanceView):
    def get(self, request):
        today = timezone.localdate()
        periods, period = period_selection(request, today)
        delegations = self.delegations()
        delegation = self.requested_delegation(delegations)
        context = {
            "periods": periods, "period": period, "delegations": delegations, "delegation": delegation,
            "can_view_delegation": True, "performance_tab": "position",
        }
        if period is None:
            return render(request, "analytics/position_performance.html", context)
        selected_delegations = delegations.filter(pk=delegation.pk) if delegation else delegations
        results = team_results(period, today, selected_delegations.order_by())
        grouped = defaultdict(list)
        for result in results:
            position = result.position
            grouped[str(position.pk) if position else "sin-cargo"].append(result)
        groups = []
        for key, members in grouped.items():
            position = members[0].position
            measured = [member for member in members if member.items]
            groups.append({
                "key": key, "name": position.position_name if position else "Sin cargo",
                "staff_count": len(members), "measured_count": len(measured),
                "activity_count": sum(member.activity_count for member in members),
                "average": sum(member.total for member in measured) / len(measured) if measured else None,
            })
        groups.sort(key=lambda group: (group["key"] == "sin-cargo", group["name"].casefold(), group["key"]))

        position_id = request.GET.get("position")
        if position_id:
            selected = next((group for group in groups if group["key"] == position_id), None)
            if selected is None:
                raise Http404("No se encontró el cargo en el período y ámbito seleccionados.")
            self.add_position_detail(context, selected, grouped[position_id], period, today)
        context.update(
            groups=groups, closed=period.status == Period.Status.CLOSED,
            activity_cutoff=min(today, period.end_date), started=period.start_date <= today,
        )
        return render(request, "analytics/position_performance.html", context)

    def add_position_detail(self, context, selected, members, period, today):
        user = self.request.user
        official_ids = [member.official.pk for member in members]
        can_open = set(scope_officials(Official.objects.filter(
            pk__in=official_ids, deleted_at__isnull=True,
        ), user, TEAM_PERFORMANCE).values_list("pk", flat=True))
        recent = recent_activity(official_ids, period, today, activity_queryset(user, TEAM_PERFORMANCE))
        context.update(
            selected=selected, item_totals=position_item_totals(members),
            members=[{
                "result": member, "recent": recent[member.official.pk],
                "delegation": member.closing_delegation if member.frozen else member.official.delegation,
                "can_open_personal": member.official.pk in can_open,
            } for member in members],
        )
