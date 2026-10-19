"""
Pruebas del bloqueo temporal por intentos fallidos de inicio de sesión y de la auditoría de
inicios, fallos, bloqueos y cierres de sesión (RNF de autenticación, ACC-02 y SEG-04).
"""

from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.forms import GENERIC_LOGIN_ERROR
from accounts.login_security import locked_message
from accounts.models import LoginThrottle, Official
from configuration.models import AuditLog

User = get_user_model()
PASSWORD = "Clave-Ingreso-123"
WRONG = "Incorrecta-123"


@override_settings(LOGIN_MAX_FAILED_ATTEMPTS=5, LOGIN_LOCKOUT_MINUTES=10)
class LoginLockoutTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user("ana.bloqueo", "ana.bloqueo@example.test", PASSWORD)
        cls.official = Official.objects.create(
            user=cls.user,
            full_name="Ana Bloqueo",
            national_id="RUT-BLOQUEO",
            email="ana.bloqueo@example.test",
        )

    def login(self, identifier, password=WRONG):
        return self.client.post(reverse("login"), {"username": identifier, "password": password})

    def assertNoSession(self):
        self.assertNotIn("_auth_user_id", self.client.session)

    def fail_times(self, identifier, times):
        for _ in range(times):
            response = self.login(identifier)
        return response

    def test_account_is_locked_after_the_maximum_and_rejects_even_the_right_password(self):
        fourth = self.fail_times("ana.bloqueo", 4)
        self.assertContains(fourth, GENERIC_LOGIN_ERROR)

        fifth = self.login("ana.bloqueo")
        self.assertContains(fifth, locked_message())

        response = self.login("ana.bloqueo", PASSWORD)

        self.assertContains(response, "Demasiados intentos fallidos")
        self.assertContains(response, "espera 10 minutos")
        self.assertNoSession()

    def test_username_and_email_share_the_counter(self):
        self.fail_times("ana.bloqueo", 3)
        self.fail_times("ANA.BLOQUEO@example.test", 2)

        self.assertContains(self.login("ana.bloqueo", PASSWORD), locked_message())
        self.assertNoSession()

    def test_unknown_identifier_locks_the_same_way_without_revealing_it(self):
        existing = self.fail_times("ana.bloqueo", 5)
        unknown = self.fail_times("nadie@example.test", 5)

        self.assertEqual(existing.context["form"].non_field_errors(), unknown.context["form"].non_field_errors())
        self.assertContains(unknown, locked_message())

    def test_lock_expires_after_the_configured_time(self):
        self.fail_times("ana.bloqueo", 5)
        LoginThrottle.objects.update(locked_until=timezone.now() - timedelta(seconds=1))

        response = self.login("ana.bloqueo", PASSWORD)

        self.assertRedirects(response, reverse("home"), fetch_redirect_response=False)
        self.assertFalse(LoginThrottle.objects.exists())

    def test_old_failures_do_not_accumulate(self):
        self.fail_times("ana.bloqueo", 4)
        LoginThrottle.objects.update(last_failure_at=timezone.now() - timedelta(minutes=11))

        self.assertContains(self.login("ana.bloqueo"), GENERIC_LOGIN_ERROR)
        self.assertEqual(LoginThrottle.objects.get().failed_attempts, 1)

    def test_successful_login_resets_the_counter(self):
        self.fail_times("ana.bloqueo", 4)
        self.login("ana.bloqueo", PASSWORD)
        self.client.post(reverse("logout"))

        response = self.fail_times("ana.bloqueo", 4)

        self.assertContains(response, GENERIC_LOGIN_ERROR)
        self.assertRedirects(self.login("ana.bloqueo", PASSWORD), reverse("home"), fetch_redirect_response=False)

    def test_inactive_account_with_the_right_password_counts_as_a_failure(self):
        Official.objects.filter(pk=self.official.pk).update(status=Official.Status.SUSPENDED)

        self.fail_times("ana.bloqueo", 4)
        response = self.login("ana.bloqueo", PASSWORD)

        self.assertContains(response, locked_message())

    @override_settings(LOGIN_MAX_FAILED_ATTEMPTS=2, LOGIN_LOCKOUT_MINUTES=3)
    def test_attempts_and_duration_come_from_settings(self):
        self.fail_times("ana.bloqueo", 2)

        response = self.login("ana.bloqueo", PASSWORD)

        self.assertContains(response, "espera 3 minutos")
        lock = LoginThrottle.objects.get(key=f"user:{self.user.pk}")
        self.assertAlmostEqual(
            (lock.locked_until - lock.last_failure_at).total_seconds(), timedelta(minutes=3).total_seconds()
        )

    def test_admin_login_is_locked_too(self):
        self.user.is_staff = True
        self.user.save(update_fields=["is_staff"])
        self.fail_times("ana.bloqueo", 5)

        self.client.post(
            reverse("admin:login"),
            {"username": "ana.bloqueo", "password": PASSWORD, "next": reverse("admin:index")},
        )

        self.assertNoSession()


@override_settings(LOGIN_MAX_FAILED_ATTEMPTS=5, LOGIN_LOCKOUT_MINUTES=10)
class LoginAuditTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user("ana.auditoria", "ana.auditoria@example.test", PASSWORD)
        cls.official = Official.objects.create(
            user=cls.user,
            full_name="Ana Auditoría",
            national_id="RUT-AUD-LOGIN",
            email="ana.auditoria@example.test",
        )

    def login(self, identifier, password):
        return self.client.post(
            reverse("login"), {"username": identifier, "password": password}, REMOTE_ADDR="10.0.0.7"
        )

    def test_successful_login_and_logout_are_audited(self):
        self.login("ana.auditoria", PASSWORD)
        self.client.post(reverse("logout"), REMOTE_ADDR="10.0.0.7")

        login = AuditLog.objects.get(action="Inicio de sesión")
        logout = AuditLog.objects.get(action="Cierre de sesión")
        for log in (login, logout):
            with self.subTest(action=log.action):
                self.assertEqual(log.official, self.official)
                self.assertEqual(log.affected_table, "auth_user")
                self.assertEqual(log.affected_record_id, self.user.pk)
                self.assertEqual(log.origin_ip, "10.0.0.7")

    def test_failures_and_lock_are_audited_without_the_password(self):
        for _ in range(5):
            self.login("ana.auditoria", WRONG)
        self.login("ana.auditoria", PASSWORD)

        failures = AuditLog.objects.filter(action="Inicio de sesión fallido").order_by("pk")
        self.assertEqual(failures.count(), 6)
        self.assertIn("Intentos fallidos: 1 de 5", failures[0].new_value)
        self.assertIn("Rechazado: bloqueo temporal vigente", failures.last().new_value)
        self.assertEqual(failures[0].affected_record_id, self.user.pk)
        self.assertIsNone(failures[0].official)
        self.assertTrue(AuditLog.objects.filter(action="Bloqueo temporal de inicio de sesión").exists())
        self.assertFalse(AuditLog.objects.filter(action="Inicio de sesión").exists())
        for log in AuditLog.objects.all():
            self.assertNotIn(WRONG, log.new_value)
            self.assertNotIn(PASSWORD, log.new_value)

    def test_unknown_identifier_failure_is_audited_without_a_record(self):
        self.login("nadie@example.test", WRONG)

        log = AuditLog.objects.get(action="Inicio de sesión fallido")
        self.assertIsNone(log.affected_record_id)
        self.assertIn("nadie@example.test", log.new_value)
