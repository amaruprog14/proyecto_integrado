from datetime import timedelta

from django.contrib.auth.models import Permission, User
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.models import Function, Official, Position, Role
from accounts.role_forms import is_global_administrator
from activities.models import Activity, SocialAttention
from activities.test_case_follow_up import CaseFixture
from analytics.measurement import activity_measurement
from analytics.models import MeasurementItem
from configuration.models import AuditLog, Item, Period


@override_settings(PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"])
class MeasurementConfigurationTests(CaseFixture, TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.create_fixture()
        cls.admin = User.objects.create_superuser("admin-medicion", password="Prueba-1234")
        cls.position = Position.objects.create(position_name="Gestor Social")
        cls.other_position = Position.objects.create(position_name="Apoyo Administrativo")
        cls.official.position = cls.position
        cls.official.save(update_fields=["position"])
        cls.function = Function.objects.create(function_name="Seguimiento social")
        cls.function.positions.add(cls.position, cls.other_position)
        cls.period = Period.objects.get()
        cls.item = Item.objects.create(item_name="Visitas sociales")
        cls.other_item = Item.objects.create(item_name="Entrega de informes")
        cls.staff.user_permissions.add(Permission.objects.get(codename="change_activity"))

    def setUp(self):
        super().setUp()
        self.management = Client()
        self.management.force_login(self.admin)

    def write(self, name, *args, **data):
        return self.management.post(reverse(name, args=args), data, HTTP_X_MODAL_REQUEST="true")

    def new_plan(self, position=None):
        position = position or self.position
        self.assertEqual(self.write("measurement_plan_create", self.period.pk, position=position.pk).status_code, 204)
        plan = self.period.measurement_plans.get(position=position)
        return plan, plan.versions.get()

    def add_item(self, version, item, weight, goal="10"):
        response = self.write("measurement_item_create", self.period.pk, version.plan_id, version.pk,
                              function=self.function.pk, item=item.pk, goal_type="QUANTITY", goal=goal, weight=weight)
        self.assertEqual(response.status_code, 204)
        return version.items.get(item=item)

    def publish(self, version):
        return self.write("measurement_version_publish", self.period.pk, version.plan_id, version.pk)

    def activity_data(self, **changes):
        return {
            "official": self.official.pk, "date": self.period.end_date.isoformat(), "item": self.item.pk,
            "record_type": Activity.RecordType.FIELD, "action_description": "Registro de prueba",
            **changes,
        }

    def test_maintainers_and_publication_validate_base_and_inherited_weights(self):
        form_url = reverse("function_create")
        self.assertEqual(self.management.post(form_url, {
            "function_name": "Atención territorial", "positions": [self.position.pk], "is_active": "True",
        }, HTTP_X_MODAL_REQUEST="true").status_code, 204)
        function = Function.objects.get(function_name="Atención territorial")
        self.assertEqual(list(function.positions.all()), [self.position])
        self.assertContains(self.management.get(reverse("function_maintainer")), function.function_name)
        self.assertEqual(self.write("function_deactivate", function.pk).status_code, 204)
        function.refresh_from_db()
        self.assertFalse(function.is_active)
        self.assertEqual(list(function.positions.all()), [self.position])
        self.assertContains(self.management.get(reverse("period_detail", args=[self.period.pk])), "Configuración de medición")

        plan, version = self.new_plan()
        self.assertContains(self.management.get(reverse("measurement_plan_list", args=[self.period.pk])), self.position.position_name)
        line = self.add_item(version, self.item, "85")
        self.assertContains(self.publish(version), "Deben sumar 100 %.")
        version.refresh_from_db()
        self.assertFalse(version.is_published)
        self.add_item(version, self.other_item, "15")

        self.assertEqual(self.write("measurement_adjustment_create", self.period.pk, plan.pk, version.pk, line.pk,
                                   official=self.official.pk, weight="70", goal="20").status_code, 204)
        self.assertContains(self.publish(version), self.official.full_name)
        adjustment = line.adjustments.get()
        self.assertEqual(self.write("measurement_adjustment_edit", self.period.pk, plan.pk, version.pk, line.pk,
                                   adjustment.pk, official=self.official.pk, weight="", goal="20").status_code, 204)
        self.assertEqual(self.publish(version).status_code, 204)
        self.assertEqual(self.write("measurement_item_remove", self.period.pk, plan.pk, version.pk, line.pk).status_code, 404)
        detail = self.management.get(reverse("measurement_plan_detail", args=[self.period.pk, plan.pk]))
        self.assertContains(detail, "Publicada")
        self.assertContains(detail, self.official.full_name)
        activity = Activity.objects.create(official=self.official, item=self.item, date=self.period.start_date,
                                           record_type=Activity.RecordType.FIELD)
        measurement = activity_measurement(activity)
        self.assertEqual(measurement["goal"], 20)
        self.assertEqual(measurement["weight"], 85)
        event = AuditLog.objects.get(action="Publicación de plan de medición", affected_record_id=version.pk)
        self.assertIn(self.admin.username, event.new_value)

    def test_revision_applies_to_existing_activities_by_effective_date(self):
        plan, version = self.new_plan()
        self.add_item(version, self.item, "100")
        self.assertEqual(self.publish(version).status_code, 204)
        before = Activity.objects.create(official=self.official, item=self.item, date=self.period.start_date,
                                         record_type=Activity.RecordType.FIELD)
        after = Activity.objects.create(official=self.official, item=self.item, date=self.period.end_date,
                                        record_type=Activity.RecordType.FIELD)
        self.assertEqual(self.write("measurement_revision_create", self.period.pk, plan.pk,
                                    effective_from=self.period.end_date.isoformat()).status_code, 204)
        revision = plan.versions.get(number=2)
        line = revision.items.get()
        self.assertEqual(self.write("measurement_item_edit", self.period.pk, plan.pk, revision.pk, line.pk,
                                   function=self.function.pk, item=self.other_item.pk, goal_type="PERCENTAGE",
                                   weight="100", goal="80").status_code, 204)
        self.assertEqual(self.publish(revision).status_code, 204)
        self.assertEqual(activity_measurement(before)["version"], version)
        self.assertEqual(activity_measurement(after)["version"], revision)
        self.assertTrue(activity_measurement(after)["excluded"])
        edit = reverse("activity_update", args=[after.pk])
        self.assertContains(
            self.client.post(edit, self.activity_data(date=self.period.start_date.isoformat(), item=self.other_item.pk)),
            "Elige un ítem disponible",
        )
        self.assertEqual(self.client.post(
            edit, self.activity_data(action_description="Descripción corregida"), HTTP_X_MODAL_REQUEST="true",
        ).status_code, 204)
        self.official.position = self.other_position
        self.official.save(update_fields=["position"])
        after.refresh_from_db()
        self.assertEqual(activity_measurement(after)["position"], self.position)
        Activity.objects.filter(pk=after.pk).update(registration_position=None, registration_position_captured=False)
        after.refresh_from_db()
        self.assertTrue(activity_measurement(after)["inferred"])

    def test_eligibility_applies_to_manual_entries_and_retains_social_service(self):
        for position, item in ((self.position, self.item), (self.other_position, self.other_item)):
            plan, version = self.new_plan(position)
            self.add_item(version, item, "100")
            self.assertEqual(self.publish(version).status_code, 204)
        colleague = Official.objects.create(
            delegation=self.delegation, position=self.other_position, full_name="Apoyo Demo",
            national_id="APOYO-DEMO", email="apoyo@example.test",
        )
        path = reverse("activity_eligible_items")
        for official, item in ((self.official, self.item), (colleague, self.other_item)):
            response = self.client.get(path, {"official": official.pk, "date": self.period.start_date})
            self.assertEqual(response.json()["items"], [{"id": item.pk, "item_name": item.item_name}])
        foreign = Official.objects.create(
            delegation=self.other_delegation, position=self.other_position, full_name="Otro funcionario",
            national_id="FUNC-OTRO", email="otro@example.test",
        )
        self.assertEqual(self.client.get(path, {"official": foreign.pk, "date": self.period.start_date}).status_code, 404)
        create = reverse("activity_create")
        self.assertContains(self.client.post(create, self.activity_data(item=self.other_item.pk)),
                            "Elige un ítem disponible")
        self.assertFalse(Activity.objects.exists())
        self.assertEqual(self.client.post(create, self.activity_data(), HTTP_X_MODAL_REQUEST="true").status_code, 204)
        self.assertEqual(Activity.objects.get().registration_position, self.position)
        self.assertEqual(self.client.post(reverse("attention_entry"), self.attention_data()).status_code, 302)
        attention = SocialAttention.objects.get()
        self.assertTrue(activity_measurement(attention.activity)["excluded"])
        self.assertContains(self.client.get(reverse("attention_detail", args=[attention.pk])), "Fuera de medición")

    def test_reopen_requires_global_permission_and_keeps_dates(self):
        plan, version = self.new_plan()
        self.add_item(version, self.item, "100")
        self.period.close_period()
        self.assertEqual(self.publish(version).status_code, 403)
        reopen = reverse("period_reopen", args=[self.period.pk])
        self.staff.user_permissions.add(*Permission.objects.filter(codename__in=["view_period", "reopen_period"]))
        self.assertEqual(self.client.post(reopen, {"reason": "Corrección de prueba."}).status_code, 403)
        self.assertContains(self.management.post(reopen, {"reason": "  "}), "Motivo de reapertura")
        self.period.refresh_from_db()
        self.assertEqual(self.period.status, Period.Status.CLOSED)
        role = Role.objects.create(role_name="Reapertura autorizada", scope=Role.Scope.ALL)
        role.permissions.add(Permission.objects.get(codename="reopen_period"))
        self.assertFalse(is_global_administrator(role.scope, role.permissions.all()))
        self.official.roles.add(role)
        self.assertEqual(self.client.post(reopen, {"reason": "Corrección de prueba."}).status_code, 302)
        self.period.refresh_from_db()
        self.assertEqual(self.period.status, Period.Status.OPEN)
        self.assertIsNotNone(self.period.first_closed_at)
        self.assertEqual(AuditLog.objects.get(action="Reapertura de período").official, self.official)
        self.assertEqual(self.publish(version).status_code, 204)
        response = self.write("period_update", self.period.pk,
                              start_date=(timezone.localdate() - timedelta(days=2)).isoformat(),
                              end_date=self.period.end_date.isoformat())
        self.assertContains(response, "Las fechas quedan fijas")
