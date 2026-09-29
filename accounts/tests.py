from django.contrib import admin
from django.test import SimpleTestCase

from activities.models import Actividad
from accounts.admin import ActividadInline, CargoAdmin, FuncionarioAdmin


class AdminConfigurationTests(SimpleTestCase):
	def test_actividad_inline_is_registered_on_funcionario_admin(self):
		self.assertIn(ActividadInline, FuncionarioAdmin.inlines)
		self.assertIs(ActividadInline.model, Actividad)
		self.assertTrue(issubclass(ActividadInline, admin.TabularInline))

	def test_cargo_actions_are_registered(self):
		self.assertIn("activar_cargos", CargoAdmin.actions)
		self.assertIn("desactivar_cargos", CargoAdmin.actions)
