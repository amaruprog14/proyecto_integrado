from django.core.exceptions import ValidationError
from django.db import models, router, transaction
from django.utils import timezone

from accounts.models import Area, Delegation, Official, ServiceRecipient
from common.mixins import BaseModel
from common.codes import AutoCodeMixin
from configuration.models import AttentionType, Item, SubattentionType
from .gift_models import GiftCampaign, GiftRegistration, GiftRegistrationEvent


class ClientRequest(BaseModel):
    """Solicitud ciudadana previa a la atención operativa de un funcionario."""
    class Status(models.TextChoices):
        RECEIVED = "RECEIVED", "Recibida"
        REVIEW = "REVIEW", "En revisión"
        RESOLVED = "RESOLVED", "Resuelta"

    recipient = models.ForeignKey(ServiceRecipient, on_delete=models.PROTECT, related_name="requests")
    territory = models.ForeignKey("accounts.Territory", null=True, blank=True, on_delete=models.PROTECT, related_name="client_requests")
    address_snapshot = models.CharField(max_length=100, blank=True, verbose_name="Dirección al ingresar")
    delegation = models.ForeignKey(Delegation, on_delete=models.PROTECT)
    attention_type = models.ForeignKey(AttentionType, on_delete=models.PROTECT)
    subattention_type = models.ForeignKey(SubattentionType, on_delete=models.PROTECT)
    subject = models.CharField(max_length=100, verbose_name="Motivo de la solicitud")
    description = models.TextField(max_length=500, verbose_name="Descripción")
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.RECEIVED)
    response = models.TextField(blank=True, max_length=500, verbose_name="Respuesta al cliente")
    submission_token = models.UUIDField(unique=True, editable=False)

    @property
    def identifier(self):
        return f"SOL-{self.pk:06d}"

    def save(self, *args, **kwargs):
        if not self._state.adding:
            return super().save(*args, **kwargs)
        using = kwargs.get("using") or router.db_for_write(type(self), instance=self)
        with transaction.atomic(using=using):
            super().save(*args, **kwargs)
            AttentionCase.objects.using(self._state.db).get_or_create(client_request=self, defaults={
                "recipient_id": self.recipient_id, "delegation_id": self.delegation_id, "subject": self.subject,
            })

    class Meta:
        ordering = ["-created_at", "-pk"]
        verbose_name = "Solicitud ciudadana"


class ClientRequestEvent(models.Model):
    request = models.ForeignKey(ClientRequest, on_delete=models.PROTECT, related_name="events")
    status = models.CharField(max_length=16, choices=ClientRequest.Status.choices)
    response = models.TextField(blank=True, max_length=500)
    created_at = models.DateTimeField(auto_now_add=True)
    actor = models.ForeignKey(Official, on_delete=models.PROTECT, null=True, blank=True)

    class Meta:
        ordering = ["-created_at", "-pk"]


class AttentionCase(BaseModel):
    class DirectStatus(models.TextChoices):
        RECORDED = "RECORDED", "Gestión registrada"
        REVIEW = "REVIEW", "En curso"
        RESOLVED = "RESOLVED", "Cerrado"

    client_request = models.OneToOneField(ClientRequest, on_delete=models.PROTECT, null=True,
        blank=True, related_name="attention_case")
    recipient = models.ForeignKey(ServiceRecipient, on_delete=models.PROTECT, related_name="attention_cases")
    delegation = models.ForeignKey(Delegation, on_delete=models.PROTECT, related_name="attention_cases")
    responsible = models.ForeignKey(Official, on_delete=models.PROTECT, null=True, blank=True,
        related_name="assigned_attention_cases")
    subject = models.CharField(max_length=100)
    direct_status = models.CharField(max_length=16, choices=DirectStatus.choices, default=DirectStatus.REVIEW)
    next_step = models.CharField(max_length=200, blank=True)
    next_step_date = models.DateField(null=True, blank=True)
    public_next_step = models.CharField(max_length=200, blank=True)
    public_response = models.TextField(max_length=500, blank=True)
    requires_visit = models.BooleanField(null=True, blank=True, verbose_name="Requiere visita")
    scheduled_visit_on = models.DateField(null=True, blank=True, verbose_name="Visita programada")
    visited_on = models.DateField(null=True, blank=True, verbose_name="Visita realizada")
    report_delivered_on = models.DateField(null=True, blank=True, verbose_name="Entrega de informe")
    benefit_delivered_on = models.DateField(null=True, blank=True, verbose_name="Entrega de beneficio")

    class Meta:
        ordering = ["-updated_at", "-pk"]
        indexes = [models.Index(fields=["delegation", "updated_at"], name="case_delegation_updated_idx")]

    def __str__(self):
        return f"{self.identifier} · {self.subject}"

    @property
    def identifier(self):
        return self.client_request.identifier if self.client_request_id else f"CAS-{self.pk:06d}"

    @property
    def status(self):
        return self.client_request.status if self.client_request_id else self.direct_status

    def get_status_display(self):
        return self.client_request.get_status_display() if self.client_request_id else self.get_direct_status_display()

    @property
    def is_closed(self):
        return self.status == self.DirectStatus.RESOLVED

    @property
    def response(self):
        return self.client_request.response if self.client_request_id else self.public_response


