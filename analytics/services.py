"""Cálculo de desempeño sobre los planes de medición publicados (#46).

Reglas de la guía: cumplimiento = avance aprobado / meta x 100 (RN-004), con tope computable
(RN-005); ponderado = ponderador x cumplimiento / 100; meta esperada al día = días transcurridos /
días totales x 100 (RN-007); semáforo según la meta esperada (RN-008); solo suma la evidencia
aprobada (RN-009). Se conserva la precisión interna y se redondea solo al mostrar.

GoalThreshold y Weighting quedan obsoletos: este servicio ya no los consulta.
"""
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, time, timedelta
from decimal import ROUND_HALF_UP, Decimal

from django.db.models import Case, Count, Exists, F, OuterRef, Q, Subquery, When
from django.db.models.functions import Coalesce
from django.utils import timezone

from activities.models import Activity, EvidenceValidation
from analytics.measurement import published_versions_on
from analytics.models import IndicatorSnapshot, MeasurementAdjustment, MeasurementItem, MeasurementVersion, ScoreAdjustment

HUNDRED = Decimal("100")
CENT = Decimal("0.01")
# Tope por defecto del resultado final; cada versión del plan puede configurar el suyo.
MAX_FINAL_SCORE = Decimal("150")
MAX_CONGRATULATIONS = 3
TrafficLight = IndicatorSnapshot.TrafficLight


def q2(value):
    """Redondeo a dos decimales (mitad hacia arriba: 5,545 → 5,55) solo para mostrar o persistir.
    Los cálculos conservan la precisión interna y el semáforo compara siempre sin redondear."""
    return None if value is None else Decimal(value).quantize(CENT, rounding=ROUND_HALF_UP)


def computable_activities(queryset):
    """Único criterio de «actividad que cuenta» (RN-003, RN-009): evidencia aprobada vigente y un
    ítem que está en la versión publicada que rige en su fecha para el cargo con que se registró.

    Lo usan el avance del calculador, el aviso de actividades ocultas del panel y el filtro
    «Solo las que cuentan en la medición» del listado de actividades, para que sus totales cuadren.
    """
    approved = EvidenceValidation.objects.filter(
        evidence__activity=OuterRef("pk"), evidence__deleted_at__isnull=True,
        deleted_at__isnull=True, status=EvidenceValidation.Status.APPROVED,
    )
    ruling = MeasurementVersion.objects.filter(
        plan__position_id=OuterRef("_measure_position"), plan__deleted_at__isnull=True,
        plan__period__start_date__lte=OuterRef("date"), plan__period__end_date__gte=OuterRef("date"),
        plan__period__deleted_at__isnull=True, deleted_at__isnull=True, published_at__isnull=False,
        effective_from__lte=OuterRef("date"),
    ).order_by("-effective_from", "-pk").values("pk")[:1]
    from accounts.models import OfficialPositionPeriod
    historical = OfficialPositionPeriod.objects.filter(official_id=OuterRef("official_id"),
        start_date__lte=OuterRef("date"), deleted_at__isnull=True).filter(
        Q(end_date__isnull=True) | Q(end_date__gte=OuterRef("date"))).order_by("-start_date").values("position_id")[:1]
    return queryset.alias(
        _measure_position=Coalesce(Subquery(historical), Case(When(registration_position_captured=True, then=F("registration_position_id")),
                               default=F("official__position_id"))),
    ).alias(_ruling_version=Subquery(ruling)).filter(
        Exists(approved),
        Exists(MeasurementItem.objects.filter(version_id=OuterRef("_ruling_version"), item_id=OuterRef("item_id"))),
    )


