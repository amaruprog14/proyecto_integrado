"""Ida y vuelta de accounts/0015: permisos de Ausencias para los roles creados por la semilla."""
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase


class Accounts0015RoundTripTests(TransactionTestCase):
    """accounts/0015 asigna los permisos de Ausencias a los roles de la semilla y se puede revertir."""

    BEFORE = ("accounts", "0014_measurement_rules")
    TARGET = ("accounts", "0015_absence_seed_roles")
    CODES = {"view_officialabsence", "manage_absence"}
    MARKER = "[SGR seed v1] Perfil de acceso del caso SGR."

    def migrate(self, targets):
        executor = MigrationExecutor(connection)
        executor.migrate(targets)
        return executor.loader.project_state(targets).apps

    def tearDown(self):
        executor = MigrationExecutor(connection)
        executor.migrate(executor.loader.graph.leaf_nodes())
        super().tearDown()

    def codes(self, apps, name):
        Role = apps.get_model("accounts", "Role")
        return set(Role.objects.get(role_name=name).permissions.filter(codename__in=self.CODES)
                   .values_list("codename", flat=True))

    def test_grant_revoke_and_grant_again(self):
        apps = self.migrate([self.BEFORE])
        Role = apps.get_model("accounts", "Role")
        Permission = apps.get_model("auth", "Permission")
        ContentType = apps.get_model("contenttypes", "ContentType")
        content_type, _ = ContentType.objects.get_or_create(app_label="accounts", model="officialabsence")
        absence_permissions = [Permission.objects.get_or_create(content_type=content_type, codename=code,
                                                                defaults={"name": code})[0] for code in self.CODES]
        for name, scope in (("Administrador", "ALL"), ("Coordinador del sistema", "ALL"), ("Delegado", "DELEGATION"),
                            ("Funcionario", "DELEGATION"), ("Verificador", "DELEGATION")):
            Role.objects.create(role_name=name, scope=scope, description=self.MARKER)
        Role.objects.get(role_name="Administrador").permissions.add(*absence_permissions)  # ya los tenía
        Role.objects.create(role_name="Delegado municipal", scope="DELEGATION", description="Rol propio")

        apps = self.migrate([self.TARGET])
        for name in ("Administrador", "Coordinador del sistema", "Delegado"):
            self.assertEqual(self.codes(apps, name), self.CODES, name)
        for name in ("Funcionario", "Verificador", "Delegado municipal"):
            self.assertEqual(self.codes(apps, name), set(), name)

        apps = self.migrate([self.BEFORE])
        self.assertEqual(self.codes(apps, "Administrador"), self.CODES)  # no se le quitan
        for name in ("Coordinador del sistema", "Delegado", "Funcionario", "Verificador"):
            self.assertEqual(self.codes(apps, name), set(), name)

        apps = self.migrate([self.TARGET])
        for name in ("Coordinador del sistema", "Delegado"):
            self.assertEqual(self.codes(apps, name), self.CODES, name)
        self.assertEqual(apps.get_model("accounts", "Role").objects.get(role_name="Delegado").permissions
                         .filter(codename__in=self.CODES).count(), 2)  # sin duplicados al repetir
