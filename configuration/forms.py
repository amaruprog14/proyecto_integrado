from common.field_validation import clean_catalog_name, clean_code, configure_text_widgets
import re

from django import forms
from django.core.exceptions import ValidationError

from common.text import DESCRIPTION_MAX_LENGTH, clean_description_text, normalize_spaces
from configuration.models import AttentionType, Item, SubattentionType

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


def attention_type_snapshot(attention_type):
    """Valores auditables del tipo de atención."""
    return {
        "Código": attention_type.code,
        "Nombre": attention_type.name,
        "Descripción": attention_type.description or "—",
        "Estado": "Activo" if attention_type.is_active else "Inactivo",
    }


def subattention_type_snapshot(subattention_type):
    """Valores auditables de la subatención, con su tipo asociado por código y nombre."""
    attention_type = subattention_type.attention_type
    return {
        "Código": subattention_type.code,
        "Nombre": subattention_type.name,
        "Descripción": subattention_type.description or "—",
        "Tipo de Atención asociado": f"{attention_type.code} · {attention_type.name}",
        "Estado": "Activo" if subattention_type.is_active else "Inactivo",
    }


def catalog_snapshot(record):
    """Snapshot del tipo de atención o de la subatención, según el registro."""
    if isinstance(record, SubattentionType):
        return subattention_type_snapshot(record)
    return attention_type_snapshot(record)


class ItemForm(forms.ModelForm):
    """
    Alta y edición de ítems.

    - Al crear, el código es opcional: si queda vacío se genera ITM-NNNN al guardar. Al editar es
      obligatorio, para que vaciarlo no cambie en silencio el código de un ítem existente. Uno
      escrito se guarda en mayúsculas y sin espacios sobrantes, y no puede usar el formato
      reservado ITM-<número> (salvo el que el ítem ya tiene), para no chocar con la numeración
      automática.
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
            "description": forms.Textarea(
                attrs={"class": "form-control", "rows": 3, "maxlength": DESCRIPTION_MAX_LENGTH}
            ),
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
        configure_text_widgets(self)
        if self.instance.pk:
            self.fields.pop("is_active")
            self.previous_snapshot = item_snapshot(self.instance)
            code_field = self.fields["code"]
            code_field.required = True
            code_field.widget.attrs.pop("placeholder", None)
            code_field.error_messages["required"] = (
                f"Ingresa el código del ítem. El código actual es {self.instance.code}; "
                "un ítem existente no puede quedar sin código."
            )
        else:
            self.previous_snapshot = None

    def clean_code(self):
        code = clean_code(self.cleaned_data.get("code"))
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
        name = clean_catalog_name(self.cleaned_data.get("item_name"))
        duplicates = Item.objects.only("pk", "item_name").all()
        if self.instance.pk:
            duplicates = duplicates.exclude(pk=self.instance.pk)
        normalized_name = name.casefold()
        if any(
            normalize_spaces(existing_name).casefold() == normalized_name
            for existing_name in duplicates.values_list("item_name", flat=True)
        ):
            raise ValidationError("Ya existe un ítem con este nombre.")
        return name

    def clean_description(self):
        return clean_description_text(self.cleaned_data.get("description"))


class AttentionTypeForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        configure_text_widgets(self)

    class Meta:
        model = AttentionType
        fields = ("name", "description", "is_active")
        widgets = {
            "name": forms.TextInput(
                attrs={"class": "form-control", "maxlength": 150, "autocomplete": "off"}
            ),
            "description": forms.Textarea(
                attrs={"class": "form-control", "rows": 3, "maxlength": DESCRIPTION_MAX_LENGTH}
            ),
            "is_active": forms.Select(
                choices=((True, "Activo"), (False, "Inactivo")),
                attrs={"class": "form-select"},
            ),
        }
        labels = {
            "name": "Nombre",
            "description": "Descripción",
            "is_active": "Estado",
        }
        error_messages = {"name": {"required": "Ingresa el nombre del tipo de atención."}}

    def clean_name(self):
        name = clean_catalog_name(self.cleaned_data.get("name"))
        duplicates = AttentionType.objects.filter(
            name__iexact=name, service_type=self.instance.service_type
        )
        if self.instance.pk:
            duplicates = duplicates.exclude(pk=self.instance.pk)
        if duplicates.exists():
            raise ValidationError("Ya existe un tipo de atención con ese nombre.")
        return name

    def clean_description(self):
        return clean_description_text(self.cleaned_data.get("description"))

    def clean(self):
        cleaned_data = super().clean()
        if (
            self.instance.pk
            and cleaned_data.get("is_active") is False
            and self.instance.subattention_types.filter(
                is_active=True, deleted_at__isnull=True
            ).exists()
        ):
            self.add_error(
                "is_active",
                "No se puede desactivar este tipo mientras tenga subatenciones activas.",
            )
        return cleaned_data


class SubattentionTypeForm(forms.ModelForm):
    class Meta:
        model = SubattentionType
        fields = ("name", "attention_type", "is_active")
        widgets = {
            "name": forms.TextInput(
                attrs={"class": "form-control", "maxlength": 150, "autocomplete": "off"}
            ),
            "attention_type": forms.Select(attrs={"class": "form-select"}),
            "is_active": forms.Select(
                choices=((True, "Activo"), (False, "Inactivo")),
                attrs={"class": "form-select"},
            ),
        }
        labels = {
            "name": "Nombre",
            "attention_type": "Tipo de Atención asociado",
            "is_active": "Estado",
        }
        error_messages = {
            "name": {"required": "Ingresa el nombre de la subatención."},
            "attention_type": {"required": "Selecciona el tipo de atención asociado."},
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        configure_text_widgets(self)
        self.fields["attention_type"].queryset = AttentionType.objects.filter(
            deleted_at__isnull=True
        ).order_by("name")

    def clean_name(self):
        return clean_catalog_name(self.cleaned_data.get("name"))

    def clean(self):
        cleaned_data = super().clean()
        attention_type = cleaned_data.get("attention_type")
        name = cleaned_data.get("name")
        is_active = cleaned_data.get("is_active")

        if attention_type is not None and name:
            duplicates = SubattentionType.objects.filter(
                name__iexact=name, attention_type=attention_type
            )
            if self.instance.pk:
                duplicates = duplicates.exclude(pk=self.instance.pk)
            if duplicates.exists():
                self.add_error(
                    "name",
                    "Ya existe una subatención con ese nombre para este tipo.",
                )

        if is_active and attention_type is not None and not attention_type.is_active:
            self.add_error(
                "attention_type",
                "No puedes activar una subatención asociada a un tipo de atención inactivo.",
            )

        if (
            self.instance.pk
            and attention_type is not None
            and attention_type.pk != self.instance.attention_type_id
            and self.instance.social_attentions.exists()
        ):
            self.add_error(
                "attention_type",
                "No puedes cambiar el tipo asociado porque esta subatención ya tiene atenciones registradas.",
            )
        return cleaned_data
