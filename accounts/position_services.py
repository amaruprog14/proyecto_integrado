from datetime import timedelta

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from accounts.models import Official, OfficialPositionPeriod
from configuration.models import Period
from configuration.period_services import lock_period_registry
from configuration.services import AuditoriaService


@transaction.atomic
def change_position(official, position, effective_from, actor):
    """Cambio fechado, incluyendo el tramo anterior de funcionarios sin historial previo.

    No inventa cargos anteriores: el primer cargo conocido se extiende al inicio del primer
    período abierto alcanzado por el cambio. Los resultados ya congelados no se reescriben.
    """
    lock_period_registry()
    locked = Official.objects.select_for_update().get(pk=official.pk)
    if locked.position_id == getattr(position, "pk", None):
        return locked
    if not position:
        raise ValidationError("Para cambiar de cargo selecciona un cargo vigente.")
    if not position.is_active or position.deleted_at:
        raise ValidationError("El cargo debe estar vigente.")
    periods = list(Period.objects.select_for_update().filter(deleted_at__isnull=True).order_by("start_date"))
    if any((p.status == p.Status.CLOSED or p.frozen_at) and p.end_date >= effective_from for p in periods):
        raise ValidationError("El cambio afecta un período cerrado o congelado.")
    history = list(OfficialPositionPeriod.objects.select_for_update().filter(
        official=locked, deleted_at__isnull=True).order_by("start_date"))
    if history:
        previous = history[-1]
        if previous.end_date is not None or effective_from <= previous.start_date:
            raise ValidationError("El cambio debe ser posterior al inicio del último tramo abierto.")
        previous.end_date = effective_from - timedelta(days=1)
        # Solo se acorta el futuro del tramo; sus fechas ya cerradas no se alteran.
        OfficialPositionPeriod.objects.filter(pk=previous.pk).update(end_date=previous.end_date, updated_at=timezone.now())
        AuditoriaService.register_change(actor, "Cierre de tramo de cargo", previous, new_value=str(previous.end_date))
    elif locked.position_id:
        closed_ends = [p.end_date for p in periods if p.status == p.Status.CLOSED or p.frozen_at]
        earliest = min([p.start_date for p in periods if p.status == p.Status.OPEN and not p.frozen_at] or [effective_from])
        start = max(earliest, max(closed_ends) + timedelta(days=1)) if closed_ends else earliest
        if start < effective_from:
            previous = OfficialPositionPeriod.objects.create(official=locked, position=locked.position,
                start_date=start, end_date=effective_from - timedelta(days=1))
            AuditoriaService.register_change(actor, "Registro de tramo anterior", previous, new_value=str(locked.position))
    current = OfficialPositionPeriod.objects.create(official=locked, position=position, start_date=effective_from)
    Official.objects.filter(pk=locked.pk).update(position=position, updated_at=timezone.now())
    AuditoriaService.register_change(actor, "Cambio de cargo", current,
        previous_value=str(locked.position or "Sin cargo"), new_value=f"{position} · desde {effective_from}")
    official.position = position
    return official
