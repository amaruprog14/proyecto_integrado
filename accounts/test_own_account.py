"""
Cuenta propia con la sesión iniciada: cambio de contraseña (funcionario y cliente) con bloqueo
por intentos con la contraseña actual incorrecta, y edición de nombre y correo en el perfil,
sincronizados con el User.
"""

from django.contrib.auth import SESSION_KEY, get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from accounts import login_security
from accounts.models import Official, ServiceRecipient
from configuration.models import AuditLog

User = get_user_model()
PASSWORD = "Clave-Actual-1"
NEW_PASSWORD = "Clave-Nueva-2"


def create_official(username, email, full_name="Ana Rojas"):
    user = User.objects.create_user(username, email, PASSWORD, first_name="Ana", last_name="Rojas")
    Official.objects.create(user=user, full_name=full_name, national_id=f"{username}-1", email=email)
    return user


def create_client(username, email, rut, first_name="Carla", last_name="Díaz"):
    user = User.objects.create_user(username, email, PASSWORD, first_name=first_name, last_name=last_name)
    ServiceRecipient.objects.create(user=user, full_name=f"{first_name} {last_name}", national_id=rut, email=email)
    return user


@override_settings(LOGIN_MAX_FAILED_ATTEMPTS=3)
class PasswordChangeTests(TestCase):
    def setUp(self):
        self.user = create_official("ana.rojas", "ana.rojas@example.test")
        self.client.force_login(self.user)
        self.url = reverse("password_change")

    def change(self, old=PASSWORD, new1=NEW_PASSWORD, new2=None):
        return self.client.post(self.url, {
            "old_password": old, "new_password1": new1, "new_password2": new2 or new1,
        })

    def test_anonymous_user_is_sent_to_login(self):
        self.client.logout()

        response = self.client.get(self.url)

        self.assertRedirects(response, f"{reverse('login')}?next={self.url}")

    def test_form_renders_from_the_profile(self):
        self.assertContains(self.client.get(reverse("my_profile")), f'href="{self.url}"')
        response = self.client.get(self.url)

        self.assertTemplateUsed(response, "accounts/password_change.html")
        self.assertContains(response, 'name="old_password"')

    def test_wrong_current_password_is_rejected_and_audited(self):
        response = self.change(old="Clave-Incorrecta-1")

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["form"].has_error("old_password", "password_incorrect"))
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password(PASSWORD))
        log = AuditLog.objects.get(action="Cambio de contraseña fallido")
        self.assertEqual(log.affected_record_id, self.user.pk)
        self.assertNotIn("Clave-Incorrecta-1", f"{log.previous_value}{log.new_value}")

    def test_new_password_must_pass_the_validators_and_match(self):
        for label, (new1, new2) in {
            "débil": ("clave", None),
            "sin mayúscula": ("clave-nueva-2", None),
            "igual al usuario": ("Ana.Rojas-1", None),
            "confirmación distinta": (NEW_PASSWORD, "Clave-Nueva-3"),
        }.items():
            with self.subTest(label):
                response = self.change(new1=new1, new2=new2)

                self.assertEqual(response.status_code, 200)
                self.assertTrue(response.context["form"].errors)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password(PASSWORD))

    def test_valid_change_keeps_the_session_and_is_audited(self):
        response = self.change()

        self.assertRedirects(response, reverse("my_profile"))
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password(NEW_PASSWORD))
        # La sesión sigue siendo válida: update_session_auth_hash guardó el nuevo hash.
        self.assertEqual(self.client.get(reverse("my_profile")).status_code, 200)
        self.assertEqual(int(self.client.session[SESSION_KEY]), self.user.pk)
        log = AuditLog.objects.get(action="Cambio de contraseña")
        self.assertEqual(log.affected_record_id, self.user.pk)
        self.assertNotIn(NEW_PASSWORD, f"{log.previous_value}{log.new_value}")

    def test_other_sessions_are_closed_after_the_change(self):
        other_device = self.client_class()
        other_device.force_login(self.user)

        self.change()

        self.assertRedirects(other_device.get(reverse("my_profile")), f"{reverse('login')}?next={reverse('my_profile')}")

    def test_repeated_wrong_current_passwords_lock_the_account_like_the_login(self):
        for _ in range(3):
            self.change(old="Clave-Incorrecta-1")
        key = login_security.throttle_key("", self.user)
        self.assertTrue(login_security.is_locked(key))
        self.assertTrue(AuditLog.objects.filter(action="Bloqueo temporal de inicio de sesión").exists())

        response = self.change()  # contraseña actual correcta, pero durante el bloqueo

        self.assertContains(response, "Demasiados intentos fallidos")
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password(PASSWORD))
        self.client.logout()
        self.assertFalse(self.client.login(username="ana.rojas", password=PASSWORD))

    def test_client_changes_the_password_from_the_portal(self):
        client = create_client("carla.diaz", "carla@example.test", "12.345.678-5")
        self.client.force_login(client)
        self.assertContains(self.client.get(reverse("client_profile")), f'href="{self.url}"')

        response = self.change()

        self.assertRedirects(response, reverse("client_profile"))
        client.refresh_from_db()
        self.assertTrue(client.check_password(NEW_PASSWORD))
        self.assertEqual(self.client.get(reverse("client_requests")).status_code, 200)


