import uuid

from django.db import models


class AutoCodeMixin(models.Model):
    """
    Agrega un código único y legible (p. ej. DEL-0003) a una tabla maestra.

    Si no se informa `code`, se genera automáticamente al guardar usando `code_prefix`
    y el id del registro. Un código ingresado manualmente se respeta tal cual.
    """

    code_prefix = "COD"

    code = models.CharField(
        max_length=20,
        unique=True,
        blank=True,
        verbose_name="Código",
        help_text="Si se deja vacío se genera automáticamente.",
    )

    class Meta:
        abstract = True

    def save(self, *args, **kwargs):
        if self.code or kwargs.get("update_fields"):
            return super().save(*args, **kwargs)

        # Primer guardado sin código: se usa uno temporal único y luego el definitivo.
        self.code = f"TMP-{uuid.uuid4().hex[:15]}"
        super().save(*args, **kwargs)
        self.code = f"{self.code_prefix}-{self.pk:04d}"
        type(self).objects.filter(pk=self.pk).update(code=self.code)
