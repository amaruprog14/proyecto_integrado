"""
Auditoría con valor anterior y nuevo en Delegaciones, Usuarios y Funcionarios (INT-03) y registro
de los intentos de acceso a registros de otra delegación, que siguen respondiendo 404 (SEG-01).
"""

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import TestCase
from django.urls import reverse

from accounts.models import Delegation, Official, Role
from configuration.models import AuditLog

User = get_user_model()
PASSWORD = "Clave-Auditoria-123"


class FieldLevelAuditTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_superuser("audit.admin", "audit.admin@example.test", PASSWORD)
        cls.delegation = Delegation.objects.create(delegation_name="Zona Auditada", address="Calle 1", commune="La Serena")

    def setUp(self):
        self.client.force_login(self.admin)

    def test_delegation_update_records_only_the_changed_fields(self):
        self.client.post(
            reverse("delegation_update", args=[self.delegation.pk]),
            {"delegation_name": "Zona Auditada", "address": "Calle 2", "commune": "Coquimbo", "status": "ACTIVE"},
        )

        log = AuditLog.objects.get(action="Actualización de delegación")
        self.assertEqual(log.previous_value, "Dirección: Calle 1")
        self.assertEqual(log.new_value, "Dirección: Calle 2")

    def test_delegation_creation_and_state_changes_are_described(self):
        self.client.post(
            reverse("delegation_create"),
            {"delegation_name": "Zona Nueva", "address": "Calle 3", "commune": "La Serena", "status": "ACTIVE"},
        )
        created = Delegation.objects.get(delegation_name="Zona Nueva")
        self.client.post(reverse("delegation_deactivate", args=[created.pk]))

        creation = AuditLog.objects.get(action="Creación de delegación")
        self.assertIn(f"Código: {created.code}", creation.new_value)
        self.assertIn("Dirección: Calle 3", creation.new_value)
        deactivation = AuditLog.objects.get(action="Desactivación de delegación")
        self.assertEqual((deactivation.previous_value, deactivation.new_value), ("Estado: Activa", "Estado: Inactiva"))

    def test_user_update_records_profile_roles_and_password_change_without_its_value(self):
        role = Role.objects.create(role_name="Rol Auditado")
        target = User.objects.create_user("auditado", "auditado@example.test", PASSWORD)
        Official.objects.create(
            user=target, full_name="Persona Auditada", national_id="12345678-5", email="auditado@example.test"
        )
        new_password = "Otra-Clave-456"

        self.client.post(
            reverse("user_update", args=[target.pk]),
            {
                "username": "auditado",
                "email": "auditado@example.test",
                "password1": new_password,
                "password2": new_password,
                "full_name": "Persona Auditada",
                "national_id": "12.345.678-5",
                "phone": "+56911112222",
                "delegation": self.delegation.pk,
                "roles": [role.pk],
                "status": Official.Status.ACTIVE,
            },
        )

        log = AuditLog.objects.get(action="Actualización de usuario")
        self.assertEqual(log.previous_value, "Teléfono: —\nDelegación principal: —\nRoles: Sin rol")
        self.assertEqual(
            log.new_value,
            f"Teléfono: +56911112222\nDelegación principal: {self.delegation.code} · Zona Auditada\n"
            "Roles: Rol Auditado\nContraseña: Actualizada (no se registra su valor)",
        )
        self.assertNotIn(new_password, log.new_value)
        target.refresh_from_db()
        self.assertNotIn(target.password, log.new_value)

    def test_user_deactivation_records_previous_and_new_state(self):
        target = User.objects.create_user("estado.auditado", "estado.auditado@example.test", PASSWORD)

        self.client.post(reverse("user_deactivate", args=[target.pk]))

        log = AuditLog.objects.get(action="Desactivación de usuario")
        self.assertEqual(log.previous_value, "Usuario: estado.auditado\nEstado: Activo")
        self.assertEqual(log.new_value, "Usuario: estado.auditado\nEstado: Inactivo")

    def test_official_update_records_the_changed_fields(self):
        official = Official.objects.create(full_name="Funcionaria Antes", national_id="16666666-K", email="off.aud@example.test")

        self.client.post(
            reverse("official_update", args=[official.pk]),
            {"full_name": "Funcionaria Después", "national_id": "16.666.666-k", "email": "off.aud@example.test",
             "status": Official.Status.ACTIVE},
        )

        log = AuditLog.objects.get(action="Actualización de funcionario")
        self.assertEqual((log.previous_value, log.new_value), ("Nombre completo: Funcionaria Antes", "Nombre completo: Funcionaria Después"))


