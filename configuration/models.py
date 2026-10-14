from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

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

class ActivityType(BaseModel):
    """Tabla maestra: tipo de actividad, definido por área."""

    area = models.ForeignKey(
        "accounts.Area",
        on_delete=models.PROTECT,
        related_name="activity_types",
        verbose_name="Área",
    )
    name = models.CharField(max_length=150, verbose_name="Nombre")
    is_active = models.BooleanField(default=True, verbose_name="Vigente")

    class Meta:
        verbose_name = "Tipo de actividad"
        verbose_name_plural = "Tipos de actividad"
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(fields=["area", "name"], name="uniq_activity_type_area_name")
        ]

    def __str__(self):
        return self.name

    def deactivate_from_catalog(self):
        self.is_active = False
        self.save(update_fields=["is_active", "updated_at"])


class ServiceType(BaseModel):
    """Tabla maestra: tipo de servicio, dependiente de un tipo de actividad."""

    activity_type = models.ForeignKey(
        ActivityType,
        on_delete=models.PROTECT,
        related_name="service_types",
        verbose_name="Tipo de actividad",
    )
    name = models.CharField(max_length=150, verbose_name="Nombre")
    is_active = models.BooleanField(default=True, verbose_name="Vigente")

    class Meta:
        verbose_name = "Tipo de servicio"
        verbose_name_plural = "Tipos de servicio"
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(
                fields=["activity_type", "name"], name="uniq_service_type_activity_name"
            )
        ]

    def __str__(self):
        return self.name

    def deactivate_from_catalog(self):
        self.is_active = False
        self.save(update_fields=["is_active", "updated_at"])


class AttentionType(BaseModel):
    """Tabla maestra: tipo de atención, dependiente de un tipo de servicio."""

    service_type = models.ForeignKey(
        ServiceType,
        on_delete=models.PROTECT,
        related_name="attention_types",
        verbose_name="Tipo de servicio",
    )
    name = models.CharField(max_length=150, verbose_name="Nombre")
    is_active = models.BooleanField(default=True, verbose_name="Vigente")

    class Meta:
        verbose_name = "Tipo de atención"
        verbose_name_plural = "Tipos de atención"
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(
                fields=["service_type", "name"], name="uniq_attention_type_service_name"
            )
        ]

    def __str__(self):
        return self.name

    def deactivate_from_catalog(self):
        self.is_active = False
        self.save(update_fields=["is_active", "updated_at"])


class SubattentionType(BaseModel):
    """Tabla maestra: tipo de subatención, dependiente de un tipo de atención."""

    attention_type = models.ForeignKey(
        AttentionType,
        on_delete=models.PROTECT,
        related_name="subattention_types",
        verbose_name="Tipo de atención",
    )
    name = models.CharField(max_length=150, verbose_name="Nombre")
    is_active = models.BooleanField(default=True, verbose_name="Vigente")

    class Meta:
        verbose_name = "Tipo de subatención"
        verbose_name_plural = "Tipos de subatención"
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(
                fields=["attention_type", "name"], name="uniq_subattention_type_attention_name"
            )
        ]

    def __str__(self):
        return self.name

    def deactivate_from_catalog(self):
        self.is_active = False
        self.save(update_fields=["is_active", "updated_at"])


class AuditLog(BaseModel):
    """Tabla operativa: registro de auditoría de eventos del sistema (LogAuditoria)."""

    official = models.ForeignKey(
        "accounts.Official",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="audit_logs",
        verbose_name="Funcionario",
    )
    date = models.DateTimeField(default=timezone.now, verbose_name="Fecha")
    origin_ip = models.GenericIPAddressField(null=True, blank=True, verbose_name="IP de origen")
    action = models.CharField(max_length=100, verbose_name="Acción")
    affected_table = models.CharField(max_length=100, verbose_name="Tabla afectada")
    affected_record_id = models.PositiveIntegerField(
        null=True, blank=True, verbose_name="ID del registro afectado"
    )
    previous_value = models.TextField(blank=True, verbose_name="Valor anterior")
    new_value = models.TextField(blank=True, verbose_name="Valor nuevo")

    class Meta:
        verbose_name = "Log de auditoría"
        verbose_name_plural = "Logs de auditoría"
        ordering = ["-date"]
        indexes = [models.Index(fields=["affected_table", "affected_record_id"])]

    def __str__(self):
        return f"{self.action} en {self.affected_table} ({self.date:%Y-%m-%d %H:%M})"

    @classmethod
    def register_event(
        cls, official, action, entity, previous_value="", new_value="", record_id=None, origin_ip=None
    ):
        return cls.objects.create(
            official=official,
            action=action,
            affected_table=entity,
            affected_record_id=record_id,
            previous_value=str(previous_value or ""),
            new_value=str(new_value or ""),
            origin_ip=origin_ip,
        )