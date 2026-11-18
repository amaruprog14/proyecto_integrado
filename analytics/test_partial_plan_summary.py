"""RF-028/RF-033: presentar los aportes de tramos anteriores aunque falte el plan final."""
from datetime import date
from decimal import Decimal
from io import BytesIO
from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from openpyxl import load_workbook

from accounts.models import Position
from accounts.position_services import change_position
from analytics.models import IndicatorSnapshot, ScoreAdjustment
from analytics.services import CalculadorDesempenoService as Calc, q2
from analytics.test_performance_calculator import CalculatorFixture, END, START


@override_settings(PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"])
@patch("analytics.views.timezone.localdate", return_value=END)
class PartialPlanSummaryTests(CalculatorFixture, TestCase):
    def setUp(self):
        self.worker = self.official("Funcionario por tramos", "Gestor social")
        self.admin = User.objects.create_superuser("resumen-admin", "resumen@example.test", "test-password")
        self.recorder = User.objects.create_user("registro-ajustes")
        self.client.force_login(self.admin)
        self.version = self.plans["Gestor social"].versions.get()
        self.version.items.exclude(item=self.items["Visita terreno"]).delete()
        line = self.version.items.get()
        line.goal, line.weight = 10, 100
        line.save()

    def without_final_plan(self):
        position = Position.objects.create(position_name="Cargo final sin plan")
        change_position(self.worker, position, date(2026, 9, 1), self.verifier)

    def adjustment(self, points):
        return ScoreAdjustment.objects.create(
            official=self.worker, period=self.period, occurred_on=START,
            kind=ScoreAdjustment.Kind.CONGRATULATION if points > 0 else ScoreAdjustment.Kind.COMPLAINT,
            channel=ScoreAdjustment.Channel.EMAIL, reason="Ajuste de prueba",
            written_support="Respaldo ficticio", status=ScoreAdjustment.Status.APPROVED,
            recorded_by=self.recorder, reviewed_by=self.admin, reviewed_at=timezone.now(),
            version=self.version, points=points,
        )

    def panel(self):
        response = self.client.get(reverse("my_performance"), {"period": self.period.pk, "official": self.worker.pk})
        self.assertEqual(response.status_code, 200)
        return response

    def workbook(self):
        response = self.client.get(reverse("my_performance"), {
            "period": self.period.pk, "official": self.worker.pk, "export": "xlsx",
        })
        self.assertEqual(response.status_code, 200)
        return load_workbook(BytesIO(response.content))

    def assert_summary(self, response, book, result):
        self.assertContains(response, "data-performance-total")
        self.assertContains(response, "data-performance-base")
        self.assertContains(response, "data-plan-coverage-notice")
        self.assertContains(response, result.plan_coverage_notice)
        summary = dict(book["Resumen"].values)
        for label, value in (
            ("Total ponderado base (puntos)", result.base_total),
            ("Ajustes computables (puntos)", result.score_adjustment_total),
            ("Tope del resultado final (puntos)", result.max_final_score),
            ("Piso del resultado final (puntos)", result.min_final_score),
            ("Resultado final (puntos)", result.total),
        ):
            self.assertEqual(q2(Decimal(str(summary[label]))), q2(value), label)
        self.assertEqual(summary["Cobertura del plan"], result.plan_coverage_notice)
        self.assertEqual(summary["Semáforo"], "Sin semáforo")
        segments = list(book["Tramos de cargo"].values)
        self.assertEqual(len(segments), 3)
        self.assertEqual(segments[1][5], "Sí")
        self.assertEqual(segments[2][5], "Sin plan publicado")
        self.assertEqual(segments[2][1].date(), date(2026, 9, 1))
        self.assertNotContains(response, "Tope computable por ítem:  %")

    def test_live_summary_shows_previous_contribution_adjustment_and_cap(self, _today):
        self.version.max_final_score = 40
        self.version.save(update_fields=["max_final_score"])
        self.record(self.worker, "Visita terreno", 15, day=date(2026, 7, 10))
        self.adjustment(10)
        self.without_final_plan()
        result = Calc.calculate(self.worker, self.period, END)
        self.assertIsNone(result.version)
        self.assertTrue(result.items)
        self.assertEqual(result.total, 40)
        self.assertEqual(result.score_adjustment_total, 10)
        response = self.panel()
        self.assertContains(response, "data-performance-cap")
        self.assert_summary(response, self.workbook(), result)

    def test_zero_result_and_complaint_still_show_floor_and_adjustment(self, _today):
        self.adjustment(-20)
        self.without_final_plan()
        result = Calc.calculate(self.worker, self.period, END)
        self.assertEqual((result.base_total, result.score_adjustment_total, result.total), (0, -20, 0))
        response = self.panel()
        self.assertContains(response, "data-performance-floor")
        self.assert_summary(response, self.workbook(), result)

    def test_frozen_summary_uses_saved_figures_and_segments(self, _today):
        self.version.max_final_score = 40
        self.version.save(update_fields=["max_final_score"])
        self.record(self.worker, "Visita terreno", 15, day=date(2026, 7, 10))
        self.adjustment(10)
        self.without_final_plan()
        self.period.close_period()
        self.period.refresh_from_db()
        result = Calc.result_for(self.worker, self.period)
        before = list(IndicatorSnapshot.objects.filter(period=self.period).values())
        with patch.object(Calc, "calculate_many", side_effect=AssertionError("Un resultado cerrado debe leerse del congelado")):
            self.assert_summary(self.panel(), self.workbook(), result)
        after = list(IndicatorSnapshot.objects.filter(period=self.period).values())
        self.assertEqual(before, after)
        self.assertTrue(result.frozen)
        self.assertEqual(result.total, 40)

    def test_without_any_plan_keeps_the_missing_plan_message(self, _today):
        self.worker.position = Position.objects.create(position_name="Sin plan en todo el período")
        self.worker.save(update_fields=["position"])
        response = self.panel()
        self.assertContains(response, "No hay un plan de medición publicado")
        self.assertNotContains(response, "data-performance-total")
        self.assertNotContains(response, "data-plan-coverage-notice")
        book = self.workbook()
        self.assertNotIn("Resultado final (puntos)", dict(book["Resumen"].values))
        self.assertNotIn("Tramos de cargo", book.sheetnames)

    def test_result_with_current_plan_keeps_the_existing_presentation(self, _today):
        self.record(self.worker, "Visita terreno", 10)
        response = self.panel()
        self.assertContains(response, "data-performance-total")
        self.assertNotContains(response, "data-plan-coverage-notice")
        book = self.workbook()
        self.assertEqual(dict(book["Resumen"].values)["Resultado final (puntos)"], 100)
        self.assertNotIn("Tramos de cargo", book.sheetnames)
