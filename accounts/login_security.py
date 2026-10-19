"""
Bloqueo temporal por intentos fallidos de inicio de sesión y su auditoría.

- Tras LOGIN_MAX_FAILED_ATTEMPTS fallos seguidos (sin una pausa de LOGIN_LOCKOUT_MINUTES entre
  ellos), el identificador queda bloqueado LOGIN_LOCKOUT_MINUTES. Durante el bloqueo no se
  comprueba la contraseña: una clave correcta también se rechaza.
- El contador es por cuenta ("user:<id>": usuario y correo comparten contador). Un identificador
  que no corresponde a ninguna cuenta tiene su propio contador y se bloquea igual, de modo que el
  comportamiento y el mensaje no revelan si la cuenta existe.
- Un ingreso correcto reinicia el contador.
- Los inicios de sesión, los fallos, los bloqueos y los cierres de sesión quedan en AuditLog con
  la IP de origen; nunca se registra la contraseña.
"""

from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from configuration.services import AuditoriaService

from .models import LoginThrottle

# Atributo que el backend deja en la petición para que el formulario muestre el mensaje de bloqueo.
LOCKED_REQUEST_FLAG = "_sgr_login_locked"


def max_failed_attempts():
    return getattr(settings, "LOGIN_MAX_FAILED_ATTEMPTS", 5)


def lockout_minutes():
    return getattr(settings, "LOGIN_LOCKOUT_MINUTES", 10)


def locked_message():
    return (
        f"Demasiados intentos fallidos. Por seguridad, espera {lockout_minutes()} minutos "
        "antes de volver a intentarlo."
    )


def client_ip(request):
    if request is None:
        return None
    return request.META.get("REMOTE_ADDR") or None


def throttle_key(identifier, user):
    if user is not None:
        return f"user:{user.pk}"
    return f"login:{identifier.strip().casefold()}"[:191]


def is_locked(key):
    return LoginThrottle.objects.filter(key=key, locked_until__gt=timezone.now()).exists()


def reset_failures(key):
    LoginThrottle.objects.filter(key=key).delete()


def register_failure(key):
    """Suma un intento fallido. Devuelve (intentos, se_bloqueó_ahora)."""
    now = timezone.now()
    window = timedelta(minutes=lockout_minutes())
    with transaction.atomic():
        # Contadores vencidos: no aportan nada y evitan que la tabla crezca sin límite.
        LoginThrottle.objects.filter(last_failure_at__lt=now - window).exclude(locked_until__gt=now).exclude(
            key=key
        ).delete()
        throttle, _ = LoginThrottle.objects.select_for_update().get_or_create(key=key)
        if throttle.last_failure_at is None or now - throttle.last_failure_at >= window:
            throttle.failed_attempts = 0
        throttle.failed_attempts += 1
        throttle.last_failure_at = now
        locked_now = throttle.failed_attempts >= max_failed_attempts()
        if locked_now:
            throttle.locked_until = now + window
            throttle.failed_attempts = 0
        throttle.save()
    return (max_failed_attempts() if locked_now else throttle.failed_attempts), locked_now


def audit_login_event(request, action, user=None, detail=""):
    AuditoriaService.register_event(
        official=getattr(user, "official", None) if action in ("Inicio de sesión", "Cierre de sesión") else None,
        action=action,
        entity="auth_user",
        record_id=user.pk if user is not None else None,
        new_value=detail,
        origin_ip=client_ip(request),
    )


def reject_locked_attempt(request, identifier, user):
    """Intento durante un bloqueo: se rechaza sin probar la contraseña y queda auditado."""
    if request is not None:
        setattr(request, LOCKED_REQUEST_FLAG, True)
    audit_login_event(
        request,
        "Inicio de sesión fallido",
        user,
        f"Identificador: {identifier[:150]}\nRechazado: bloqueo temporal vigente",
    )


def record_failed_attempt(request, identifier, user, key):
    attempts, locked_now = register_failure(key)
    audit_login_event(
        request,
        "Inicio de sesión fallido",
        user,
        f"Identificador: {identifier[:150]}\nIntentos fallidos: {attempts} de {max_failed_attempts()}",
    )
    if locked_now:
        if request is not None:
            setattr(request, LOCKED_REQUEST_FLAG, True)
        audit_login_event(
            request,
            "Bloqueo temporal de inicio de sesión",
            user,
            f"Identificador: {identifier[:150]}\nBloqueado por {lockout_minutes()} minutos",
        )
