from django.db import models

from common.mixins import BaseModel


class Cargo(BaseModel):
    """Tabla maestra: cargos formales dentro de la organización."""

    nombre_cargo = models.CharField(max_length=150, unique=True, verbose_name="Nombre del cargo")
    descripcion = models.TextField(blank=True)
    vigente = models.BooleanField(default=True)

    class Meta:
        verbose_name = "Cargo"
        verbose_name_plural = "Cargos"
        ordering = ["nombre_cargo"]

    def __str__(self):
        return self.nombre_cargo

    def activar_cargo(self):
        self.vigente = True
        self.save(update_fields=["vigente", "updated_at"])

    def desactivar_cargo(self):
        self.vigente = False
        self.save(update_fields=["vigente", "updated_at"])


class Area(BaseModel):
    """Tabla maestra: áreas/unidades organizacionales."""

    nombre_area = models.CharField(max_length=150, unique=True, verbose_name="Nombre del área")
    vigente = models.BooleanField(default=True)

    class Meta:
        verbose_name = "Área"
        verbose_name_plural = "Áreas"
        ordering = ["nombre_area"]

    def __str__(self):
        return self.nombre_area


class Funcionario(BaseModel):
    """Tabla operativa: funcionarios/as del organismo (usuarios del sistema)."""

    class Estado(models.TextChoices):
        ACTIVO = "ACTIVO", "Activo"
        INACTIVO = "INACTIVO", "Inactivo"
        SUSPENDIDO = "SUSPENDIDO", "Suspendido"

    cargo = models.ForeignKey(
        Cargo, on_delete=models.PROTECT, related_name="funcionarios", null=True, blank=True
    )

    nombre_completo = models.CharField(max_length=200)
    rut_identificador = models.CharField(max_length=20, unique=True, verbose_name="RUT / identificador")
    estado = models.CharField(max_length=20, choices=Estado.choices, default=Estado.ACTIVO)
    email = models.EmailField(unique=True, max_length=191)
    telefono = models.CharField(max_length=30, blank=True)

    class Meta:
        verbose_name = "Funcionario"
        verbose_name_plural = "Funcionarios"
        ordering = ["nombre_completo"]

    def __str__(self):
        return self.nombre_completo