"""Cancelados con justificación en «Soluciones de ingresos al tubo» (mismo criterio que «Pendientes en tubo»)."""
from datetime import date, datetime, time
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from agenda.models import Commitment, CommitmentStatusHistory
from analytics.services import CalculadorDesempenoService as Calc, q2
from analytics.test_performance_calculator import END, START, CalculatorFixture
from common.sgr_seed_data import PERCENTAGE_ITEM

STAMP = timezone.make_aware(datetime.combine(START, time(9)))
REASON = "Cancelado por causa documentada"


class TubeCancellationTests(CalculatorFixture, TestCase):
    def setUp(self):
        self.worker = self.official("Gestora del tubo", "Gestor social")

    def commitment(self, status, reason=""):
        return Commitment.objects.create(responsible=self.worker, requester="Vecino ficticio", territory="Centro",
                                         committed_date=date(2026, 9, 1), creation_date=STAMP, current_status=status,
                                         cancellation_reason=reason)

    def progress(self, on_date=END):
        return self.rows(Calc.calculate(self.worker, self.period, on_date))[PERCENTAGE_ITEM].progress

    def test_without_cancellations_the_rule_is_unchanged(self):
        for status in ("DONE", "DONE", "DONE", "PENDING"):
            self.commitment(status)
        self.assertEqual(self.progress(), 75)

    def test_exact_cal_c_batch_with_cancellations(self):
        # Lote CAL-C de la guía: 8 Realizados, 1 Pendiente y 1 En proceso → 80 % con meta 80 % = 100 %.
        for status in ["DONE"] * 8 + ["PENDING", "IN_PROGRESS"]:
            self.commitment(status)
        row = self.rows(Calc.calculate(self.worker, self.period, END))[PERCENTAGE_ITEM]
        self.assertEqual((row.progress, row.compliance), (80, 100))
        # Cancelados con justificación: no cambian la razón del lote (8 de 10).
        self.commitment("CANCELLED", REASON)
        self.commitment("CANCELLED", REASON)
        row = self.rows(Calc.calculate(self.worker, self.period, END))[PERCENTAGE_ITEM]
        self.assertEqual((row.progress, row.compliance), (80, 100))
        # Un cancelado sin justificación (dato legado) sí cuenta como no realizado: 8 de 11.
        self.commitment("CANCELLED")
        row = self.rows(Calc.calculate(self.worker, self.period, END))[PERCENTAGE_ITEM]
        self.assertEqual(row.progress, Decimal(8) / 11 * 100)
        self.assertEqual(q2(row.compliance), q2(Decimal(8) / 11 * 100 / 80 * 100))
        # Congelado: el respaldo trae los 11 del denominador y 8 en el numerador.
        self.period.close_period()
        snapshot = Calc.frozen_snapshots(self.period).get(official=self.worker, item=self.items[PERCENTAGE_ITEM])
        self.assertEqual((snapshot.supports.count(), snapshot.supports.filter(in_numerator=True).count()), (11, 8))
        self.assertEqual(snapshot.progress, q2(Decimal(8) / 11 * 100))

    def test_justified_cancellations_leave_numerator_and_denominator(self):
        for status in ("DONE", "DONE", "DONE", "PENDING"):
            self.commitment(status)
        self.commitment("CANCELLED", REASON)
        self.commitment("CANCELLED", REASON)
        self.assertEqual(self.progress(), 75)  # 3 de 4, no 3 de 6

    def test_cancellation_without_reason_still_counts(self):
        self.commitment("DONE")
        self.commitment("CANCELLED")  # dato legado sin justificación
        self.assertEqual(self.progress(), 50)

    def test_cancelled_after_the_cutoff_counts_as_it_was(self):
        self.commitment("DONE")
        late = self.commitment("CANCELLED", REASON)
        CommitmentStatusHistory.objects.create(
            commitment=late, author=self.verifier, previous_status="PENDING", new_status="CANCELLED",
            date=timezone.make_aware(datetime.combine(date(2026, 9, 20), time(10))), observation=REASON)
        self.assertEqual(self.progress(date(2026, 9, 10)), 50)  # al 10/9 estaba pendiente
        self.assertEqual(self.progress(END), 100)  # al cierre ya estaba cancelado con justificación

    def test_all_cancelled_means_no_denominator(self):
        self.commitment("CANCELLED", REASON)
        self.commitment("CANCELLED", REASON)
        row = self.rows(Calc.calculate(self.worker, self.period, END))[PERCENTAGE_ITEM]
        self.assertIsNone(row.progress)
        self.assertEqual(row.weighted, 0)
        self.assertIn("Sin compromisos", row.notice)

    def test_frozen_period_and_support_use_the_same_criterion(self):
        for status in ("DONE", "PENDING"):
            self.commitment(status)
        cancelled = self.commitment("CANCELLED", REASON)
        self.period.close_period()
        snapshot = Calc.frozen_snapshots(self.period).get(official=self.worker, item=self.items[PERCENTAGE_ITEM])
        self.assertEqual(snapshot.progress, 50)
        supports = snapshot.supports.all()
        self.assertEqual(supports.count(), 2)
        self.assertFalse(supports.filter(commitment=cancelled).exists())
        numerator = supports.filter(in_numerator=True).count()
        self.assertEqual(q2(Decimal(numerator) / supports.count() * 100), snapshot.progress)
        # Un cambio posterior no altera el congelado.
        Commitment.objects.filter(pk=cancelled.pk).update(current_status="DONE", cancellation_reason="")
        self.assertEqual(self.rows(Calc.result_for(self.worker, self.period))[PERCENTAGE_ITEM].progress, 50)
