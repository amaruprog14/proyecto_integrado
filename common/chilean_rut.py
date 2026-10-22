import re

from django.core.exceptions import ValidationError


INVALID_RUT_MESSAGE = "Ingresa un RUT o RUN chileno válido."
RUT_PATTERN = re.compile(
    r"(?:[0-9]{1,2}(?:\.[0-9]{3}){1,2}|[0-9]{1,8})-?[0-9K]"
)


def normalize_chilean_rut(value):
    """Valida el dígito verificador y devuelve el RUT sin puntos, con guion."""
    rut = (value or "").strip().upper()
    if not RUT_PATTERN.fullmatch(rut):
        raise ValidationError(INVALID_RUT_MESSAGE, code="invalid_chilean_rut")

    digits = rut.replace(".", "").replace("-", "")
    number, check_digit = digits[:-1], digits[-1]
    weighted_sum = sum(
        int(digit) * (index % 6 + 2)
        for index, digit in enumerate(reversed(number))
    )
    remainder = 11 - weighted_sum % 11
    expected_digit = "0" if remainder == 11 else "K" if remainder == 10 else str(remainder)
    if check_digit != expected_digit:
        raise ValidationError(INVALID_RUT_MESSAGE, code="invalid_chilean_rut")

    return f"{number}-{check_digit}"


def validate_chilean_rut(value):
    normalize_chilean_rut(value)
