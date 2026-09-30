from django.contrib import admin
from django.test import SimpleTestCase, TestCase

from accounts.admin import ActivityInline, OfficialAdmin, PositionAdmin
from accounts.models import Position
from activities.models import Activity


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