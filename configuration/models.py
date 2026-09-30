from django.core.exceptions import ValidationError
from django.db import models

from common.mixins import BaseModel


class Item(BaseModel):
    """Tabla maestra: ítems medibles del sistema, usado luego por Actividad."""

    item_name = models.CharField(max_length=150, unique=True, verbose_name="Nombre del ítem")
    is_active = models.BooleanField(default=True, verbose_name="Vigente")

    class Meta:
        verbose_name = "Ítem"
        verbose_name_plural = "Ítems"
        ordering = ["item_name"]

    def __str__(self):
        return self.item_name


class Period(BaseModel):
    """Tabla maestra: períodos de evaluación/gestión (ej. mensual, trimestral)."""

    class Status(models.TextChoices):
        OPEN = "OPEN", "Abierto"
        CLOSED = "CLOSED", "Cerrado"

    start_date = models.DateField(verbose_name="Fecha de inicio")
    end_date = models.DateField(verbose_name="Fecha de término")
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.OPEN, verbose_name="Estado"
    )

    class Meta:
        verbose_name = "Período"
        verbose_name_plural = "Períodos"
        ordering = ["-start_date"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(end_date__gte=models.F("start_date")),
                name="period_end_date_gte_start_date",
            )
        ]

    def __str__(self):
        return f"{self.start_date} - {self.end_date}"

    def clean(self):
        super().clean()
        if not self.start_date or not self.end_date:
            return

        if self.end_date < self.start_date:
            raise ValidationError(
                {"end_date": "La fecha de término debe ser igual o posterior a la fecha de inicio."}
            )

        overlapping_periods = type(self).objects.filter(
            start_date__lte=self.end_date,
            end_date__gte=self.start_date,
        )
        if self.pk:
            overlapping_periods = overlapping_periods.exclude(pk=self.pk)
        if overlapping_periods.exists():
            raise ValidationError({"start_date": "El período se solapa con otro período existente."})

    def close_period(self):
        self.status = self.Status.CLOSED
        self.save(update_fields=["status", "updated_at"])