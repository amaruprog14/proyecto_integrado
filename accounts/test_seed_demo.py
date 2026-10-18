"""Datos de demostración (seed_demo): delegaciones, roles, contexto de cada funcionario y acceso."""
from datetime import timedelta
from io import StringIO
from unittest import mock

from django.contrib.auth.models import Group, Permission, User
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import Area, Delegation, Official, Position, Role
from activities.models import Activity
from configuration.models import Item, Period

SEEDED_USERNAMES = ("admin_demo", "funcionario1", "funcionario2", "funcionario3", "funcionario4", "consulta_norte")


def run_seed():
    call_command("seed_demo", stdout=StringIO())


def permission_names(queryset):
    return {f"{p.content_type.app_label}.{p.codename}" for p in queryset.select_related("content_type")}


def snapshot():
    """Cantidad de filas de cada tabla que toca el seed, incluidas las relaciones M2M."""
    counts = {
        model.__name__: model.objects.count()
        for model in (User, Group, Area, Position, Delegation, Role, Official, Item, Period, Activity)
    }
    counts.update(
        role_permissions=Role.permissions.through.objects.count(),
        role_officials=Role.officials.through.objects.count(),
        authorized_delegations=Official.authorized_delegations.through.objects.count(),
        group_permissions=Group.permissions.through.objects.count(),
        user_groups=User.groups.through.objects.count(),
    )
    return counts


class SeedDemoDataTests(TestCase):
    def setUp(self):
        run_seed()

    def test_creates_three_active_delegations_and_one_inactive(self):
        active = Delegation.objects.filter(status=Delegation.Status.ACTIVE)

        self.assertEqual(
            sorted(active.values_list("code", "delegation_name")),
            [("D01", "Centro"), ("D02", "Norte"), ("D03", "Sur")],
        )
        self.assertEqual(Delegation.objects.filter(status=Delegation.Status.INACTIVE).count(), 1)
        for delegation in Delegation.objects.all():
            with self.subTest(delegation=delegation.delegation_name):
                self.assertTrue(delegation.address)
                self.assertTrue(delegation.commune)

    def test_creates_the_six_roles_with_their_scope_and_permissions(self):
        expected_scopes = {
            "Administrador": Role.Scope.ALL,
            "Coordinador": Role.Scope.ALL,
            "Supervisor": Role.Scope.DELEGATION,
            "Operador": Role.Scope.DELEGATION,
            "Verificador": Role.Scope.DELEGATION,
            "Consulta": Role.Scope.DELEGATION,
        }

        self.assertEqual(dict(Role.objects.values_list("role_name", "scope")), expected_scopes)
        for role in Role.objects.all():
            with self.subTest(role=role.role_name):
                self.assertTrue(role.is_active)
                self.assertTrue(role.permissions.exists())
                self.assertFalse(role.permissions.filter(codename__startswith="delete_").exists())

    def test_permissions_come_only_from_roles(self):
        for username in SEEDED_USERNAMES[1:] + ("funcionario5",):  # admin_demo es superusuario
            with self.subTest(username=username):
                user = User.objects.get(username=username)

                self.assertFalse(user.groups.exists())
                self.assertFalse(user.user_permissions.exists())
                self.assertEqual(
                    user.get_all_permissions(),
                    permission_names(Permission.objects.filter(sgr_roles__officials__user=user)),
                )

    def test_coordinator_and_supervisor_also_hold_the_operator_role(self):
        for username, main_role in (("funcionario3", "Coordinador"), ("funcionario4", "Supervisor")):
            with self.subTest(username=username):
                official = User.objects.get(username=username).official

                self.assertEqual(
                    set(official.roles.values_list("role_name", flat=True)), {main_role, "Operador"}
                )

    def test_reseeding_removes_demo_users_from_legacy_groups(self):
        group = Group.objects.create(name="Funcionarios")
        group.permissions.add(Permission.objects.get(content_type__app_label="activities", codename="add_activity"))
        user = User.objects.get(username="funcionario1")
        user.groups.add(group)

        run_seed()

        self.assertFalse(user.groups.exists())
        self.assertTrue(Group.objects.filter(name="Funcionarios").exists())

    def test_administrator_role_manages_the_system_but_cannot_alter_the_audit_log(self):
        permissions = permission_names(Role.objects.get(role_name="Administrador").permissions.all())

        self.assertTrue(
            {"accounts.change_delegation", "accounts.change_role", "auth.change_user",
             "configuration.change_item", "configuration.view_auditlog"} <= permissions
        )
        self.assertFalse({"configuration.add_auditlog", "configuration.change_auditlog"} & permissions)

    def test_every_seeded_official_has_a_delegation_and_a_role(self):
        officials = Official.objects.all()

        self.assertEqual(officials.count(), 7)
        for official in officials:
            with self.subTest(official=official.full_name):
                self.assertIsNotNone(official.delegation)
                self.assertTrue(official.roles.exists())

    def test_funcionario1_is_an_operator_in_centro(self):
        official = User.objects.get(username="funcionario1").official

        self.assertEqual(official.delegation.delegation_name, "Centro")
        self.assertEqual(list(official.roles.values_list("role_name", flat=True)), ["Operador"])
        self.assertEqual(list(official.get_authorized_delegations()), [official.delegation])

    def test_one_official_has_two_authorized_delegations(self):
        official = User.objects.get(username="funcionario4").official

        self.assertEqual(official.authorized_delegations.count(), 2)
        self.assertEqual(
            set(official.get_authorized_delegations().values_list("delegation_name", flat=True)),
            {"Sur", "Norte"},
        )

    def test_admin_demo_has_an_administrator_official_with_all_scope(self):
        official = User.objects.get(username="admin_demo").official

        self.assertEqual(list(official.roles.values_list("role_name", "scope")), [("Administrador", Role.Scope.ALL)])
        self.assertEqual(
            set(official.get_authorized_delegations()),
            set(Delegation.objects.filter(status=Delegation.Status.ACTIVE)),
        )

    def test_funcionario5_keeps_no_context(self):
        archived = Official.objects.get(email="funcionario5@demo.cl")

        self.assertIsNotNone(archived.deleted_at)
        self.assertIsNone(archived.user)
        self.assertFalse(Official.objects.filter(user__username="funcionario5").exists())

    def test_header_shows_delegation_and_role(self):
        for username in SEEDED_USERNAMES:
            with self.subTest(username=username):
                user = User.objects.get(username=username)
                self.client.force_login(user)

                response = self.client.get(reverse("home"))

                delegation = user.official.delegation
                self.assertContains(response, f"{delegation.code} · {delegation.delegation_name}")
                self.assertNotContains(response, "Sin delegación asignada")
                self.assertNotContains(response, "Sin rol asignado")

    def test_running_twice_does_not_duplicate_or_touch_data(self):
        before = snapshot()
        last_update = Official.objects.order_by("-updated_at").values_list("updated_at", flat=True).first()

        run_seed()

        self.assertEqual(snapshot(), before)
        self.assertEqual(
            Official.objects.order_by("-updated_at").values_list("updated_at", flat=True).first(),
            last_update,
        )

    def test_running_on_another_day_does_not_duplicate_data(self):
        before = snapshot()
        now = timezone.now()
        another_day = now.replace(day=2 if now.day != 2 else 3)

        with mock.patch("django.utils.timezone.now", return_value=another_day):
            run_seed()

        self.assertEqual(snapshot(), before)


