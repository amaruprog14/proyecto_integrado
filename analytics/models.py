from datetime import timedelta
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.utils import timezone

from accounts.models import Official, Position
from common.mixins import BaseModel
from configuration.models import Item, Period


class GoalThreshold(BaseModel):
    """Tabla maestra versionada: meta y umbrales por ítem (MetaUmbral)."""

    item = models.ForeignKey(
        Item, on_delete=models.PROTECT, related_name="goal_thresholds", verbose_name="Ítem"
    )
    goal = models.DecimalField(max_digits=12, decimal_places=2, verbose_name="Meta")
    min_threshold = models.DecimalField(
        max_digits=6, decimal_places=2, default=Decimal("0"), verbose_name="Umbral mínimo (%)"
    )
    max_computable_threshold = models.DecimalField(
        max_digits=6, decimal_places=2, default=Decimal("150"), verbose_name="Máximo computable (%)"
    )
    amber_threshold = models.DecimalField(
        max_digits=6, decimal_places=2, default=Decimal("60"), verbose_name="Umbral ámbar (%)"
    )
    green_threshold = models.DecimalField(
        max_digits=6, decimal_places=2, default=Decimal("100"), verbose_name="Umbral verde (%)"
    )
    collective_threshold = models.DecimalField(
        max_digits=6, decimal_places=2, default=Decimal("80"), verbose_name="Umbral colectivo (%)"
    )
    version = models.PositiveIntegerField(default=1, verbose_name="Versión")
    valid_from = models.DateField(verbose_name="Vigente desde")
    valid_to = models.DateField(null=True, blank=True, verbose_name="Vigente hasta")

    class Meta:
        verbose_name = "Meta y umbral"
        verbose_name_plural = "Metas y umbrales"
        ordering = ["item", "-version"]
        constraints = [
            models.UniqueConstraint(fields=["item", "version"], name="uniq_goal_threshold_item_version"),
            models.CheckConstraint(
                condition=models.Q(valid_to__isnull=True) | models.Q(valid_to__gte=models.F("valid_from")),
                name="goal_threshold_valid_to_gte_valid_from",
            ),
        ]

    def __str__(self):
        return f"{self.item} v{self.version}"

    def clean(self):
        super().clean()
        if self.goal is not None and self.goal <= 0:
            raise ValidationError({"goal": "La meta debe ser mayor que cero."})

    def is_current(self, on_date=None):
        on_date = on_date or timezone.localdate()
        return self.valid_from <= on_date and (self.valid_to is None or on_date <= self.valid_to)

    @transaction.atomic
    def create_new_version(self, **changes):
        """
        Cierra esta versión (valid_to = día anterior a la nueva vigencia) y crea la siguiente.
        `changes` permite sobrescribir campos, p. ej. goal=120 o valid_from=date(...).
        """
        new_from = changes.pop("valid_from", timezone.localdate())
        self.valid_to = new_from - timedelta(days=1)
        self.save(update_fields=["valid_to", "updated_at"])
        data = {
            "item": self.item,
            "goal": self.goal,
            "min_threshold": self.min_threshold,
            "max_computable_threshold": self.max_computable_threshold,
            "amber_threshold": self.amber_threshold,
            "green_threshold": self.green_threshold,
            "collective_threshold": self.collective_threshold,
        }
        data.update(changes)
        return type(self).objects.create(version=self.version + 1, valid_from=new_from, **data)


class Weighting(BaseModel):
    """Tabla maestra: ponderación (%) de un ítem para un cargo (Ponderacion)."""

    item = models.ForeignKey(
        Item, on_delete=models.PROTECT, related_name="weightings", verbose_name="Ítem"
    )
    position = models.ForeignKey(
        Position, on_delete=models.PROTECT, related_name="weightings", verbose_name="Cargo"
    )
    percentage = models.DecimalField(max_digits=5, decimal_places=2, verbose_name="Porcentaje")

    class Meta:
        verbose_name = "Ponderación"
        verbose_name_plural = "Ponderaciones"
        ordering = ["position", "item"]
        constraints = [
            models.UniqueConstraint(fields=["item", "position"], name="uniq_weighting_item_position"),
            models.CheckConstraint(
                condition=models.Q(percentage__gte=0) & models.Q(percentage__lte=100),
                name="weighting_percentage_between_0_and_100",
            ),
        ]

    def __str__(self):
        return f"{self.position} / {self.item}: {self.percentage}%"


