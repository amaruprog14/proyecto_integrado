"""
Pruebas de acceso (SCRUM-30) y recuperación de contraseña por enlace con token (SCRUM-31).
Casos del plan de la segunda evaluación: ACC-01 a ACC-06.
"""
import re
import time
from datetime import datetime, timedelta
from unittest import mock

from django.conf import settings
from django.contrib.auth.models import Group, Permission, User
from django.contrib.auth.tokens import PasswordResetTokenGenerator
from django.core import mail
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.test import Client, SimpleTestCase, TestCase, override_settings
from django.urls import reverse
from django.utils.encoding import force_bytes
from django.utils import timezone
from django.utils.http import urlsafe_base64_encode

from accounts.forms import GENERIC_LOGIN_ERROR
from accounts.models import Official, Role
from accounts.validators import PasswordCompositionValidator
from accounts.views import RECOVERY_SENT_MESSAGE
from configuration.models import AuditLog

PASSWORD = "Clave-Segura-1"
NEW_PASSWORD = "Nueva-Clave-9"

MAINTAINER_PERMISSIONS = (
    ("delegation_list", "accounts.view_delegation"),
    ("role_list", "accounts.view_role"),
    ("position_maintainer", "accounts.view_position"),
    ("area_maintainer", "accounts.view_area"),
    ("official_maintainer", "accounts.view_official"),
    ("user_maintainer", "auth.view_user"),
    ("group_maintainer", "auth.view_group"),
    ("activity_maintainer", "activities.view_activity"),
    ("attention_entry", "activities.add_socialattention"),
    ("item_maintainer", "configuration.view_item"),
    ("period_maintainer", "configuration.view_period"),
    ("attention_type_maintainer", "configuration.view_attentiontype"),
    ("subattention_type_maintainer", "configuration.view_subattentiontype"),
)


def create_official_user(username, email=None, status=Official.Status.ACTIVE):
    user = User.objects.create_user(username, "", PASSWORD)
    Official.objects.create(
        user=user,
        full_name=username.title(),
        national_id=f"{username}-1",
        email=email or f"{username}@example.test",
        status=status,
    )
    return user


def get_permission(dotted_name):
    app_label, codename = dotted_name.split(".")
    return Permission.objects.get(content_type__app_label=app_label, codename=codename)


