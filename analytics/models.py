from datetime import timedelta
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator, MaxValueValidator
from django.db import models, transaction
from django.utils import timezone

from accounts.models import Delegation, Function, Official, Position
from common.mixins import BaseModel
from configuration.models import Item, Period


class MeasurementPlan(BaseModel):
    period = models.ForeignKey(Period, on_delete=models.PROTECT, related_name="measurement_plans")
    position = models.ForeignKey(Position, on_delete=models.PROTECT, verbose_name="Cargo")

    class Meta:
        verbose_name = "Plan de medición"
        verbose_name_plural = "Planes de medición"
        constraints = [models.UniqueConstraint(fields=["period", "position"], name="measurement_plan_period_position")]
        permissions = [("publish_measurementplan", "Puede publicar planes de medición")]

    def __str__(self):
        return str(self.position)


class MeasurementVersion(BaseModel):
    plan = models.ForeignKey(MeasurementPlan, on_delete=models.PROTECT, related_name="versions")
    number = models.PositiveIntegerField(verbose_name="Versión")
    effective_from = models.DateField(verbose_name="Vigente desde")
    published_at = models.DateTimeField(null=True, editable=False)
    max_computable = models.DecimalField(
        max_digits=6, decimal_places=2, default=Decimal("150"), verbose_name="Tope computable (%)",
        validators=[MinValueValidator(Decimal("0.01"))],
    )
    amber_threshold = models.DecimalField(
        max_digits=5, decimal_places=2, default=Decimal("60"), verbose_name="Umbral naranjo (%)",
        validators=[MinValueValidator(0), MaxValueValidator(100)],
    )
    green_threshold = models.DecimalField(
        max_digits=5, decimal_places=2, default=Decimal("100"), verbose_name="Umbral verde (%)",
        validators=[MinValueValidator(0), MaxValueValidator(100)],
    )
    collective_threshold = models.DecimalField(
        max_digits=5, decimal_places=2, default=Decimal("80"), verbose_name="Umbral colectivo (%)",
        validators=[MinValueValidator(0), MaxValueValidator(100)],
    )

    class Meta:
        ordering = ["-number"]
        constraints = [models.UniqueConstraint(fields=["plan", "number"], name="measurement_plan_version_number")]
        indexes = [models.Index(fields=["plan", "effective_from"], name="measurement_effective_idx")]

    @property
    def is_published(self):
        return self.published_at is not None


class MeasurementItem(models.Model):
    class GoalType(models.TextChoices):
        QUANTITY = "QUANTITY", "Cantidad"
        PERCENTAGE = "PERCENTAGE", "Porcentaje"

    version = models.ForeignKey(MeasurementVersion, on_delete=models.CASCADE, related_name="items")
    function = models.ForeignKey(Function, on_delete=models.PROTECT, verbose_name="Función")
    item = models.ForeignKey(Item, on_delete=models.PROTECT, verbose_name="Ítem")
    goal_type = models.CharField(max_length=10, choices=GoalType.choices, verbose_name="Tipo de meta")
    goal = models.DecimalField(
        max_digits=12, decimal_places=2, null=True, blank=True, verbose_name="Meta",
        validators=[MinValueValidator(Decimal("0.01"))],
    )
    weight = models.DecimalField(
        max_digits=5, decimal_places=2, null=True, blank=True, verbose_name="Ponderador (%)",
        validators=[MinValueValidator(0), MaxValueValidator(100)],
    )

    class Meta:
        ordering = ["item__item_name", "pk"]
        constraints = [models.UniqueConstraint(fields=["version", "item"], name="measurement_version_unique_item")]


