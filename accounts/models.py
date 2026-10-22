import secrets
from datetime import timedelta

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone
from django.utils.crypto import constant_time_compare, salted_hmac

from common.chilean_rut import validate_chilean_rut
from common.codes import AutoCodeMixin
from common.mixins import BaseModel


class Position(BaseModel):
    """Tabla maestra: cargos formales dentro de la organización."""

    position_name = models.CharField(max_length=150, unique=True, verbose_name="Nombre del cargo")
    description = models.TextField(blank=True, verbose_name="Descripción")
    is_active = models.BooleanField(default=True, verbose_name="Vigente")

    class Meta:
        verbose_name = "Cargo"
        verbose_name_plural = "Cargos"
        ordering = ["position_name"]

    def __str__(self):
        return self.position_name

    def activate_position(self):
        self.is_active = True
        self.save(update_fields=["is_active", "updated_at"])

    def deactivate_position(self):
        self.is_active = False
        self.save(update_fields=["is_active", "updated_at"])


class Area(BaseModel):
    """Tabla maestra: áreas/unidades organizacionales."""

    area_name = models.CharField(max_length=150, unique=True, verbose_name="Nombre del área")
    is_active = models.BooleanField(default=True, verbose_name="Vigente")

    class Meta:
        verbose_name = "Área"
        verbose_name_plural = "Áreas"
        ordering = ["area_name"]

    def __str__(self):
        return self.area_name


class Official(BaseModel):
    """Tabla operativa: funcionarios/as del organismo (usuarios del sistema)."""

    class Status(models.TextChoices):
        ACTIVE = "ACTIVE", "Activo"
        INACTIVE = "INACTIVE", "Inactivo"
        SUSPENDED = "SUSPENDED", "Suspendido"

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="official",
        null=True,
        blank=True,
        verbose_name="Usuario del sistema",
    )
    area = models.ForeignKey(
        Area,
        on_delete=models.PROTECT,
        related_name="officials",
        null=True,
        blank=True,
        verbose_name="Área",
    )
    position = models.ForeignKey(
        Position,
        on_delete=models.PROTECT,
        related_name="officials",
        null=True,
        blank=True,
        verbose_name="Cargo",
    )
    delegation = models.ForeignKey(
        "Delegation",
        on_delete=models.PROTECT,
        related_name="officials",
        null=True,
        blank=True,
        verbose_name="Delegación",
    )

    authorized_delegations = models.ManyToManyField(
        "Delegation",
        related_name="authorized_officials",
        blank=True,
        verbose_name="Delegaciones autorizadas",
    )

    full_name = models.CharField(max_length=200, verbose_name="Nombre completo")
    national_id = models.CharField(
        max_length=20,
        unique=True,
        validators=[validate_chilean_rut],
        verbose_name="RUT o RUN chileno",
    )
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.ACTIVE, verbose_name="Estado"
    )
    email = models.EmailField(unique=True, max_length=191, verbose_name="Correo electrónico")
    phone = models.CharField(max_length=30, blank=True, verbose_name="Teléfono")

    class Meta:
        verbose_name = "Funcionario"
        verbose_name_plural = "Funcionarios"
        ordering = ["full_name"]

    def __str__(self):
        return self.full_name

    @property
    def is_enabled(self):
        """Habilitado para operar: estado Activo y no archivado."""
        return self.status == self.Status.ACTIVE and self.deleted_at is None

    def get_authorized_delegations(self):
        """
        Delegaciones activas a las que puede acceder el funcionario.
        Con un rol vigente de alcance ALL son todas; en otro caso, la principal
        (`delegation`) más las `authorized_delegations`.
        """
        if self.pk is None:
            return Delegation.objects.none()
        if self.roles.filter(is_active=True, scope=Role.Scope.ALL).exists():
            return Delegation.objects.filter(status=Delegation.Status.ACTIVE)
        ids = set(self.authorized_delegations.values_list("pk", flat=True))
        if self.delegation_id:
            ids.add(self.delegation_id)
        return Delegation.objects.filter(pk__in=ids, status=Delegation.Status.ACTIVE)


class Delegation(AutoCodeMixin, BaseModel):
    """Tabla maestra: delegaciones o unidades organizacionales."""

    code_prefix = "DEL"

    class Status(models.TextChoices):
        ACTIVE = "ACTIVE", "Activa"
        INACTIVE = "INACTIVE", "Inactiva"

    delegation_name = models.CharField(
        max_length=150, unique=True, verbose_name="Nombre de la delegación"
    )
    address = models.CharField(max_length=255, verbose_name="Dirección")
    commune = models.CharField(max_length=100, verbose_name="Comuna")
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.ACTIVE, verbose_name="Estado"
    )

    class Meta:
        verbose_name = "Delegación"
        verbose_name_plural = "Delegaciones"
        ordering = ["delegation_name"]

    def __str__(self):
        return self.delegation_name

    def activate(self):
        self.status = self.Status.ACTIVE
        self.save(update_fields=["status", "updated_at"])

    def deactivate(self):
        self.status = self.Status.INACTIVE
        self.save(update_fields=["status", "updated_at"])


