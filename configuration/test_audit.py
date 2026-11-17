from datetime import date, datetime, time

from django.contrib.auth.models import Permission, User
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import Official, Role
from configuration.models import AuditLog


class AuditViewTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        permission = Permission.objects.get(content_type__app_label="configuration", codename="view_auditlog")
        for scope in (Role.Scope.ALL, Role.Scope.DELEGATION):
            user = User.objects.create_user(f"auditor-{scope}")
            official = Official.objects.create(user=user, full_name=f"Auditor {scope}",
                                               national_id=scope, email=f"{scope.lower()}@example.test")
            role = Role.objects.create(role_name=f"Auditor {scope}", scope=scope)
            role.permissions.add(permission)
            official.roles.add(role)
            if scope == Role.Scope.ALL:
                cls.auditor = user
            else:
                cls.local_user = user
        cls.event = AuditLog.objects.create(
            actor_username="coordinacion-original", action="Edición de reglas de medición",
            affected_table="analytics_measurementversion", affected_record_id=42,
            date=timezone.make_aware(datetime.combine(date(2026, 11, 17), time(23, 59))),
            origin_ip="192.0.2.1", previous_value="Puntos a descontar por reclamo: 20",
            new_value="Puntos a descontar por reclamo: 30\nCorreo de contacto: persona@example.test\nToken: secreto",
        )
        cls.list_url = reverse("audit_list")
        cls.detail_url = reverse("audit_detail", args=[cls.event.pk])

    def test_global_auditor_filters_and_sees_allowed_fields(self):
        AuditLog.objects.create(
            actor_username="coordinacion-original", action=self.event.action,
            affected_table=self.event.affected_table, affected_record_id=42,
            date=timezone.make_aware(datetime.combine(date(2026, 11, 18), time.min)),
        )
        self.client.force_login(self.auditor)
        response = self.client.get(self.list_url, {
            "since": "2026-11-17", "until": "2026-11-17", "actor": "coordinacion",
            "action": "reglas", "entity": "measurementversion", "record": 42,
        })
        self.assertEqual(list(response.context["page_obj"]), [self.event])
        self.assertContains(response, self.detail_url)
        detail = self.client.get(self.detail_url)
        self.assertContains(detail, "coordinacion-original")
        self.assertContains(detail, "192.0.2.1")
        self.assertContains(detail, "Puntos a descontar por reclamo: 20")
        self.assertContains(detail, "Puntos a descontar por reclamo: 30")
        self.assertNotContains(detail, "persona@example.test")
        self.assertNotContains(detail, "secreto")
        self.assertIn("no-store", detail.headers["Cache-Control"])
        invalid = self.client.get(self.list_url, {"since": "2026-11-18", "until": "2026-11-17"})
        self.assertContains(invalid, "El término debe ser igual o posterior al inicio.")
        self.assertEqual(len(invalid.context["page_obj"]), 0)

    def test_mutations_with_or_without_csrf_are_denied_and_audited(self):
        self.client.force_login(self.auditor)
        self.assertEqual(self.client.delete(self.detail_url).status_code, 403)
        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.force_login(self.auditor)
        self.assertEqual(csrf_client.post(self.detail_url, {"new_value": "Adulterado"}).status_code, 403)
        self.event.refresh_from_db()
        self.assertNotIn("Adulterado", self.event.new_value)
        attempts = AuditLog.objects.filter(action="Intento de alterar la bitácora", affected_record_id=self.event.pk)
        self.assertCountEqual(attempts.values_list("new_value", flat=True), ["POST", "DELETE"])
        self.assertEqual(set(attempts.values_list("actor_username", flat=True)), {self.auditor.username})

    def test_delegation_permission_does_not_expose_the_global_log(self):
        self.assertEqual(self.client.get(self.list_url).status_code, 302)
        self.client.force_login(self.local_user)
        self.assertEqual(self.client.get(self.list_url).status_code, 403)
        self.assertNotContains(self.client.get(self.detail_url), self.event.action, status_code=403)
