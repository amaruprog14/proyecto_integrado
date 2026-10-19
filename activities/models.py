from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from accounts.models import Delegation, Official, ServiceRecipient
from common.mixins import BaseModel
from configuration.models import AttentionType, Item, SubattentionType


class Activity(BaseModel):
    """Tabla operativa: registro de una actividad realizada por un Funcionario."""

    official = models.ForeignKey(
        Official, on_delete=models.PROTECT, related_name="activities", verbose_name="Funcionario"
    )
    item = models.ForeignKey(
        Item, on_delete=models.PROTECT, related_name="activities", verbose_name="Ítem"
    )

    date = models.DateField(verbose_name="Fecha")
    record_type = models.CharField(max_length=50, verbose_name="Tipo de registro")
    action_description = models.TextField(blank=True, verbose_name="Descripción de la acción")

    class Meta:
        verbose_name = "Actividad"
        verbose_name_plural = "Actividades"
        ordering = ["-date"]

    def __str__(self):
        return f"Actividad {self.pk} - {self.official}"

class SocialAttention(BaseModel):
    """
    Tabla operativa: atención social. Una persona usuaria puede tener hasta
    MAX_ATTENTIONS_PER_RECIPIENT gestiones relacionadas (RN-012).
    """

    MAX_ATTENTIONS_PER_RECIPIENT = 3

    activity = models.ForeignKey(
        Activity,
        on_delete=models.PROTECT,
        related_name="social_attentions",
        null=True,
        blank=True,
        verbose_name="Actividad",
    )
    recipient = models.ForeignKey(
        ServiceRecipient,
        on_delete=models.PROTECT,
        related_name="social_attentions",
        verbose_name="Solicitante (persona usuaria)",
    )
    attention_type = models.ForeignKey(
        AttentionType,
        on_delete=models.PROTECT,
        related_name="social_attentions",
        verbose_name="Tipo de atención",
    )
    subattention_type = models.ForeignKey(
        SubattentionType,
        on_delete=models.PROTECT,
        related_name="social_attentions",
        verbose_name="Sub atención",
    )
    description = models.TextField(blank=True, verbose_name="Descripción")
    delegation = models.ForeignKey(
        Delegation,
        on_delete=models.PROTECT,
        related_name="social_attentions",
        verbose_name="Delegación",
    )
    responsible = models.ForeignKey(
        Official,
        on_delete=models.PROTECT,
        related_name="social_attentions",
        verbose_name="Usuario responsable",
    )
    date = models.DateField(default=timezone.localdate, verbose_name="Fecha")
    registered_at = models.DateTimeField(default=timezone.now, verbose_name="Fecha y hora de registro")
    # Token de un solo uso del formulario de ingreso: la restricción única impide que un doble
    # envío (doble clic, reintento o Atrás) cree dos atenciones, incluso si llegan a la vez.
    submission_token = models.CharField(
        max_length=32,
        unique=True,
        null=True,
        blank=True,
        editable=False,
        verbose_name="Token de envío",
    )

    class Meta:
        verbose_name = "Atención social"
        verbose_name_plural = "Atenciones sociales"
        ordering = ["recipient", "date", "created_at"]

    def __str__(self):
        return f"Atención {self.pk} - {self.recipient}"

    @classmethod
    def validate_attention_limit(cls, recipient_id, exclude_pk=None):
        """True si la persona usuaria aún puede registrar otra gestión."""
        qs = cls.objects.filter(recipient_id=recipient_id, deleted_at__isnull=True)
        if exclude_pk:
            qs = qs.exclude(pk=exclude_pk)
        return qs.count() < cls.MAX_ATTENTIONS_PER_RECIPIENT

    @property
    def identifier(self):
        """Identificador de atención que se muestra al confirmar el registro."""
        return f"AS-{self.pk:06d}" if self.pk else ""

    def clean(self):
        super().clean()
        errors = {}

        if self.recipient_id and not self.validate_attention_limit(self.recipient_id, self.pk):
            errors["recipient"] = (
                f"La persona usuaria ya tiene {self.MAX_ATTENTIONS_PER_RECIPIENT} gestiones registradas."
            )

        if self.attention_type_id and self.subattention_type_id:
            if self.subattention_type.attention_type_id != self.attention_type_id:
                errors["subattention_type"] = "La sub atención no pertenece al tipo de atención elegido."
            elif not self.subattention_type.is_active:
                errors["subattention_type"] = "La sub atención seleccionada no está vigente."
        if self.attention_type_id and not self.attention_type.is_active:
            errors["attention_type"] = "El tipo de atención seleccionado no está vigente."

        if self.delegation_id and self.responsible_id:
            if not self.responsible.get_authorized_delegations().filter(pk=self.delegation_id).exists():
                errors["delegation"] = "El responsable no tiene autorizada esta delegación."

        if errors:
            raise ValidationError(errors)