class LoginTests(TestCase):
    """ACC-02: ingreso correcto e incorrecto, campos vacíos y cuenta inactiva."""

    def setUp(self):
        self.user = create_official_user("ana", email="ana.rojas@example.test")

    def login(self, username, password=PASSWORD):
        return self.client.post(reverse("login"), {"username": username, "password": password})

    def assertNoSession(self):
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_login_with_username(self):
        response = self.login("ana")

        self.assertRedirects(response, reverse("home"))
        self.assertEqual(int(self.client.session["_auth_user_id"]), self.user.pk)

    def test_login_with_official_email_ignores_case(self):
        response = self.login("ANA.Rojas@example.test")

        self.assertRedirects(response, reverse("home"))
        self.assertEqual(int(self.client.session["_auth_user_id"]), self.user.pk)

    def test_login_with_user_email_when_there_is_no_official(self):
        admin = User.objects.create_superuser("root", "root@example.test", PASSWORD)

        response = self.login("root@example.test")

        self.assertRedirects(response, reverse("home"))
        self.assertEqual(int(self.client.session["_auth_user_id"]), admin.pk)

    def test_wrong_credentials_show_a_generic_error_and_create_no_session(self):
        for identifier in ("ana", "ana.rojas@example.test", "nadie@example.test", "nadie"):
            with self.subTest(identifier=identifier):
                response = self.login(identifier, "Incorrecta-1")

                self.assertEqual(response.status_code, 200)
                self.assertContains(response, GENERIC_LOGIN_ERROR)
                self.assertNoSession()

    def test_empty_fields_are_reported_per_field(self):
        response = self.client.post(reverse("login"), {"username": "", "password": ""})

        self.assertEqual(response.status_code, 200)
        self.assertIn("username", response.context["form"].errors)
        self.assertIn("password", response.context["form"].errors)
        self.assertNoSession()

    def test_inactive_accounts_cannot_log_in(self):
        inactive_user = User.objects.create_user("bloqueado", "", PASSWORD, is_active=False)
        archived = create_official_user("archivado")
        Official.objects.filter(user=archived).update(deleted_at=timezone.now())
        cases = {
            "usuario inactivo": inactive_user.username,
            "funcionario inactivo": create_official_user("inactivo", status=Official.Status.INACTIVE).username,
            "funcionario suspendido": create_official_user("suspendido", status=Official.Status.SUSPENDED).username,
            "funcionario archivado": archived.username,
        }
        for label, username in cases.items():
            with self.subTest(label):
                response = self.login(username)

                self.assertContains(response, GENERIC_LOGIN_ERROR)
                self.assertNoSession()

    def test_suspending_the_official_ends_an_open_session(self):
        self.login("ana")
        self.assertEqual(self.client.get(reverse("home")).status_code, 200)

        Official.objects.filter(user=self.user).update(status=Official.Status.SUSPENDED)

        response = self.client.get(reverse("home"))
        self.assertRedirects(response, f"{reverse('login')}?next={reverse('home')}")

    def test_authenticated_user_is_sent_from_login_to_home(self):
        self.client.force_login(self.user)

        self.assertRedirects(self.client.get(reverse("login")), reverse("home"))

    def test_login_requires_csrf_and_accepts_current_token(self):
        csrf_client = Client(enforce_csrf_checks=True)
        login_url = reverse("login")

        page = csrf_client.get(login_url)
        self.assertEqual(page.status_code, 200)
        self.assertIn("csrftoken", csrf_client.cookies)

        rejected = csrf_client.post(
            login_url,
            {"username": "ana", "password": PASSWORD},
        )
        self.assertEqual(rejected.status_code, 403)

        token = csrf_client.cookies["csrftoken"].value
        accepted = csrf_client.post(
            login_url,
            {"username": "ana", "password": PASSWORD, "csrfmiddlewaretoken": token},
            HTTP_X_CSRFTOKEN=token,
        )
        self.assertRedirects(accepted, reverse("home"))


class ProtectedRouteTests(TestCase):
    """ACC-01 y ACC-03: rutas protegidas, permisos validados en el servidor y cierre de sesión."""

    def test_anonymous_users_are_sent_to_login(self):
        for route_name in ("home", *(route for route, _ in MAINTAINER_PERMISSIONS)):
            with self.subTest(route=route_name):
                url = reverse(route_name)

                self.assertRedirects(self.client.get(url), f"{reverse('login')}?next={url}")

    def test_each_screen_requires_its_permission_and_logs_the_denial(self):
        user = create_official_user("luis")
        self.client.force_login(user)

        for route_name, permission in MAINTAINER_PERMISSIONS:
            with self.subTest(route=route_name):
                url = reverse(route_name)

                self.assertEqual(self.client.get(url).status_code, 403)
                log = AuditLog.objects.order_by("-pk").first()
                self.assertEqual(log.action, "Acceso denegado")
                self.assertEqual(log.official, user.official)
                self.assertIn(url, log.new_value)
                self.assertIn(permission, log.new_value)

                user.user_permissions.add(get_permission(permission))
                self.assertEqual(self.client.get(url).status_code, 200)

    def test_permission_without_an_enabled_official_is_not_enough(self):
        without_official = User.objects.create_user("sin_contexto", "", PASSWORD)
        without_official.user_permissions.add(get_permission("activities.view_activity"))
        self.client.force_login(without_official)

        self.assertEqual(self.client.get(reverse("activity_maintainer")).status_code, 403)

    def test_superuser_reaches_every_screen(self):
        self.client.force_login(User.objects.create_superuser("root", "root@example.test", PASSWORD))

        for route_name, _ in MAINTAINER_PERMISSIONS:
            with self.subTest(route=route_name):
                self.assertEqual(self.client.get(reverse(route_name)).status_code, 200)

    def test_menu_only_lists_permitted_sections(self):
        user = create_official_user("marta")
        user.user_permissions.add(get_permission("activities.view_activity"))
        self.client.force_login(user)

        response = self.client.get(reverse("home"))

        self.assertContains(response, reverse("activity_maintainer"))
        self.assertNotContains(response, reverse("delegation_list"))
        self.assertNotContains(response, reverse("item_maintainer"))

    def test_logout_ends_access_and_pages_are_not_cached(self):
        self.client.force_login(User.objects.create_superuser("root", "root@example.test", PASSWORD))
        url = reverse("delegation_list")

        response = self.client.get(url)
        self.assertIn("no-store", response["Cache-Control"])
        self.assertIn("no-store", self.client.get(reverse("home"))["Cache-Control"])

        self.assertEqual(self.client.get(reverse("logout")).status_code, 405)
        self.assertRedirects(self.client.post(reverse("logout")), reverse("login"))
        self.assertRedirects(self.client.get(url), f"{reverse('login')}?next={url}")


