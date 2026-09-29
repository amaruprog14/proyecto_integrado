from django.core.exceptions import ValidationError
from django.db import models

from common.mixins import BaseModel


class Item(BaseModel):
    """Tabla maestra: ítems medibles del sistema, usado luego por Actividad."""

    nombre_item = models.CharField(max_length=150, unique=True)
    vigente = models.BooleanField(default=True)

    class Meta:
        verbose_name = "Ítem"
        verbose_name_plural = "Ítems"
        ordering = ["nombre_item"]

    def __str__(self):
        return self.nombre_item


class Periodo(BaseModel):
    """Tabla maestra: períodos de evaluación/gestión (ej. mensual, trimestral)."""

    class Estado(models.TextChoices):
        ABIERTO = "ABIERTO", "Abierto"
        CERRADO = "CERRADO", "Cerrado"

    fecha_inicio = models.DateField()
    fecha_termino = models.DateField()
    estado = models.CharField(max_length=20, choices=Estado.choices, default=Estado.ABIERTO)

    class Meta:
        verbose_name = "Período"
        verbose_name_plural = "Períodos"
        ordering = ["-fecha_inicio"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(fecha_termino__gte=models.F("fecha_inicio")),
                name="periodo_fecha_termino_gte_inicio",
            )
        ]

    def __str__(self):
        return f"{self.fecha_inicio} - {self.fecha_termino}"

    def clean(self):
        super().clean()
        if not self.fecha_inicio or not self.fecha_termino:
            return

        if self.fecha_termino < self.fecha_inicio:
            raise ValidationError({"fecha_termino": "La fecha de término debe ser igual o posterior a la fecha de inicio."})

        periodos_solapados = type(self).objects.filter(
            fecha_inicio__lte=self.fecha_termino,
            fecha_termino__gte=self.fecha_inicio,
        )
        if self.pk:
            periodos_solapados = periodos_solapados.exclude(pk=self.pk)
        if periodos_solapados.exists():
            raise ValidationError({"fecha_inicio": "El período se solapa con otro período existente."})

    def cerrar_periodo(self):
        self.estado = self.Estado.CERRADO
        self.save(update_fields=["estado", "updated_at"])