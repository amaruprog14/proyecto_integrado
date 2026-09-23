from django.db import models


class TimestampedModel(models.Model):
    """
    Agrega trazabilidad de creación/actualización a cualquier modelo.
    Se usa tanto en tablas 'maestras' como 'operativas'.
    """
    creado_en = models.DateTimeField(auto_now_add=True, verbose_name="Creado en")
    actualizado_en = models.DateTimeField(auto_now=True, verbose_name="Actualizado en")

    class Meta:
        abstract = True