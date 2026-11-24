"""Escaneo previo a la persistencia mediante el cliente local de clamd."""
import subprocess

from django.conf import settings
from django.core.exceptions import ValidationError


def scan_upload(upload):
    if not settings.CLAMAV_ENABLED:
        return
    upload.seek(0)
    try:
        result = subprocess.run(
            [settings.CLAMAV_CLIENT, "--stream", "--no-summary", "-"],
            input=upload.read(), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            timeout=15, check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise ValidationError("El antivirus no está disponible. Intenta nuevamente.") from error
    finally:
        upload.seek(0)
    if result.returncode == 1:
        raise ValidationError("El antivirus rechazó el archivo.")
    if result.returncode != 0:
        raise ValidationError("No se pudo completar el análisis antivirus.")