class Role(BaseModel):
    """Tabla maestra: roles de acceso. Un funcionario puede tener uno o más roles."""

    class Scope(models.TextChoices):
        ALL = "ALL", "Transversal (todas las delegaciones)"
        DELEGATION = "DELEGATION", "Delegaciones autorizadas"
        OWN = "OWN", "Solo registros propios"

    role_name = models.CharField(max_length=100, unique=True, verbose_name="Nombre del rol")
    description = models.TextField(blank=True, verbose_name="Descripción")
    permissions = models.ManyToManyField(
        "auth.Permission",
        related_name="sgr_roles",
        blank=True,
        verbose_name="Permisos",
    )
    scope = models.CharField(
        max_length=20,
        choices=Scope.choices,
        default=Scope.DELEGATION,
        verbose_name="Alcance autorizado",
    )
    is_active = models.BooleanField(default=True, verbose_name="Vigente")
    officials = models.ManyToManyField(
        Official,
        related_name="roles",
        blank=True,
        verbose_name="Funcionarios",
    )

    class Meta:
        verbose_name = "Rol"
        verbose_name_plural = "Roles"
        ordering = ["role_name"]

    def __str__(self):
        return self.role_name


class Function(BaseModel):
    """Tabla maestra: funciones asociadas a uno o más cargos."""

    function_name = models.CharField(max_length=150, unique=True, verbose_name="Nombre de la función")
    description = models.TextField(blank=True, verbose_name="Descripción")
    is_active = models.BooleanField(default=True, verbose_name="Vigente")
    positions = models.ManyToManyField(
        Position,
        related_name="functions",
        blank=True,
        verbose_name="Cargos",
    )

    class Meta:
        verbose_name = "Función"
        verbose_name_plural = "Funciones"
        ordering = ["function_name"]

    def __str__(self):
        return self.function_name

    def activate_function(self):
        self.is_active = True
        self.save(update_fields=["is_active", "updated_at"])

    def deactivate_function(self):
        self.is_active = False
        self.save(update_fields=["is_active", "updated_at"])


class ServiceRecipient(BaseModel):
    """
    Tabla operativa: persona usuaria que recibe servicios o atenciones.
    (PersonaUsuaria en el diagrama; no es el usuario de Django.)
    """

    class Status(models.TextChoices):
        ACTIVE = "ACTIVE", "Activa"
        INACTIVE = "INACTIVE", "Inactiva"

    full_name = models.CharField(max_length=200, verbose_name="Nombre")
    national_id = models.CharField(
        max_length=20,
        unique=True,
        validators=[validate_chilean_rut],
        verbose_name="RUT o RUN chileno",
    )
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.ACTIVE, verbose_name="Estado"
    )

    class Meta:
        verbose_name = "Persona usuaria"
        verbose_name_plural = "Personas usuarias"
        ordering = ["full_name"]

    def __str__(self):
        return self.full_name


class LoginThrottle(BaseModel):
    """
    Tabla operativa: intentos fallidos de inicio de sesión para el bloqueo temporal
    (accounts.login_security). `key` es "user:<id>" si la cuenta existe (usuario y correo
    comparten contador) o "login:<identificador>" si no existe, que se bloquea igual.
    """

    key = models.CharField(max_length=191, unique=True, verbose_name="Clave de intentos")
    failed_attempts = models.PositiveSmallIntegerField(default=0, verbose_name="Intentos fallidos")
    last_failure_at = models.DateTimeField(null=True, blank=True, db_index=True, verbose_name="Último intento fallido")
    locked_until = models.DateTimeField(null=True, blank=True, verbose_name="Bloqueado hasta")

    class Meta:
        verbose_name = "Bloqueo de inicio de sesión"
        verbose_name_plural = "Bloqueos de inicio de sesión"
        ordering = ["-last_failure_at"]

    def __str__(self):
        return f"{self.key} ({self.failed_attempts} intentos fallidos)"


