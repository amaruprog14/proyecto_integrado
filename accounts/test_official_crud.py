from io import BytesIO

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from openpyxl import load_workbook

from accounts.models import Area, Delegation, Official, Position, Role
from configuration.models import AuditLog


User = get_user_model()
PASSWORD = "Clave-Official-123"


class OfficialCrudTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_superuser("official.admin", "official.admin@example.test", PASSWORD)
        cls.delegation = Delegation.objects.create(
            delegation_name="Delegación Funcionarios",
            address="Calle Funcionario 1",
            commune="La Serena",
        )
        cls.area = Area.objects.create(area_name="Área Funcionarios")
        cls.position = Position.objects.create(position_name="Cargo Funcionario")
        cls.role = Role.objects.create(
            role_name="Rol Funcionario",
            scope=Role.Scope.DELEGATION,
        )

    def setUp(self):
        self.client.force_login(self.admin)

    def payload(self, **overrides):
        payload = {
            "full_name": "Funcionario Independiente",
            "national_id": "RUT-OFFICIAL-1",
            "email": "funcionario.independiente@example.test",
            "phone": "+56912345678",
            "area": self.area.pk,
            "position": self.position.pk,
            "delegation": self.delegation.pk,
            "authorized_delegations": [self.delegation.pk],
            "roles": [self.role.pk],
            "status": Official.Status.ACTIVE,
        }
        payload.update(overrides)
        return payload

    def test_create_official_without_account(self):
        response = self.client.post(reverse("official_create"), self.payload(), follow=True)

        self.assertEqual(response.status_code, 200)
        official = Official.objects.get(national_id="RUT-OFFICIAL-1")
        self.assertIsNone(official.user)
        self.assertEqual(list(official.authorized_delegations.all()), [])
        self.assertEqual(list(official.roles.all()), [self.role])
        self.assertContains(response, "fue creado correctamente")

    def test_create_official_with_account_is_atomic_and_linked(self):
        response = self.client.post(
            reverse("official_create"),
            self.payload(
                full_name="Funcionario Con Cuenta",
                national_id="RUT-OFFICIAL-2",
                email="funcionario.cuenta@example.test",
                create_account="on",
                username="funcionario.cuenta",
                first_name="Funcionario",
                last_name="Cuenta",
                password1=PASSWORD,
                password2=PASSWORD,
            ),
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        official = Official.objects.get(national_id="RUT-OFFICIAL-2")
        user = User.objects.get(username="funcionario.cuenta")
        self.assertEqual(official.user_id, user.pk)
        self.assertTrue(user.check_password(PASSWORD))
        self.assertContains(response, "fue creado correctamente")

    def test_create_account_requires_credentials(self):
        response = self.client.post(
            reverse("official_create"),
            self.payload(
                create_account="on",
                username="sin.clave.official",
                password1="",
                password2="",
            ),
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Ingresa una contraseña para la nueva cuenta")
        self.assertFalse(Official.objects.filter(national_id="RUT-OFFICIAL-1").exists())
        self.assertFalse(User.objects.filter(username="sin.clave.official").exists())

    def test_edit_official_keeps_linked_user_credentials(self):
        user = User.objects.create_user("cuenta.vinculada", "cuenta@example.test", PASSWORD)
        official = Official.objects.create(
            user=user,
            full_name="Nombre Original",
            national_id="RUT-OFFICIAL-3",
            email="original@example.test",
            delegation=self.delegation,
        )

        response = self.client.post(
            reverse("official_update", args=[official.pk]),
            self.payload(
                full_name="Nombre Editado",
                national_id="RUT-OFFICIAL-3",
                email="editado@example.test",
            ),
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        official.refresh_from_db()
        user.refresh_from_db()
        self.assertEqual(official.full_name, "Nombre Editado")
        self.assertEqual(official.user_id, user.pk)
        self.assertEqual(user.username, "cuenta.vinculada")
        self.assertTrue(user.check_password(PASSWORD))

    def test_official_list_exposes_create_and_edit_actions(self):
        official = Official.objects.create(
            full_name="Visible en tabla",
            national_id="RUT-OFFICIAL-4",
            email="visible@example.test",
            delegation=self.delegation,
        )

        response = self.client.get(reverse("official_maintainer"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, f'href="{reverse("official_create")}"')
        self.assertContains(response, f'href="{reverse("official_update", args=[official.pk])}"')


def export_rows(response):
    return list(load_workbook(BytesIO(response.content), read_only=True).active.values)


class OfficialExportTests(TestCase):
    """Exportación a Excel del listado de funcionarios: mismas columnas, filtros y ámbito."""

    HEADERS = ("Nombre completo", "RUT / identificador", "Correo", "Área", "Cargo", "Estado")

    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_superuser("export.admin", "export.admin@example.test", PASSWORD)
        cls.own = Delegation.objects.create(delegation_name="Zona Propia", address="Calle 1", commune="La Serena")
        cls.foreign = Delegation.objects.create(delegation_name="Zona Ajena", address="Calle 2", commune="La Serena")
        cls.area = Area.objects.create(area_name="Área Exportación")
        cls.position = Position.objects.create(position_name="Analista Exportación")
        cls.active = Official.objects.create(
            full_name="Ana Exportable",
            national_id="RUT-EXP-1",
            email="ana.exportable@example.test",
            phone="+56900000001",
            area=cls.area,
            position=cls.position,
            delegation=cls.own,
        )
        cls.suspended = Official.objects.create(
            full_name="Bruno Exportable",
            national_id="RUT-EXP-2",
            email="bruno.exportable@example.test",
            delegation=cls.own,
            status=Official.Status.SUSPENDED,
        )
        cls.outsider = Official.objects.create(
            full_name="Carla Ajena",
            national_id="RUT-EXP-3",
            email="carla.ajena@example.test",
            delegation=cls.foreign,
        )

    def test_export_is_xlsx_with_the_table_columns_and_no_internal_fields(self):
        self.client.force_login(self.admin)

        response = self.client.get(reverse("official_export"), {"q": "EXPORTABLE", "status": "ACTIVE"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response["Content-Type"],
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        self.assertIn('attachment; filename="funcionarios.xlsx"', response["Content-Disposition"])
        # Sin teléfono, cuenta vinculada, id ni fechas internas: solo lo que muestra la tabla.
        self.assertEqual(
            export_rows(response),
            [
                self.HEADERS,
                ("Ana Exportable", "RUT-EXP-1", "ana.exportable@example.test", "Área Exportación",
                 "Analista Exportación", "Activo"),
            ],
        )

    def test_search_also_matches_the_status_label_like_the_table(self):
        self.client.force_login(self.admin)

        rows = export_rows(self.client.get(reverse("official_export"), {"q": "suspendido"}))

        self.assertEqual(
            rows[1:], [("Bruno Exportable", "RUT-EXP-2", "bruno.exportable@example.test", "—", "—", "Suspendido")]
        )

    def test_archived_officials_are_not_exported(self):
        Official.objects.filter(pk=self.suspended.pk).update(deleted_at=timezone.now())
        self.client.force_login(self.admin)

        names = [row[0] for row in export_rows(self.client.get(reverse("official_export")))]

        self.assertNotIn("Bruno Exportable", names)

    def test_export_only_includes_officials_in_scope(self):
        manager = User.objects.create_user("gestor.export", "gestor.export@example.test", PASSWORD)
        Official.objects.create(
            user=manager,
            full_name="Gestor Exportación",
            national_id="RUT-EXP-GESTOR",
            email="gestor.export@example.test",
            delegation=self.own,
        )
        manager.user_permissions.add(
            Permission.objects.get(content_type__app_label="accounts", codename="view_official")
        )
        self.client.force_login(manager)

        names = [row[0] for row in export_rows(self.client.get(reverse("official_export")))]

        self.assertIn("Ana Exportable", names)
        self.assertNotIn("Carla Ajena", names)

    def test_export_requires_view_official_and_logs_the_denial(self):
        outsider = User.objects.create_user("sin.permiso.export", "sin.permiso.export@example.test", PASSWORD)
        Official.objects.create(
            user=outsider,
            full_name="Sin Permiso Exportación",
            national_id="RUT-EXP-NOPERM",
            email="sin.permiso.export@example.test",
            delegation=self.own,
        )
        self.client.force_login(outsider)

        response = self.client.get(reverse("official_export"))

        self.assertEqual(response.status_code, 403)
        self.assertTrue(
            AuditLog.objects.filter(action="Acceso denegado", affected_table="official_export").exists()
        )

    def test_list_links_to_the_server_export_without_csv(self):
        self.client.force_login(self.admin)

        response = self.client.get(reverse("official_maintainer"))

        self.assertContains(response, f'data-export-url="{reverse("official_export")}"')
        self.assertContains(response, "Exportar a Excel")
        self.assertNotContains(response, "CSV")


class OfficialRoleRulesTests(TestCase):
    """El mantenedor de funcionarios aplica las mismas reglas de roles que Usuarios y Roles."""

    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_superuser("roles.official", "roles.official@example.test", PASSWORD)
        cls.global_role = Role.objects.create(role_name="Administración Funcionarios", scope=Role.Scope.ALL)
        cls.global_role.permissions.add(
            Permission.objects.get(content_type__app_label="accounts", codename="change_role")
        )
        cls.inactive_role = Role.objects.create(role_name="Rol Histórico", is_active=False)
        holder_user = User.objects.create_user("titular.unico", "titular.unico@example.test", PASSWORD)
        cls.holder = Official.objects.create(
            user=holder_user,
            full_name="Titular Único",
            national_id="RUT-TITULAR",
            email="titular.unico@example.test",
        )
        cls.holder.roles.add(cls.global_role, cls.inactive_role)

    def setUp(self):
        self.client.force_login(self.admin)

    def payload(self, **overrides):
        payload = {
            "full_name": "Titular Único",
            "national_id": "RUT-TITULAR",
            "email": "titular.unico@example.test",
            "roles": [self.global_role.pk],
            "status": Official.Status.ACTIVE,
        }
        payload.update(overrides)
        return payload

    def test_sole_global_administrator_cannot_be_deactivated(self):
        response = self.client.post(
            reverse("official_update", args=[self.holder.pk]), self.payload(status=Official.Status.INACTIVE)
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "No se puede desactivar ni suspender a Titular Único")
        self.holder.refresh_from_db()
        self.assertEqual(self.holder.status, Official.Status.ACTIVE)

    def test_sole_global_administrator_keeps_the_role(self):
        payload = self.payload()
        payload.pop("roles")

        response = self.client.post(reverse("official_update", args=[self.holder.pk]), payload)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "No se puede quitar el rol Administración Funcionarios a Titular Único")
        self.assertTrue(self.holder.roles.filter(pk=self.global_role.pk).exists())

    def test_editing_keeps_the_inactive_role_and_shows_it_locked(self):
        form_page = self.client.get(reverse("official_update", args=[self.holder.pk]))
        self.assertContains(form_page, "Rol Histórico")
        self.assertContains(form_page, "Rol inactivo")

        response = self.client.post(
            reverse("official_update", args=[self.holder.pk]), self.payload(full_name="Titular Editado")
        )

        self.assertRedirects(response, reverse("official_maintainer"))
        self.holder.refresh_from_db()
        self.assertEqual(self.holder.full_name, "Titular Editado")
        self.assertEqual(set(self.holder.roles.all()), {self.global_role, self.inactive_role})

    def test_privileged_role_without_role_permission_is_denied_with_403_and_audited(self):
        manager = User.objects.create_user("gestor.funcionarios", "gestor.funcionarios@example.test", PASSWORD)
        manager_official = Official.objects.create(
            user=manager,
            full_name="Gestor Funcionarios",
            national_id="RUT-GESTOR-FUNC",
            email="gestor.funcionarios@example.test",
        )
        manager.user_permissions.add(
            *Permission.objects.filter(
                content_type__app_label="accounts", codename__in=["view_official", "add_official"]
            )
        )
        self.client.force_login(manager)

        form_page = self.client.get(reverse("official_create"))
        self.assertContains(form_page, 'data-role-locked="true"')

        response = self.client.post(
            reverse("official_create"),
            {
                "full_name": "Escalada",
                "national_id": "RUT-ESCALADA",
                "email": "escalada@example.test",
                "roles": [self.global_role.pk],
                "status": Official.Status.ACTIVE,
            },
        )

        self.assertEqual(response.status_code, 403)
        self.assertFalse(Official.objects.filter(national_id="RUT-ESCALADA").exists())
        log = AuditLog.objects.get(action="Acceso denegado")
        self.assertIn("accounts.change_role", log.new_value)
        self.assertEqual(log.official, manager_official)
