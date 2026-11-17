from collections import defaultdict

from django.http import Http404

from accounts.models import Delegation, Official, Role
from analytics.services import CalculadorDesempenoService, TrafficLight
from common.scopes import delegation_ids, permission_scope
from configuration.models import Period


VIEW_PERFORMANCE = "analytics.view_indicatorsnapshot"
TEAM_PERFORMANCE = "analytics.view_team_performance"


def available_periods():
    return Period.objects.filter(deleted_at__isnull=True).order_by("-start_date")


def default_period(periods, today):
    current = next((p for p in periods if p.start_date <= today <= p.end_date), None)
    started = next((p for p in periods if p.start_date <= today), None)
    return current or started or (periods[0] if periods else None)


def select_period(periods, today, period_id=None):
    if not period_id:
        return default_period(periods, today)
    period = next((option for option in periods if str(option.pk) == str(period_id)), None)
    if period is None:
        raise Http404("No se encontró el período solicitado.")
    return period


def performance_delegations(user):
    queryset = Delegation.objects.filter(deleted_at__isnull=True).order_by("delegation_name", "pk")
    scope = permission_scope(user, TEAM_PERFORMANCE)
    if scope == Role.Scope.ALL:
        return queryset
    if scope == Role.Scope.DELEGATION:
        return queryset.filter(pk__in=delegation_ids(user))
    return queryset.none()


def team_results(period, today, delegations):
    if period.status == Period.Status.CLOSED:
        if period.frozen_at is None:
            return []
        grouped = defaultdict(list)
        snapshots = CalculadorDesempenoService.frozen_snapshots(period).filter(
            closing_delegation__in=delegations,
        ).select_related("official", "item", "version__plan__position", "closing_delegation").order_by(
            "official__full_name", "official_id", "item__item_name", "pk",
        )
        for snapshot in snapshots:
            grouped[snapshot.official_id].append(snapshot)
        return [
            CalculadorDesempenoService.frozen_result(rows[0].official, period, rows)
            for rows in grouped.values()
        ]
    officials = Official.objects.filter(delegation__in=delegations, deleted_at__isnull=True).select_related(
        "position", "delegation",
    ).order_by("full_name", "pk")
    return CalculadorDesempenoService.calculate_many(officials, period, today)


def summarize_team(results):
    measured = [result for result in results if result.items and result.computable_days != 0]
    count = len(measured)
    colors = dict.fromkeys(TrafficLight.values, 0)
    for result in results:
        light = result.total_traffic_light
        if light in colors:
            colors[light] += 1
    return {
        "measured_count": count,
        "colors": colors,
        "total_activities": sum(result.activity_count for result in results),
        "average": sum(result.total for result in measured) / count if count else None,
        "expected_average": sum(result.expected_percentage for result in measured) / count if count else None,
    }
