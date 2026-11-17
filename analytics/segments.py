"""Cálculo por tramos de cargo y respaldo serializable de cada contribución."""
from collections import defaultdict
from copy import copy
from datetime import datetime, time, timedelta
from decimal import Decimal
from types import SimpleNamespace

from django.db.models import Count, F, OuterRef, Q, Subquery
from django.db.models.functions import Coalesce
from django.utils import timezone

from analytics.models import MeasurementAdjustment, MeasurementItem


def commitments_at_cutoff(official_ids, period, until=None):
    from agenda.models import Commitment, CommitmentStatusHistory
    rows = Commitment.objects.filter(responsible_id__in=official_ids, deleted_at__isnull=True,
        committed_date__range=(period.start_date, period.end_date))
    if until is not None:
        cutoff = timezone.make_aware(datetime.combine(min(until, period.end_date) + timedelta(days=1), time.min))
        history = CommitmentStatusHistory.objects.filter(commitment_id=OuterRef("pk"), deleted_at__isnull=True)
        rows = rows.filter(creation_date__lt=cutoff).annotate(measured_status=Coalesce(
            Subquery(history.filter(date__gte=cutoff).order_by("date", "pk").values("previous_status")[:1]),
            Subquery(history.filter(date__lt=cutoff).order_by("-date", "-pk").values("new_status")[:1]),
            F("current_status")))
    else:
        rows = rows.annotate(measured_status=F("current_status"))
    return rows


def pending_percentages(official_ids, period, until=None):
    from agenda.models import Commitment
    rows = commitments_at_cutoff(official_ids, period, until).exclude(
        measured_status=Commitment.Status.CANCELLED, cancellation_reason__gt="")
    counts = rows.order_by().values("responsible_id").annotate(total=Count("pk"),
        pending=Count("pk", filter=~Q(measured_status=Commitment.Status.DONE)))
    return {row["responsible_id"]: Decimal(row["pending"]) / row["total"] * 100 for row in counts}


def result_rows_payload(result):
    return [{"item_id": row.item.pk, "item": str(row.item), "goal_type": row.goal_type,
        **{key: str(getattr(row, key)) if getattr(row, key) is not None else None
           for key in ("goal", "weight", "progress", "raw_compliance", "compliance", "weighted", "expected_units", "difference")},
        "traffic_light": row.traffic_light, "notice": row.notice, "individual": row.individual} for row in result.items]


def _version_lookup(period, position_ids):
    """Versiones publicadas del período por cargo, cargadas en una sola consulta."""
    from analytics.models import MeasurementVersion
    by_position = defaultdict(list)
    rows = MeasurementVersion.objects.filter(
        plan__period=period, plan__position_id__in=position_ids, plan__deleted_at__isnull=True,
        plan__period__deleted_at__isnull=True, published_at__isnull=False, deleted_at__isnull=True,
    ).select_related("plan").order_by("-effective_from", "-pk")
    for version in rows:
        by_position[version.plan.position_id].append(version)
    # Mismo criterio que published_versions_on: la última versión con vigencia hasta ese día.
    return lambda position_id, day: next((v for v in by_position.get(position_id, ()) if v.effective_from <= day), None)


def _position_spans(period, histories):
    """Tramos de cargo dentro del período: (inicio, término, historial o None)."""
    boundaries = {period.start_date, period.end_date + timedelta(days=1)}
    for history in histories:
        boundaries.add(max(period.start_date, history.start_date))
        if history.end_date and history.end_date < period.end_date:
            boundaries.add(history.end_date + timedelta(days=1))
    boundaries = sorted(day for day in boundaries if day <= period.end_date + timedelta(days=1))
    spans = []
    for start, stop in zip(boundaries, boundaries[1:]):
        history = next((h for h in histories if h.start_date <= start and (h.end_date is None or h.end_date >= start)), None)
        spans.append((start, stop - timedelta(days=1), history))
    return spans


def segmented_results(calc, officials, period, on_date, include_start_day, histories):
    """Resultados por tramos de cargo para varios funcionarios, con los datos cargados en bloque.

    Cada tramo usa la versión publicada de su cargo vigente al corte del tramo (el mismo criterio
    que el cálculo sin historial usa para todo el período), de modo que un único tramo que cubre el
    período da exactamente el resultado de siempre.
    """
    from activities.models import Activity
    from analytics.services import computable_activities

    officials = list(officials)
    if not officials:
        return {}
    ids = [official.pk for official in officials]
    spans = {official.pk: _position_spans(period, sorted(histories[official.pk], key=lambda h: h.start_date))
             for official in officials}
    lookup = _version_lookup(period, {h.position_id for official in officials for h in histories[official.pk]})
    versions = {}
    for official_id, rows in spans.items():
        for start, end, history in rows:
            cutoff = min(max(on_date, start), end)
            versions[(official_id, start)] = lookup(history.position_id, cutoff) if history else None
    version_ids = {version.pk for version in versions.values() if version}
    lines_by_version = defaultdict(list)
    for line in MeasurementItem.objects.filter(version_id__in=version_ids).select_related("item"):
        lines_by_version[line.version_id].append(line)
    adjustments = defaultdict(dict)
    for adjustment in MeasurementAdjustment.objects.filter(official_id__in=ids, line__version_id__in=version_ids).order_by():
        adjustments[adjustment.official_id][adjustment.line_id] = adjustment
    # Mismo criterio de conteo que el resto del sistema; la fecha atribuye cada actividad a su tramo.
    end = min(on_date, period.end_date)
    counted_by_day = defaultdict(list)
    activities = Activity.objects.filter(official_id__in=ids, date__range=(period.start_date, end), deleted_at__isnull=True)
    for row in computable_activities(activities).order_by().values("official_id", "item_id", "date").annotate(total=Count("pk")):
        counted_by_day[row["official_id"]].append(row)
    return {official.pk: _segmented_result(calc, official, period, on_date, include_start_day, spans[official.pk],
                                           versions, lines_by_version, adjustments[official.pk], counted_by_day[official.pk])
            for official in officials}


