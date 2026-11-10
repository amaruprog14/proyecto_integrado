"""Reglas compartidas por los formularios de mantenedores."""
import re

from django.core.exceptions import ValidationError

from common.text import normalize_spaces

DEFAULT_COMMUNE = "La Serena"
CATALOG_PATTERN = r"[^\W\d_]+(?:[ -][^\W\d_]+)*"
ADDRESS_PATTERN = r"[^\W_]+(?:[ #.,/'ºª°-]+[^\W_]+)*[.,ºª°]?"
CODE_PATTERN = r"[A-Za-z0-9_-]+"
PERSON_PATTERN = r"[^\W\d_]+(?: [^\W\d_]+)*"
PHONE_PATTERN = r"[0-9]+"
ACCOUNT_TEXT_LIMITS = {
    "first_name": 50, "last_name": 50, "username": 50, "email": 60,
    "password1": 40, "password2": 40, "national_id": 20, "phone": 30,
    "address": 50, "full_name": 101,
}


def text_length(value):
    return len(value.replace("\r\n", "\n").encode("utf-16-le")) // 2


class LimitedTextFieldsMixin:
    """Aplica los límites de edición sin alterar las columnas ni los datos históricos."""

    text_limits = {}

    def keeps_original_text(self, name):
        if not getattr(getattr(self, "instance", None), "pk", None):
            return False
        original = self.initial.get(name)
        value = self.data.get(self.add_prefix(name))
        return isinstance(original, str) and isinstance(value, str) and (
            original.replace("\r\n", "\n") == value.replace("\r\n", "\n")
        )

    def clean(self):
        data = super().clean()
        for name, limit in self.text_limits.items():
            if name not in data:
                continue
            value = self.data.get(self.add_prefix(name))
            if isinstance(value, str) and text_length(value) > limit and not self.keeps_original_text(name):
                self.add_error(name, ValidationError(
                    f"Este campo no puede superar los {limit} caracteres.", code="max_length"
                ))
        return data


def clean_catalog_name(value):
    value = normalize_spaces(value)
    if value and not re.fullmatch(CATALOG_PATTERN, value):
        raise ValidationError("Usa solo letras, tildes, espacios y guiones.")
    return value


def clean_address(value):
    value = normalize_spaces(value)
    if value and not re.fullmatch(ADDRESS_PATTERN, value):
        raise ValidationError("Usa letras, números, espacios y puntuación habitual (# . , / -).")
    return value


def clean_code(value):
    value = normalize_spaces(value).upper()
    if value and not re.fullmatch(CODE_PATTERN, value):
        raise ValidationError("Usa solo letras, números, guiones y guiones bajos.")
    return value


def configure_text_widgets(form):
    """El navegador anticipa las mismas reglas; el servidor conserva la autoridad."""
    patterns = {
        "delegation_name": CATALOG_PATTERN, "item_name": CATALOG_PATTERN,
        "territory_name": CATALOG_PATTERN,
        "role_name": CATALOG_PATTERN, "name": CATALOG_PATTERN,
        "position_name": CATALOG_PATTERN, "area_name": CATALOG_PATTERN,
        "full_name": PERSON_PATTERN, "first_name": PERSON_PATTERN,
        "last_name": PERSON_PATTERN, "recipient_full_name": PERSON_PATTERN,
        "address": ADDRESS_PATTERN, "code": CODE_PATTERN,
        "phone": PHONE_PATTERN,
        "username": r"[\w@.+-]+",
    }
    for name, field in form.fields.items():
        if name in patterns:
            field.widget.attrs["data-field-pattern"] = patterns[name]
        limit = getattr(form, "text_limits", {}).get(name, getattr(field, "max_length", None))
        if limit:
            field.widget.attrs["maxlength"] = limit
        if name == "phone":
            field.widget.attrs["inputmode"] = "numeric"
        if name in {"full_name", "first_name", "last_name", "phone"}:
            original = form.initial.get(name)
            if isinstance(original, str) and getattr(getattr(form, "instance", None), "pk", None):
                field.widget.attrs["data-original-text"] = original