class RolePermissionBackendTests(TestCase):
    """Los permisos de los roles SGR vigentes se suman a los de usuario y grupo."""

    def setUp(self):
        self.user = create_official_user("rita")
        self.role = Role.objects.create(role_name="Operador")
        self.role.permissions.add(get_permission("accounts.view_delegation"))
        self.role.officials.add(self.user.official)

    def fresh_user(self, user=None):
        return User.objects.get(pk=(user or self.user).pk)

    def test_active_role_grants_its_permissions_on_the_server(self):
        self.assertTrue(self.fresh_user().has_perm("accounts.view_delegation"))
        self.client.force_login(self.user)

        self.assertEqual(self.client.get(reverse("delegation_list")).status_code, 200)
        self.assertEqual(self.client.get(reverse("role_list")).status_code, 403)

    def test_inactive_or_archived_role_grants_nothing(self):
        for changes in ({"is_active": False}, {"deleted_at": timezone.now()}):
            with self.subTest(changes=changes):
                Role.objects.filter(pk=self.role.pk).update(**{"is_active": True, "deleted_at": None, **changes})

                self.assertFalse(self.fresh_user().has_perm("accounts.view_delegation"))

    def test_role_permissions_require_an_enabled_official(self):
        Official.objects.filter(user=self.user).update(status=Official.Status.SUSPENDED)

        self.assertFalse(self.fresh_user().has_perm("accounts.view_delegation"))

    def test_role_does_not_leak_to_other_officials(self):
        other = create_official_user("otro")

        self.assertFalse(self.fresh_user(other).has_perm("accounts.view_delegation"))

    def test_group_permissions_still_apply(self):
        group = Group.objects.create(name="Consulta")
        group.permissions.add(get_permission("configuration.view_item"))
        self.user.groups.add(group)

        user = self.fresh_user()
        self.assertTrue(user.has_perm("configuration.view_item"))
        self.assertTrue(user.has_perm("accounts.view_delegation"))


