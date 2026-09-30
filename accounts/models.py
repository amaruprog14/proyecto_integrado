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