class IndicatorSnapshot(BaseModel):
    """Tabla operativa: foto del indicador de un funcionario por ítem y período."""

    class TrafficLight(models.TextChoices):
        GREEN = "GREEN", "Verde"
        AMBER = "AMBER", "Ámbar"
        RED = "RED", "Rojo"

    official = models.ForeignKey(
        Official, on_delete=models.PROTECT, related_name="indicator_snapshots", verbose_name="Funcionario"
    )
    item = models.ForeignKey(
        Item, on_delete=models.PROTECT, related_name="indicator_snapshots", verbose_name="Ítem"
    )
    period = models.ForeignKey(
        Period, on_delete=models.PROTECT, related_name="indicator_snapshots", verbose_name="Período"
    )
    goal = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0"), verbose_name="Meta")
    progress = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0"), verbose_name="Avance")
    compliance = models.DecimalField(
        max_digits=8, decimal_places=2, default=Decimal("0"), verbose_name="Cumplimiento (%)"
    )
    applied_weighting = models.DecimalField(
        max_digits=5, decimal_places=2, default=Decimal("0"), verbose_name="Ponderación aplicada (%)"
    )
    adjustment = models.DecimalField(
        max_digits=8, decimal_places=2, default=Decimal("0"), verbose_name="Ajuste"
    )
    traffic_light = models.CharField(
        max_length=10, choices=TrafficLight.choices, blank=True, verbose_name="Semáforo"
    )
    calculated_at = models.DateTimeField(default=timezone.now, verbose_name="Fecha de cálculo")

    class Meta:
        verbose_name = "Indicador (snapshot)"
        verbose_name_plural = "Indicadores (snapshots)"
        ordering = ["-calculated_at"]
        indexes = [models.Index(fields=["official", "period", "item"])]

    def __str__(self):
        return f"{self.official} / {self.item} / {self.period}"

    def calculate_compliance(self, max_computable=None):
        """% de cumplimiento = avance / meta x 100 (RN-004), limitado al máximo computable si se indica."""
        if not self.goal or self.goal <= 0:
            self.compliance = Decimal("0")
        else:
            value = (self.progress / self.goal * 100).quantize(Decimal("0.01"))
            if max_computable is not None:
                value = min(value, Decimal(max_computable))
            self.compliance = value
        return self.compliance

    def calculate_weighted_compliance(self):
        """Cumplimiento ponderado = ponderador x % de cumplimiento (RN-005)."""
        return (self.applied_weighting / 100 * self.compliance).quantize(Decimal("0.01"))

    def determine_traffic_light(self, expected_goal_to_date, amber_ratio=Decimal("0.6")):
        """
        RN-008: verde si el avance >= meta esperada; ámbar si >= 60 % de ella; rojo en otro caso.
        `expected_goal_to_date` está en las mismas unidades que `progress`.
        """
        expected = Decimal(expected_goal_to_date)
        if self.progress >= expected:
            self.traffic_light = self.TrafficLight.GREEN
        elif self.progress >= expected * Decimal(amber_ratio):
            self.traffic_light = self.TrafficLight.AMBER
        else:
            self.traffic_light = self.TrafficLight.RED
        return self.traffic_light


class IncentiveApplication(BaseModel):
    """Tabla operativa: incentivo o penalización aplicado a un indicador."""

    class Kind(models.TextChoices):
        CONGRATULATION = "CONGRATULATION", "Felicitación"
        COMPLAINT = "COMPLAINT", "Reclamo"
        BONUS = "BONUS", "Incentivo"
        PENALTY = "PENALTY", "Penalización"

    indicator = models.ForeignKey(
        IndicatorSnapshot,
        on_delete=models.PROTECT,
        related_name="incentive_applications",
        verbose_name="Indicador",
    )
    applied_value = models.DecimalField(
        max_digits=8, decimal_places=2, verbose_name="Valor aplicado (positivo o negativo)"
    )
    kind = models.CharField(max_length=20, choices=Kind.choices, verbose_name="Tipo")

    class Meta:
        verbose_name = "Aplicación de incentivo"
        verbose_name_plural = "Aplicaciones de incentivo"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.get_kind_display()} {self.applied_value} - {self.indicator}"

    @transaction.atomic
    def apply_adjustment_to_performance(self):
        """Suma el valor aplicado al ajuste del indicador asociado."""
        indicator = self.indicator
        indicator.adjustment = indicator.adjustment + self.applied_value
        indicator.save(update_fields=["adjustment", "updated_at"])
        return indicator