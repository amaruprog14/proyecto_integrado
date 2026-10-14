from decimal import Decimal

from django.utils import timezone

from activities.models import Activity, EvidenceValidation
from analytics.models import GoalThreshold, IndicatorSnapshot, Weighting


class CalculadorDesempenoService:
    """Servicio (sin tabla): cálculos de avance, meta esperada y snapshots de indicadores."""

    @staticmethod
    def calculate_current_progress(official, item, period):
        """
        Avance actual (RN-003, RN-009): actividades del funcionario, ítem y período
        con al menos una validación aprobada. Cada actividad cuenta una sola vez.
        """
        return (
            Activity.objects.filter(
                official=official,
                item=item,
                date__range=(period.start_date, period.end_date),
                deleted_at__isnull=True,
                evidences__deleted_at__isnull=True,
                evidences__validations__status=EvidenceValidation.Status.APPROVED,
            )
            .distinct()
            .count()
        )

    @staticmethod
    def calculate_expected_goal_to_date(period, on_date=None):
        """
        Meta esperada al día (RN-007) en %: días transcurridos / días totales x 100.
        Sigue el ejemplo de la guía: 1/07 a 30/09 = 91 días y el 26/08 = 56 días (61,54 %).
        Días corridos, con tope de 100 %; el tratamiento de días no computables queda pendiente.
        """
        on_date = on_date or timezone.localdate()
        total_days = (period.end_date - period.start_date).days
        if total_days <= 0:
            return Decimal("100.00")
        elapsed = (min(on_date, period.end_date) - period.start_date).days
        elapsed = max(0, min(elapsed, total_days))
        return (Decimal(elapsed) / Decimal(total_days) * 100).quantize(Decimal("0.01"))

    @classmethod
    def generate_snapshot(cls, official, period, item, on_date=None):
        """Calcula y guarda el IndicatorSnapshot de un ítem para el funcionario y período."""
        on_date = on_date or timezone.localdate()
        threshold = (
            GoalThreshold.objects.filter(item=item, valid_from__lte=on_date, deleted_at__isnull=True)
            .exclude(valid_to__lt=on_date)
            .order_by("-version")
            .first()
        )
        weighting = Weighting.objects.filter(
            item=item, position=official.position, period=period, deleted_at__isnull=True
        ).first() or Weighting.objects.filter(
            item=item, position=official.position, period__isnull=True, deleted_at__isnull=True
        ).first()

        snapshot = IndicatorSnapshot(
            official=official,
            item=item,
            period=period,
            goal=threshold.goal if threshold else Decimal("0"),
            progress=Decimal(cls.calculate_current_progress(official, item, period)),
            applied_weighting=weighting.percentage if weighting else Decimal("0"),
            calculated_at=timezone.now(),
        )
        snapshot.calculate_compliance(threshold.max_computable_threshold if threshold else None)

        # La meta esperada al día se expresa en las unidades del ítem: % del período x meta.
        expected_pct = cls.calculate_expected_goal_to_date(period, on_date)
        expected_units = snapshot.goal * expected_pct / 100
        snapshot.determine_traffic_light(expected_units)
        snapshot.save()
        return snapshot

    @classmethod
    def generate_snapshots(cls, official, period, on_date=None):
        """Genera un snapshot por cada ítem ponderado para el cargo del funcionario en el período."""
        items = {
            w.item
            for w in Weighting.objects.filter(
                position=official.position, deleted_at__isnull=True
            ).filter(period=period).select_related("item")
        } or {
            w.item
            for w in Weighting.objects.filter(
                position=official.position, period__isnull=True, deleted_at__isnull=True
            ).select_related("item")
        }
        return [cls.generate_snapshot(official, period, item, on_date) for item in items]
