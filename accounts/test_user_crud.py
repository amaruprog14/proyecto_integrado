"""
Pruebas del CRUD de Usuarios (auth.User + accounts.Official).

Cubren creación con y sin perfil de funcionario, consulta, edición, contraseñas,
sincronización de estado, validaciones y duplicados, permisos, búsqueda, filtros,
paginación, exportación Excel sin datos sensibles y el ámbito por delegación.
"""

from io import BytesIO

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django import forms
from django.test import TestCase
from django.urls import reverse
from openpyxl import load_workbook

from accounts.backends import SGRAuthBackend
from accounts.forms import OfficialUserForm
from accounts.models import Area, Delegation, Official, Position, Role
from configuration.models import AuditLog

User = get_user_model()
PASSWORD = "Clave-Segura-123"


def grant_permissions(user, *codenames):
    for codename in codenames:
        app_label, name = codename.split(".")
        permission = Permission.objects.get(content_type__app_label=app_label, codename=name)
        user.user_permissions.add(permission)
    return user


def make_official(user, *, delegation=None, status=Official.Status.ACTIVE, full_name=None, national_id=None, email=None):
    return Official.objects.create(
        user=user,
        full_name=full_name or user.username.replace(".", " ").title(),
        national_id=national_id or f"RUT-{user.username}",
        email=email or f"{user.username}@example.test",
        delegation=delegation,
        status=status,
    )


def user_payload(**overrides):
    payload = {
        "username": "usuario.nuevo",
        "first_name": "Usuario",
        "last_name": "Nuevo",
        "email": "usuario.nuevo@example.test",
        "password1": PASSWORD,
        "password2": PASSWORD,
        "status": Official.Status.ACTIVE,
    }
    payload.update(overrides)
    return payload