class OutOfScopeAccessAuditTests(TestCase):
    """Un identificador de otra delegación responde 404 igual que uno inexistente, pero queda auditado."""

    @classmethod
    def setUpTestData(cls):
        cls.own = Delegation.objects.create(delegation_name="Zona Propia", address="Calle 1", commune="La Serena")
        cls.foreign = Delegation.objects.create(delegation_name="Zona Ajena", address="Calle 2", commune="La Serena")
        cls.manager = User.objects.create_user("gestor.ambito", "gestor.ambito@example.test", PASSWORD)
        cls.manager_official = Official.objects.create(
            user=cls.manager, full_name="Gestor Ámbito", national_id="RUT-AMBITO", email="gestor.ambito@example.test",
            delegation=cls.own,
        )
        cls.manager.user_permissions.add(
            *Permission.objects.filter(
                content_type__app_label__in=["accounts", "auth"],
                codename__in=[
                    "view_delegation", "change_delegation", "view_user", "change_user", "view_official", "change_official",
                ],
            )
        )
        cls.foreign_user = User.objects.create_user("usuario.ajeno.aud", "ajeno.aud@example.test", PASSWORD)
        cls.foreign_official = Official.objects.create(
            user=cls.foreign_user, full_name="Usuario Ajeno", national_id="RUT-AJENO-AUD", email="ajeno.aud@example.test",
            delegation=cls.foreign,
        )

    def setUp(self):
        self.client.force_login(self.manager)

    def test_foreign_records_answer_404_and_leave_an_audit_entry(self):
        requests = (
            ("get", reverse("delegation_detail", args=[self.foreign.pk]), self.foreign.pk),
            ("get", reverse("delegation_update", args=[self.foreign.pk]), self.foreign.pk),
            ("post", reverse("delegation_deactivate", args=[self.foreign.pk]), self.foreign.pk),
            ("get", reverse("user_detail", args=[self.foreign_user.pk]), self.foreign_user.pk),
            ("get", reverse("user_update", args=[self.foreign_user.pk]), self.foreign_user.pk),
            ("post", reverse("user_deactivate", args=[self.foreign_user.pk]), self.foreign_user.pk),
            ("get", reverse("official_update", args=[self.foreign_official.pk]), self.foreign_official.pk),
        )
        for method, url, record_id in requests:
            with self.subTest(url=url, method=method):
                AuditLog.objects.all().delete()

                request_headers = (
                    {"HTTP_X_MODAL_REQUEST": "true"}
                    if method == "get" and url.endswith("/editar/")
                    else {}
                )
                response = getattr(self.client, method)(url, **request_headers)

                self.assertEqual(response.status_code, 404)
                log = AuditLog.objects.get(action="Acceso denegado")
                self.assertEqual(log.affected_record_id, record_id)
                self.assertEqual(log.official, self.manager_official)
                self.assertIn("fuera del ámbito de delegación", log.new_value)
        self.foreign.refresh_from_db()
        self.assertEqual(self.foreign.status, Delegation.Status.ACTIVE)

    def test_nonexistent_records_answer_404_without_audit(self):
        response = self.client.get(reverse("delegation_detail", args=[999999]))

        self.assertEqual(response.status_code, 404)
        self.assertFalse(AuditLog.objects.filter(action="Acceso denegado").exists())
