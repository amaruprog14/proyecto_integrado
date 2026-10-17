from datetime import date

from django.core.exceptions import ValidationError
from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from configuration.admin import PeriodAdmin
from configuration.models import Period


class ConfigurationFrontendRouteTests(SimpleTestCase):
    def test_c4_and_c5_catalogue_routes_render_their_templates(self):
        routes_and_templates = (
            ("item_maintainer", "configuration/item_list.html", "Ítems y metas"),
            (
                "attention_type_maintainer",
                "configuration/attention_type_list.html",
                "Tipos de Atención",
            ),
            (
                "subattention_type_maintainer",
                "configuration/subattention_type_list.html",
                "Tipo asociado",
            ),
            ("period_maintainer", "configuration/period_list.html", "Períodos"),
        )

        for route_name, template_name, expected_content in routes_and_templates:
            with self.subTest(route=route_name):
                response = self.client.get(reverse(route_name))

                self.assertEqual(response.status_code, 200)
                self.assertTemplateUsed(response, template_name)
                self.assertContains(response, expected_content)
                self.assertContains(response, 'id="maintainer-table"')

    def test_catalogue_crud_actions_remain_disabled(self):
        response = self.client.get(reverse("attention_type_maintainer"))

        self.assertContains(response, 'disabled>+ Nuevo registro</button>')
        self.assertContains(response, '<button type="button" disabled>Ver</button>')
        self.assertContains(response, '<button type="button" disabled>Editar</button>')
        self.assertContains(response, '<button type="button" disabled>Eliminar</button>')


class PeriodValidationTests(TestCase):
    """Validación Period.clean(): fechas coherentes y sin solapamientos."""

    def test_period_end_date_before_start_date_is_rejected(self):
        period = Period(start_date=date(2026, 3, 2), end_date=date(2026, 3, 1))

        with self.assertRaises(ValidationError) as error:
            period.full_clean()

        self.assertIn("end_date", error.exception.message_dict)

    def test_period_overlapping_existing_one_is_rejected(self):
        Period.objects.create(start_date=date(2026, 1, 1), end_date=date(2026, 1, 31))
        period = Period(start_date=date(2026, 1, 31), end_date=date(2026, 2, 28))

        with self.assertRaises(ValidationError) as error:
            period.full_clean()

        self.assertIn("start_date", error.exception.message_dict)

    def test_period_consecutive_to_existing_one_is_accepted(self):
        Period.objects.create(start_date=date(2026, 1, 1), end_date=date(2026, 1, 31))
        period = Period(start_date=date(2026, 2, 1), end_date=date(2026, 2, 28))

        period.full_clean()  


class PeriodActionTests(TestCase):
    """Acción del Admin 'Cerrar períodos seleccionados' y el método que usa."""

    def test_close_periods_action_is_registered_in_period_admin(self):
        self.assertIn("close_periods", PeriodAdmin.actions)

    def test_close_period_sets_status_to_closed(self):
        period = Period.objects.create(start_date=date(2026, 1, 1), end_date=date(2026, 1, 31))

        period.close_period()
        period.refresh_from_db()

        self.assertEqual(period.status, Period.Status.CLOSED)