class Evidence(BaseModel):
    """Tabla operativa: archivo de respaldo asociado a una actividad."""

    ALLOWED_FORMATS = ("jpg", "jpeg", "png", "pdf")
    MAX_SIZE_KB = 5120

    activity = models.ForeignKey(
        Activity,
        on_delete=models.PROTECT,
        related_name="evidences",
        verbose_name="Actividad",
    )
    file_url = models.CharField(max_length=500, verbose_name="URL del archivo")
    file_format = models.CharField(max_length=10, blank=True, verbose_name="Formato")
    size_kb = models.PositiveIntegerField(default=0, verbose_name="Tamaño (KB)")
    upload_date = models.DateTimeField(default=timezone.now, verbose_name="Fecha de carga")

    class Meta:
        verbose_name = "Evidencia"
        verbose_name_plural = "Evidencias"
        ordering = ["-upload_date"]

    def __str__(self):
        return f"Evidencia {self.pk} - Actividad {self.activity_id}"

    def validate_format_and_size(self):
        """True si el formato está permitido y el tamaño no supera el máximo."""
        return self.file_format.lower() in self.ALLOWED_FORMATS and 0 < self.size_kb <= self.MAX_SIZE_KB

    def clean(self):
        super().clean()
        if not self.validate_format_and_size():
            raise ValidationError(
                f"Formato no permitido o tamaño sobre {self.MAX_SIZE_KB} KB. "
                f"Formatos válidos: {', '.join(self.ALLOWED_FORMATS)}."
            )


class EvidenceValidation(BaseModel):
    """Tabla operativa: decisión de un verificador sobre una evidencia."""

    class Status(models.TextChoices):
        PENDING = "PENDING", "Pendiente"
        APPROVED = "APPROVED", "Aprobada"
        REJECTED = "REJECTED", "Rechazada"
        CORRECTION_REQUESTED = "CORRECTION_REQUESTED", "Corrección solicitada"

    evidence = models.ForeignKey(
        Evidence,
        on_delete=models.PROTECT,
        related_name="validations",
        verbose_name="Evidencia",
    )
    verifier = models.ForeignKey(
        Official,
        on_delete=models.PROTECT,
        related_name="evidence_validations",
        null=True,
        blank=True,
        verbose_name="Verificador",
    )
    status = models.CharField(
        max_length=30, choices=Status.choices, default=Status.PENDING, verbose_name="Estado"
    )
    observation = models.TextField(blank=True, verbose_name="Observación")
    validated_at = models.DateTimeField(null=True, blank=True, verbose_name="Fecha de validación")

    class Meta:
        verbose_name = "Validación de evidencia"
        verbose_name_plural = "Validaciones de evidencia"
        ordering = ["-created_at"]

    def __str__(self):
        return f"Validación {self.pk} - {self.get_status_display()}"

    def process_validation(self, verifier, status, observation=""):
        """Registra la decisión del verificador (aprobar, rechazar o pedir corrección)."""
        if status not in self.Status.values or status == self.Status.PENDING:
            raise ValidationError({"status": "Estado de validación no válido."})
        if status != self.Status.APPROVED and not observation.strip():
            raise ValidationError({"observation": "Debe indicar el motivo si no aprueba la evidencia."})
        self.verifier = verifier
        self.status = status
        self.observation = observation
        self.validated_at = timezone.now()
        self.save(update_fields=["verifier", "status", "observation", "validated_at", "updated_at"])