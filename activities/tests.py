from datetime import date

from django.contrib.auth.models import Permission, User
from django.test import TestCase
from django.urls import reverse

from accounts.models import Area, Official, Position
from configuration.models import Item
from .models import Activity


class ActivityAdminScopingTests(TestCase):
	def setUp(self):
		self.north_area = Area.objects.create(area_name="Área Norte")
		self.south_area = Area.objects.create(area_name="Área Sur")
		position = Position.objects.create(position_name="Analista")
		item = Item.objects.create(item_name="Atención ciudadana")

		activity_permissions = {
			"north_user": ("view_activity", "add_activity", "change_activity"),
			"south_user": ("view_activity", "add_activity", "change_activity"),
			"consulta_norte": ("view_activity",),
		}
		users = {
			username: self._create_user(username, codenames)
			for username, codenames in activity_permissions.items()
		}

		north_official = Official.objects.create(
			user=users["north_user"],
			area=self.north_area,
			position=position,
			full_name="Funcionario Norte",
			national_id="11111111-1",
			email="norte@example.test",
		)
		south_official = Official.objects.create(
			user=users["south_user"],
			area=self.south_area,
			position=position,
			full_name="Funcionario Sur",
			national_id="22222222-2",
			email="sur@example.test",
		)
		Official.objects.create(
			user=users["consulta_norte"],
			area=self.north_area,
			position=position,
			full_name="Usuario Consulta Norte",
			national_id="33333333-3",
			email="consulta@example.test",
		)

		self.north_activity = Activity.objects.create(
			official=north_official,
			item=item,
			date=date(2026, 1, 1),
			record_type="Registro",
			action_description="Actividad Norte",
		)
		self.south_activity = Activity.objects.create(
			official=south_official,
			item=item,
			date=date(2026, 1, 2),
			record_type="Registro",
			action_description="Actividad Sur",
		)

	def _create_user(self, username, permission_codenames):
		user = User.objects.create_user(
			username=username,
			password="test-password",
			is_staff=True,
		)
		permissions = Permission.objects.filter(
			content_type__app_label="activities",
			codename__in=permission_codenames,
		)
		user.user_permissions.add(*permissions)
		return user

	def test_each_user_only_sees_activities_from_own_area(self):
		expected_activities = {
			"north_user": [self.north_activity.pk],
			"south_user": [self.south_activity.pk],
			"consulta_norte": [self.north_activity.pk],
		}

		for username, expected_ids in expected_activities.items():
			with self.subTest(username=username):
				self.client.force_login(User.objects.get(username=username))
				response = self.client.get(reverse("admin:activities_activity_changelist"))

				self.assertEqual(response.status_code, 200)
				actual_ids = [activity.pk for activity in response.context["cl"].result_list]
				self.assertEqual(actual_ids, expected_ids)

	def test_north_user_cannot_open_south_activity_directly(self):
		self.client.force_login(User.objects.get(username="north_user"))
		response = self.client.get(
			reverse("admin:activities_activity_change", args=[self.south_activity.pk])
		)

		self.assertIn(response.status_code, (302, 403, 404))

	def test_consulta_user_cannot_add_or_change_activities(self):
		self.client.force_login(User.objects.get(username="consulta_norte"))

		add_response = self.client.get(reverse("admin:activities_activity_add"))
		change_response = self.client.post(
			reverse("admin:activities_activity_change", args=[self.north_activity.pk]),
			{"action_description": "Intento de modificación", "_save": "Guardar"},
		)
		self.client.post(
			reverse("admin:activities_activity_changelist"),
			{
				"action": "archive_activities",
				"_selected_action": [self.north_activity.pk],
				"index": 0,
			},
		)

		self.assertEqual(add_response.status_code, 403)
		self.assertEqual(change_response.status_code, 403)
		self.north_activity.refresh_from_db()
		self.assertEqual(self.north_activity.action_description, "Actividad Norte")
		self.assertIsNone(self.north_activity.deleted_at)
