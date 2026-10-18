from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from accounts.models import Area, Delegation, Official, Position, Role


User = get_user_model()
PASSWORD = "Clave-Official-123"


class OfficialCrudTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_superuser("official.admin", "official.admin@example.test", PASSWORD)
        cls.delegation = Delegation.objects.create(
            delegation_name="Delegación Funcionarios",
            address="Calle Funcionario 1",
            commune="La Serena",
        )
        cls.area = Area.objects.create(area_name="Área Funcionarios")
        cls.position = Position.objects.create(position_name="Cargo Funcionario")
        cls.role = Role.objects.create(
            role_name="Rol Funcionario",
            scope=Role.Scope.DELEGATION,
        )

    def setUp(self):
        self.client.force_login(self.admin)

    def payload(self, **overrides):
        payload = {
            "full_name": "Funcionario Independiente",
            "national_id": "RUT-OFFICIAL-1",
            "email": "funcionario.independiente@example.test",
            "phone": "+56912345678",
            "area": self.area.pk,
            "position": self.position.pk,
            "delegation": self.delegation.pk,
            "authorized_delegations": [self.delegation.pk],
            "roles": [self.role.pk],
            "status": Official.Status.ACTIVE,
        }
        payload.update(overrides)
        return payload

    def test_create_official_without_account(self):
        response = self.client.post(reverse("official_create"), self.payload(), follow=True)

        self.assertEqual(response.status_code, 200)
        official = Official.objects.get(national_id="RUT-OFFICIAL-1")
        self.assertIsNone(official.user)
        self.assertEqual(list(official.authorized_delegations.all()), [])
        self.assertEqual(list(official.roles.all()), [self.role])
        self.assertContains(response, "fue creado correctamente")

    def test_create_official_with_account_is_atomic_and_linked(self):
        response = self.client.post(
            reverse("official_create"),
            self.payload(
                full_name="Funcionario Con Cuenta",
                national_id="RUT-OFFICIAL-2",
                email="funcionario.cuenta@example.test",
                create_account="on",
                username="funcionario.cuenta",
                first_name="Funcionario",
                last_name="Cuenta",
                password1=PASSWORD,
                password2=PASSWORD,
            ),
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        official = Official.objects.get(national_id="RUT-OFFICIAL-2")
        user = User.objects.get(username="funcionario.cuenta")
        self.assertEqual(official.user_id, user.pk)
        self.assertTrue(user.check_password(PASSWORD))
        self.assertContains(response, "fue creado correctamente")

    def test_create_account_requires_credentials(self):
        response = self.client.post(
            reverse("official_create"),
            self.payload(
                create_account="on",
                username="sin.clave.official",
                password1="",
                password2="",
            ),
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Ingresa una contraseña para la nueva cuenta")
        self.assertFalse(Official.objects.filter(national_id="RUT-OFFICIAL-1").exists())
        self.assertFalse(User.objects.filter(username="sin.clave.official").exists())

    def test_edit_official_keeps_linked_user_credentials(self):
        user = User.objects.create_user("cuenta.vinculada", "cuenta@example.test", PASSWORD)
        official = Official.objects.create(
            user=user,
            full_name="Nombre Original",
            national_id="RUT-OFFICIAL-3",
            email="original@example.test",
            delegation=self.delegation,
        )

        response = self.client.post(
            reverse("official_update", args=[official.pk]),
            self.payload(
                full_name="Nombre Editado",
                national_id="RUT-OFFICIAL-3",
                email="editado@example.test",
            ),
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        official.refresh_from_db()
        user.refresh_from_db()
        self.assertEqual(official.full_name, "Nombre Editado")
        self.assertEqual(official.user_id, user.pk)
        self.assertEqual(user.username, "cuenta.vinculada")
        self.assertTrue(user.check_password(PASSWORD))

    def test_official_list_exposes_create_and_edit_actions(self):
        official = Official.objects.create(
            full_name="Visible en tabla",
            national_id="RUT-OFFICIAL-4",
            email="visible@example.test",
            delegation=self.delegation,
        )

        response = self.client.get(reverse("official_maintainer"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, f'href="{reverse("official_create")}"')
        self.assertContains(response, f'href="{reverse("official_update", args=[official.pk])}"')
