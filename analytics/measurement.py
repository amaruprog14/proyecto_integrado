from collections import defaultdict
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.utils import timezone

from analytics.models import MeasurementAdjustment, MeasurementItem, MeasurementVersion
from configuration.models import Item


VIEW_PLAN = "analytics.view_measurementplan"
ADD_PLAN = "analytics.add_measurementplan"
CHANGE_PLAN = "analytics.change_measurementplan"
PUBLISH_PLAN = "analytics.publish_measurementplan"


def version_for(position_id, date):
    if position_id is None or date is None:
        return None
    return MeasurementVersion.objects.filter(
        plan__position_id=position_id, plan__deleted_at__isnull=True,
        plan__period__deleted_at__isnull=True, plan__period__start_date__lte=date,
        plan__period__end_date__gte=date, effective_from__lte=date, published_at__isnull=False,
    ).order_by("-effective_from").first()


def eligible_items(position_id, date):
    items = Item.objects.filter(is_active=True, deleted_at__isnull=True)
    version = version_for(position_id, date)
    return items.filter(pk__in=version.items.values("item_id")) if version else items


def activity_measurement(activity):
    position = activity.registration_position if activity.registration_position_captured else activity.official.position
    version = version_for(position.pk if position else None, activity.date)
    line = version.items.filter(item_id=activity.item_id).first() if version else None
    adjustment = line.adjustments.filter(official_id=activity.official_id).first() if line else None
    return {
        "official_id": activity.official_id,
        "position": position,
        "inferred": not activity.registration_position_captured and position is not None,
        "version": version,
        "excluded": version is not None and line is None,
        "goal": adjustment.goal if adjustment and adjustment.goal is not None else line.goal if line else None,
        "weight": adjustment.weight if adjustment and adjustment.weight is not None else line.weight if line else None,
        "percentage": line is not None and line.goal_type == MeasurementItem.GoalType.PERCENTAGE,
    }


def publish_version(version):
    """El llamador mantiene bloqueado el registro de períodos durante la publicación."""
    if version.is_published:
        raise ValidationError("Esta versión ya está publicada.")
    period = version.plan.period
    if period.status != period.Status.OPEN:
        raise ValidationError("El período está cerrado.")
    if not version.plan.position.is_active or version.plan.position.deleted_at:
        raise ValidationError("El cargo debe estar vigente para publicar.")
    previous = version.plan.versions.filter(published_at__isnull=False).first()
    if previous is None and version.effective_from != period.start_date:
        raise ValidationError({"effective_from": "La primera versión debe comenzar el primer día del período."})
    if previous and not previous.effective_from < version.effective_from <= period.end_date:
        raise ValidationError({"effective_from": "Elige una fecha posterior a la última vigencia y dentro del período."})
    if version.amber_threshold >= version.green_threshold:
        raise ValidationError({"amber_threshold": "El umbral naranjo debe ser menor que el verde."})

    lines = list(version.items.select_related("item", "function").prefetch_related("adjustments__official"))
    if not lines:
        raise ValidationError("Agrega al menos un ítem de medición antes de publicar.")
    functions = set(version.plan.position.functions.filter(
        is_active=True, deleted_at__isnull=True,
    ).values_list("pk", flat=True))
    differences = defaultdict(Decimal)
    officials = {}
    total = Decimal("0")
    errors = []
    for line in lines:
        if line.function_id not in functions or not line.item.is_active or line.item.deleted_at:
            errors.append(f"{line.item}: selecciona una función del cargo y un ítem vigentes.")
        if line.goal is None or line.weight is None:
            errors.append(f"{line.item}: completa la meta y el ponderador.")
            continue
        total += line.weight
        for adjustment in line.adjustments.all():
            official = adjustment.official
            officials[official.pk] = official
            if official.position_id != version.plan.position_id or official.deleted_at or official.status != official.Status.ACTIVE:
                errors.append(f"{official}: el ajuste requiere un funcionario activo de este cargo.")
            if adjustment.weight is not None:
                differences[official.pk] += adjustment.weight - line.weight
    if total != 100:
        errors.append(f"Los ponderadores del cargo suman {total:.2f} %. Deben sumar 100 %.")
    errors.extend(
        f"Los ponderadores de {officials[pk]} suman {total + difference:.2f} %. Deben sumar 100 %."
        for pk, difference in differences.items() if total + difference != 100
    )
    if errors:
        raise ValidationError(errors)
    version.published_at = timezone.now()
    version.save(update_fields=["effective_from", "published_at", "updated_at"])


def create_revision(plan, effective_from):
    previous = plan.versions.first()
    version = plan.versions.create(
        number=previous.number + 1, effective_from=effective_from,
        max_computable=previous.max_computable, amber_threshold=previous.amber_threshold,
        green_threshold=previous.green_threshold, collective_threshold=previous.collective_threshold,
    )
    for line in previous.items.prefetch_related("adjustments"):
        new_line = MeasurementItem.objects.create(
            version=version, function_id=line.function_id, item_id=line.item_id,
            goal_type=line.goal_type, goal=line.goal, weight=line.weight,
        )
        MeasurementAdjustment.objects.bulk_create([
            MeasurementAdjustment(line=new_line, official_id=adjustment.official_id,
                                  goal=adjustment.goal, weight=adjustment.weight)
            for adjustment in line.adjustments.all()
        ])
    return version
