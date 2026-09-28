from django.db import models


class BaseModel(models.Model):
    """
    Agrega trazabilidad de creación/actualización a cualquier modelo.
    Se usa tanto en tablas 'maestras' como 'operativas'.
    """
    created_at = models.DateTimeField(auto_now_add=True, editable=False,db_index=True, verbose_name="Creado en")
    updated_at = models.DateTimeField(auto_now=True, editable=False, db_index=True, verbose_name="Actualizado en")
    deleted_at = models.DateTimeField(null=True, editable=False, blank=True, db_index=True, verbose_name="Eliminado en")

    class Meta:
        abstract = True