@override_settings(
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    PASSWORD_RESET_MIN_RESPONSE_SECONDS=0,
)
class PasswordRecoveryFlowTests(TestCase):
    """ACC-04 a ACC-06: solicitud genérica, enlace con token y nueva contraseña."""

    def setUp(self):
        cache.clear()  # espera mínima entre correos (clave por cuenta)
        self.user = create_official_user("ana", email="ana@example.test")

    def request_link(self, email="ana@example.test", **extra):
        return self.client.post(reverse("recovery_request"), {"email": email}, follow=True, **extra)

    def sent_link(self):
        return re.search(r"https?://\S+", mail.outbox[-1].body).group(0)

    def open_link(self, link):
        """Abre el enlace y devuelve la respuesta del formulario (Django quita el token de la URL)."""
        return self.client.get(link, follow=True)

    def set_password(self, password1, password2=None):
        return self.client.post(
            self.set_password_url,
            {"new_password1": password1, "new_password2": password2 or password1},
            follow=True,
        )

    def start_valid_reset(self):
        self.request_link()
        response = self.open_link(self.sent_link())
        self.assertTrue(response.context["validlink"])
        self.set_password_url = response.request["PATH_INFO"]
        self.assertNotIn(self.sent_link().rstrip("/").rsplit("/", 1)[-1], self.set_password_url)
        return response

    # --- ACC-04 ---
    def test_response_is_the_same_for_existing_and_unknown_emails(self):
        existing = self.request_link("ana@example.test")
        self.client = self.client_class()
        unknown = self.request_link("nadie@example.test")

        for response in (existing, unknown):
            self.assertRedirects(response, reverse("login"))
            self.assertContains(response, RECOVERY_SENT_MESSAGE)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ["ana@example.test"])
        logs = AuditLog.objects.filter(action="Solicitud de recuperación de contraseña").order_by("pk")
        self.assertEqual(
            [(log.affected_record_id, log.new_value.splitlines()[-1]) for log in logs],
            [(self.user.pk, "Enlace enviado"),
             (None, "Sin envío: el correo no corresponde a una cuenta activa")],
        )
        self.assertNotIn("nadie@example.test", logs[1].new_value)

    @override_settings(PASSWORD_RESET_MIN_RESPONSE_SECONDS=0.3)
    def test_request_takes_the_same_minimum_time_with_and_without_account(self):
        for email in ("ana@example.test", "nadie@example.test"):
            with self.subTest(email=email):
                started = time.monotonic()
                self.request_link(email)
                self.assertGreaterEqual(time.monotonic() - started, 0.3)

    def test_inactive_account_receives_no_link(self):
        Official.objects.filter(user=self.user).update(status=Official.Status.INACTIVE)

        response = self.request_link()

        self.assertContains(response, RECOVERY_SENT_MESSAGE)
        self.assertEqual(len(mail.outbox), 0)

    def test_invalid_email_is_rejected_by_the_server(self):
        response = self.client.post(reverse("recovery_request"), {"email": "no-es-correo"})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Ingresa un correo electrónico válido para continuar.")
        self.assertEqual(len(mail.outbox), 0)

    def test_link_is_absolute_and_uses_the_request_host(self):
        self.request_link(HTTP_HOST="127.0.0.1")

        link = self.sent_link()
        uidb64 = urlsafe_base64_encode(force_bytes(self.user.pk))
        self.assertTrue(link.startswith(f"http://127.0.0.1/accounts/recuperar/{uidb64}/"), link)
        self.assertIn(f"{settings.PASSWORD_RESET_TIMEOUT // 60} minutos", mail.outbox[-1].body)

    def test_host_outside_allowed_hosts_gets_400_and_no_link(self):
        with self.assertLogs("django.security.DisallowedHost", "ERROR"):
            response = self.client.post(
                reverse("recovery_request"), {"email": "ana@example.test"}, HTTP_HOST="sitio-ajeno.example"
            )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(len(mail.outbox), 0)

    def test_a_second_request_waits_before_sending_another_link(self):
        self.request_link()
        self.assertContains(self.request_link(), RECOVERY_SENT_MESSAGE)
        self.assertEqual(len(mail.outbox), 1)

        with self.settings(PASSWORD_RESET_RESEND_WAIT_SECONDS=0):
            cache.clear()
            self.request_link()
        self.assertEqual(len(mail.outbox), 2)

    # --- ACC-05 ---
    def test_valid_token_opens_the_new_password_form(self):
        response = self.start_valid_reset()

        self.assertTemplateUsed(response, "accounts/recovery_password.html")
        self.assertContains(response, "Crear nueva contraseña")

    def test_invalid_token_shows_a_clear_message_and_a_new_request_link(self):
        uidb64 = urlsafe_base64_encode(force_bytes(self.user.pk))
        cases = {
            "token alterado": reverse("recovery_confirm", args=[uidb64, "abc-123"]),
            "usuario inexistente": reverse("recovery_confirm", args=["OTk5OTk", "abc-123"]),
            "uid no decodificable": reverse("recovery_confirm", args=["%%%", "abc-123"]),
        }
        for label, url in cases.items():
            with self.subTest(label):
                response = self.client.get(url, follow=True)

                self.assertEqual(response.status_code, 200)
                self.assertFalse(response.context["validlink"])
                self.assertContains(response, "El enlace no es válido")
                self.assertContains(response, f'href="{reverse("recovery_request")}"')

    def test_expired_token_is_rejected(self):
        self.request_link()
        expired = datetime.now() + timedelta(seconds=settings.PASSWORD_RESET_TIMEOUT + 1)

        with mock.patch.object(PasswordResetTokenGenerator, "_now", return_value=expired):
            response = self.open_link(self.sent_link())

        self.assertFalse(response.context["validlink"])
        self.assertContains(response, "El enlace no es válido")

    def test_token_of_an_account_that_can_no_longer_log_in_is_rejected(self):
        self.request_link()
        Official.objects.filter(user=self.user).update(status=Official.Status.SUSPENDED)

        self.assertFalse(self.open_link(self.sent_link()).context["validlink"])

    # --- ACC-06 ---
    def test_weak_or_mismatched_passwords_are_rejected(self):
        self.start_valid_reset()
        cases = {
            "corta": ("Ab1-x", None),
            "sin mayúscula": ("clave-segura-9", None),
            "sin minúscula": ("CLAVE-SEGURA-9", None),
            "sin número": ("Clave-Segura", None),
            "confirmación distinta": (NEW_PASSWORD, "Nueva-Clave-8"),
        }
        for label, (password1, password2) in cases.items():
            with self.subTest(label):
                response = self.set_password(password1, password2)

                self.assertEqual(response.status_code, 200)
                self.assertTemplateUsed(response, "accounts/recovery_password.html")
                self.assertTrue(response.context["form"].errors)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password(PASSWORD))

    def test_valid_password_replaces_the_old_one_and_is_audited(self):
        self.start_valid_reset()

        response = self.set_password(NEW_PASSWORD)

        self.assertRedirects(response, reverse("login"))
        self.assertContains(response, "Tu contraseña fue actualizada.")
        self.assertContains(response, "sweetalert2")
        log = AuditLog.objects.get(action="Cambio de contraseña por recuperación")
        self.assertEqual(log.affected_record_id, self.user.pk)
        self.assertNotIn(NEW_PASSWORD, f"{log.previous_value}{log.new_value}")
        self.assertFalse(self.client.login(username="ana", password=PASSWORD))
        self.assertTrue(self.client.login(username="ana", password=NEW_PASSWORD))

    def test_used_token_cannot_be_reused(self):
        self.start_valid_reset()
        used_link = self.sent_link()
        self.set_password(NEW_PASSWORD)

        self.client = self.client_class()
        response = self.open_link(used_link)

        self.assertFalse(response.context["validlink"])
        self.assertContains(response, "El enlace no es válido")
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password(NEW_PASSWORD))


class PasswordCompositionValidatorTests(SimpleTestCase):
    def test_requires_uppercase_lowercase_and_digit(self):
        validator = PasswordCompositionValidator()
        validator.validate("Clave-Segura-1")

        for weak in ("clave-segura-1", "CLAVE-SEGURA-1", "Clave-Segura"):
            with self.subTest(password=weak), self.assertRaises(ValidationError):
                validator.validate(weak)
