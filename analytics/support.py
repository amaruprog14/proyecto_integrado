"""Respaldo exacto de los indicadores congelados («¿Qué respaldó este resultado?»).

Se captura al congelar, con el mismo criterio y el mismo corte que la cifra:
- ítems de cantidad: `computable_activities`, atribuidas al tramo de cargo por su fecha y solo si el
  ítem está en el plan de ese tramo (como `segmented_results` y `_counted_progress_by_official`);
- «Soluciones de ingresos al tubo» (PERCENTAGE): `measured_commitments`, numerador = Realizado;
- «Pendientes en tubo» (MAX_PERCENTAGE): `measured_commitments`, numerador = no Realizado.
  En ambos, los cancelados con justificación al corte quedan fuera del denominador.

Un resultado sin días computables no se evalúa: no aporta al total y no guarda respaldo. Con tramos,
el porcentaje integrado pondera cada tramo por sus días: un tramo de 0 días no guarda compromisos.
"""
from collections import defaultdict
from datetime import date
from itertools import islice
from types import SimpleNamespace

from activities.models import Activity
from analytics.models import IndicatorSupportSnapshot, MeasurementItem
from analytics.segments import measured_commitments

GoalType = MeasurementItem.GoalType


def _spans(result):
    """Tramos del resultado: (inicio, término, cargo, {(ítem, tipo de meta)} del tramo, días computables)."""
    if result.segments:
        return [(date.fromisoformat(segment["start_date"]), date.fromisoformat(segment["end_date"]),
                 segment["position"], {(row["item_id"], row["goal_type"]) for row in segment["items"]},
                 segment["days"]) for segment in result.segments]
    period = result.period
    return [(period.start_date, period.end_date, "", {(row.item.pk, row.goal_type) for row in result.items},
             result.computable_days)]


def support_rows(result, on_date):
    """Respaldo por (ítem, tipo de meta) de un resultado calculado, sin el snapshot asignado."""
    if not result.items or not result.computable_days:
        return {}
    official, period = result.official, result.period
    spans = _spans(result)
    segmented = bool(result.segments)
    rows = defaultdict(list)

    def segment(span):
        if not segmented:
            return {}
        return {"segment_start": span[0], "segment_end": span[1], "position_name": span[2]}

    if any(goal_type == GoalType.QUANTITY for span in spans for _, goal_type in span[3]):
        from analytics.services import computable_activities

        activities = computable_activities(Activity.objects.filter(
            official=official, date__range=(period.start_date, min(on_date, period.end_date)), deleted_at__isnull=True,
        )).order_by("date", "pk").values_list("pk", "code", "date", "item_id", "item__item_name")
        for pk, code, day, item_id, item_name in activities:
            span = next((span for span in spans if span[0] <= day <= span[1]), None)
            if span is not None and (item_id, GoalType.QUANTITY) in span[3]:
                rows[item_id, GoalType.QUANTITY].append(IndicatorSupportSnapshot(
                    activity_id=pk, code=code, date=day, item_name=item_name, **segment(span)))

    from agenda.models import Commitment

    for span in spans:
        if not span[4]:
            # Un tramo sin días computables pesa 0 en el porcentaje integrado: sus compromisos no
            # respaldan la cifra. (En cantidad sí: el avance integrado suma todos los tramos.)
            continue
        scope = SimpleNamespace(start_date=span[0], end_date=span[1]) if segmented else period
        for item_id, goal_type in span[3]:
            if goal_type not in (GoalType.PERCENTAGE, GoalType.MAX_PERCENTAGE):
                continue
            commitments = measured_commitments([official.pk], scope, on_date)
            for pk, day, status in commitments.order_by("committed_date", "pk").values_list(
                    "pk", "committed_date", "measured_status"):
                done = status == Commitment.Status.DONE
                rows[item_id, goal_type].append(IndicatorSupportSnapshot(
                    commitment_id=pk, code=f"#{pk}", date=day, status=status,
                    in_numerator=done if goal_type == GoalType.PERCENTAGE else not done, **segment(span)))
    return rows


def save_supports(snapshots, supports):
    """Guarda el respaldo ya calculado. `snapshots` son los congelados recién creados (con PK) y
    `supports` mapea (funcionario, ítem, tipo de meta) a sus filas."""
    ids = {(row.official_id, row.item_id, row.goal_type): row.pk for row in snapshots}

    def assigned():
        for key, entries in supports.items():
            for support in entries:
                support.snapshot_id = ids[key]
                yield support

    pending = assigned()
    while batch := list(islice(pending, 500)):
        IndicatorSupportSnapshot.objects.bulk_create(batch)