def computable_days(period, official=None, until=None, include_start_day=False):
    """Única convención de días computables del sistema (README, «Supuestos y limitaciones»).

    Días corridos. Sin `until` devuelve los días del período; con `until`, los transcurridos hasta
    esa fecha (0 antes del inicio y el total después del término).
    - include_start_day=False (por defecto, ejemplo de la guía): (fecha - inicio). 1/07–30/09 da
      91 días y el 26/08 da 56 (61,54 %).
    - include_start_day=True (lote de ensayo CAL-D): conteo inclusivo. 1–30/10 da 30 días y el
      15/10 da 15 (50 %); el día de inicio ya cuenta 1.
    Con funcionario se descuentan sus rangos de ausencia, recortados al intervalo contado.
    """
    extra = 1 if include_start_day else 0
    if until is not None and until < period.start_date:
        return 0
    end = period.end_date if until is None else min(until, period.end_date)
    days = max(0, (end - period.start_date).days + extra)
    if official is not None and days:
        from accounts.models import OfficialAbsence
        absences = getattr(official, "_measurement_absences", None)
        if absences is None:
            absences = OfficialAbsence.objects.filter(official=official, deleted_at__isnull=True,
                start_date__lte=period.end_date, end_date__gte=period.start_date)
        start = period.start_date + timedelta(days=0 if include_start_day else 1)
        # La unión evita descuentos duplicados incluso ante datos legados superpuestos.
        intervals = sorted((max(start, a.start_date), min(end, a.end_date)) for a in absences
                           if a.start_date <= end and a.end_date >= start)
        last = start - timedelta(days=1)
        for first, final in intervals:
            first = max(first, last + timedelta(days=1))
            if final >= first:
                days -= (final - first).days + 1
                last = final
    return max(0, days)


def expected_percentage(period, on_date, official=None, include_start_day=False):
    total = computable_days(period, official, include_start_day=include_start_day)
    if total <= 0:
        return None if official is not None else HUNDRED
    elapsed = computable_days(period, official, on_date, include_start_day=include_start_day)
    return Decimal(elapsed) / Decimal(total) * HUNDRED


def traffic_light(compliance, expected, version):
    """RN-008 con los umbrales de la versión: verde desde green_threshold % de lo esperado,
    ámbar desde amber_threshold % de lo esperado y rojo bajo ese límite. Ambos valores en %."""
    if compliance is None or expected is None:
        return None
    if compliance >= expected * version.green_threshold / HUNDRED:
        return TrafficLight.GREEN
    if compliance >= expected * version.amber_threshold / HUNDRED:
        return TrafficLight.AMBER
    return TrafficLight.RED


@dataclass
class ItemResult:
    item: object
    goal_type: str
    goal: Decimal | None
    weight: Decimal
    progress: Decimal | None
    raw_compliance: Decimal | None
    compliance: Decimal
    weighted: Decimal
    expected_units: Decimal | None
    difference: Decimal | None
    traffic_light: str | None
    individual: bool = False
    notice: str = ""

    @property
    def is_percentage(self):
        return self.goal_type in (MeasurementItem.GoalType.PERCENTAGE, MeasurementItem.GoalType.MAX_PERCENTAGE)

    @property
    def traffic_light_label(self):
        return TrafficLight(self.traffic_light).label if self.traffic_light else "Sin semáforo"


@dataclass
class PerformanceResult:
    official: object
    period: object
    on_date: object
    version: MeasurementVersion | None
    expected_percentage: Decimal
    items: list = field(default_factory=list)
    notice: str = ""
    frozen: bool = False
    calculated_at: object = None
    frozen_total_light: str | None = None
    closing_delegation: object | None = None
    computable_days: int | None = None
    elapsed_days: int | None = None
    segments: list = field(default_factory=list)
    score_adjustments: list = field(default_factory=list)
    frozen_score_summary: dict = field(default_factory=dict)
    # Con tramos: última versión aplicada hasta el corte, aunque el último tramo no tenga plan.
    cap_version: MeasurementVersion | None = None

    @property
    def position(self):
        if self.frozen and self.version:
            return self.version.plan.position
        return self.official.position

    @property
    def base_total(self):
        if self.frozen_score_summary:
            return Decimal(self.frozen_score_summary["base"])
        return sum((row.weighted for row in self.items), Decimal("0"))

    @property
    def score_adjustment_total(self):
        return sum((Decimal(entry["applied_points"]) for entry in self.score_adjustments), Decimal("0"))

    @property
    def total(self):
        if self.frozen:
            return Decimal(self.frozen_score_summary["total"]) if self.frozen_score_summary else self.base_total
        return min(self.base_total + self.score_adjustment_total, self.max_final_score or MAX_FINAL_SCORE)

    @property
    def max_final_score(self):
        """Tope del resultado final. Congelado: el guardado al cierre (los resúmenes anteriores a este
        campo se calcularon con 150 fijo); sin resumen congelado no hubo ajustes ni tope aplicado."""
        if self.frozen:
            if not self.frozen_score_summary:
                return None
            return Decimal(self.frozen_score_summary.get("max_final", MAX_FINAL_SCORE))
        version = self.cap_version or self.version
        return version.max_final_score if version else MAX_FINAL_SCORE

    @property
    def activity_count(self):
        return sum((row.progress or 0) for row in self.items if row.goal_type == MeasurementItem.GoalType.QUANTITY)

    @property
    def total_traffic_light(self):
        # Un resultado congelado conserva el semáforo guardado al cierre; nunca se recalcula.
        if self.frozen:
            return self.frozen_total_light
        return traffic_light(self.total, self.expected_percentage, self.version) if self.version else None

    @property
    def max_computable(self):
        return self.version.max_computable if self.version else None