class OwnNameEditTests(TestCase):
    def setUp(self):
        self.user = create_official("ana.rojas", "ana.rojas@example.test")
        self.official = self.user.official
        self.client.force_login(self.user)

    def post_profile(self, url_name="my_profile", **data):
        payload = {"first_name": "Ana", "last_name": "Rojas", "email": "ana.rojas@example.test", "phone": ""}
        payload.update(data)
        return self.client.post(reverse(url_name), payload)

    def test_name_and_email_are_saved_in_the_profile_and_the_user(self):
        response = self.post_profile(
            first_name="  María   José ", last_name="O'Ryan-Pérez", email="mj.oryan@example.test"
        )

        self.assertRedirects(response, reverse("my_profile"))
        self.official.refresh_from_db()
        self.user.refresh_from_db()
        self.assertEqual(self.official.full_name, "María José O'Ryan-Pérez")
        self.assertEqual(self.official.email, "mj.oryan@example.test")
        self.assertEqual(
            (self.user.first_name, self.user.last_name, self.user.email),
            ("María José", "O'Ryan-Pérez", "mj.oryan@example.test"),
        )
        log = AuditLog.objects.get(action="Actualización del perfil propio")
        self.assertIn("Nombre: Ana Rojas", log.previous_value)
        self.assertIn("Nombre: María José O'Ryan-Pérez", log.new_value)

    def test_abbreviations_ñ_and_tildes_are_accepted(self):
        self.post_profile(first_name="Ma. Ñuñoa", last_name="Muñoz Jr.")

        self.official.refresh_from_db()
        self.assertEqual(self.official.full_name, "Ma. Ñuñoa Muñoz Jr.")

    def test_invalid_names_are_rejected_without_saving(self):
        cases = {
            "con dígitos": {"first_name": "Ana 2"},
            "con símbolos": {"last_name": "<b>Rojas</b>"},
            "guion bajo": {"first_name": "Ana_María"},
            "vacío": {"last_name": "   "},
            "muy largo en total": {"first_name": "A" * 120, "last_name": "B" * 100},
        }
        for label, data in cases.items():
            with self.subTest(label):
                response = self.post_profile(**data)

                self.assertEqual(response.status_code, 200)
                self.assertTrue(response.context["form"].errors)
        self.official.refresh_from_db()
        self.user.refresh_from_db()
        self.assertEqual(self.official.full_name, "Ana Rojas")
        self.assertEqual((self.user.first_name, self.user.last_name), ("Ana", "Rojas"))

    def test_email_of_another_account_is_rejected(self):
        User.objects.create_user("otra.cuenta", "otra@example.test", PASSWORD)

        response = self.post_profile(email="OTRA@example.test")

        self.assertIn("email", response.context["form"].errors)
        self.user.refresh_from_db()
        self.assertEqual(self.user.email, "ana.rojas@example.test")

    def test_client_edits_its_own_name_but_never_another_clients_data(self):
        own = create_client("carla.diaz", "carla@example.test", "12.345.678-5")
        other = create_client("pedro.soto", "pedro@example.test", "11.111.111-1", "Pedro", "Soto")
        self.client.force_login(own)

        response = self.post_profile(
            "client_profile", first_name="Carla Andrea", last_name="Díaz", email="carla.andrea@example.test",
            # Identificadores ajenos o de solo lectura: se ignoran.
            pk=other.service_recipient.pk, user=other.pk, recipient=other.service_recipient.pk,
            national_id="11.111.111-1", full_name="Pedro Soto Modificado", status="INACTIVE",
        )

        self.assertRedirects(response, reverse("client_profile"))
        own.refresh_from_db()
        other.refresh_from_db()
        own_profile, other_profile = own.service_recipient, other.service_recipient
        own_profile.refresh_from_db()
        other_profile.refresh_from_db()
        self.assertEqual(own_profile.full_name, "Carla Andrea Díaz")
        self.assertEqual((own.first_name, own.email), ("Carla Andrea", "carla.andrea@example.test"))
        self.assertEqual(own_profile.national_id, "12.345.678-5")
        self.assertEqual(own_profile.status, ServiceRecipient.Status.ACTIVE)
        self.assertEqual(
            (other_profile.full_name, other_profile.email, other.first_name, other.email),
            ("Pedro Soto", "pedro@example.test", "Pedro", "pedro@example.test"),
        )

    def test_client_cannot_take_the_email_of_another_client(self):
        own = create_client("carla.diaz", "carla@example.test", "12.345.678-5")
        create_client("pedro.soto", "pedro@example.test", "11.111.111-1", "Pedro", "Soto")
        self.client.force_login(own)

        response = self.post_profile("client_profile", first_name="Carla", last_name="Díaz", email="pedro@example.test")

        self.assertIn("email", response.context["form"].errors)
