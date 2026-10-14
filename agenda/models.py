from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.utils import timezone

from accounts.models import Official
from activities.models import Activity
from common.mixins import BaseModel


class Commitment(BaseModel):
    """Tabla operativa: compromiso de la agenda colectiva."""

    class Status(models.TextChoices):
        ENTERED = "ENTERED", "Ingresado"
        PENDING = "PENDING", "Pendiente"
        IN_PROGRESS = "IN_PROGRESS", "En proceso"
        DONE = "DONE", "Realizado"

    responsible = models.ForeignKey(
        Official,
        on_delete=models.PROTECT,
        related_name="commitments",
        verbose_name="Responsable",
    )
    requester = models.CharField(max_length=200, verbose_name="Solicitante")
    territory = models.CharField(max_length=200, verbose_name="Territorio")
    support_area = models.CharField(max_length=150, blank=True, verbose_name="Área de apoyo")
    committed_date = models.DateField(verbose_name="Fecha comprometida")
    creation_date = models.DateTimeField(default=timezone.now, verbose_name="Fecha de creación")
    current_status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.ENTERED, verbose_name="Estado actual"
    )

    class Meta:
        verbose_name = "Compromiso"
        verbose_name_plural = "Compromisos"
        ordering = ["committed_date"]

    def __str__(self):
        return f"Compromiso {self.pk} - {self.requester}"

    @transaction.atomic
    def change_status(self, new_status, author, observation=""):
        """Cambia el estado y deja historial (estado anterior, nuevo, autor, fecha y observación)."""
        if new_status not in self.Status.values:
            raise ValidationError({"current_status": "Estado no válido."})
        previous = self.current_status
        if previous == new_status:
            return None
        self.current_status = new_status
        self.save(update_fields=["current_status", "updated_at"])
        return CommitmentStatusHistory.objects.create(
            commitment=self,
            author=author,
            previous_status=previous,
            new_status=new_status,
            observation=observation,
        )

    def reassign_responsible(self, new_responsible, reason=""):
        self.responsible = new_responsible
        self.save(update_fields=["responsible", "updated_at"])

    def is_overdue(self):
        """Vencido: fecha comprometida pasada y no realizado."""
        return self.current_status != self.Status.DONE and self.committed_date < timezone.localdate()


class CommitmentStatusHistory(BaseModel):
    """Tabla operativa: historial de cambios de estado de un compromiso."""

    commitment = models.ForeignKey(
        Commitment,
        on_delete=models.CASCADE,
        related_name="status_history",
        verbose_name="Compromiso",
    )
    author = models.ForeignKey(
        Official,
        on_delete=models.PROTECT,
        related_name="commitment_status_changes",
        verbose_name="Autor",
    )
    previous_status = models.CharField(
        max_length=20, choices=Commitment.Status.choices, verbose_name="Estado anterior"
    )
    new_status = models.CharField(
        max_length=20, choices=Commitment.Status.choices, verbose_name="Estado nuevo"
    )
    date = models.DateTimeField(default=timezone.now, verbose_name="Fecha")
    observation = models.TextField(blank=True, verbose_name="Observación")

    class Meta:
        verbose_name = "Historial de estado de compromiso"
        verbose_name_plural = "Historial de estados de compromisos"
        ordering = ["-date"]

    def __str__(self):
        return f"{self.previous_status} -> {self.new_status}"


class Comment(BaseModel):
    """Tabla operativa: comentario asociado a una actividad o a un compromiso."""

    author = models.ForeignKey(
        Official,
        on_delete=models.PROTECT,
        related_name="comments",
        verbose_name="Autor",
    )
    activity = models.ForeignKey(
        Activity,
        on_delete=models.CASCADE,
        related_name="comments",
        null=True,
        blank=True,
        verbose_name="Actividad",
    )
    commitment = models.ForeignKey(
        Commitment,
        on_delete=models.CASCADE,
        related_name="comments",
        null=True,
        blank=True,
        verbose_name="Compromiso",
    )
    date = models.DateTimeField(default=timezone.now, verbose_name="Fecha")
    text = models.TextField(verbose_name="Texto")

    class Meta:
        verbose_name = "Comentario"
        verbose_name_plural = "Comentarios"
        ordering = ["date"]
        constraints = [
            models.CheckConstraint(
                condition=(
                    models.Q(activity__isnull=False, commitment__isnull=True)
                    | models.Q(activity__isnull=True, commitment__isnull=False)
                ),
                name="comment_exactly_one_target",
            )
        ]

    def __str__(self):
        return f"Comentario {self.pk} - {self.author}"

    def validate_association(self):
        """True si el comentario está asociado a una actividad o a un compromiso, no a ambos."""
        return (self.activity_id is None) != (self.commitment_id is None)

    def clean(self):
        super().clean()
        if not self.validate_association():
            raise ValidationError("El comentario debe asociarse a una actividad o a un compromiso.")


class Alert(BaseModel):
    """Tabla operativa: alerta dirigida a un funcionario."""

    class AlertType(models.TextChoices):
        DUE_DATE = "DUE_DATE", "Vencimiento"
        PENDING_EVIDENCE = "PENDING_EVIDENCE", "Evidencia pendiente"
        NO_RECORDS = "NO_RECORDS", "Ausencia de registros"
        LOW_PROGRESS = "LOW_PROGRESS", "Avance bajo el umbral"

    class Status(models.TextChoices):
        PENDING = "PENDING", "Pendiente"
        SEEN = "SEEN", "Vista"

    official = models.ForeignKey(
        Official,
        on_delete=models.PROTECT,
        related_name="alerts",
        verbose_name="Funcionario",
    )
    alert_type = models.CharField(max_length=30, choices=AlertType.choices, verbose_name="Tipo de alerta")
    reason = models.CharField(max_length=255, verbose_name="Motivo")
    date = models.DateTimeField(default=timezone.now, verbose_name="Fecha")
    reference_link = models.CharField(max_length=500, blank=True, verbose_name="Enlace de referencia")
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.PENDING, verbose_name="Estado"
    )

    class Meta:
        verbose_name = "Alerta"
        verbose_name_plural = "Alertas"
        ordering = ["-date"]

    def __str__(self):
        return f"{self.get_alert_type_display()} - {self.official}"

    def mark_as_seen(self):
        self.status = self.Status.SEEN
        self.save(update_fields=["status", "updated_at"])