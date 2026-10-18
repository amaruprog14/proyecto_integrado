"""Normalización de textos de formularios y formato de los valores que se registran en la auditoría."""


def normalize_spaces(value):
    """Quita los espacios de los extremos y deja uno solo entre palabras."""
    return " ".join((value or "").split())


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
