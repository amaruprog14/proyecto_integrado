"""Rangos de ausencias y de cargos; escrituras serializadas contra el cierre del período."""
from datetime import date

from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.db.models import Q
from django.utils import timezone

from common.mixins import BaseModel


def ensure_mutable_range(start, end):
    from configuration.models import Period
    if start and Period.objects.filter(
        start_date__lte=end or date.max, end_date__gte=start, deleted_at__isnull=True,
    ).filter(Q(status=Period.Status.CLOSED) | Q(frozen_at__isnull=False)).exists():
        raise ValidationError("El rango afecta un período cerrado o congelado y no se puede modificar.")


class OfficialRange(BaseModel):
    official = models.ForeignKey("accounts.Official", on_delete=models.PROTECT, verbose_name="Funcionario")
    start_date = models.DateField(verbose_name="Desde")
    end_date = models.DateField(null=True, blank=True, verbose_name="Hasta")

    class Meta:
        abstract = True

    def clean(self):
        super().clean()
        if not self.start_date:
            return
        if self.end_date and self.end_date < self.start_date:
            raise ValidationError({"end_date": "El término debe ser igual o posterior al inicio."})
        if self.official_id and type(self).objects.filter(
            official_id=self.official_id, deleted_at__isnull=True,
            start_date__lte=self.end_date or date.max,
        ).filter(Q(end_date__isnull=True) | Q(end_date__gte=self.start_date)).exclude(pk=self.pk).exists():
            raise ValidationError("El rango se superpone con otro registro del funcionario.")
        ensure_mutable_range(self.start_date, self.end_date)
        if self.pk:
            previous = type(self).objects.get(pk=self.pk)
            ensure_mutable_range(previous.start_date, previous.end_date)

    @transaction.atomic
    def save(self, *args, **kwargs):
        from accounts.models import Official
        from configuration.period_services import lock_period_registry
        lock_period_registry()
        Official.objects.select_for_update().get(pk=self.official_id)
        self.full_clean()
        return super().save(*args, **kwargs)

    def delete(self, using=None, keep_parents=False):
        self.deleted_at = timezone.now()
        self.save(update_fields=["deleted_at", "updated_at"])


class OfficialAbsence(OfficialRange):
    class Kind(models.TextChoices):
        LICENCIA = "LICENCIA", "Licencia"
        VACACIONES = "VACACIONES", "Vacaciones"
        EMERGENCIA = "EMERGENCIA", "Emergencia"
        COMPENSATORIO = "COMPENSATORIO", "Compensatorio"

    kind = models.CharField(max_length=16, choices=Kind.choices, verbose_name="Tipo")
    end_date = models.DateField(verbose_name="Hasta")
    reason = models.TextField(max_length=500, verbose_name="Motivo")
    registered_by = models.ForeignKey("accounts.Official", on_delete=models.PROTECT, related_name="registered_absences",
                                      verbose_name="Registrada por")

    class Meta:
        ordering = ["-start_date", "-pk"]
        verbose_name = "Ausencia"
        verbose_name_plural = "Ausencias"
        permissions = [("manage_absence", "Puede gestionar ausencias")]
        constraints = [models.CheckConstraint(condition=Q(end_date__gte=models.F("start_date")), name="absence_valid_dates")]
        indexes = [models.Index(fields=["official", "start_date", "end_date"], name="absence_official_dates")]

    def clean(self):
        super().clean()
        if not (self.reason or "").strip():
            raise ValidationError({"reason": "Indica el motivo de la ausencia."})

    def __str__(self):
        return f"{self.official} · {self.get_kind_display()} · {self.start_date} al {self.end_date}"


class OfficialPositionPeriod(OfficialRange):
    position = models.ForeignKey("accounts.Position", on_delete=models.PROTECT, verbose_name="Cargo")

    class Meta:
        ordering = ["start_date", "pk"]
        verbose_name = "Tramo de cargo"
        constraints = [models.CheckConstraint(condition=Q(end_date__isnull=True) | Q(end_date__gte=models.F("start_date")),
                                               name="position_period_valid_dates")]
        indexes = [models.Index(fields=["official", "start_date"], name="position_period_official")]