class MeasurementAdjustment(models.Model):
    line = models.ForeignKey(MeasurementItem, on_delete=models.CASCADE, related_name="adjustments")
    official = models.ForeignKey(Official, on_delete=models.PROTECT, verbose_name="Funcionario")
    goal = models.DecimalField(
        max_digits=12, decimal_places=2, null=True, blank=True, verbose_name="Meta individual",
        validators=[MinValueValidator(Decimal("0.01"))],
    )
    weight = models.DecimalField(
        max_digits=5, decimal_places=2, null=True, blank=True, verbose_name="Ponderador individual (%)",
        validators=[MinValueValidator(0), MaxValueValidator(100)],
    )

    class Meta:
        ordering = ["official__full_name", "pk"]
        constraints = [
            models.UniqueConstraint(fields=["line", "official"], name="measurement_item_unique_official"),
            models.CheckConstraint(
                condition=models.Q(goal__isnull=False) | models.Q(weight__isnull=False),
                name="measurement_adjustment_has_value",
            ),
        ]


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
    """Tabla maestra: ponderación (%) de un ítem para un cargo (Ponderacion).

    OBSOLETA: los ponderadores salen de MeasurementItem y MeasurementAdjustment (#46).
    Se conserva sin migrar datos; no agregar usos nuevos.
    """

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
    """Tabla operativa: foto del indicador de un funcionario por ítem y período.

    Con `is_frozen` es el resultado oficial de un período cerrado (RN-013): se guarda al cerrar y
    se muestra tal cual, sin recalcular. Guarda el ponderado y el avance ya calculados (también el
    porcentual del tubo), de modo que cambios posteriores en planes, evidencias o compromisos no
    alteran el período cerrado.
    """

    class TrafficLight(models.TextChoices):
        GREEN = "GREEN", "Verde"
        AMBER = "AMBER", "Ámbar"
        RED = "RED", "Rojo"

    official = models.ForeignKey(
        Official, on_delete=models.PROTECT, related_name="indicator_snapshots", verbose_name="Funcionario"
    )
    closing_delegation = models.ForeignKey(
        Delegation, on_delete=models.PROTECT, null=True, editable=False, related_name="+",
        verbose_name="Delegación al cierre",
    )
    item = models.ForeignKey(
        Item, on_delete=models.PROTECT, related_name="indicator_snapshots", verbose_name="Ítem"
    )
    period = models.ForeignKey(
        Period, on_delete=models.PROTECT, related_name="indicator_snapshots", verbose_name="Período"
    )
    version = models.ForeignKey(
        MeasurementVersion, on_delete=models.PROTECT, null=True, blank=True, related_name="snapshots",
        verbose_name="Versión del plan",
    )
    goal_type = models.CharField(max_length=10, choices=MeasurementItem.GoalType.choices, blank=True,
                                 verbose_name="Tipo de meta")
    goal = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0"), verbose_name="Meta")
    progress = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True, default=Decimal("0"),
                                   verbose_name="Avance")
    compliance = models.DecimalField(
        max_digits=8, decimal_places=2, default=Decimal("0"), verbose_name="Cumplimiento (%)"
    )
    raw_compliance = models.DecimalField(max_digits=16, decimal_places=6, null=True, blank=True,
                                         verbose_name="Cumplimiento sin tope (%)")
    applied_weighting = models.DecimalField(
        max_digits=5, decimal_places=2, default=Decimal("0"), verbose_name="Ponderación aplicada (%)"
    )
    weighted = models.DecimalField(max_digits=16, decimal_places=6, default=Decimal("0"),
                                   verbose_name="Ponderado (puntos)")
    expected_percentage = models.DecimalField(max_digits=10, decimal_places=6, null=True, blank=True,
                                              verbose_name="Meta esperada (%)")
    expected_units = models.DecimalField(max_digits=16, decimal_places=6, null=True, blank=True,
                                         verbose_name="Meta esperada (unidades)")
    difference = models.DecimalField(max_digits=16, decimal_places=6, null=True, blank=True,
                                     verbose_name="Diferencia")
    individual = models.BooleanField(default=False, verbose_name="Con ajuste individual")
    notice = models.CharField(max_length=200, blank=True, verbose_name="Aviso")
    is_frozen = models.BooleanField(default=False, db_index=True, verbose_name="Congelado al cierre")
    adjustment = models.DecimalField(
        max_digits=8, decimal_places=2, default=Decimal("0"), verbose_name="Ajuste"
    )
    traffic_light = models.CharField(
        max_length=10, choices=TrafficLight.choices, blank=True, verbose_name="Semáforo"
    )
    total_traffic_light = models.CharField(
        max_length=10, choices=TrafficLight.choices, blank=True, verbose_name="Semáforo del total",
        help_text="Semáforo del total ponderado del funcionario al congelar; no se recalcula.",
    )
    calculated_at = models.DateTimeField(default=timezone.now, verbose_name="Fecha de cálculo")

    class Meta:
        verbose_name = "Indicador (snapshot)"
        verbose_name_plural = "Indicadores (snapshots)"
        ordering = ["-calculated_at"]
        indexes = [models.Index(fields=["official", "period", "item"])]
        permissions = [
            ("view_team_performance", "Puede ver el desempeño de otros funcionarios de su ámbito"),
        ]

    def __str__(self):
        return f"{self.official} / {self.item} / {self.period}"


class DelegationActivityFreeze(models.Model):
    period = models.ForeignKey(Period, on_delete=models.PROTECT)
    captured_at = models.DateTimeField()

    class Meta:
        constraints = [models.UniqueConstraint(fields=["period", "captured_at"], name="unique_delegation_activity_freeze")]


class DelegationActivitySnapshot(models.Model):
    freeze = models.ForeignKey(DelegationActivityFreeze, on_delete=models.PROTECT, related_name="activities")
    activity = models.ForeignKey("activities.Activity", on_delete=models.PROTECT, related_name="+")
    delegation = models.ForeignKey(Delegation, on_delete=models.PROTECT, related_name="+")
    official = models.ForeignKey(Official, on_delete=models.PROTECT, related_name="+")
    code = models.CharField(max_length=32)
    date = models.DateField()
    official_name = models.CharField(max_length=200)
    item_name = models.CharField(max_length=150)
    estimated = models.BooleanField(default=False)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["freeze", "activity"], name="unique_frozen_territorial_activity")]
        indexes = [models.Index(fields=["freeze", "delegation"], name="frozen_activity_delegation_idx")]


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