class AttentionCaseEvent(models.Model):
    case = models.ForeignKey(AttentionCase, on_delete=models.PROTECT, related_name="events")
    actor = models.ForeignKey(Official, on_delete=models.PROTECT)
    title = models.CharField(max_length=100)
    detail = models.TextField(max_length=500, blank=True)
    public_text = models.TextField(max_length=500, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-pk"]


class OfficeLetter(BaseModel):
    class Status(models.TextChoices):
        IN_PROGRESS = "IN_PROGRESS", "En proceso"
        APPROVED = "APPROVED", "Aprobada"
        FINALIZED = "FINALIZED", "Finalizada"
        NOT_APPLICABLE = "NOT_APPLICABLE", "No aplica"

    delegation = models.ForeignKey(Delegation, on_delete=models.PROTECT, verbose_name="Delegación")
    received_on = models.DateField(verbose_name="Fecha de recepción")
    received_year = models.PositiveSmallIntegerField(editable=False)
    external_number = models.CharField(max_length=60, null=True, blank=True, verbose_name="Número externo")
    addressee = models.CharField(max_length=200, verbose_name="Destinatario")
    sender = models.CharField(max_length=200, verbose_name="Remitente")
    phone = models.CharField(max_length=40, blank=True, verbose_name="Teléfono de contacto")
    subject = models.CharField(max_length=250, verbose_name="Actividad o tema")
    activity_on = models.DateField(null=True, blank=True, verbose_name="Fecha de la actividad")
    responsible = models.ForeignKey(Official, null=True, blank=True, on_delete=models.PROTECT,
                                    verbose_name="Funcionario encargado")
    responsible_area = models.ForeignKey(Area, null=True, blank=True, on_delete=models.PROTECT,
                                         verbose_name="Área encargada")
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.IN_PROGRESS,
                              verbose_name="Estado")
    decision = models.TextField(max_length=1000, blank=True, verbose_name="Pronunciamiento")
    referred_to = models.CharField(max_length=200, blank=True, verbose_name="Derivada a")
    notes = models.TextField(max_length=2000, blank=True, verbose_name="Observaciones")
    created_by = models.ForeignKey(Official, null=True, editable=False, on_delete=models.PROTECT,
                                   related_name="registered_office_letters")
    case = models.ForeignKey(AttentionCase, null=True, blank=True, on_delete=models.PROTECT,
                             related_name="office_letters")

    class Meta:
        verbose_name = "Carta de Oficina de Partes"
        verbose_name_plural = "Cartas de Oficina de Partes"
        default_permissions = ("add", "change", "view")
        ordering = ["-received_on", "-pk"]
        indexes = [models.Index(fields=["delegation", "received_on"], name="letter_delegation_received")]
        constraints = [
            models.UniqueConstraint(fields=["delegation", "received_year", "external_number"],
                                    name="letter_unique_external_number"),
            models.CheckConstraint(condition=models.Q(responsible__isnull=True) |
                                    models.Q(responsible_area__isnull=True), name="letter_one_responsible"),
        ]

    @property
    def identifier(self):
        return f"CAR-{self.pk:06d}"

    def __str__(self):
        return f"{self.identifier} · {self.subject}"

    def save(self, *args, **kwargs):
        self.received_year = self.received_on.year
        self.external_number = (self.external_number or "").strip().upper() or None
        if kwargs.get("update_fields") and "received_on" in kwargs["update_fields"]:
            kwargs["update_fields"] = {*kwargs["update_fields"], "received_year"}
        return super().save(*args, **kwargs)


