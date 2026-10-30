"""Reglas compartidas por los formularios de mantenedores."""
import re

from django.core.exceptions import ValidationError

from common.text import normalize_spaces

DEFAULT_COMMUNE = "La Serena"
CATALOG_PATTERN = r"[^\W\d_]+(?:[ -][^\W\d_]+)*"
ADDRESS_PATTERN = r"[^\W_]+(?:[ #.,/'ºª°-]+[^\W_]+)*[.,ºª°]?"
CODE_PATTERN = r"[A-Za-z0-9_-]+"
PERSON_PATTERN = r"[^\W\d_]+\.?(?:(?: |['’-])[^\W\d_]+\.?)*"


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
        "role_name": CATALOG_PATTERN, "name": CATALOG_PATTERN,
        "full_name": PERSON_PATTERN, "first_name": PERSON_PATTERN,
        "last_name": PERSON_PATTERN, "recipient_full_name": PERSON_PATTERN,
        "address": ADDRESS_PATTERN, "code": CODE_PATTERN,
        "phone": r"\+?[0-9 ()-]+",
        "username": r"[\w@.+-]+",
    }
    for name, field in form.fields.items():
        if name in patterns:
            field.widget.attrs["data-field-pattern"] = patterns[name]
        if getattr(field, "max_length", None):
            field.widget.attrs["maxlength"] = field.max_length
