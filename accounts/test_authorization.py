from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import TestCase
from django.urls import reverse

from accounts.models import Delegation, Official, Role
from configuration.models import AuditLog


User = get_user_model()
PASSWORD = "Clave-Autorizacion-123"


def grant_permissions(user, *codenames):
    for value in codenames:
        app_label, codename = value.split(".")
        user.user_permissions.add(
            Permission.objects.get(content_type__app_label=app_label, codename=codename)
        )


class OwnProfileAuthorizationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.delegation = Delegation.objects.create(
            delegation_name="Delegación Perfil Propio",
            address="Calle Perfil 1",
            commune="La Serena",
        )
        cls.user = User.objects.create_user("perfil.propio", "perfil@example.test", PASSWORD)
        cls.official = Official.objects.create(
            user=cls.user,
            full_name="Perfil Propio",
            national_id="RUT-PERFIL-PROPIO",
            email="contacto@example.test",
            phone="111111111",
            delegation=cls.delegation,
        )

    def setUp(self):
        self.client.force_login(self.user)

    def test_own_profile_updates_only_personal_contact_fields(self):
        response = self.client.post(
            reverse("my_profile"),
            {
                "email": "nuevo.contacto@example.test",
                "phone": "222222222",
                "full_name": "Intento de elevación",
                "status": Official.Status.SUSPENDED,
                "delegation": "",
            },
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        self.official.refresh_from_db()
        self.user.refresh_from_db()
        self.assertEqual(self.official.email, "nuevo.contacto@example.test")
        self.assertEqual(self.official.phone, "222222222")
        self.assertEqual(self.official.full_name, "Perfil Propio")
        self.assertEqual(self.official.status, Official.Status.ACTIVE)
        self.assertEqual(self.official.delegation_id, self.delegation.pk)
        self.assertEqual(self.user.email, "perfil@example.test")

    def test_own_profile_is_unavailable_without_official(self):
        account = User.objects.create_user("sin.perfil", "sinperfil@example.test", PASSWORD)
        self.client.force_login(account)

        self.assertEqual(self.client.get(reverse("my_profile")).status_code, 403)

    def test_own_official_admin_url_requires_administrative_permission(self):
        response = self.client.get(reverse("official_update", args=[self.official.pk]))

        self.assertEqual(response.status_code, 403)

    def test_admin_state_action_cannot_change_own_account(self):
        response = self.client.post(
            reverse("user_activate", args=[self.user.pk]), follow=True
        )

        self.assertEqual(response.status_code, 403)
        self.user.refresh_from_db()
        self.assertTrue(self.user.is_active)


class AdministrativeAuthorizationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.own = Delegation.objects.create(
            delegation_name="Delegación Admin Propia",
            address="Calle Admin 1",
            commune="La Serena",
        )
        cls.foreign = Delegation.objects.create(
            delegation_name="Delegación Admin Ajena",
            address="Calle Admin 2",
            commune="La Serena",
        )
        cls.manager = User.objects.create_user("gestor.seguridad", "gestor@example.test", PASSWORD)
        Official.objects.create(
            user=cls.manager,
            full_name="Gestor Seguridad",
            national_id="RUT-GESTOR-SEG",
            email="gestor@example.test",
            delegation=cls.own,
        )
        grant_permissions(
            cls.manager,
            "accounts.view_official",
            "accounts.change_official",
            "auth.view_user",
            "auth.change_user",
        )
        cls.foreign_user = User.objects.create_user(
            "usuario.ajeno", "ajeno@example.test", PASSWORD
        )
        cls.foreign_official = Official.objects.create(
            user=cls.foreign_user,
            full_name="Usuario Ajeno",
            national_id="RUT-AJENO-SEG",
            email="ajeno@example.test",
            delegation=cls.foreign,
        )

    def setUp(self):
        self.client.force_login(self.manager)

    def test_foreign_official_cannot_be_edited_by_changing_url_id(self):
        response = self.client.post(
            reverse("official_update", args=[self.foreign_official.pk]),
            {"full_name": "Cambio no autorizado"},
        )

        self.assertEqual(response.status_code, 404)
        self.foreign_official.refresh_from_db()
        self.assertEqual(self.foreign_official.full_name, "Usuario Ajeno")

    def test_foreign_user_cannot_be_activated_or_deactivated(self):
        deactivate = self.client.post(
            reverse("user_deactivate", args=[self.foreign_user.pk])
        )
        activate = self.client.post(
            reverse("user_activate", args=[self.foreign_user.pk])
        )

        self.assertEqual(deactivate.status_code, 404)
        self.assertEqual(activate.status_code, 404)
        self.foreign_user.refresh_from_db()
        self.assertTrue(self.foreign_user.is_active)

    def test_authorized_manager_cannot_change_own_account_state(self):
        response = self.client.post(
            reverse("user_activate", args=[self.manager.pk]), follow=True
        )

        self.assertEqual(response.status_code, 200)
        self.manager.refresh_from_db()
        self.assertTrue(self.manager.is_active)
        self.assertContains(response, "No puedes cambiar el estado de tu propia cuenta")

    def test_role_privilege_is_not_assignable_without_role_permission(self):
        role = Role.objects.create(
            role_name="Rol Administrativo No Autorizado",
            scope=Role.Scope.ALL,
        )
        role.permissions.add(
            Permission.objects.get(content_type__app_label="auth", codename="change_user")
        )
        target = User.objects.create_user("usuario.propia", "propia@example.test", PASSWORD)
        official = Official.objects.create(
            user=target,
            full_name="Usuario Propio",
            national_id="RUT-PROPIA-SEG",
            email="propia@example.test",
            delegation=self.own,
        )

        response = self.client.post(
            reverse("user_update", args=[target.pk]),
            {
                "username": target.username,
                "email": target.email,
                "password1": "",
                "password2": "",
                "full_name": official.full_name,
                "national_id": official.national_id,
                "status": Official.Status.ACTIVE,
                "delegation": self.own.pk,
                "roles": [role.pk],
            },
        )

        # Igual que Roles: 403 y registro en la auditoría (SEG-02).
        self.assertEqual(response.status_code, 403)
        official.refresh_from_db()
        self.assertFalse(official.roles.filter(pk=role.pk).exists())
        log = AuditLog.objects.get(action="Acceso denegado")
        self.assertIn("accounts.change_role", log.new_value)