class OfficeLetterEvent(models.Model):
    letter = models.ForeignKey(OfficeLetter, on_delete=models.PROTECT, related_name="events")
    actor = models.ForeignKey(Official, null=True, on_delete=models.PROTECT)
    actor_username = models.CharField(max_length=150)
    created_at = models.DateTimeField(auto_now_add=True)
    title = models.CharField(max_length=100)
    changes = models.JSONField(default=list)

    class Meta:
        ordering = ["-created_at", "-pk"]
        default_permissions = ()


class PortalInvitation(models.Model):
    recipient = models.OneToOneField(ServiceRecipient, on_delete=models.PROTECT, related_name="portal_invitation")
    email = models.EmailField(unique=True)
    token_digest = models.CharField(max_length=64, unique=True)
    expires_at = models.DateTimeField()
    consumed_at = models.DateTimeField(null=True, blank=True)


class Activity(AutoCodeMixin, BaseModel):
    code_prefix = "ACT"

    @classmethod
    def validate_daily_capacity(cls, official_id, day, exclude_pk=None):
        """Se invoca dentro de la transacción que mantiene el bloqueo del registro de períodos."""
        records = cls.objects.filter(official_id=official_id, date=day, deleted_at__isnull=True)
        if records.exclude(pk=exclude_pk).count() >= 7:
            raise ValidationError("El funcionario ya tiene siete actividades vigentes en esta fecha.")


    class ListingStatus(models.TextChoices):
        ACTIVE = "ACTIVE", "Vigente"
        RESOLVED = "RESOLVED", "Resuelta"
        INACTIVE = "INACTIVE", "Archivada"

    class RecordType(models.TextChoices):
        MONTHLY = "Registro mensual", "Registro mensual"
        FIELD = "Terreno", "Terreno"
        ATTENTION = "Atención social", "Atención social"

    """Tabla operativa: registro de una actividad realizada por un Funcionario."""

    official = models.ForeignKey(
        Official, on_delete=models.PROTECT, related_name="activities", verbose_name="Funcionario"
    )
    registration_position = models.ForeignKey(
        "accounts.Position", on_delete=models.PROTECT, null=True, editable=False,
        related_name="+", verbose_name="Cargo al registrar",
    )
    registration_position_captured = models.BooleanField(default=False, editable=False)
    registration_delegation = models.ForeignKey(
        Delegation, on_delete=models.PROTECT, null=True, blank=True, related_name="+",
        verbose_name="Delegación al registrar",
    )
    delegation_estimated = models.BooleanField(default=False, editable=False)
    item = models.ForeignKey(
        Item, on_delete=models.PROTECT, related_name="activities", verbose_name="Ítem"
    )

    date = models.DateField(verbose_name="Fecha")
    record_type = models.CharField(max_length=50, choices=RecordType.choices, verbose_name="Tipo de registro")
    subject = models.CharField(max_length=200, blank=True, verbose_name="Actividad, solicitud o problema atendido")
    contact_name = models.CharField(max_length=150, blank=True, verbose_name="Nombre o referencia de contacto")
    phone = models.CharField(max_length=30, blank=True, verbose_name="Teléfono de contacto")
    action_description = models.TextField(blank=True, verbose_name="Descripción de la acción")
    activity_type = models.ForeignKey("configuration.ActivityType", on_delete=models.PROTECT, null=True, blank=True,
                                     related_name="manual_activities", verbose_name="Tipo de actividad")
    service_type = models.ForeignKey("configuration.ServiceType", on_delete=models.PROTECT, null=True, blank=True,
                                    related_name="manual_activities", verbose_name="Servicio")
    attention_type = models.ForeignKey(AttentionType, on_delete=models.PROTECT, null=True, blank=True,
                                      related_name="manual_activities", verbose_name="Tipo de atención")
    subattention_type = models.ForeignKey(SubattentionType, on_delete=models.PROTECT, null=True, blank=True,
                                         related_name="manual_activities", verbose_name="Subatención")

    class Meta:
        verbose_name = "Actividad"
        verbose_name_plural = "Actividades"
        ordering = ["-date"]
        permissions = [("archive_activity", "Puede archivar y restaurar actividades")]

    def __str__(self):
        return f"Actividad {self.pk} - {self.official}"

    def save(self, *args, **kwargs):
        if self._state.adding and self.registration_delegation_id is None:
            self.registration_delegation_id = self.official.delegation_id
        if self._state.adding and not self.registration_position_captured:
            if self.registration_position_id is None:
                self.registration_position_id = self.official.position_id
            self.registration_position_captured = True
        return super().save(*args, **kwargs)

