from django.contrib import admin
from django.contrib.auth.models import User
from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from accounts.admin import ActivityInline, OfficialAdmin, PositionAdmin
from accounts.models import Position
from activities.models import Activity


class AuthenticationFrontendRouteTests(TestCase):
    def test_login_and_recovery_request_render_without_session(self):
        routes_and_templates = (
            ("login", "registration/login.html"),
            ("recovery_request", "accounts/recovery_request.html"),
        )

        for route_name, template_name in routes_and_templates:
            with self.subTest(route=route_name):
                response = self.client.get(reverse(route_name))

                self.assertEqual(response.status_code, 200)
                self.assertTemplateUsed(response, template_name)

    def test_code_and_password_steps_require_a_recovery_in_progress(self):
        for route_name in ("recovery_code", "recovery_password"):
            with self.subTest(route=route_name):
                response = self.client.get(reverse(route_name))

                self.assertRedirects(response, reverse("recovery_request"))


class AccountMaintainerFrontendRouteTests(TestCase):
    def setUp(self):
        self.client.force_login(
            User.objects.create_superuser("admin", "admin@example.test", "Clave-Admin-1")
        )

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