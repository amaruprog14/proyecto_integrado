from django.db import models

from accounts.models import Official
from common.mixins import BaseModel
from configuration.models import Item


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