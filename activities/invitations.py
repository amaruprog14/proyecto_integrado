import hashlib
import logging
import secrets
from datetime import timedelta

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import SetPasswordForm
from django.core.exceptions import ValidationError
from django.core.mail import send_mail
from django.db import IntegrityError, transaction
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods

from accounts.models import Official, ServiceRecipient
from configuration.services import AuditoriaService

from .models import PortalInvitation


logger = logging.getLogger(__name__)
SESSION_KEY = "portal_invitation_digest"
User = get_user_model()


def email_in_use(email):
    return (User.objects.filter(email__iexact=email).exists()
            or User.objects.filter(username__iexact=email).exists()
            or Official.objects.filter(email__iexact=email).exists())


def invite_to_portal(request, recipient_id, email):
    email = email.strip().lower()
    actor = getattr(request.user, "official", None)
    token = secrets.token_urlsafe(32)
    digest = hashlib.sha256(token.encode()).hexdigest()
    hours = settings.PORTAL_INVITATION_TIMEOUT_HOURS
    url = request.build_absolute_uri(reverse("portal_invitation_token", args=[token]))
    try:
        with transaction.atomic():
            recipient = ServiceRecipient.objects.select_for_update().get(pk=recipient_id)
            if not recipient.is_enabled:
                raise ValidationError("La ficha debe estar activa para enviar una invitación.")
            if recipient.user_id:
                raise ValidationError("La ficha ya tiene cuenta. La persona puede ingresar o recuperar su contraseña.")
            if email_in_use(email):
                raise ValidationError("El correo ya está asociado a una cuenta. Verifica los datos con la persona.")
            previous = PortalInvitation.objects.filter(recipient=recipient).first()
            if previous and previous.expires_at > timezone.now() + timedelta(hours=hours, seconds=-45):
                raise ValidationError("Espera 45 segundos antes de volver a enviar una invitación.")
            PortalInvitation.objects.update_or_create(recipient=recipient, defaults={"email": email,
                "token_digest": digest, "expires_at": timezone.now() + timedelta(hours=hours), "consumed_at": None})
            AuditoriaService.register_change(actor, "Invitación al portal", recipient)
    except IntegrityError as error:
        raise ValidationError("El correo ya tiene una invitación asociada a otra ficha.") from error

    def send_invitation():
        try:
            sent = send_mail("Invitación al portal del SGR",
                      f"Define tu contraseña para consultar tus solicitudes y atenciones.\n\n{url}\n\n"
                      f"El enlace vence en {hours} horas y se puede usar una sola vez.", None, [email])
            if sent != 1:
                raise RuntimeError("No se entregó el mensaje al servicio de correo.")
        except Exception:
            logger.warning("No se pudo enviar una invitación al portal para la ficha %s", recipient_id)
            messages.warning(request, "La atención se guardó. No se pudo enviar la invitación. Puedes reenviarla desde el caso.")
            PortalInvitation.objects.filter(token_digest=digest).update(expires_at=timezone.now())
        else:
            messages.success(request, "Invitación al portal enviada.")

    transaction.on_commit(send_invitation)


def valid_invitation(digest):
    return PortalInvitation.objects.filter(token_digest=digest, consumed_at__isnull=True,
        expires_at__gt=timezone.now())


@never_cache
@require_http_methods(["GET", "POST"])
def activate_portal(request, token=None):
    if token is not None:
        if request.method != "GET":
            return redirect("portal_invitation_activate")
        request.session[SESSION_KEY] = hashlib.sha256(token.encode()).hexdigest()
        response = redirect("portal_invitation_activate")
        response["Referrer-Policy"] = "no-referrer"
        return response

    digest = request.session.get(SESSION_KEY, "")
    invitation = valid_invitation(digest).select_related("recipient").first()
    form = None
    if invitation and not invitation.recipient.user_id and invitation.recipient.is_enabled:
        user = User(username=f"cliente-{invitation.recipient_id}", email=invitation.email)
        form = SetPasswordForm(user, request.POST if request.method == "POST" else None)
        for field in form.fields.values():
            field.widget.attrs["class"] = "form-control"
        if form.is_valid():
            try:
                with transaction.atomic():
                    recipient = ServiceRecipient.objects.select_for_update().get(pk=invitation.recipient_id)
                    current = valid_invitation(digest).select_for_update().first()
                    if not current or recipient.user_id or not recipient.is_enabled or email_in_use(user.email):
                        raise ValidationError("La invitación ya no está disponible. Solicita una nueva en la delegación.")
                    user.username = f"cliente-{secrets.token_hex(12)}"
                    form.save()
                    recipient.user = user
                    if not recipient.email:
                        recipient.email = user.email
                    recipient.save(update_fields=["user", "email", "updated_at"])
                    current.consumed_at = timezone.now()
                    current.save(update_fields=["consumed_at"])
                    AuditoriaService.register_change(None, "Activación de cuenta de cliente", recipient,
                                                     new_value=f"Cuenta {user.pk}")
            except (ValidationError, IntegrityError):
                form.add_error(None, "No se pudo activar la cuenta. Solicita una nueva invitación en la delegación.")
            else:
                request.session.pop(SESSION_KEY, None)
                messages.success(request, "Cuenta activada. Ingresa con tu correo y contraseña.")
                return redirect("login")
    response = render(request, "client/activate.html", {"form": form})
    response["Referrer-Policy"] = "no-referrer"
    return response
