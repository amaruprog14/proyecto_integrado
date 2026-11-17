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

    def test_catalog_changes_show_names_and_keep_sensitive_fields_reserved(self):
        delegation = AuditLog.objects.create(
            actor_username="coordinacion-original", action="Edición de delegación",
            affected_table="accounts_delegation", affected_record_id=7,
            previous_value="Nombre de la delegación: Centro",
            new_value="\n".join([
                "Nombre de la delegación: Centro Histórico", "Correo electrónico: oficina@example.test",
                "Contraseña: clave-secreta", "Ruta del archivo: privado/acta.pdf",
                "RUT o RUN chileno: 11.111.111-1", "Token de acceso: abc123",
            ]),
        )
        position = AuditLog.objects.create(
            actor_username="coordinacion-original", action="Cargos: update", affected_table="accounts_position",
            affected_record_id=8, previous_value="Nombre del cargo: Gestor social",
            new_value="Nombre del cargo: Gestor social territorial",
        )
        official = AuditLog.objects.create(
            actor_username="coordinacion-original", action="Edición de funcionario", affected_table="accounts_official",
            affected_record_id=9, previous_value="Nombre completo: Persona Ficticia",
            new_value="Nombre completo: Persona Ficticia Editada",
        )
        self.client.force_login(self.auditor)
        detail = self.client.get(reverse("audit_detail", args=[delegation.pk]))
        self.assertContains(detail, "Nombre de la delegación: Centro")
        self.assertContains(detail, "Nombre de la delegación: Centro Histórico")
        for secret in ("oficina@example.test", "clave-secreta", "privado/acta.pdf", "11.111.111-1", "abc123"):
            self.assertNotContains(detail, secret)
        detail = self.client.get(reverse("audit_detail", args=[position.pk]))
        self.assertContains(detail, "Nombre del cargo: Gestor social territorial")
        # Fuera de los catálogos rige la lista explícita: los datos personales siguen reservados.
        detail = self.client.get(reverse("audit_detail", args=[official.pk]))
        self.assertNotContains(detail, "Persona Ficticia")
        self.assertContains(detail, "Detalle reservado")
        # Con el formato real de los mantenedores (snapshot + describe_changes).
        from accounts.models import Delegation, Position
        from accounts.views import delegation_snapshot
        from common.maintainers import snapshot
        from common.text import describe_changes
        office = Delegation.objects.create(delegation_name="Oriente", address="Calle 5", commune="La Serena")
        before = delegation_snapshot(office)
        office.delegation_name = "Oriente Alto"
        cargo = Position.objects.create(position_name="Encargado de bodega")
        cargo_before = snapshot(cargo)
        cargo.position_name = "Encargado de bodega municipal"
        for table, values, expected in (
            ("accounts_delegation", describe_changes(before, delegation_snapshot(office)), "Nombre: Oriente Alto"),
            ("accounts_position", describe_changes(cargo_before, snapshot(cargo)), "Nombre del cargo: Encargado de bodega municipal"),
        ):
            event = AuditLog.objects.create(actor_username="coordinacion-original", action="Actualización de catálogo",
                                            affected_table=table, affected_record_id=1,
                                            previous_value=values[0], new_value=values[1])
            self.assertContains(self.client.get(reverse("audit_detail", args=[event.pk])), expected)
        # El alcance no cambia: una cuenta con alcance de delegación no ve la bitácora.
        self.client.force_login(self.local_user)
        self.assertEqual(self.client.get(reverse("audit_detail", args=[delegation.pk])).status_code, 403)
