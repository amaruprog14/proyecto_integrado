"""Reversión conservadora de analytics/0008 sin pérdida de permisos manuales."""
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase


class ScoreRoleMigrationTests(TransactionTestCase):
    BEFORE = ("analytics", "0007_score_adjustments")
    TARGET = ("analytics", "0008_score_adjustment_roles")

    def migrate(self, target):
        executor = MigrationExecutor(connection)
        executor.migrate([target])
        return executor.loader.project_state([target]).apps

    def tearDown(self):
        executor = MigrationExecutor(connection)
        executor.migrate(executor.loader.graph.leaf_nodes())
        super().tearDown()

    def assignments(self, apps):
        Role = apps.get_model("accounts", "Role")
        return {role.pk: set(role.permissions.values_list("pk", flat=True)) for role in Role.objects.all()}

    def test_reverse_preserves_manual_and_granted_permissions_and_reapply_is_idempotent(self):
        apps = self.migrate(self.BEFORE)
        ContentType = apps.get_model("contenttypes", "ContentType")
        Permission = apps.get_model("auth", "Permission")
        Role = apps.get_model("accounts", "Role")
        content_type, _ = ContentType.objects.get_or_create(app_label="analytics", model="scoreadjustment")
        view, _ = Permission.objects.get_or_create(content_type=content_type, codename="view_scoreadjustment", defaults={"name": "Consulta"})
        review, _ = Permission.objects.get_or_create(content_type=content_type, codename="review_scoreadjustment", defaults={"name": "Validación"})
        unrelated = Permission.objects.create(content_type=content_type, codename="unrelated_test_permission", name="Otro permiso")
        roles = {}
        for name, scope in (("Administrador", "ALL"), ("Coordinador del sistema", "ALL"),
                            ("Funcionario", "DELEGATION"), ("Delegado", "DELEGATION")):
            role = Role.objects.create(role_name=name, scope=scope, description="[SGR seed v1] Perfil")
            role.permissions.add(view, unrelated)
            roles[name] = role.pk
        custom = Role.objects.create(role_name="Coordinador propio", scope="ALL", description="Rol del equipo")
        custom.permissions.add(review)
        apps = self.migrate(self.TARGET)
        Role = apps.get_model("accounts", "Role")
        for name in ("Administrador", "Coordinador del sistema"):
            self.assertEqual(Role.objects.get(pk=roles[name]).permissions.filter(content_type_id=content_type.pk,
                codename__in=["view_scoreadjustment", "add_scoreadjustment", "review_scoreadjustment"]).count(), 3)
        for name in ("Funcionario", "Delegado"):
            role = Role.objects.get(pk=roles[name])
            self.assertEqual(role.permissions.filter(codename__in=["view_scoreadjustment", "add_scoreadjustment"]).count(), 2)
            self.assertFalse(role.permissions.filter(pk=review.pk).exists())
        self.assertEqual(set(Role.objects.get(pk=custom.pk).permissions.values_list("pk", flat=True)), {review.pk})
        after_grant = self.assignments(apps)
        apps = self.migrate(self.BEFORE)
        self.assertEqual(self.assignments(apps), after_grant)
        apps = self.migrate(self.TARGET)
        self.assertEqual(self.assignments(apps), after_grant)

        # Una modificación posterior del administrador tampoco se deshace al revertir.
        Role = apps.get_model("accounts", "Role")
        Role.objects.get(pk=roles["Coordinador del sistema"]).permissions.remove(view.pk)
        Role.objects.get(pk=roles["Delegado"]).permissions.add(review.pk)
        after_manual_change = self.assignments(apps)
        apps = self.migrate(self.BEFORE)
        self.assertEqual(self.assignments(apps), after_manual_change)
