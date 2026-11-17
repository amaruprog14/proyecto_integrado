"""Reversión automática de analytics.0006 (MAX_PERCENTAGE, metas nulas y columnas de tramos).

Migra a 0006 (deshaciendo 0007 en adelante), carga datos que el esquema anterior no admite, revierte
a 0005, comprueba la conversión y el esquema restaurado y vuelve a migrar hasta las hojas actuales.
"""
from datetime import date
from decimal import Decimal

from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase

BEFORE = ("analytics", "0005_territorial_activity_reconciliation")
TARGET = ("analytics", "0006_measurement_rules")
NEW_COLUMNS = {"computable_days", "elapsed_days", "segments", "result_notice"}


class Analytics0006ReversalTests(TransactionTestCase):
    def executor(self):
        return MigrationExecutor(connection)

    def migrate(self, targets):
        executor = self.executor()
        executor.loader.build_graph()
        executor.migrate(targets)
        return executor.loader.project_state(targets).apps

    def columns(self, table):
        with connection.cursor() as cursor:
            return {column.name for column in connection.introspection.get_table_description(cursor, table)}

    def column_size(self, table, name):
        with connection.cursor() as cursor:
            return next(column.internal_size for column in connection.introspection.get_table_description(cursor, table)
                        if column.name == name)

    def tearDown(self):
        # Siempre se vuelve al esquema completo, aunque el test falle a mitad de camino.
        executor = self.executor()
        executor.migrate(executor.loader.graph.leaf_nodes())
        super().tearDown()

    def seed(self, apps):
        Period = apps.get_model("configuration", "Period")
        Item = apps.get_model("configuration", "Item")
        Position = apps.get_model("accounts", "Position")
        Function = apps.get_model("accounts", "Function")
        Official = apps.get_model("accounts", "Official")
        Plan = apps.get_model("analytics", "MeasurementPlan")
        Version = apps.get_model("analytics", "MeasurementVersion")
        Line = apps.get_model("analytics", "MeasurementItem")
        Snapshot = apps.get_model("analytics", "IndicatorSnapshot")

        period = Period.objects.create(start_date=date(2026, 7, 1), end_date=date(2026, 9, 30))
        item = Item.objects.create(item_name="Pendientes en tubo de reversión")
        position = Position.objects.create(position_name="Cargo de reversión")
        function = Function.objects.create(function_name="Función de reversión")
        official = Official.objects.create(full_name="Funcionario de reversión", national_id="REV-1",
                                           email="reversion@example.test", position=position)
        plan = Plan.objects.create(period=period, position=position)
        version = Version.objects.create(plan=plan, number=1, effective_from=period.start_date)
        line = Line.objects.create(version=version, function=function, item=item, goal_type="MAX_PERCENTAGE",
                                   goal=Decimal("10"), weight=Decimal("100"))
        common = {"official": official, "item": item, "period": period, "version": version}
        max_snapshot = Snapshot.objects.create(goal_type="MAX_PERCENTAGE", goal=Decimal("10"), computable_days=91,
                                               elapsed_days=91, segments=[], result_notice="", **common)
        null_goal = Snapshot.objects.create(goal_type="QUANTITY", goal=None, computable_days=91, elapsed_days=91,
                                            segments=[{"days": 45}, {"days": 46}],
                                            result_notice="Resultado calculado por tramos de cargo", **common)
        return line.pk, max_snapshot.pk, null_goal.pk

    def test_reverting_to_0005_converts_data_restores_schema_and_migrates_forward(self):
        apps = self.migrate([TARGET])
        snapshot_table = apps.get_model("analytics", "IndicatorSnapshot")._meta.db_table
        line_table = apps.get_model("analytics", "MeasurementItem")._meta.db_table
        self.assertTrue(NEW_COLUMNS <= self.columns(snapshot_table))
        line_pk, max_pk, null_pk = self.seed(apps)

        apps = self.migrate([BEFORE])
        self.assertFalse(NEW_COLUMNS & self.columns(snapshot_table))
        Line = apps.get_model("analytics", "MeasurementItem")
        Snapshot = apps.get_model("analytics", "IndicatorSnapshot")
        self.assertEqual(Line.objects.get(pk=line_pk).goal_type, "PERCENTAGE")
        self.assertEqual(Snapshot.objects.get(pk=max_pk).goal_type, "PERCENTAGE")
        self.assertEqual(Snapshot.objects.get(pk=null_pk).goal, Decimal("0"))
        self.assertFalse(Snapshot.objects.filter(goal__isnull=True).exists())
        self.assertFalse(Line.objects.filter(goal_type="MAX_PERCENTAGE").exists())
        if connection.vendor == "mysql":  # SQLite no informa el largo de VARCHAR
            self.assertEqual(self.column_size(line_table, "goal_type"), 10)

        executor = self.executor()
        leaves = executor.loader.graph.leaf_nodes()
        executor.migrate(leaves)
        self.assertTrue(NEW_COLUMNS <= self.columns(snapshot_table))
        self.assertFalse(self.executor().migration_plan(leaves))  # nada pendiente: volvió a la hoja actual
