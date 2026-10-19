"""Auditoría de inicios y cierres de sesión (los fallos se registran en accounts.login_security)."""

from django.contrib.auth.signals import user_logged_in, user_logged_out
from django.dispatch import receiver

from .login_security import audit_login_event


@receiver(user_logged_in, dispatch_uid="sgr_audit_login")
def audit_login(sender, request, user, **kwargs):
    audit_login_event(request, "Inicio de sesión", user, f"Usuario: {user.get_username()}")


@receiver(user_logged_out, dispatch_uid="sgr_audit_logout")
def audit_logout(sender, request, user, **kwargs):
    if user is None:
        return
    audit_login_event(request, "Cierre de sesión", user, f"Usuario: {user.get_username()}")
