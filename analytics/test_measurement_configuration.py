from datetime import timedelta

from django.contrib.auth.models import Permission, User
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from common.testing_edit import revision_from_form
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
        from accounts.models import Area
        from configuration.models import ActivityType

        cls.official.area = Area.objects.create(area_name="Gestión social")
        cls.official.save(update_fields=["position", "area"])
        cls.activity_type = ActivityType.objects.create(area=cls.official.area, name="Visita")
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
        url = reverse(name, args=args)
        if name.startswith("measurement_") and name != "measurement_plan_create" and "edit_revision" not in data:
            response = self.management.get(url, HTTP_X_MODAL_REQUEST="true")
            if response.status_code == 200:
                data["edit_revision"] = response.context["edit_revision"]
        return self.management.post(url, data, HTTP_X_MODAL_REQUEST="true")

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

    def test_parameter_changes_are_visible_with_before_after_and_account_in_audit(self):
        plan, version = self.new_plan()
        self.assertEqual(self.write(
            "measurement_version_edit", self.period.pk, plan.pk, version.pk,
            max_computable="150", amber_threshold="60", green_threshold="100",
            collective_threshold="80", congratulation_points="10", complaint_points="30", max_final_score="120",
        ).status_code, 204)
        event = AuditLog.objects.get(action="Edición de reglas de medición", affected_record_id=version.pk)
        self.assertEqual(event.actor_username, self.admin.username)
        self.assertIn("Puntos a descontar por reclamo: 20", event.previous_value)
        self.assertIn("Puntos a descontar por reclamo: 30", event.new_value)
        response = self.management.get(reverse("audit_detail", args=[event.pk]))
        self.assertContains(response, "Puntos a descontar por reclamo: 20")
        self.assertContains(response, "Puntos a descontar por reclamo: 30")
        self.assertContains(response, "Tope del resultado final (puntos): 150")
        self.assertContains(response, "Tope del resultado final (puntos): 120")
        version.refresh_from_db()
        self.assertEqual(version.max_final_score, 120)

    def test_stale_rules_do_not_overwrite_another_edit(self):
        plan, version = self.new_plan()
        other_admin = User.objects.create_superuser("otro-admin-medicion", password="Prueba-1234")
        other_client = Client()
        other_client.force_login(other_admin)
        url = reverse("measurement_version_edit", args=[self.period.pk, plan.pk, version.pk])
        first_revision = revision_from_form(self.management, url)
        stale_revision = revision_from_form(other_client, url)
        values = dict(max_computable="150", amber_threshold="60", green_threshold="100",
                      collective_threshold="80", congratulation_points="10", complaint_points="20",
                      max_final_score="150")
        response = self.management.post(url, {
            **values, "complaint_points": "30", "edit_revision": first_revision,
        }, HTTP_X_MODAL_REQUEST="true")
        self.assertEqual(response.status_code, 204)
        before = AuditLog.objects.count()
        response = other_client.post(url, {
            **values, "green_threshold": "95", "edit_revision": stale_revision,
        }, HTTP_X_MODAL_REQUEST="true")
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["code"], "edit_conflict")
        version.refresh_from_db()
        self.assertEqual(version.complaint_points, 30)
        self.assertEqual(version.green_threshold, 100)
        self.assertEqual(AuditLog.objects.count(), before)
        self.assertEqual(other_client.post(url, {
            **values, "complaint_points": "30", "green_threshold": "95",
            "edit_revision": revision_from_form(other_client, url),
        }, HTTP_X_MODAL_REQUEST="true").status_code, 204)
        version.refresh_from_db()
        self.assertEqual(version.green_threshold, 95)

    def test_stale_publish_and_removal_detect_changes_in_items_and_adjustments(self):
        plan, version = self.new_plan()
        line = self.add_item(version, self.item, "100")
        args = [self.period.pk, plan.pk, version.pk]
        publish_url = reverse("measurement_version_publish", args=args)
        publish_revision = revision_from_form(self.management, publish_url)
        self.assertEqual(self.write("measurement_item_edit", *args, line.pk,
                                   function=self.function.pk, item=self.item.pk, goal_type="QUANTITY",
                                   goal="20", weight="100").status_code, 204)
        response = self.management.post(publish_url, {"edit_revision": publish_revision},
                                        HTTP_X_MODAL_REQUEST="true")
        self.assertEqual(response.status_code, 409)
        version.refresh_from_db()
        self.assertFalse(version.is_published)
        remove_url = reverse("measurement_item_remove", args=[*args, line.pk])
        remove_revision = revision_from_form(self.management, remove_url)
        self.assertEqual(self.write("measurement_adjustment_create", *args, line.pk,
                                   official=self.official.pk, goal="15", weight="").status_code, 204)
        response = self.management.post(remove_url, {"edit_revision": remove_revision},
                                        HTTP_X_MODAL_REQUEST="true")
        self.assertEqual(response.status_code, 409)
        self.assertTrue(version.items.filter(pk=line.pk).exists())
        self.assertTrue(line.adjustments.exists())
        self.assertEqual(self.publish(version).status_code, 204)

    def test_stale_item_and_adjustment_forms_detect_changes_and_keep_validation_revision(self):
        plan, version = self.new_plan()
        line = self.add_item(version, self.item, "100")
        args = [self.period.pk, plan.pk, version.pk, line.pk]
        item_url = reverse("measurement_item_edit", args=args)
        item_values = dict(function=self.function.pk, item=self.item.pk, goal_type="QUANTITY", goal="10", weight="100")
        revision = revision_from_form(self.management, item_url)
        invalid = self.management.post(item_url, {**item_values, "goal": "0", "edit_revision": revision},
                                       HTTP_X_MODAL_REQUEST="true")
        self.assertEqual(invalid.status_code, 200)
        self.assertEqual(invalid.context["edit_revision"], revision)
        self.assertEqual(self.write("measurement_adjustment_create", *args,
                                   official=self.official.pk, goal="15", weight="").status_code, 204)
        adjustment = line.adjustments.get()
        adjustment_url = reverse("measurement_adjustment_edit", args=[*args, adjustment.pk])
        adjustment_revision = revision_from_form(self.management, adjustment_url)
        self.assertEqual(self.management.post(item_url, {**item_values, "edit_revision": revision},
                                              HTTP_X_MODAL_REQUEST="true").status_code, 409)
        self.assertEqual(self.write("measurement_adjustment_edit", *args, adjustment.pk,
                                   official=self.official.pk, goal="25", weight="").status_code, 204)
        self.assertEqual(self.management.post(adjustment_url, {
            "official": self.official.pk, "goal": "16", "weight": "", "edit_revision": adjustment_revision,
        }, HTTP_X_MODAL_REQUEST="true").status_code, 409)
        adjustment.refresh_from_db()
        self.assertEqual(adjustment.goal, 25)
        self.assertEqual(self.management.post(item_url, item_values, HTTP_X_MODAL_REQUEST="true").status_code, 409)

    def activity_data(self, **changes):
        return {
            "official": self.official.pk, "date": self.period.end_date.isoformat(), "item": self.item.pk,
            "record_type": Activity.RecordType.FIELD, "action_description": "Registro de prueba",
            "subject": "Visita social", "activity_type": self.activity_type.pk,
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
        revision = revision_from_form(self.client, edit)
        self.assertContains(
            self.client.post(edit, self.activity_data(date=self.period.start_date.isoformat(),
                                                        item=self.other_item.pk, edit_revision=revision)),
            "Elige un ítem disponible",
        )
        self.assertEqual(self.client.post(
            edit, self.activity_data(action_description="Descripción corregida", edit_revision=revision),
            HTTP_X_MODAL_REQUEST="true",
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

    def test_publication_requires_weights_to_add_exactly_one_hundred(self):
        # RN-001: 40/59 (99 %) y 40/61 (101 %) se rechazan; 40/60 (100 %) se publica.
        _, version = self.new_plan()
        self.add_item(version, self.item, "40")
        line = self.add_item(version, self.other_item, "59")
        for weight, total in (("59", "99.00"), ("61", "101.00")):
            MeasurementItem.objects.filter(pk=line.pk).update(weight=weight)
            self.assertContains(self.publish(version), f"suman {total} %. Deben sumar 100 %.")
            version.refresh_from_db()
            self.assertFalse(version.is_published)
        MeasurementItem.objects.filter(pk=line.pk).update(weight="60")
        self.assertEqual(self.publish(version).status_code, 204)
        version.refresh_from_db()
        self.assertTrue(version.is_published)

    def test_item_form_rejects_zero_and_negative_goals(self):
        _, version = self.new_plan()
        for goal in ("0", "-1"):
            response = self.write("measurement_item_create", self.period.pk, version.plan_id, version.pk,
                                  function=self.function.pk, item=self.item.pk, goal_type="QUANTITY",
                                  goal=goal, weight="100")
            self.assertEqual(response.status_code, 200, goal)
            self.assertTrue(response.context["form"].errors.get("goal"), goal)
            self.assertFalse(version.items.exists(), goal)
        self.add_item(version, self.item, "100", goal="10")

    def test_item_form_rejects_negative_and_over_one_hundred_weights(self):
        _, version = self.new_plan()
        for weight in ("-1", "100.01", "101"):
            response = self.write("measurement_item_create", self.period.pk, version.plan_id, version.pk,
                                  function=self.function.pk, item=self.item.pk, goal_type="QUANTITY",
                                  goal="10", weight=weight)
            self.assertEqual(response.status_code, 200, weight)
            self.assertTrue(response.context["form"].errors.get("weight"), weight)
            self.assertFalse(version.items.exists(), weight)
        self.add_item(version, self.item, "100")


    def test_individual_adjustment_audit_distinguishes_creation_and_edition(self):
        plan, version = self.new_plan()
        line = self.add_item(version, self.item, "100", goal="10")
        args = (self.period.pk, plan.pk, version.pk, line.pk)
        self.assertEqual(self.write("measurement_adjustment_create", *args, official=self.official.pk,
                                    weight="", goal="20").status_code, 204)
        adjustment = line.adjustments.get()
        self.assertEqual(self.write("measurement_adjustment_edit", *args, adjustment.pk, official=self.official.pk,
                                    weight="", goal="25").status_code, 204)

        created = AuditLog.objects.get(action="Creación de ajuste individual")
        # Sin valor anterior inventado: no toma la meta ni el ítem de la línea del plan como «anterior».
        self.assertEqual(created.previous_value, "")
        self.assertIn("Meta individual: 20", created.new_value)
        self.assertEqual((created.affected_table, created.affected_record_id), ("analytics_measurementadjustment", adjustment.pk))
        edited = AuditLog.objects.get(action="Edición de ajuste individual")
        self.assertEqual((edited.previous_value, edited.new_value), ("Meta individual: 20", "Meta individual: 25"))
        self.assertEqual(edited.affected_record_id, adjustment.pk)
        self.assertFalse(AuditLog.objects.filter(action="Edición de ajuste individual", previous_value__contains="Tipo de meta").exists())
