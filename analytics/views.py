"""Panel «Mi desempeño» (RF-008, RF-027, RF-028, RF-038, HU-06, HU-16, HU-17).

Un funcionario ve solo su propio resultado. Con `analytics.view_team_performance` se puede elegir
otro funcionario dentro del alcance del rol (delegación o global). Un período cerrado se muestra
siempre desde los snapshots congelados al cerrarlo (RN-013), nunca recalculado.

Alcance cruzado: el desempeño es del funcionario completo (todas sus actividades, aunque se
registren en otra delegación). El enlace a las actividades de origen queda limitado al alcance de
quien consulta y la fila avisa cuántas actividades contadas no puede ver.
"""
from urllib.parse import urlencode

from django.db.models import Count, Exists, Max, OuterRef, Q
from django.http import Http404
from django.shortcuts import render
from django.urls import reverse
from django.utils import timezone
from django.views import View

from accounts.models import Official, Role
from activities.models import Activity, EvidenceBatch, EvidenceValidation
from agenda.models import Commitment
from analytics.services import CalculadorDesempenoService, TrafficLight, computable_activities
from common.access import ProtectedViewMixin, get_scoped_object_or_404
from common.maintainers import activity_queryset
from common.scopes import permission_scope, scope_officials
from configuration.models import Period

VIEW_PERFORMANCE = "analytics.view_indicatorsnapshot"
TEAM_PERFORMANCE = "analytics.view_team_performance"
VIEW_ACTIVITY = "activities.view_activity"


def default_period(periods, today):
    current = next((p for p in periods if p.start_date <= today <= p.end_date), None)
    started = next((p for p in periods if p.start_date <= today), None)
    return current or started or (periods[0] if periods else None)


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


def deviation(official, period, today):
    """RF-030 (parte A): último registro del funcionario y días sin registrar hasta hoy o el término."""
    reference = min(today, period.end_date)
    last = Activity.objects.filter(official=official, deleted_at__isnull=True, date__lte=reference).aggregate(
        last=Max("date"))["last"]
    return {"last_date": last, "days_without": (reference - last).days if last else None}


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
        periods = list(Period.objects.filter(deleted_at__isnull=True).order_by("-start_date"))
        period_id = request.GET.get("period", "")
        if period_id:
            period = next((p for p in periods if str(p.pk) == period_id), None)
            if period is None:
                raise Http404("No se encontró el período solicitado.")
        else:
            period = default_period(periods, today)

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

        context = {
            "periods": periods, "period": period, "subject": subject, "can_choose": can_choose,
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
                    link = reverse("activity_maintainer") + "?" + urlencode({
                        "record_source": "activity", "official": subject.pk, "item": row.item.pk,
                        "evidence": "counted", "status": "", "q": "", "record_type": "",
                        "date_from": period.start_date.isoformat(), "date_to": until.isoformat(),
                    })
                rows.append({"row": row, "link": link, "hidden": 0 if row.is_percentage else hidden.get(row.item.pk, 0)})
            total_light = result.total_traffic_light
            context.update(
                result=result, rows=rows, total_light=total_light,
                evidence=evidence_counts(subject, period), commitments=commitment_counts(subject, period, today),
                deviation=deviation(subject, period, today) if total_light == TrafficLight.RED else None,
            )
        return render(request, "analytics/my_performance.html", context)