class SocialAttention(BaseModel):
    MAX_ATTENTIONS_PER_CASE = 3

    case = models.ForeignKey(AttentionCase, on_delete=models.PROTECT, related_name="attentions")
    activity = models.OneToOneField(
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
    result = models.CharField(max_length=300, blank=True, verbose_name="Resultado de la gestión")
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

    @property
    def client_request(self):
        return self.case.client_request

    @property
    def client_request_id(self):
        return self.case.client_request_id

    @property
    def identifier(self):
        """Identificador de atención que se muestra al confirmar el registro."""
        return f"AS-{self.pk:06d}" if self.pk else ""

    def clean(self):
        super().clean()
        errors = {}

        if self.case_id:
            if self.case.is_closed and self._state.adding:
                errors["case"] = "El caso está cerrado."
            if (self.case.recipient_id, self.case.delegation_id) != (self.recipient_id, self.delegation_id):
                errors["case"] = "La gestión debe corresponder a la persona y delegación del caso."
            if self.case.attentions.exclude(pk=self.pk).count() >= self.MAX_ATTENTIONS_PER_CASE:
                errors["case"] = f"El caso ya tiene {self.MAX_ATTENTIONS_PER_CASE} gestiones registradas."

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


class EvidenceBatch(BaseModel):
    class Stage(models.TextChoices):
        INITIAL = "INITIAL", "Diagnóstico inicial"
        IN_PROGRESS = "IN_PROGRESS", "Trabajo en curso"
        COMPLETED = "COMPLETED", "Trabajo terminado"

    activity = models.ForeignKey(Activity, on_delete=models.PROTECT, related_name="evidence_batches")
    author = models.ForeignKey(Official, on_delete=models.PROTECT, related_name="evidence_batches")
    stage = models.CharField(max_length=16, choices=Stage.choices, verbose_name="Etapa del trabajo")
    description = models.TextField(max_length=500, verbose_name="Descripción de lo realizado")

    class Meta:
        ordering = ["created_at", "pk"]
        default_permissions = ()


class EvidenceBatchAnnulment(models.Model):
    batch = models.OneToOneField(EvidenceBatch, on_delete=models.PROTECT, related_name="annulment")
    actor = models.ForeignKey(Official, on_delete=models.PROTECT)
    reason = models.TextField(max_length=500)
    annulled_at = models.DateTimeField(default=timezone.now)

    class Meta:
        default_permissions = ()


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
    batch = models.ForeignKey(EvidenceBatch, on_delete=models.PROTECT, related_name="images", null=True, blank=True)
    original_name = models.CharField(max_length=255, blank=True)
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

    @classmethod
    def approved_for_activity(cls, activity_id):
        return cls.objects.filter(
            evidence__activity_id=activity_id, evidence__deleted_at__isnull=True,
            deleted_at__isnull=True, status=cls.Status.APPROVED,
        )

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
