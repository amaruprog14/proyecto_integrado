"""Normalización de textos de formularios y formato de los valores que se registran en la auditoría."""

from django.core.exceptions import ValidationError

# Largo máximo de las descripciones de los mantenedores. El modelo usa TextField (sin límite en
# la base de datos), así que el tope se aplica en el formulario y en el maxlength del Textarea.
DESCRIPTION_MAX_LENGTH = 500


def normalize_spaces(value):
    """Quita los espacios de los extremos y deja uno solo entre palabras."""
    return " ".join((value or "").split())


def clean_description_text(value, max_length=DESCRIPTION_MAX_LENGTH):
    """
    Descripción sin espacios en los extremos y con a lo sumo `max_length` caracteres.

    El navegador envía los saltos de línea del Textarea como "\\r\\n" pero los cuenta como uno
    solo para su maxlength; aquí se cuentan igual, para que lo que el navegador deja escribir
    no sea rechazado por el servidor.
    """
    text = (value or "").strip()
    length = len(text.replace("\r\n", "\n"))
    if length > max_length:
        raise ValidationError(
            f"La descripción no puede superar los {max_length} caracteres (tiene {length}).",
            code="max_length",
        )
    return text


def format_snapshot(snapshot, keys=None):
    """Líneas "Campo: valor" de un snapshot (dict), opcionalmente solo de `keys`."""
    return "\n".join(
        f"{key}: {value}" for key, value in snapshot.items() if keys is None or key in keys
    )


def describe_changes(previous, current):
    """Valor anterior y nuevo para la auditoría, solo con los campos que cambiaron."""
    changed = [key for key in current if current[key] != previous.get(key)]
    if not changed:
        return "Sin cambios", "Sin cambios"
    return format_snapshot(previous, changed), format_snapshot(current, changed)
