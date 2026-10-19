from io import BytesIO

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import TestCase
from django.urls import reverse
from openpyxl import load_workbook

from accounts.delegation_context import ACTIVE_DELEGATION_SESSION_KEY
from accounts.models import Delegation, Official

User = get_user_model()


class ActiveDelegationContextTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.first = Delegation.objects.create(
            delegation_name="Delegación Centro",
            address="Calle Uno",
            commune="La Serena",
        )
        cls.second = Delegation.objects.create(
            delegation_name="Delegación Norte",
            address="Calle Dos",
            commune="La Serena",
        )
        cls.user = User.objects.create_superuser(
            "context.admin", "context.admin@example.test", "Clave-Admin-1"
        )
        Official.objects.create(
            user=cls.user,
            full_name="Administrador de contexto",
            national_id="RUT-CONTEXT-ADMIN",
            email="context.official@example.test",
            delegation=cls.first,
        )

    def setUp(self):
        self.client.force_login(self.user)

    def test_context_defaults_to_the_officials_authorized_primary_delegation(self):
        response = self.client.get(reverse("delegation_list"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.first.delegation_name)
        self.assertContains(response, 'id="active-delegation-select"')
        self.assertEqual(
            self.client.session[ACTIVE_DELEGATION_SESSION_KEY], self.first.pk
        )

    def test_user_can_select_an_authorized_delegation_in_session(self):
        response = self.client.post(
            reverse("active_delegation_select"),
            {"delegation_id": self.second.pk, "next": reverse("delegation_list")},
        )

        self.assertRedirects(response, reverse("delegation_list"))
        self.assertEqual(
            self.client.session[ACTIVE_DELEGATION_SESSION_KEY], self.second.pk
        )
        self.assertContains(
            self.client.get(reverse("delegation_list")),
            self.second.delegation_name,
        )

    def test_inactive_or_unauthorized_selection_does_not_change_session(self):
        self.client.post(
            reverse("active_delegation_select"),
            {"delegation_id": self.first.pk, "next": reverse("delegation_list")},
        )
        self.second.deactivate()

        response = self.client.post(
            reverse("active_delegation_select"),
            {"delegation_id": self.second.pk, "next": reverse("delegation_list")},
            follow=True,
        )

        self.assertEqual(
            self.client.session[ACTIVE_DELEGATION_SESSION_KEY], self.first.pk
        )
        self.assertContains(response, "No tienes autorización")

    def test_inactive_session_selection_is_cleared_and_replaced(self):
        self.client.post(
            reverse("active_delegation_select"),
            {"delegation_id": self.second.pk, "next": reverse("delegation_list")},
        )
        self.second.deactivate()

        self.client.get(reverse("delegation_list"))

        self.assertEqual(
            self.client.session[ACTIVE_DELEGATION_SESSION_KEY], self.first.pk
        )

    def test_single_delegation_does_not_render_selector(self):
        user = User.objects.create_user(
            "single.context", "single.context@example.test", "Clave-Admin-1"
        )
        Official.objects.create(
            user=user,
            full_name="Funcionario de una delegación",
            national_id="RUT-CONTEXT-SINGLE",
            email="single.official@example.test",
            delegation=self.first,
        )
        permission = Permission.objects.get(
            content_type__app_label="accounts", codename="view_delegation"
        )
        user.user_permissions.add(permission)
        self.client.force_login(user)

        response = self.client.get(reverse("delegation_list"))

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'id="active-delegation-select"')
        self.assertEqual(
            self.client.session[ACTIVE_DELEGATION_SESSION_KEY], self.first.pk
        )

    def test_user_cannot_select_an_active_but_unauthorized_delegation(self):
        user = User.objects.create_user(
            "limited.context", "limited.context@example.test", "Clave-Admin-1"
        )
        Official.objects.create(
            user=user,
            full_name="Funcionario con alcance limitado",
            national_id="RUT-CONTEXT-LIMITED",
            email="limited.official@example.test",
            delegation=self.first,
        )
        permission = Permission.objects.get(
            content_type__app_label="accounts", codename="view_delegation"
        )
        user.user_permissions.add(permission)
        self.client.force_login(user)
        self.client.get(reverse("delegation_list"))

        response = self.client.post(
            reverse("active_delegation_select"),
            {"delegation_id": self.second.pk, "next": reverse("delegation_list")},
            follow=True,
        )

        self.assertEqual(
            self.client.session[ACTIVE_DELEGATION_SESSION_KEY], self.first.pk
        )
        self.assertContains(response, "No tienes autorización")

    def test_user_list_and_export_follow_the_selected_delegation(self):
        first_user = User.objects.create_user(
            "first.delegation", "first.delegation@example.test", "Clave-Admin-1"
        )
        Official.objects.create(
            user=first_user,
            full_name="Funcionario Centro",
            national_id="RUT-CONTEXT-CENTRO",
            email="first.official@example.test",
            delegation=self.first,
        )
        second_user = User.objects.create_user(
            "second.delegation", "second.delegation@example.test", "Clave-Admin-1"
        )
        Official.objects.create(
            user=second_user,
            full_name="Funcionario Norte",
            national_id="RUT-CONTEXT-NORTE",
            email="second.official@example.test",
            delegation=self.second,
        )
        self.client.post(
            reverse("active_delegation_select"),
            {"delegation_id": self.second.pk, "next": reverse("user_maintainer")},
        )

        response = self.client.get(reverse("user_maintainer"))
        usernames = [user.username for user in response.context["users"]]
        export_response = self.client.get(reverse("user_export"))
        exported_rows = list(
            load_workbook(BytesIO(export_response.content), read_only=True).active.values
        )

        self.assertIn("second.delegation", usernames)
        self.assertNotIn("first.delegation", usernames)
        self.assertIn("second.delegation", str(exported_rows))
        self.assertNotIn("first.delegation", str(exported_rows))

    def test_user_creation_uses_active_primary_but_keeps_all_authorized_choices(self):
        self.client.post(
            reverse("active_delegation_select"),
            {"delegation_id": self.second.pk, "next": reverse("user_create")},
        )

        response = self.client.get(reverse("user_create"))
        form = response.context["form"]

        self.assertEqual(
            list(form.fields["delegation"].queryset), [self.second]
        )
        self.assertEqual(
            set(form.fields["authorized_delegations"].queryset),
            {self.first, self.second},
        )
