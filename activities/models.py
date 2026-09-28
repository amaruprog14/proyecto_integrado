from django.db import models

from accounts.models import Funcionario
from common.mixins import BaseModel
from configuration.models import Item


class Actividad(BaseModel):
    """Tabla operativa: registro de una actividad realizada por un Funcionario."""

    funcionario = models.ForeignKey(Funcionario, on_delete=models.PROTECT, related_name="actividades")
    item = models.ForeignKey(Item, on_delete=models.PROTECT, related_name="actividades")

    fecha = models.DateField()
    tipo_registro = models.CharField(max_length=50)
    descripcion_accion = models.TextField(blank=True)

    class Meta:
        verbose_name = "Actividad"
        verbose_name_plural = "Actividades"
        ordering = ["-fecha"]

    def __str__(self):
        return f"Actividad {self.pk} - {self.funcionario}"