class UserCrudAdminTests(TestCase):
    """CRUD de usuarios con un administrador de alcance total."""

    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_superuser("admin.user", "admin.user@example.test", PASSWORD)
        make_official(cls.admin, full_name="Administrador Usuarios", national_id="RUT-ADMIN-USER")

    def setUp(self):
        self.client.force_login(self.admin)

    def test_list_renders_persisted_accounts(self):
        response = self.client.get(reverse("user_maintainer"))

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "accounts/user_list.html")
        self.assertContains(response, "admin.user")
        self.assertContains(response, f'href="{reverse("user_create")}"')

    def test_create_user_with_official_profile(self):
        delegation = Delegation.objects.create(
            delegation_name="Zona Usuarios", address="Calle Uno", commune="La Serena"
        )
        area = Area.objects.create(area_name="Área Social")
        position = Position.objects.create(position_name="Analista")
        role = Role.objects.create(role_name="Operador de Prueba", scope=Role.Scope.DELEGATION)

        response = self.client.post(
            reverse("user_create"),
            user_payload(
                username="nuevo.funcionario",
                email="nuevo.funcionario@example.test",
                has_official="on",
                full_name="Nuevo Funcionario",
                national_id="RUT-NUEVO-1",
                phone="+56911111111",
                area=area.pk,
                position=position.pk,
                delegation=delegation.pk,
                authorized_delegations=[delegation.pk],
                roles=[role.pk],
            ),
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        user = User.objects.get(username="nuevo.funcionario")
        self.assertTrue(user.check_password(PASSWORD))
        self.assertNotEqual(user.password, PASSWORD)
        self.assertTrue(user.is_active)

        official = user.official
        self.assertEqual(official.full_name, "Nuevo Funcionario")
        self.assertEqual(official.national_id, "RUT-NUEVO-1")
        self.assertEqual(official.delegation, delegation)
        self.assertEqual(list(official.authorized_delegations.all()), [])
        self.assertEqual(list(official.roles.all()), [role])
        self.assertContains(response, "fue creado correctamente")

    def test_create_administrative_account_without_official_profile(self):
        response = self.client.post(
            reverse("user_create"),
            user_payload(username="cuenta.admin", email="cuenta.admin@example.test"),
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        user = User.objects.get(username="cuenta.admin")
        self.assertFalse(Official.objects.filter(user=user).exists())
        self.assertTrue(user.is_active)

    def test_create_requires_password(self):
        response = self.client.post(
            reverse("user_create"),
            user_payload(username="sin.clave", email="sin.clave@example.test", password1="", password2=""),
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Ingresa una contraseña para la nueva cuenta")
        self.assertFalse(User.objects.filter(username="sin.clave").exists())

    def test_password_mismatch_is_rejected(self):
        response = self.client.post(
            reverse("user_create"),
            user_payload(
                username="clave.distinta",
                email="clave.distinta@example.test",
                password1=PASSWORD,
                password2="Otra-Clave-123",
            ),
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Las contraseñas no coinciden")
        self.assertFalse(User.objects.filter(username="clave.distinta").exists())

    def test_weak_password_is_rejected(self):
        response = self.client.post(
            reverse("user_create"),
            user_payload(username="clave.debil", email="clave.debil@example.test", password1="123", password2="123"),
        )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(User.objects.filter(username="clave.debil").exists())

    def test_duplicate_username_email_and_national_id_are_rejected(self):
        existing = User.objects.create_user("existe", "existe@example.test", PASSWORD)
        make_official(existing, full_name="Existe Ya", national_id="RUT-EXISTE")

        duplicated_username = self.client.post(
            reverse("user_create"),
            user_payload(username="EXISTE", email="otro@example.test"),
        )
        self.assertContains(duplicated_username, "Ya existe una cuenta con este nombre de usuario")

        duplicated_email = self.client.post(
            reverse("user_create"),
            user_payload(username="otro.usuario", email="EXISTE@example.test"),
        )
        self.assertContains(duplicated_email, "Ya existe una cuenta con este correo electrónico")

        duplicated_national_id = self.client.post(
            reverse("user_create"),
            user_payload(
                username="otro.funcionario",
                email="otro.funcionario@example.test",
                has_official="on",
                full_name="Otro Funcionario",
                national_id="rut-existe",
            ),
        )
        self.assertContains(duplicated_national_id, "Ya existe un funcionario con este RUT")

        self.assertEqual(User.objects.filter(username__iexact="existe").count(), 1)

    def test_edit_without_password_keeps_current_password(self):
        user = User.objects.create_user("mantener.clave", "mantener.clave@example.test", "Clave-Original-123")
        official = make_official(user, full_name="Mantener Clave", national_id="RUT-MANTENER")

        response = self.client.post(
            reverse("user_update", args=[user.pk]),
            {
                "username": "mantener.clave",
                "first_name": "Mantener",
                "last_name": "Clave",
                "email": "mantener.clave@example.test",
                "password1": "",
                "password2": "",
                "full_name": "Nombre Editado",
                "national_id": "RUT-MANTENER",
                "status": Official.Status.ACTIVE,
            },
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        user.refresh_from_db()
        official.refresh_from_db()
        self.assertTrue(user.check_password("Clave-Original-123"))
        self.assertEqual(official.full_name, "Nombre Editado")
        self.assertContains(response, "fue actualizado correctamente")

    def test_edit_can_change_password(self):
        user = User.objects.create_user("cambia.clave", "cambia.clave@example.test", "Clave-Original-123")
        make_official(user, national_id="RUT-CAMBIA")

        self.client.post(
            reverse("user_update", args=[user.pk]),
            {
                "username": "cambia.clave",
                "first_name": "",
                "last_name": "",
                "email": "cambia.clave@example.test",
                "password1": "Clave-Nueva-456",
                "password2": "Clave-Nueva-456",
                "full_name": "Cambia Clave",
                "national_id": "RUT-CAMBIA",
                "status": Official.Status.ACTIVE,
            },
        )

        user.refresh_from_db()
        self.assertTrue(user.check_password("Clave-Nueva-456"))
        self.assertNotEqual(user.password, "Clave-Nueva-456")

    def test_status_inactive_deactivates_user_and_profile(self):
        user = User.objects.create_user("sincroniza.uno", "sincroniza.uno@example.test", PASSWORD)
        official = make_official(user, national_id="RUT-SINC-1")

        self.client.post(
            reverse("user_update", args=[user.pk]),
            {
                "username": "sincroniza.uno",
                "first_name": "",
                "last_name": "",
                "email": "sincroniza.uno@example.test",
                "password1": "",
                "password2": "",
                "full_name": "Sincroniza Uno",
                "national_id": "RUT-SINC-1",
                "status": Official.Status.INACTIVE,
            },
        )

        user.refresh_from_db()
        official.refresh_from_db()
        self.assertFalse(user.is_active)
        self.assertEqual(official.status, Official.Status.INACTIVE)

    def test_status_suspended_blocks_authentication(self):
        user = User.objects.create_user("sincroniza.dos", "sincroniza.dos@example.test", PASSWORD)
        make_official(user, national_id="RUT-SINC-2")

        self.client.post(
            reverse("user_update", args=[user.pk]),
            {
                "username": "sincroniza.dos",
                "first_name": "",
                "last_name": "",
                "email": "sincroniza.dos@example.test",
                "password1": "",
                "password2": "",
                "full_name": "Sincroniza Dos",
                "national_id": "RUT-SINC-2",
                "status": Official.Status.SUSPENDED,
            },
        )

        user.refresh_from_db()
        user.official.refresh_from_db()
        self.assertFalse(user.is_active)
        self.assertEqual(user.official.status, Official.Status.SUSPENDED)
        self.assertIsNone(SGRAuthBackend().authenticate(None, username="sincroniza.dos", password=PASSWORD))

    def test_admin_cannot_deactivate_own_account_through_form(self):
        response = self.client.post(
            reverse("user_update", args=[self.admin.pk]),
            {
                "username": "admin.user",
                "first_name": "",
                "last_name": "",
                "email": "admin.user@example.test",
                "password1": "",
                "password2": "",
                "full_name": "Administrador Usuarios",
                "national_id": "RUT-ADMIN-USER",
                "status": Official.Status.INACTIVE,
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "No puedes desactivar tu propia cuenta")
        self.admin.refresh_from_db()
        self.assertTrue(self.admin.is_active)

    def test_admin_cannot_deactivate_own_account_through_list_action(self):
        response = self.client.post(reverse("user_deactivate", args=[self.admin.pk]), follow=True)

        self.admin.refresh_from_db()
        self.assertTrue(self.admin.is_active)
        self.assertContains(response, "No puedes desactivar tu propia cuenta")

    def test_deactivate_and_activate_account(self):
        user = User.objects.create_user("accion.usuario", "accion.usuario@example.test", PASSWORD)
        official = make_official(user, national_id="RUT-ACCION")

        deactivated = self.client.post(reverse("user_deactivate", args=[user.pk]), follow=True)
        user.refresh_from_db()
        official.refresh_from_db()
        self.assertFalse(user.is_active)
        self.assertEqual(official.status, Official.Status.INACTIVE)
        self.assertContains(deactivated, "fue desactivado correctamente")
        self.assertTrue(AuditLog.objects.filter(action="Desactivación de usuario").exists())

        activated = self.client.post(reverse("user_activate", args=[user.pk]), follow=True)
        user.refresh_from_db()
        official.refresh_from_db()
        self.assertTrue(user.is_active)
        self.assertEqual(official.status, Official.Status.ACTIVE)
        self.assertContains(activated, "fue activado correctamente")

    def test_detail_shows_profile_without_exposing_password(self):
        user = User.objects.create_user("detalle.usuario", "detalle.usuario@example.test", PASSWORD)
        make_official(user, full_name="Detalle Funcionario", national_id="RUT-DETALLE")

        response = self.client.get(reverse("user_detail", args=[user.pk]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Detalle Funcionario")
        self.assertContains(response, "RUT-DETALLE")
        self.assertNotContains(response, user.password)

    def test_search_pagination_and_status_filter(self):
        for index in range(12):
            user = User.objects.create_user(
                f"busqueda{index:02d}", f"busqueda{index:02d}@example.test", PASSWORD
            )
            make_official(user, full_name=f"Funcionario Busqueda {index:02d}", national_id=f"RUT-B{index:02d}")

        response = self.client.get(reverse("user_maintainer"), {"q": "Busqueda"})

        self.assertEqual(len(response.context["users"]), 10)
        self.assertEqual(response.context["querystring"], "q=Busqueda")

        second_page = self.client.get(reverse("user_maintainer"), {"q": "Busqueda", "page": 2})

        self.assertEqual(len(second_page.context["users"]), 2)
        self.assertEqual(second_page.context["querystring"], "q=Busqueda")

    def test_export_has_no_passwords_and_includes_all_filtered_rows(self):
        for index in range(12):
            user = User.objects.create_user(
                f"exporta{index:02d}", f"exporta{index:02d}@example.test", PASSWORD
            )
            make_official(user, full_name=f"Funcionario Exporta {index:02d}", national_id=f"RUT-E{index:02d}")

        response = self.client.get(reverse("user_export"), {"q": "Exporta"})

        self.assertEqual(response.status_code, 200)
        self.assertIn('attachment; filename="usuarios.xlsx"', response["Content-Disposition"])

        sheet = load_workbook(BytesIO(response.content), read_only=True).active
        rows = list(sheet.values)
        self.assertEqual(len(rows), 13)
        content = str(rows).lower()
        self.assertNotIn("password", content)
        self.assertNotIn("pbkdf2", content)
        self.assertNotIn(PASSWORD.lower(), content)

    def test_anonymous_is_redirected_to_login(self):
        self.client.logout()
        url = reverse("user_maintainer")

        self.assertRedirects(self.client.get(url), f"{reverse('login')}?next={url}")

    def test_create_update_and_detail_views_render(self):
        create_response = self.client.get(reverse("user_create"))
        self.assertEqual(create_response.status_code, 200)
        self.assertTemplateUsed(create_response, "accounts/user_form.html")

        update_response = self.client.get(reverse("user_update", args=[self.admin.pk]))
        self.assertEqual(update_response.status_code, 200)
        self.assertTemplateUsed(update_response, "accounts/user_form.html")

        detail_response = self.client.get(reverse("user_detail", args=[self.admin.pk]))
        self.assertEqual(detail_response.status_code, 200)
        self.assertTemplateUsed(detail_response, "accounts/user_detail.html")
        self.assertContains(detail_response, "Administrador Usuarios")

    def test_edit_form_uses_checkboxes_and_precargas_relations(self):
        delegation = Delegation.objects.create(
            delegation_name="Zona Checkbox", address="Calle Checkbox", commune="La Serena"
        )
        role = Role.objects.create(role_name="Rol Checkbox", scope=Role.Scope.DELEGATION)
        user = User.objects.create_user("precargado.checkbox", "precargado@example.test", PASSWORD)
        official = make_official(
            user,
            delegation=delegation,
            national_id="RUT-CHECKBOX",
            email="precargado@example.test",
        )
        official.authorized_delegations.add(delegation)
        official.roles.add(role)

        response = self.client.get(reverse("user_update", args=[user.pk]))

        form = response.context["form"]
        self.assertIsInstance(form.fields["roles"].widget, forms.CheckboxSelectMultiple)
        self.assertIsInstance(
            form.fields["authorized_delegations"].widget, forms.CheckboxSelectMultiple
        )
        self.assertEqual(form.initial["roles"], [role.pk])
        self.assertEqual(form.initial["authorized_delegations"], [delegation.pk])
        self.assertContains(response, 'type="checkbox"')
        self.assertContains(response, f'value="{role.pk}"')

    def test_actor_without_role_management_permission_cannot_assign_privileged_role(self):
        delegation = Delegation.objects.create(
            delegation_name="Zona Manager", address="Calle Manager", commune="La Serena"
        )
        manager = User.objects.create_user(
            "manager.sin.roles", "manager.sin.roles@example.test", PASSWORD
        )
        manager_official = make_official(
            manager,
            delegation=delegation,
            national_id="RUT-MANAGER",
        )
        grant_permissions(manager, "auth.change_user")
        target = User.objects.create_user("objetivo.rol", "objetivo.rol@example.test", PASSWORD)
        make_official(
            target,
            delegation=manager_official.delegation,
            national_id="RUT-OBJETIVO-ROL",
        )
        privileged_role = Role.objects.create(role_name="Rol Privilegiado")
        privileged_role.permissions.add(
            Permission.objects.get(content_type__app_label="accounts", codename="change_delegation")
        )

        self.client.force_login(manager)
        response = self.client.post(
            reverse("user_update", args=[target.pk]),
            user_payload(
                username=target.username,
                email=target.email,
                full_name=target.official.full_name,
                national_id=target.official.national_id,
                delegation=manager_official.delegation.pk,
                roles=[privileged_role.pk],
            ),
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "No tienes permisos para asignar roles privilegiados")
        self.assertFalse(target.official.roles.filter(pk=privileged_role.pk).exists())

    def test_global_administrator_role_cannot_be_combined_with_other_roles(self):
        global_admin = Role.objects.create(
            role_name="Administrador Global",
            scope=Role.Scope.ALL,
            description="Permisos generales del sistema",
        )
        global_admin.permissions.add(
            Permission.objects.get(
                content_type__app_label="auth",
                codename="change_user",
            )
        )
        other_role = Role.objects.create(role_name="Rol Operativo")
        target = User.objects.create_user("mezcla.roles", "mezcla.roles@example.test", PASSWORD)
        make_official(target, national_id="RUT-MEZCLA")

        form = OfficialUserForm(
            data=user_payload(
                username=target.username,
                email=target.email,
                full_name=target.official.full_name,
                national_id=target.official.national_id,
                roles=[global_admin.pk, other_role.pk],
            ),
            actor=self.admin,
            instance=target,
            delegation_queryset=Delegation.objects.all(),
        )

        self.assertFalse(form.is_valid())
        self.assertIn("no puede combinarse", form.errors["roles"][0])


class UserScopeTests(TestCase):
    """Un gestor solo ve y administra las cuentas de su ámbito de delegaciones."""

    @classmethod
    def setUpTestData(cls):
        cls.own = Delegation.objects.create(
            delegation_name="Zona Propia", address="Calle Uno", commune="La Serena"
        )
        cls.foreign = Delegation.objects.create(
            delegation_name="Zona Ajena", address="Calle Dos", commune="La Serena"
        )

        cls.manager = User.objects.create_user("gestor.usuarios", "gestor.usuarios@example.test", PASSWORD)
        make_official(
            cls.manager,
            delegation=cls.own,
            national_id="RUT-GESTOR",
            email="gestor.usuarios@example.test",
        )
        grant_permissions(cls.manager, "auth.view_user", "auth.add_user", "auth.change_user")

        cls.own_user = User.objects.create_user("pertenece.propia", "pertenece.propia@example.test", PASSWORD)
        make_official(cls.own_user, delegation=cls.own, national_id="RUT-PROPIA")

        cls.foreign_user = User.objects.create_user("pertenece.ajena", "pertenece.ajena@example.test", PASSWORD)
        make_official(cls.foreign_user, delegation=cls.foreign, national_id="RUT-AJENA")

    def setUp(self):
        self.client.force_login(self.manager)

    def test_list_only_shows_users_of_authorized_delegations(self):
        response = self.client.get(reverse("user_maintainer"))

        self.assertContains(response, "pertenece.propia")
        self.assertNotContains(response, "pertenece.ajena")

    def test_foreign_user_detail_is_not_visible(self):
        response = self.client.get(reverse("user_detail", args=[self.foreign_user.pk]))

        self.assertEqual(response.status_code, 404)

    def test_foreign_user_cannot_be_updated(self):
        response = self.client.post(reverse("user_update", args=[self.foreign_user.pk]), user_payload())

        self.assertEqual(response.status_code, 404)

    def test_foreign_user_cannot_be_deactivated(self):
        response = self.client.post(reverse("user_deactivate", args=[self.foreign_user.pk]))

        self.assertEqual(response.status_code, 404)
        self.foreign_user.refresh_from_db()
        self.assertTrue(self.foreign_user.is_active)

    def test_export_only_includes_authorized_users(self):
        response = self.client.get(reverse("user_export"))
        rows = list(load_workbook(BytesIO(response.content), read_only=True).active.values)
        content = str(rows)

        self.assertIn("pertenece.propia", content)
        self.assertNotIn("pertenece.ajena", content)

    def test_create_form_only_offers_authorized_delegations(self):
        response = self.client.get(reverse("user_create"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Zona Propia")
        self.assertNotContains(response, "Zona Ajena")

    def test_form_rejects_delegation_outside_scope(self):
        response = self.client.post(
            reverse("user_create"),
            user_payload(
                username="fuga.delegacion",
                email="fuga.delegacion@example.test",
                has_official="on",
                full_name="Fuga Delegación",
                national_id="RUT-FUGA",
                delegation=self.foreign.pk,
            ),
        )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(User.objects.filter(username="fuga.delegacion").exists())


class UserPermissionTests(TestCase):
    """Los permisos estándar controlan cada operación del mantenedor de usuarios."""

    @classmethod
    def setUpTestData(cls):
        cls.delegation = Delegation.objects.create(
            delegation_name="Zona Permisos Usuarios", address="Calle Uno", commune="La Serena"
        )
        cls.viewer = User.objects.create_user("viewer.users", "viewer.users@example.test", PASSWORD)
        make_official(cls.viewer, delegation=cls.delegation, national_id="RUT-VIEWER-USERS")
        grant_permissions(cls.viewer, "auth.view_user")

        cls.target = User.objects.create_user("objetivo.users", "objetivo.users@example.test", PASSWORD)
        make_official(cls.target, delegation=cls.delegation, national_id="RUT-OBJETIVO")

    def test_viewer_can_list_but_not_create_or_edit(self):
        self.client.force_login(self.viewer)

        self.assertEqual(self.client.get(reverse("user_maintainer")).status_code, 200)
        self.assertEqual(
            self.client.post(reverse("user_create"), user_payload(username="no.autorizado")).status_code,
            403,
        )
        self.assertEqual(
            self.client.post(reverse("user_update", args=[self.target.pk]), user_payload()).status_code,
            403,
        )
        self.assertFalse(User.objects.filter(username="no.autorizado").exists())
