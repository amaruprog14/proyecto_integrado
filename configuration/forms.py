import re

from django import forms
from django.core.exceptions import ValidationError

from common.text import normalize_spaces
from configuration.models import Item

ITEM_STATUS_CHOICES = [("ACTIVE", "Activo"), ("INACTIVE", "Inactivo")]
# Formato de la numeración automática (AutoCodeMixin): no se acepta como código manual.
RESERVED_ITEM_CODE = re.compile(rf"^{re.escape(Item.code_prefix)}-\d+$")
CODE_MAX_LENGTH = Item._meta.get_field("code").max_length


def item_snapshot(item):
    """Valores auditables del ítem."""
    return {
        "Código": item.code,
        "Nombre": item.item_name,
        "Descripción": item.description or "—",
        "Estado": "Activo" if item.is_active else "Inactivo",
    }


class ItemForm(forms.ModelForm):
    """
    Alta y edición de ítems.

    - El código es opcional: si queda vacío se genera ITM-NNNN al guardar. Uno escrito se guarda
      en mayúsculas y sin espacios sobrantes, y no puede usar el formato reservado ITM-<número>
      (salvo el que el ítem ya tiene), para no chocar con la numeración automática.
    - El estado solo se elige al crear; después se cambia con Desactivar/Activar.
    """

    is_active = forms.TypedChoiceField(
        label="Estado",
        choices=[("True", "Activo"), ("False", "Inactivo")],
        coerce=lambda value: value == "True",
        widget=forms.Select(attrs={"class": "form-select"}),
    )

    class Meta:
        model = Item
        fields = ["code", "item_name", "description", "is_active"]
        widgets = {
            "code": forms.TextInput(
                attrs={
                    "class": "form-control",
                    "maxlength": CODE_MAX_LENGTH,
                    "autocomplete": "off",
                    "placeholder": "Se genera automáticamente si se deja vacío",
                }
            ),
            "item_name": forms.TextInput(
                attrs={"class": "form-control", "maxlength": 150, "autocomplete": "off"}
            ),
            "description": forms.Textarea(attrs={"class": "form-control", "rows": 3}),
        }
        labels = {
            "code": "Código",
            "item_name": "Nombre del ítem",
            "description": "Descripción",
        }
        help_texts = {"code": ""}
        error_messages = {
            "code": {"unique": "Ya existe un ítem con este código."},
            "item_name": {
                "required": "Ingresa el nombre del ítem.",
                "unique": "Ya existe un ítem con este nombre.",
            },
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance.pk:
            self.fields.pop("is_active")
            self.previous_snapshot = item_snapshot(self.instance)
        else:
            self.previous_snapshot = None

    def clean_code(self):
        code = normalize_spaces(self.cleaned_data.get("code")).upper()
        if not code:
            return ""
        if len(code) > CODE_MAX_LENGTH:
            raise ValidationError(f"El código no puede superar los {CODE_MAX_LENGTH} caracteres.")
        current = (self.instance.code or "").upper() if self.instance.pk else ""
        if RESERVED_ITEM_CODE.match(code) and code != current:
            raise ValidationError(
                f"Los códigos {Item.code_prefix}-<número> se reservan para la numeración automática. "
                "Deja el campo vacío o usa otro código."
            )
        duplicates = Item.objects.filter(code__iexact=code)
        if self.instance.pk:
            duplicates = duplicates.exclude(pk=self.instance.pk)
        if duplicates.exists():
            raise ValidationError("Ya existe un ítem con este código.")
        return code

    def clean_item_name(self):
        name = normalize_spaces(self.cleaned_data.get("item_name"))
        duplicates = Item.objects.filter(item_name__iexact=name)
        if self.instance.pk:
            duplicates = duplicates.exclude(pk=self.instance.pk)
        if duplicates.exists():
            raise ValidationError("Ya existe un ítem con este nombre.")
        return name

    def clean_description(self):
        return (self.cleaned_data.get("description") or "").strip()
