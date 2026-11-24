from datetime import date

from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase
from django.utils import timezone


class FinalScoreCapMigrationTests(TransactionTestCase):
    def test_only_excessive_draft_caps_change(self):
        before = [("analytics", "0009_frozen_support_and_final_score_cap")]
        executor = MigrationExecutor(connection)
        leaves = executor.loader.graph.leaf_nodes()
        self.addCleanup(lambda: MigrationExecutor(connection).migrate(leaves))
        executor.migrate(before)
        apps = executor.loader.project_state(before).apps
        period = apps.get_model("configuration", "Period").objects.create(
            start_date=date(2026, 7, 1), end_date=date(2026, 9, 30),
        )
        position = apps.get_model("accounts", "Position").objects.create(position_name="Cargo de prueba")
        plan = apps.get_model("analytics", "MeasurementPlan").objects.create(period=period, position=position)
        versions = apps.get_model("analytics", "MeasurementVersion").objects
        for number, (cap, published) in enumerate(((150, True), (200, False), (90, False)), start=1):
            versions.create(plan=plan, number=number, effective_from=period.start_date,
                            published_at=timezone.now() if published else None, max_final_score=cap)

        MigrationExecutor(connection).migrate([("analytics", "0010_limit_individual_final_score")])
        self.assertEqual(list(versions.filter(plan=plan).order_by("number")
                              .values_list("max_final_score", flat=True)), [150, 120, 90])
