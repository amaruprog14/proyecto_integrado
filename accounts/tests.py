from django.contrib import admin
from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from accounts.admin import ActivityInline, OfficialAdmin, PositionAdmin
from accounts.models import Position
from activities.models import Activity


class AuthenticationFrontendRouteTests(SimpleTestCase):
    def test_login_and_recovery_pages_render_their_templates(self):
        routes_and_templates = (
            ("login", "registration/login.html"),
            ("recovery_request", "accounts/recovery_request.html"),
            ("recovery_code", "accounts/recovery_code.html"),
            ("recovery_password", "accounts/recovery_password.html"),
        )

        for route_name, template_name in routes_and_templates:
            with self.subTest(route=route_name):
                response = self.client.get(reverse(route_name))

                self.assertEqual(response.status_code, 200)
                self.assertTemplateUsed(response, template_name)

    def test_recovery_pages_explain_the_demo_scope(self):
        response = self.client.get(reverse("recovery_request"))

        self.assertContains(response, "no se envía ningún correo")
        self.assertContains(
            self.client.get(reverse("recovery_code")),
            "no se valida con un servidor",
        )
        self.assertContains(
            self.client.get(reverse("recovery_password")),
            "no se guarda ni modifica en el sistema",
        )


class AccountMaintainerFrontendRouteTests(SimpleTestCase):
    def test_c3_and_c4_account_maintainers_render_and_keep_crud_disabled(self):
        routes_and_templates = (
            ("delegation_list", "accounts/delegation_list.html"),
            ("role_list", "accounts/role_list.html"),
            ("user_maintainer", "accounts/user_list.html"),
        )

        for route_name, template_name in routes_and_templates:
            with self.subTest(route=route_name):
                response = self.client.get(reverse(route_name))

                self.assertEqual(response.status_code, 200)
                self.assertTemplateUsed(response, template_name)
                self.assertContains(response, 'id="maintainer-table"')
                self.assertContains(response, 'disabled>+ Nuevo registro</button>')
                self.assertContains(response, 'class="maintainer-actions"')


class OfficialAdminInlineTests(SimpleTestCase):
    """Inline de actividades dentro del Admin de funcionarios."""

    def test_activity_inline_is_attached_to_official_admin(self):
        self.assertIn(ActivityInline, OfficialAdmin.inlines)

    def test_activity_inline_uses_activity_model_as_tabular(self):
        self.assertIs(ActivityInline.model, Activity)
        self.assertTrue(issubclass(ActivityInline, admin.TabularInline))


class PositionActionTests(SimpleTestCase):
    """Acciones del Admin para activar y desactivar cargos."""

    def test_activate_and_deactivate_actions_are_registered(self):
        self.assertIn("activate_positions", PositionAdmin.actions)
        self.assertIn("deactivate_positions", PositionAdmin.actions)


class PositionModelTests(TestCase):
    """Métodos del modelo Position usados por las acciones."""

    def test_deactivate_position_sets_is_active_to_false(self):
        position = Position.objects.create(position_name="Analista")

        position.deactivate_position()
        position.refresh_from_db()

        self.assertFalse(position.is_active)

    def test_activate_position_sets_is_active_to_true(self):
        position = Position.objects.create(position_name="Analista", is_active=False)

        position.activate_position()
        position.refresh_from_db()

        self.assertTrue(position.is_active)