from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.utils import timezone

from common.codes import AutoCodeMixin
from common.mixins import BaseModel


class Item(AutoCodeMixin, BaseModel):
    """Tabla maestra: ítems medibles del sistema, usado luego por Actividad."""

    code_prefix = "ITM"

    code = models.CharField(
        max_length=25, unique=True, blank=True, verbose_name="Código",
        help_text="Si se deja vacío se genera automáticamente.",
    )
    item_name = models.CharField(max_length=150, unique=True, verbose_name="Nombre del ítem")
    description = models.TextField(blank=True, verbose_name="Descripción")
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
    first_closed_at = models.DateTimeField(null=True, editable=False)
    # Marca del congelamiento de resultados (RN-013). Se fija al cerrar aunque no se genere
    # ninguna fila, para que un período cerrado sin funcionarios medibles no se congele después.
    frozen_at = models.DateTimeField(null=True, blank=True, editable=False, verbose_name="Resultados congelados el")

    class Meta:
        verbose_name = "Período"
        verbose_name_plural = "Períodos"
        ordering = ["-start_date"]
        permissions = [("reopen_period", "Puede reabrir períodos")]
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
        """Cierra el período y congela sus resultados (RN-013) en la misma transacción."""
        from analytics.services import CalculadorDesempenoService
        from configuration.period_services import lock_period_registry

        with transaction.atomic():
            # Mismo orden de bloqueos que las demás rutas de escritura (registro de períodos →
            # período → funcionario...): un cambio concurrente (reasignar compromisos, cambiar de
            # cargo o ausencias) no se cuela entre el cálculo congelado y su respaldo.
            lock_period_registry()
            # Se relee bloqueado: cerrar dos veces nunca reemplaza el resultado oficial congelado.
            # Se trabaja con la fila bloqueada (fechas y estado actuales), no con la copia recibida.
            locked = type(self).objects.select_for_update().get(pk=self.pk)
            if locked.status != self.Status.CLOSED:
                locked.status = self.Status.CLOSED
                if locked.first_closed_at is None:
                    locked.first_closed_at = timezone.now()
                locked.save(update_fields=["status", "first_closed_at", "updated_at"])
                # Cerrar de nuevo tras una reapertura reemplaza los resultados congelados anteriores.
                CalculadorDesempenoService.freeze_period(locked, replace=True)
            for field in ("start_date", "end_date", "status", "first_closed_at", "frozen_at", "updated_at"):
                setattr(self, field, getattr(locked, field))

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


class AttentionType(AutoCodeMixin, BaseModel):
    """Tabla maestra: tipo de atención. El tipo de servicio es opcional."""

    code_prefix = "TAT"

    service_type = models.ForeignKey(
        ServiceType,
        on_delete=models.PROTECT,
        related_name="attention_types",
        null=True,
        blank=True,
        verbose_name="Tipo de servicio",
    )
    name = models.CharField(max_length=150, verbose_name="Nombre")
    description = models.TextField(blank=True, verbose_name="Descripción")
    is_active = models.BooleanField(default=True, verbose_name="Vigente")

    activity_item = models.ForeignKey(Item, null=True, blank=True, on_delete=models.PROTECT,
        related_name="attention_types", verbose_name="Ítem para actividad automática")

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


class SubattentionType(AutoCodeMixin, BaseModel):
    """Tabla maestra: tipo de subatención, dependiente de un tipo de atención."""

    code_prefix = "SAT"

    attention_type = models.ForeignKey(
        AttentionType,
        on_delete=models.PROTECT,
        related_name="subattention_types",
        verbose_name="Tipo de atención",
    )
    name = models.CharField(max_length=150, verbose_name="Nombre")
    description = models.TextField(blank=True, verbose_name="Descripción")
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
    actor_username = models.CharField("Cuenta que realizó la acción", max_length=150, blank=True, editable=False)
    date = models.DateTimeField(default=timezone.now, verbose_name="Fecha", db_index=True)
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
        cls, official, action, entity, previous_value="", new_value="", record_id=None, origin_ip=None,
        *, actor_username="",
    ):
        return cls.objects.create(
            official=official,
            actor_username=actor_username,
            action=action,
            affected_table=entity,
            affected_record_id=record_id,
            previous_value=str(previous_value or ""),
            new_value=str(new_value or ""),
            origin_ip=origin_ip,
        )

class PeriodMutex(models.Model):
    """Fila única para serializar definición, cierre e ingreso en períodos."""
    id = models.PositiveSmallIntegerField(primary_key=True, default=1, editable=False)


class RegistrationWeek(models.Model):
    delegation = models.ForeignKey("accounts.Delegation", on_delete=models.PROTECT)
    monday = models.DateField("Inicio de la semana")
    closed = models.BooleanField(default=False)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["delegation", "monday"], name="unique_registration_week")]
