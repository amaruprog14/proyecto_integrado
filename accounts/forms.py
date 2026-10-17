from django import forms
from django.contrib.auth.forms import AuthenticationForm

GENERIC_LOGIN_ERROR = "Usuario, correo o contraseña incorrectos."


class SGRAuthenticationForm(AuthenticationForm):
    """Login con usuario o correo. El error es genérico para no revelar qué dato falló."""

    error_messages = {
        "invalid_login": GENERIC_LOGIN_ERROR,
        "inactive": GENERIC_LOGIN_ERROR,
    }

    def __init__(self, request=None, *args, **kwargs):
        super().__init__(request, *args, **kwargs)
        username = self.fields["username"]
        username.label = "Usuario o correo"
        username.max_length = 254
        username.widget.attrs.update({"maxlength": 254, "autocomplete": "username"})


class RecoveryRequestForm(forms.Form):
    email = forms.EmailField(
        label="Correo electrónico",
        max_length=191,
        error_messages={
            "required": "Ingresa un correo electrónico válido para continuar.",
            "invalid": "Ingresa un correo electrónico válido para continuar.",
        },
    )


class RecoveryCodeForm(forms.Form):
    code = forms.RegexField(
        regex=r"^\d{6}$",
        error_messages={
            "required": "Ingresa los seis dígitos para continuar.",
            "invalid": "Ingresa los seis dígitos para continuar.",
        },
    )
