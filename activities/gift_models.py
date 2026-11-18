"""Campañas de regalos y registro individual, independiente del puntaje de desempeño."""
from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models

from common.chilean_rut import normalize_chilean_rut
from common.mixins import BaseModel

GIFT_PERMISSIONS = [
    f"activities.{action}_{model}"
    for model, actions in (
        ("giftcampaign", ("view", "add", "change")),
        ("giftregistration", ("view", "add", "change", "deliver", "cancel")),
    )
    for action in actions
]


def canonical_gift_rut(value):
    number, digit = normalize_chilean_rut(value).split("-")
    if not int(number):
        raise ValidationError("Ingresa un RUT válido distinto de cero.")
    return f"{int(number)}-{digit}"


class GiftCampaign(BaseModel):
    class Celebration(models.TextChoices):
        CHRISTMAS = "CHRISTMAS", "Navidad"
        CHILDREN = "CHILDREN", "Día del Niño"
        ANNIVERSARY = "ANNIVERSARY", "Aniversario"

    name = models.CharField(max_length=150, verbose_name="Nombre de la campaña")
    celebration = models.CharField(max_length=16, choices=Celebration.choices, verbose_name="Celebración")
    year = models.PositiveSmallIntegerField(validators=[MinValueValidator(1), MaxValueValidator(9999)], verbose_name="Año")
    start_date = models.DateField(verbose_name="Inicio")
    end_date = models.DateField(verbose_name="Término")
    is_open = models.BooleanField(default=True, verbose_name="Abierta para inscripciones y entregas")
    delegations = models.ManyToManyField("accounts.Delegation", related_name="gift_campaigns", verbose_name="Delegaciones participantes")

    class Meta:
        ordering = ["-year", "name", "pk"]
        verbose_name = "Campaña de regalos"
        verbose_name_plural = "Campañas de regalos"
        default_permissions = ("view", "add", "change")
        constraints = [models.UniqueConstraint(fields=["celebration", "year"], name="unique_gift_celebration_year")]

    def __str__(self):
        return f"{self.name} ({self.year})"

    def clean(self):
        super().clean()
        if self.start_date and self.end_date and self.end_date < self.start_date:
            raise ValidationError({"end_date": "El término debe ser igual o posterior al inicio."})
        if self.year and any(day and day.year != self.year for day in (self.start_date, self.end_date)):
            raise ValidationError("Las fechas deben pertenecer al año de la campaña.")


class GiftRegistration(BaseModel):
    class Status(models.TextChoices):
        REGISTERED = "REGISTERED", "Inscrito"
        DELIVERED = "DELIVERED", "Entregado"
        CANCELLED = "CANCELLED", "Anulado"

    campaign = models.ForeignKey(GiftCampaign, on_delete=models.PROTECT, related_name="registrations", verbose_name="Campaña")
    child_rut = models.CharField(max_length=12, verbose_name="RUT del menor")
    child_name = models.CharField(max_length=150, verbose_name="Nombre del menor")
    guardian_rut = models.CharField(max_length=12, verbose_name="RUT del adulto responsable")
    guardian_name = models.CharField(max_length=150, verbose_name="Nombre del adulto responsable")
    phone = models.CharField(max_length=30, verbose_name="Teléfono de contacto")
    territory = models.ForeignKey("accounts.Territory", on_delete=models.PROTECT, verbose_name="Territorio")
    delegation = models.ForeignKey("accounts.Delegation", on_delete=models.PROTECT, editable=False, verbose_name="Delegación de inscripción")
    activity = models.ForeignKey("activities.Activity", on_delete=models.PROTECT, null=True, blank=True,
                                 related_name="gift_registrations", verbose_name="Jornada (actividad opcional)")
    notes = models.TextField(max_length=500, blank=True, verbose_name="Observaciones")
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.REGISTERED, editable=False)
    registered_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="gift_registrations", editable=False)
    delivered_at = models.DateTimeField(null=True, blank=True, editable=False)
    delivered_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="gift_deliveries", null=True, blank=True, editable=False)
    cancellation_reason = models.CharField(max_length=500, blank=True, editable=False)

    class Meta:
        ordering = ["-created_at", "-pk"]
        verbose_name = "Inscripción de regalo"
        verbose_name_plural = "Inscripciones de regalos"
        default_permissions = ("view", "add", "change")
        permissions = [("deliver_giftregistration", "Puede confirmar entregas de regalos"),
                       ("cancel_giftregistration", "Puede anular inscripciones de regalos")]
        constraints = [
            models.UniqueConstraint(fields=["campaign", "child_rut"], name="unique_gift_child_campaign"),
            models.CheckConstraint(condition=(
                models.Q(status="DELIVERED", delivered_at__isnull=False, delivered_by__isnull=False)
                | models.Q(status__in=["REGISTERED", "CANCELLED"], delivered_at__isnull=True, delivered_by__isnull=True)
            ), name="gift_delivery_state_consistent"),
            models.CheckConstraint(condition=(~models.Q(status="CANCELLED") | ~models.Q(cancellation_reason="")),
                                   name="gift_cancellation_has_reason"),
        ]

    def __str__(self):
        return f"REG-{self.pk:06d}" if self.pk else "Nueva inscripción"

    def clean(self):
        super().clean()
        for field in ("child_rut", "guardian_rut"):
            try:
                setattr(self, field, canonical_gift_rut(getattr(self, field)))
            except ValidationError as error:
                raise ValidationError({field: error.messages}) from error
        if self.child_rut == self.guardian_rut:
            raise ValidationError({"guardian_rut": "El menor y el adulto responsable deben tener RUT distintos."})
        if self.territory_id:
            self.delegation_id = self.territory.delegation_id
            if not self.territory.is_active or self.territory.deleted_at or self.territory.delegation.deleted_at or self.territory.delegation.status != "ACTIVE":
                raise ValidationError({"territory": "Selecciona un territorio y una delegación vigentes."})
        if self.activity_id and (self.activity.deleted_at or self.activity.registration_delegation_id != self.delegation_id):
            raise ValidationError({"activity": "La actividad debe estar vigente y pertenecer a la delegación de inscripción."})

    def save(self, *args, **kwargs):
        self.child_rut = canonical_gift_rut(self.child_rut)
        self.guardian_rut = canonical_gift_rut(self.guardian_rut)
        return super().save(*args, **kwargs)


class GiftRegistrationEvent(models.Model):
    registration = models.ForeignKey(GiftRegistration, on_delete=models.PROTECT, related_name="events")
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    created_at = models.DateTimeField(auto_now_add=True)
    action = models.CharField(max_length=80)
    observation = models.CharField(max_length=500, blank=True)
    previous = models.JSONField(default=dict)
    current = models.JSONField(default=dict)

    class Meta:
        ordering = ["-created_at", "-pk"]
        default_permissions = ()
