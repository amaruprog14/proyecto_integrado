"""Cumplimiento de los compromisos computables por delegación y versión de plan."""
from decimal import Decimal

from django.db.models import BigIntegerField, F, OuterRef, Q, Subquery
from django.db.models.functions import Coalesce

from accounts.models import Official, OfficialPositionPeriod
from agenda.models import Commitment
from analytics.models import DelegationActivityFreeze, MeasurementVersion
from analytics.segments import measured_commitments


def collective_figures(done, total, threshold):
    percent = Decimal(done) * 100 / total
    return {
        "done": done, "total": total, "percent": str(round(percent, 2)),
        "pending_percent": str(round(100 - percent, 2)),
        "threshold": str(threshold) if threshold is not None else None,
        "verdict": ("Sin plan publicado" if threshold is None else
                    "Alcanza el umbral" if percent >= threshold else "Bajo el umbral"),
    }


def collective_by_delegation(period, cutoff, delegation_id=None):
    rows = measured_commitments(Official.objects.values("pk"), period, cutoff).annotate(
        measured_delegation=Coalesce("delegation_id", "responsible__delegation_id", output_field=BigIntegerField()))
    if delegation_id is not None:
        rows = rows.filter(measured_delegation=delegation_id)
    histories = OfficialPositionPeriod.objects.filter(official_id=OuterRef("responsible_id"),
        deleted_at__isnull=True, start_date__lte=OuterRef("committed_date")).filter(
        Q(end_date__isnull=True) | Q(end_date__gte=OuterRef("committed_date"))).order_by("-start_date", "-pk")
    rows = rows.annotate(cargo=Coalesce(Subquery(histories.values("position_id")[:1]), F("responsible__position_id"), output_field=BigIntegerField()))
    versions = MeasurementVersion.objects.filter(plan__period=period, published_at__isnull=False,
        deleted_at__isnull=True, plan__deleted_at__isnull=True).select_related("plan__position").order_by("-effective_from", "-pk")
    by_position = {}
    for version in versions:
        by_position.setdefault(version.plan.position_id, []).append(version)
    counts = {}
    for territory, cargo, day, state in rows.order_by().values_list(
            "measured_delegation", "cargo", "committed_date", "measured_status").iterator():
        version = next((v for v in by_position.get(cargo, ()) if v.effective_from <= day), None)
        pair = counts.setdefault((territory, version), [0, 0])
        pair[0] += state == Commitment.Status.DONE
        pair[1] += 1
    groups = {}
    for (territory, version), (done, total) in counts.items():
        result = collective_figures(done, total, version.collective_threshold if version else None)
        result["plan"] = f"{version.plan.position} · Versión {version.number}" if version else "Sin plan publicado"
        groups.setdefault(str(territory), []).append(result)
    for group in groups.values():
        group.sort(key=lambda item: item["plan"])
    return groups


def collective_for_panel(period, today, delegation):
    if period.status == period.Status.CLOSED:
        groups = DelegationActivityFreeze.objects.filter(period=period, captured_at=period.frozen_at).values_list(
            "collective_results", flat=True).first()
        if groups is None:
            return None
    else:
        groups = collective_by_delegation(period, today, delegation.pk)
    return groups.get(str(delegation.pk), [])