class SeedDemoAccessTests(TestCase):
    """ACC-01 con los datos de demostración: cada perfil ve solo lo autorizado."""

    def setUp(self):
        run_seed()

    def login(self, username):
        self.client.force_login(User.objects.get(username=username))

    def assertStatus(self, route_name, status_code):
        self.assertEqual(self.client.get(reverse(route_name)).status_code, status_code, route_name)

    def test_operator_registers_attentions_but_does_not_administer(self):
        self.login("funcionario1")

        self.assertStatus("attention_entry", 200)
        self.assertStatus("activity_maintainer", 200)
        self.assertStatus("delegation_list", 403)
        self.assertStatus("period_maintainer", 403)

    def test_read_only_profile_cannot_register_attentions(self):
        self.login("consulta_norte")

        self.assertStatus("activity_maintainer", 200)
        self.assertStatus("attention_entry", 403)

    def test_role_permissions_open_their_screens(self):
        self.login("funcionario3")  # Coordinador
        self.assertStatus("period_maintainer", 200)
        self.assertStatus("attention_type_maintainer", 200)
        self.assertStatus("role_list", 403)

        self.login("funcionario4")  # Supervisor y Operador
        self.assertStatus("delegation_list", 200)
        self.assertStatus("attention_entry", 200)
        self.assertStatus("user_maintainer", 403)

    def test_deactivating_the_operator_role_removes_the_access_it_granted(self):
        Role.objects.filter(role_name="Operador").update(is_active=False)

        self.login("funcionario1")  # solo Operador
        self.assertStatus("attention_entry", 403)
        self.assertStatus("activity_maintainer", 403)

        self.login("funcionario3")  # conserva lo que otorga Coordinador
        self.assertStatus("attention_entry", 403)
        self.assertStatus("period_maintainer", 200)

    def test_user_without_context_is_denied(self):
        self.login("funcionario5")

        self.assertStatus("activity_maintainer", 403)

    def test_admin_demo_reaches_every_screen(self):
        self.login("admin_demo")

        for route_name in ("delegation_list", "role_list", "user_maintainer", "attention_entry", "period_maintainer"):
            self.assertStatus(route_name, 200)