class PasswordResetCode(BaseModel):
    """
    Tabla operativa: código de un solo uso para recuperar la contraseña.

    Se guarda solo el hash del código. Los valores de vigencia, espera entre envíos y
    límites se leen de settings (valores referenciales del diseño: 10 min y 45 s):
    PASSWORD_RESET_CODE_TTL_MINUTES, PASSWORD_RESET_RESEND_WAIT_SECONDS,
    PASSWORD_RESET_MAX_ATTEMPTS y PASSWORD_RESET_MAX_RESENDS.
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="password_reset_codes",
        verbose_name="Usuario",
    )
    code_hash = models.CharField(max_length=64, editable=False, verbose_name="Hash del código")
    expires_at = models.DateTimeField(verbose_name="Vence en")
    last_sent_at = models.DateTimeField(default=timezone.now, verbose_name="Último envío")
    verified_at = models.DateTimeField(null=True, blank=True, verbose_name="Verificado en")
    used_at = models.DateTimeField(null=True, blank=True, verbose_name="Usado o invalidado en")
    failed_attempts = models.PositiveSmallIntegerField(default=0, verbose_name="Intentos fallidos")
    resend_count = models.PositiveSmallIntegerField(default=0, verbose_name="Reenvíos")

    class Meta:
        verbose_name = "Código de recuperación"
        verbose_name_plural = "Códigos de recuperación"
        ordering = ["-created_at"]

    def __str__(self):
        return f"Código de {self.user} ({self.created_at:%Y-%m-%d %H:%M})"

    # --- parámetros configurables ---
    @staticmethod
    def _setting(name, default):
        return getattr(settings, name, default)

    @classmethod
    def ttl(cls):
        return timedelta(minutes=cls._setting("PASSWORD_RESET_CODE_TTL_MINUTES", 10))

    @classmethod
    def resend_wait(cls):
        return timedelta(seconds=cls._setting("PASSWORD_RESET_RESEND_WAIT_SECONDS", 45))

    @classmethod
    def max_attempts(cls):
        return cls._setting("PASSWORD_RESET_MAX_ATTEMPTS", 5)

    @classmethod
    def max_resends(cls):
        return cls._setting("PASSWORD_RESET_MAX_RESENDS", 3)

    @staticmethod
    def _hash(code):
        return salted_hmac("sgr.password_reset", str(code)).hexdigest()

    # --- emisión ---
    @classmethod
    def issue(cls, user):
        """
        Genera un código nuevo e invalida los anteriores. Devuelve (registro, código_en_claro).
        Lanza ValidationError si se pide antes de la espera mínima o se superó el máximo de reenvíos.
        El conteo de reenvíos se reinicia cuando vence el código vigente, para no bloquear la cuenta
        de forma permanente.
        """
        now = timezone.now()
        previous = cls.objects.filter(user=user, used_at__isnull=True).order_by("-created_at").first()
        resend_count = 0
        if previous is not None:
            if now - previous.last_sent_at < cls.resend_wait():
                raise ValidationError(
                    "Debe esperar antes de solicitar un nuevo código.", code="resend_too_soon"
                )
            if now < previous.expires_at:
                resend_count = previous.resend_count + 1
            if resend_count > cls.max_resends():
                raise ValidationError(
                    "Se alcanzó el máximo de reenvíos de código.", code="resend_limit"
                )
        cls.objects.filter(user=user, used_at__isnull=True).update(used_at=now)

        plain_code = f"{secrets.randbelow(10**6):06d}"
        record = cls.objects.create(
            user=user,
            code_hash=cls._hash(plain_code),
            expires_at=now + cls.ttl(),
            last_sent_at=now,
            resend_count=resend_count,
        )
        return record, plain_code

    # --- estado ---
    @property
    def is_expired(self):
        return timezone.now() >= self.expires_at

    @property
    def is_active(self):
        """Vigente: no usado, no vencido y con intentos disponibles."""
        return (
            self.used_at is None
            and not self.is_expired
            and self.failed_attempts < self.max_attempts()
        )

    # --- verificación y uso ---
    def verify(self, code):
        """True si el código es correcto y sigue vigente; cuenta los intentos fallidos."""
        if not self.is_active:
            return False
        if constant_time_compare(self._hash(code), self.code_hash):
            self.verified_at = timezone.now()
            self.save(update_fields=["verified_at", "updated_at"])
            return True
        self.failed_attempts += 1
        self.save(update_fields=["failed_attempts", "updated_at"])
        return False

    def can_set_password(self):
        """La pantalla de nueva contraseña solo se habilita tras una verificación válida."""
        return self.verified_at is not None and self.is_active

    def consume(self):
        """Invalida el código tras cambiar la contraseña (no puede reutilizarse)."""
        self.used_at = timezone.now()
        self.save(update_fields=["used_at", "updated_at"])