def _segmented_result(calc, official, period, on_date, include_start_day, spans, versions, lines_by_version,
                      adjustments, counted_rows):
    from analytics.services import HUNDRED, PerformanceResult, expected_percentage, traffic_light
    segments, aggregate, parts = [], {}, []
    last_version = None
    for start, end, history in spans:
        version = versions[(official.pk, start)]
        position_id = history.position_id if history else None
        if start <= min(on_date, period.end_date):
            last_version = version
        span = SimpleNamespace(start_date=start, end_date=end)
        inclusive = include_start_day if start == period.start_date else True
        lines = lines_by_version[version.pk] if version else []
        counted = defaultdict(int)
        for row in counted_rows:
            if start <= row["date"] <= end:
                counted[row["item_id"]] += row["total"]
        types = {line.goal_type for line in lines}
        # Las consultas de compromisos solo se hacen si el plan del tramo tiene ítems porcentuales.
        percentage = (calc.percentage_progress(official, span, on_date)
                      if MeasurementItem.GoalType.PERCENTAGE in types else None)
        pending = (pending_percentages([official.pk], span, on_date).get(official.pk)
                   if MeasurementItem.GoalType.MAX_PERCENTAGE in types else None)
        proxy = copy(official)
        proxy.position_id = position_id
        part = calc._build_result(proxy, span, on_date, inclusive, version, lines, adjustments, counted, percentage, pending)
        parts.append(part)
        segments.append({"start_date": start.isoformat(), "end_date": end.isoformat(),
            "position_id": position_id, "position": str(history.position) if history else "Sin cargo histórico",
            "version_id": version.pk if version else None, "days": part.computable_days, "elapsed_days": part.elapsed_days,
            "total": str(part.total), "expected": str(part.expected_percentage) if part.expected_percentage is not None else None,
            "traffic_light": part.total_traffic_light, "notice": part.notice, "items": result_rows_payload(part)})
        for row in part.items:
            aggregate.setdefault((row.item.pk, row.goal_type), []).append((row, part.computable_days, part))
    total_days = sum(s["days"] for s in segments)
    result = PerformanceResult(official, period, on_date, last_version,
        expected_percentage(period, on_date, official, include_start_day=include_start_day),
        computable_days=total_days, elapsed_days=sum(s["elapsed_days"] for s in segments), segments=segments)
    if len(parts) == 1:
        # Un solo tramo: el resultado es el del tramo, sin reagregar (sin regresión).
        result.items = parts[0].items
        result.notice = parts[0].notice
        return result
    if total_days == 0:
        result.notice = "Sin días computables: el período no se evalúa."
    else:
        result.notice = "Resultado calculado por tramos de cargo, ponderado por días computables."
    for entries in aggregate.values():
        rows = [(r, days) for r, days, _ in entries]
        row = copy(rows[0][0])
        # Aporte al total: cada tramo pesa por sus días sobre los días de todo el período.
        row.weighted = sum(r.weighted * days for r, days in rows) / total_days if total_days else Decimal(0)
        row.weight = sum(r.weight * days for r, days in rows) / total_days if total_days else Decimal(0)
        progresses = [(r.progress, days) for r, days in rows if r.progress is not None]
        if row.is_percentage:
            denominator = sum(days for _, days in progresses)
            row.progress = sum(value * days for value, days in progresses) / denominator if denominator else None
        else:
            row.progress = sum(value for value, _ in progresses)
        # Cumplimiento del ítem: solo sobre los tramos donde el ítem se evaluó (no se diluye).
        evaluated = [(r, days, part) for r, days, part in entries if r.raw_compliance is not None and days]
        applicable = sum(days for _, days, _ in evaluated)
        if applicable:
            row.raw_compliance = sum(r.raw_compliance * days for r, days, _ in evaluated) / applicable
            row.compliance = sum(r.compliance * days for r, days, _ in evaluated) / applicable
            # Referencia del semáforo: el esperado de los tramos donde se evaluó el ítem, ponderado por
            # sus días, con los umbrales de la versión del último de esos tramos (no la del período).
            if row.goal_type == MeasurementItem.GoalType.MAX_PERCENTAGE:
                reference = HUNDRED
            else:
                reference = sum(part.expected_percentage * days for _, days, part in evaluated) / applicable
            version = evaluated[-1][2].version
            row.traffic_light = traffic_light(row.raw_compliance, reference, version) if version else None
        else:
            row.raw_compliance, row.compliance, row.traffic_light = None, Decimal(0), None
        goals = {r.goal for r, _ in rows}
        row.goal = goals.pop() if len(goals) == 1 else None
        row.expected_units = row.difference = None
        row.notice = "Metas y avances por tramo en el detalle; ponderado integrado por días."
        result.items.append(row)
    return result
