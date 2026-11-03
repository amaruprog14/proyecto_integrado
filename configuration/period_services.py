"""Serialización de altas y cierres sobre las mismas filas de períodos."""
from django.core.exceptions import ValidationError
from configuration.models import Period, PeriodMutex


def lock_open_period(date):
    period = Period.objects.select_for_update().filter(start_date__lte=date,
        end_date__gte=date, deleted_at__isnull=True).first()
    if period is None or period.status != Period.Status.OPEN:
        raise ValidationError("La fecha debe pertenecer a un período abierto.")
    return period


def lock_activity_periods(activity, new_date=None):
    dates = sorted({activity.date, new_date or activity.date})
    for date in dates:
        lock_open_period(date)


def lock_period_registry():
    PeriodMutex.objects.get_or_create(pk=1)
    PeriodMutex.objects.select_for_update().get(pk=1)
