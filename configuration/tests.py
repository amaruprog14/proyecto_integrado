from datetime import date

from django.core.exceptions import ValidationError
from django.test import TestCase

from configuration.admin import PeriodoAdmin
from configuration.models import Periodo


class PeriodoValidationTests(TestCase):
	def test_end_date_cannot_precede_start_date(self):
		periodo = Periodo(fecha_inicio=date(2026, 3, 2), fecha_termino=date(2026, 3, 1))

		with self.assertRaises(ValidationError) as error:
			periodo.full_clean()

		self.assertIn("fecha_termino", error.exception.message_dict)

	def test_overlapping_period_is_rejected(self):
		Periodo.objects.create(fecha_inicio=date(2026, 1, 1), fecha_termino=date(2026, 1, 31))
		periodo = Periodo(fecha_inicio=date(2026, 1, 31), fecha_termino=date(2026, 2, 28))

		with self.assertRaises(ValidationError) as error:
			periodo.full_clean()

		self.assertIn("fecha_inicio", error.exception.message_dict)

	def test_non_overlapping_period_is_allowed(self):
		Periodo.objects.create(fecha_inicio=date(2026, 1, 1), fecha_termino=date(2026, 1, 31))
		periodo = Periodo(fecha_inicio=date(2026, 2, 1), fecha_termino=date(2026, 2, 28))

		periodo.full_clean()

	def test_close_period_action_is_registered(self):
		self.assertIn("cerrar_periodos", PeriodoAdmin.actions)
