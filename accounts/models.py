from django.conf import settings
from django.db import models

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

    full_name = models.CharField(max_length=200, verbose_name="Nombre completo")
    national_id = models.CharField(max_length=20, unique=True, verbose_name="RUT / identificador")
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

class Delegation(BaseModel):
    """Tabla maestra: delegaciones o unidades organizacionales."""

    class Status(models.TextChoices):
        ACTIVE = "ACTIVE", "Activa"
        INACTIVE = "INACTIVE", "Inactiva"

    delegation_name = models.CharField(
        max_length=150, unique=True, verbose_name="Nombre de la delegación"
    )
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

    role_name = models.CharField(max_length=100, unique=True, verbose_name="Nombre del rol")
    description = models.TextField(blank=True, verbose_name="Descripción")
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
    national_id = models.CharField(max_length=20, unique=True, verbose_name="Identificador único")
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.ACTIVE, verbose_name="Estado"
    )

    class Meta:
        verbose_name = "Persona usuaria"
        verbose_name_plural = "Personas usuarias"
        ordering = ["full_name"]

    def __str__(self):
        return self.full_name
