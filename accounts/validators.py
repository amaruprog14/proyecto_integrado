import re

from django.core.exceptions import ValidationError


class PasswordCompositionValidator:
    """
    Exige al menos una mayúscula, una minúscula y un número: los requisitos que muestra la
    pantalla de nueva contraseña también se validan en el servidor.
    """

    def validate(self, password, user=None):
        missing = []
        if not any(char.isupper() for char in password):
            missing.append("una letra mayúscula")
        if not any(char.islower() for char in password):
            missing.append("una letra minúscula")
        if not re.search(r"[0-9]", password):
            missing.append("un número")
        if missing:
            raise ValidationError(
                "La contraseña debe contener al menos %(missing)s.",
                code="password_composition",
                params={"missing": ", ".join(missing)},
            )

    def get_help_text(self):
        return "La contraseña debe contener al menos una letra mayúscula, una minúscula y un número."
