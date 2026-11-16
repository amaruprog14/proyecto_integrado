from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.utils import timezone

from accounts.models import Official
from activities.models import Activity, AttentionCase, EvidenceBatch
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
    delegation = models.ForeignKey("accounts.Delegation", on_delete=models.PROTECT, null=True, blank=True)
    territory_ref = models.ForeignKey("accounts.Territory", on_delete=models.PROTECT, null=True, blank=True,
                                     verbose_name="Territorio")
    origin_activity = models.ForeignKey(Activity, on_delete=models.PROTECT, null=True, blank=True,
                                        related_name="originated_commitments")
    origin_case = models.ForeignKey(AttentionCase, on_delete=models.PROTECT, null=True, blank=True,
                                    related_name="originated_commitments")
    description = models.TextField(blank=True, max_length=500, verbose_name="Descripción del compromiso")
    completed_on = models.DateField(null=True, blank=True, editable=False, verbose_name="Fecha de realización")
    submission_token = models.UUIDField(unique=True, null=True, editable=False)
    committed_date = models.DateField(verbose_name="Fecha comprometida")
    creation_date = models.DateTimeField(default=timezone.now, verbose_name="Fecha de creación")
    current_status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.ENTERED, verbose_name="Estado actual"
    )

    class Meta:
        verbose_name = "Compromiso"
        verbose_name_plural = "Compromisos"
        ordering = ["committed_date", "pk"]
        permissions = [("assign_commitment", "Puede asignar y reasignar compromisos")]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(origin_activity__isnull=True) | models.Q(origin_case__isnull=True),
                name="commitment_at_most_one_origin",
            ),
        ]
        indexes = [models.Index(fields=["delegation", "committed_date"], name="commitment_delegation_date")]

    @property
    def identifier(self):
        return f"COM-{self.pk:06d}"

    @property
    def next_statuses(self):
        return {
            self.Status.ENTERED: (self.Status.PENDING, self.Status.IN_PROGRESS, self.Status.DONE),
            self.Status.PENDING: (self.Status.IN_PROGRESS, self.Status.DONE),
            self.Status.IN_PROGRESS: (self.Status.PENDING, self.Status.DONE),
            self.Status.DONE: (),
        }[self.current_status]

    def __str__(self):
        return f"Compromiso {self.pk} - {self.requester}"

    @transaction.atomic
    def change_status(self, new_status, author, observation=""):
        """Cambia el estado y deja historial (estado anterior, nuevo, autor, fecha y observación)."""
        previous = self.current_status
        if previous == new_status:
            return None
        if new_status not in self.next_statuses:
            raise ValidationError("El cambio de estado no está permitido.")
        self.current_status = new_status
        if new_status == self.Status.DONE:
            self.completed_on = timezone.localdate()
        self.save(update_fields=["current_status", "completed_on", "updated_at"])
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
    """Comentario interno asociado a un registro de gestión."""

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
    case = models.ForeignKey(
        AttentionCase, on_delete=models.CASCADE, related_name="comments", null=True, blank=True,
        verbose_name="Caso social",
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
                    models.Q(activity__isnull=False, commitment__isnull=True, case__isnull=True)
                    | models.Q(activity__isnull=True, commitment__isnull=False, case__isnull=True)
                    | models.Q(activity__isnull=True, commitment__isnull=True, case__isnull=False)
                ),
                name="comment_exactly_one_target",
            )
        ]

    def __str__(self):
        return f"Comentario {self.pk} - {self.author}"

    def validate_association(self):
        return sum(value is not None for value in (self.activity_id, self.commitment_id, self.case_id)) == 1

    def clean(self):
        super().clean()
        if not self.validate_association():
            raise ValidationError("Asocia el comentario a un único registro.")


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
    evidence_batch = models.ForeignKey(
        EvidenceBatch, on_delete=models.PROTECT, null=True, blank=True, related_name="alerts",
    )
    performance_period = models.ForeignKey(
        "configuration.Period", on_delete=models.PROTECT, null=True, blank=True, related_name="+",
    )
    performance_subject = models.ForeignKey(
        Official, on_delete=models.PROTECT, null=True, blank=True, related_name="+",
    )
    resolved_at = models.DateTimeField(null=True, blank=True, editable=False)
    commitment = models.ForeignKey(Commitment, on_delete=models.PROTECT, null=True, blank=True, related_name="alerts")
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.PENDING, verbose_name="Estado"
    )

    class Meta:
        verbose_name = "Alerta"
        verbose_name_plural = "Alertas"
        ordering = ["-date", "-pk"]
        constraints = [
            models.UniqueConstraint(fields=["official", "evidence_batch"], name="alert_unique_evidence_recipient"),
            models.UniqueConstraint(fields=["official", "commitment"], name="alert_unique_commit_recipient"),
            models.UniqueConstraint(
                fields=["official", "alert_type", "performance_period", "performance_subject"],
                name="alert_unique_performance_recipient",
            ),
        ]

    def __str__(self):
        return f"{self.get_alert_type_display()} - {self.official}"

    def mark_as_seen(self):
        self.status = self.Status.SEEN
        self.save(update_fields=["status", "updated_at"])