class CalculadorDesempenoService:
    """Servicio (sin tabla): avance, cumplimiento, meta esperada y snapshots de indicadores."""

    @staticmethod
    def approved_activities(official, period, until=None):
        """Actividades vigentes del período con evidencia aprobada, hasta `until` si se indica."""
        end = period.end_date if until is None else min(until, period.end_date)
        approved = EvidenceValidation.objects.filter(
            evidence__activity=OuterRef("pk"), evidence__deleted_at__isnull=True,
            deleted_at__isnull=True, status=EvidenceValidation.Status.APPROVED,
        )
        return Activity.objects.filter(
            official=official, date__range=(period.start_date, end), deleted_at__isnull=True,
        ).filter(Exists(approved))

    @classmethod
    def calculate_current_progress(cls, official, item, period):
        """Actividades del funcionario, ítem y período con evidencia aprobada (RN-003, RN-009).
        Cada actividad cuenta una sola vez aunque tenga varias imágenes aprobadas."""
        return cls.approved_activities(official, period).filter(item=item).count()

    @staticmethod
    def calculate_expected_goal_to_date(period, on_date=None, include_start_day=False, official=None):
        """Meta esperada al día (RN-007) en %, con dos decimales."""
        return q2(expected_percentage(period, on_date or timezone.localdate(), official, include_start_day=include_start_day))

    @classmethod
    def percentage_progress(cls, official, period, until=None):
        return cls._percentage_progress_by_official([official.pk], period, until).get(official.pk)

    @staticmethod
    def _percentage_progress_by_official(official_ids, period, until=None):
        """Ítems porcentuales («Soluciones de ingresos al tubo»): % de compromisos del funcionario
        con fecha comprometida en el período que están Realizados (guía, CAL-C y CAL-F).

        Con `until`, solo cuentan los compromisos creados hasta ese día y cada uno con el estado
        que tenía al cierre de ese día según su historial. Sin compromisos no hay denominador:
        devuelve None y el ítem no aporta."""
        from agenda.models import Commitment
        from analytics.segments import commitments_at_cutoff

        # Se acota al término dentro de commitments_at_cutoff: un período terminado no cambia
        # según el día de la consulta. Sin historial, el estado al corte es el actual.
        rows = commitments_at_cutoff(official_ids, period, until).order_by().values("responsible_id").annotate(
            total=Count("pk"), done=Count("pk", filter=Q(measured_status=Commitment.Status.DONE)),
        )
        return {row["responsible_id"]: Decimal(row["done"]) / row["total"] * HUNDRED for row in rows}

    @classmethod
    def counted_progress(cls, official, period, until=None):
        return cls._counted_progress_by_official([official.pk], period, until).get(official.pk, {})

    @staticmethod
    def _counted_progress_by_official(official_ids, period, until=None):
        """Avance por ítem. Cada actividad cuenta si su ítem está en la versión publicada que rige
        en su fecha para el cargo con que se registró; si el ítem quedó fuera del plan, no cuenta
        (criterio único en `computable_activities`)."""
        end = period.end_date if until is None else min(until, period.end_date)
        activities = Activity.objects.filter(
            official_id__in=official_ids, date__range=(period.start_date, end), deleted_at__isnull=True,
        )
        rows = computable_activities(activities).order_by().values("official_id", "item_id").annotate(total=Count("pk"))
        progress = defaultdict(dict)
        for row in rows:
            progress[row["official_id"]][row["item_id"]] = row["total"]
        return progress

    @classmethod
    def calculate(cls, official, period, on_date=None, include_start_day=False):
        """Resultado del funcionario en el período, con la versión vigente a la fecha de cálculo.

        El avance cuenta las actividades aprobadas con fecha hasta `on_date` (por defecto, hoy).

        `include_start_day` elige la convención de días computables (ver `computable_days`).
        La meta y el ponderador de cada ítem son los del ajuste individual cuando existe y, si no,
        los de la línea del plan. Los umbrales y el tope computable salen de la versión.
        """
        return cls.calculate_many((official,), period, on_date, include_start_day)[0]

    @classmethod
    def calculate_many(cls, officials, period, on_date=None, include_start_day=False):
        """Carga los datos de todo el equipo en bloque y usa el mismo cálculo para cada funcionario."""
        officials = list(officials)
        from accounts.models import OfficialAbsence, OfficialPositionPeriod
        absences = defaultdict(list)
        histories = defaultdict(list)
        ids = [official.pk for official in officials]
        for absence in OfficialAbsence.objects.filter(official_id__in=ids, deleted_at__isnull=True,
                start_date__lte=period.end_date, end_date__gte=period.start_date):
            absences[absence.official_id].append(absence)
        for history in OfficialPositionPeriod.objects.filter(official_id__in=ids, deleted_at__isnull=True,
                start_date__lte=period.end_date).filter(Q(end_date__isnull=True) | Q(end_date__gte=period.start_date)).select_related("position"):
            histories[history.official_id].append(history)
        for official in officials:
            official._measurement_absences = absences[official.pk]
        on_date = on_date or timezone.localdate()
        reference = min(max(on_date, period.start_date), period.end_date)
        position_ids = {official.position_id for official in officials if official.position_id is not None}
        versions = {}
        published = published_versions_on(reference, period).filter(plan__position_id__in=position_ids)
        for version in published.select_related("plan"):
            versions.setdefault(version.plan.position_id, version)
        version_ids = {version.pk for version in versions.values()}
        lines_by_version = defaultdict(list)
        for line in MeasurementItem.objects.filter(version_id__in=version_ids).select_related("item"):
            lines_by_version[line.version_id].append(line)

        measured = [official for official in officials if official.position_id in versions]
        official_ids = [official.pk for official in measured]
        adjustments_by_official = defaultdict(dict)
        adjustments = MeasurementAdjustment.objects.filter(
            official_id__in=official_ids, line__version_id__in=version_ids,
        ).order_by()
        for adjustment in adjustments:
            adjustments_by_official[adjustment.official_id][adjustment.line_id] = adjustment
        counted = cls._counted_progress_by_official(official_ids, period, on_date)
        percentage_versions = {
            version_id for version_id, lines in lines_by_version.items()
            if any(line.goal_type in (MeasurementItem.GoalType.PERCENTAGE, MeasurementItem.GoalType.MAX_PERCENTAGE) for line in lines)
        }
        percentage = cls._percentage_progress_by_official(
            [official.pk for official in measured if versions[official.position_id].pk in percentage_versions],
            period, on_date,
        )
        from analytics.segments import pending_percentages, segmented_results
        pending = pending_percentages(official_ids, period, on_date) if any(
            line.goal_type == MeasurementItem.GoalType.MAX_PERCENTAGE
            for lines in lines_by_version.values() for line in lines) else {}
        segmented = segmented_results(cls, [official for official in officials if histories[official.pk]],
                                      period, on_date, include_start_day, histories)
        scores = cls.approved_score_adjustments(ids, period, on_date)
        results = []
        for official in officials:
            result = segmented.get(official.pk)
            if result is None:
                version = versions.get(official.position_id)
                lines = lines_by_version[version.pk] if version else ()
                result = cls._build_result(
                    official, period, on_date, include_start_day, version, lines,
                    adjustments_by_official[official.pk], counted.get(official.pk, {}), percentage.get(official.pk),
                    pending.get(official.pk),
                )
            if result.items and result.computable_days:
                result.score_adjustments = scores.get(official.pk, [])
            results.append(result)
        return results

    @staticmethod
    def approved_score_adjustments(official_ids, period, on_date):
        adjustments = ScoreAdjustment.objects.filter(
            official_id__in=official_ids, period=period, occurred_on__lte=on_date,
            status=ScoreAdjustment.Status.APPROVED, deleted_at__isnull=True, points__isnull=False,
        )
        if on_date < period.end_date:
            # Los cortes intermedios muestran solo lo validado hasta ese día.
            # Al cierre también entran las validaciones tardías de hechos del período.
            cutoff = timezone.make_aware(datetime.combine(on_date + timedelta(days=1), time.min))
            adjustments = adjustments.filter(reviewed_at__lt=cutoff)
        entries = defaultdict(list)
        congratulations = defaultdict(int)
        for adjustment in adjustments.only("official", "kind", "occurred_on", "points").order_by("reviewed_at", "pk"):
            excluded = False
            if adjustment.kind == ScoreAdjustment.Kind.CONGRATULATION:
                congratulations[adjustment.official_id] += 1
                excluded = congratulations[adjustment.official_id] > MAX_CONGRATULATIONS
            entries[adjustment.official_id].append({
                "id": adjustment.pk,
                "kind": adjustment.get_kind_display(),
                "date": adjustment.occurred_on.isoformat(),
                "points": str(adjustment.points),
                "positive": adjustment.points > 0,
                "applied_points": "0" if excluded else str(adjustment.points),
                "excluded": excluded,
            })
        return entries

    @staticmethod
    def _build_result(official, period, on_date, include_start_day, version, lines, adjustments, counted, percentage, pending=None):
        expected = expected_percentage(period, on_date, official, include_start_day=include_start_day)
        result = PerformanceResult(official, period, on_date, version, expected)
        result.computable_days = computable_days(period, official, include_start_day=include_start_day)
        result.elapsed_days = computable_days(period, official, on_date, include_start_day=include_start_day)
        if result.computable_days == 0:
            result.notice = "Sin días computables: el período no se evalúa."
        if official.position_id is None:
            result.notice = "El funcionario no tiene cargo asignado."
            return result
        if version is None:
            result.notice = "No hay un plan de medición publicado para el cargo en este período."
            return result

        for line in lines:
            adjustment = adjustments.get(line.pk)
            goal = adjustment.goal if adjustment and adjustment.goal is not None else line.goal
            weight = adjustment.weight if adjustment and adjustment.weight is not None else line.weight
            weight = weight or Decimal("0")
            if line.goal_type == MeasurementItem.GoalType.MAX_PERCENTAGE:
                progress = pending
            elif line.goal_type == MeasurementItem.GoalType.PERCENTAGE:
                progress = percentage
            else:
                progress = Decimal(counted.get(line.item_id, 0))
            row = ItemResult(
                item=line.item, goal_type=line.goal_type, goal=goal, weight=weight, progress=progress, raw_compliance=None,
                compliance=Decimal("0"), weighted=Decimal("0"), expected_units=None, difference=None,
                traffic_light=None, individual=adjustment is not None,
            )
            if result.computable_days == 0:
                row.notice = "Sin días computables: el ítem no se evalúa."
            elif goal is None or goal <= 0:
                row.notice = "Meta no válida: el ítem no se calcula."
            elif progress is None:
                row.notice = "Sin compromisos en el período: el ítem no aporta."
                row.expected_units = goal if row.is_percentage else goal * expected / HUNDRED
            else:
                # Matriz SGR, SALON!G23: escalones 100/50/0; prevalece sobre el supuesto proporcional.
                if line.goal_type == MeasurementItem.GoalType.MAX_PERCENTAGE:
                    row.raw_compliance = HUNDRED if progress <= goal else Decimal("50") if progress <= 50 else Decimal("0")
                else:
                    row.raw_compliance = progress / goal * HUNDRED
                row.compliance = min(row.raw_compliance, version.max_computable)
                row.weighted = weight * row.compliance / HUNDRED
                row.expected_units = goal if line.goal_type == MeasurementItem.GoalType.MAX_PERCENTAGE else goal * expected / HUNDRED
                row.difference = progress - row.expected_units
                row.traffic_light = traffic_light(row.raw_compliance, HUNDRED if line.goal_type == MeasurementItem.GoalType.MAX_PERCENTAGE else expected, version)
            result.items.append(row)
        return result

    @staticmethod
    def build_snapshot(result, row, calculated_at, frozen=False):
        """Snapshot con el resultado completo; el ponderado y el avance se guardan ya calculados."""
        return IndicatorSnapshot(
            official=result.official, item=row.item, period=result.period, version=result.version,
            closing_delegation_id=result.official.delegation_id if frozen else None,
            goal_type=row.goal_type, goal=q2(row.goal) if row.goal is not None else None, progress=row.progress,
            raw_compliance=row.raw_compliance, compliance=q2(row.compliance), applied_weighting=q2(row.weight),
            weighted=row.weighted, expected_percentage=result.expected_percentage,
            expected_units=row.expected_units, difference=row.difference, individual=row.individual,
            notice=row.notice, traffic_light=row.traffic_light or "", is_frozen=frozen,
            total_traffic_light=result.total_traffic_light or "", calculated_at=calculated_at,
            computable_days=result.computable_days, elapsed_days=result.elapsed_days,
            segments=result.segments, result_notice=result.notice,
            score_summary={
                "base": str(result.base_total), "total": str(result.total),
                "max_final": str(result.max_final_score),
                "adjustments": result.score_adjustments,
            },
        )

    @classmethod
    def generate_snapshots(cls, official, period, on_date=None, frozen=False):
        """Guarda un IndicatorSnapshot por ítem del plan vigente."""
        result = cls.calculate(official, period, on_date)
        now = timezone.now()
        return IndicatorSnapshot.objects.bulk_create(
            [cls.build_snapshot(result, row, now, frozen) for row in result.items])

    @classmethod
    def generate_snapshot(cls, official, period, item, on_date=None):
        """Snapshot de un solo ítem; None si el ítem no está en el plan vigente."""
        result = cls.calculate(official, period, on_date)
        row = next((row for row in result.items if row.item.pk == item.pk), None)
        if row is None:
            return None
        snapshot = cls.build_snapshot(result, row, timezone.now())
        snapshot.save()
        return snapshot

    @staticmethod
    def frozen_snapshots(period):
        return IndicatorSnapshot.objects.filter(period=period, is_frozen=True, deleted_at__isnull=True)

    @classmethod
    def frozen_result(cls, official, period, snapshots=None):
        """Resultado oficial de un período cerrado, leído de los snapshots congelados (RN-013).
        Nunca se recalcula. None si el período no está congelado (`frozen_at` nulo)."""
        if period.frozen_at is None:
            return None
        if snapshots is None:
            snapshots = list(cls.frozen_snapshots(period).filter(official=official)
                             .select_related("item", "version", "closing_delegation").order_by("item__item_name", "pk"))
        version = snapshots[0].version if snapshots else None
        expected = snapshots[0].expected_percentage if snapshots else HUNDRED
        result = PerformanceResult(official, period, period.end_date, version,
                                   expected if expected is not None else HUNDRED, frozen=True,
                                   calculated_at=snapshots[0].calculated_at if snapshots else period.frozen_at,
                                   frozen_total_light=(snapshots[0].total_traffic_light or None) if snapshots else None,
                                   closing_delegation=snapshots[0].closing_delegation if snapshots else None)
        if snapshots:
            result.expected_percentage = snapshots[0].expected_percentage
            result.computable_days = snapshots[0].computable_days
            result.elapsed_days = snapshots[0].elapsed_days
            result.segments = snapshots[0].segments
            result.notice = snapshots[0].result_notice
            result.frozen_score_summary = snapshots[0].score_summary
            result.score_adjustments = result.frozen_score_summary.get("adjustments", [])
        if not snapshots:
            result.notice = "El funcionario no tenía un plan de medición aplicable al cerrar el período."
        for snapshot in snapshots:
            result.items.append(ItemResult(
                item=snapshot.item, goal_type=snapshot.goal_type, goal=snapshot.goal,
                weight=snapshot.applied_weighting, progress=snapshot.progress,
                raw_compliance=snapshot.raw_compliance, compliance=snapshot.compliance,
                weighted=snapshot.weighted, expected_units=snapshot.expected_units,
                difference=snapshot.difference, traffic_light=snapshot.traffic_light or None,
                individual=snapshot.individual, notice=snapshot.notice,
            ))
        return result

    @classmethod
    def result_for(cls, official, period, on_date=None):
        """Lo que se muestra: el resultado congelado si el período está cerrado; si no, el cálculo
        en vivo. Un período cerrado sin congelar devuelve un aviso, nunca un recálculo."""
        if period.status == period.Status.CLOSED:
            frozen = cls.frozen_result(official, period)
            if frozen is not None:
                return frozen
            result = PerformanceResult(official, period, period.end_date, None, HUNDRED, frozen=True)
            result.notice = ("El período está cerrado y aún no tiene resultados congelados. "
                             "Un administrador debe ejecutar freeze_period.")
            return result
        return cls.calculate(official, period, on_date)

    @classmethod
    def freeze_period(cls, period, replace=False):
        """Congela el resultado de cada funcionario medible del período al día de término y fija
        `period.frozen_at`, aunque no se genere ninguna fila.

        Idempotente: con `frozen_at` ya fijado no hace nada, salvo con `replace=True` (nuevo
        cierre tras una reapertura), que archiva los snapshots anteriores y congela de nuevo.
        Los funcionarios archivados no se congelan. Devuelve la cantidad de snapshots creados.
        """
        from accounts.models import Official, OfficialPositionPeriod

        if period.frozen_at is not None and not replace:
            return 0
        now = timezone.now()
        cls.frozen_snapshots(period).update(deleted_at=now)
        officials = Official.objects.filter(
            Q(position__measurementplan__period=period, position__measurementplan__deleted_at__isnull=True)
            | Q(activities__date__range=(period.start_date, period.end_date)),
            # Incluye cargos anteriores que ya no coinciden con el cargo actual.
            deleted_at__isnull=True,
        ).distinct().order_by("pk")
        historical_ids = OfficialPositionPeriod.objects.filter(start_date__lte=period.end_date,
            deleted_at__isnull=True).filter(Q(end_date__isnull=True) | Q(end_date__gte=period.start_date)).values("official_id")
        officials = Official.objects.filter(Q(pk__in=officials.values("pk")) | Q(pk__in=historical_ids), deleted_at__isnull=True)
        from analytics.support import save_supports, support_rows

        snapshots, supports = [], {}
        for official in officials:
            result = cls.calculate(official, period, period.end_date)
            for row in result.items:
                snapshot = cls.build_snapshot(result, row, now, frozen=True)
                snapshot.support_captured = True
                snapshots.append(snapshot)
            # Respaldo exacto con el mismo criterio y corte que la cifra congelada.
            for (item_id, goal_type), rows in support_rows(result, period.end_date).items():
                supports[official.pk, item_id, goal_type] = rows
        IndicatorSnapshot.objects.bulk_create(snapshots, batch_size=500)
        if supports:
            # En MySQL bulk_create no devuelve las PK: se leen los congelados recién creados (los
            # anteriores ya quedaron archivados arriba).
            save_supports(cls.frozen_snapshots(period).only("pk", "official_id", "item_id", "goal_type"), supports)
        from analytics.territorial import freeze_territorial_activities

        freeze_territorial_activities(period, now)
        period.frozen_at = now
        period.save(update_fields=["frozen_at", "updated_at"])
        return len(snapshots)
