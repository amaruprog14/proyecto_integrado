"""Calculador de desempeño sobre planes publicados (RF-022 a RF-026, RN-001 a RN-008, guía §15.3)."""
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from itertools import count

from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from accounts.models import Delegation, Function, Official, Position
from activities.models import Activity, Evidence, EvidenceValidation
from agenda.models import Commitment, CommitmentStatusHistory
from analytics.measurement import create_revision, publish_version
from analytics.models import IndicatorSnapshot, MeasurementAdjustment, MeasurementItem, MeasurementPlan
from analytics.services import CalculadorDesempenoService as Calc, computable_days, q2, traffic_light
from common.sgr_seed_data import PERCENTAGE_ITEM, POSITION_PLANS
from configuration.models import Item, Period

START, END = date(2026, 7, 1), date(2026, 9, 30)
SERIAL = count(1)


class CalculatorFixture:
    @classmethod
    def setUpTestData(cls):
        cls.delegation = Delegation.objects.create(delegation_name="Centro", address="Calle 1", commune="La Serena")
        cls.period = Period.objects.create(start_date=START, end_date=END)
        cls.items, cls.positions, cls.plans = {}, {}, {}
        for name in ("Apoyo administrativo", "Coordinador de servicios comunitarios", "Gestor social"):
            cls.plans[name] = cls.make_plan(name, POSITION_PLANS[name])
        cls.verifier = cls.official("Verificador")

    @classmethod
    def make_plan(cls, name, rows, period=None):
        period = period or cls.period
        position = cls.positions[name] = Position.objects.create(position_name=name)
        function = Function.objects.create(function_name=f"Funciones de {name}")
        function.positions.add(position)
        plan = MeasurementPlan.objects.create(period=period, position=position)
        version = plan.versions.create(number=1, effective_from=period.start_date)
        for item_name, weight, goal in rows:
            item = cls.items.get(item_name) or Item.objects.create(item_name=item_name)
            cls.items[item_name] = item
            MeasurementItem.objects.create(
                version=version, function=function, item=item, goal=goal, weight=Decimal(weight),
                goal_type=MeasurementItem.GoalType.PERCENTAGE if item_name == PERCENTAGE_ITEM
                else MeasurementItem.GoalType.QUANTITY,
            )
        publish_version(version)
        return plan

    @classmethod
    def official(cls, name, position=None):
        serial = next(SERIAL)
        return Official.objects.create(
            full_name=name, national_id=f"CALC-{serial}", email=f"calc{serial}@example.test",
            delegation=cls.delegation, position=cls.positions.get(position),
        )

    def record(self, official, item_name, quantity, day=date(2026, 8, 1), status=EvidenceValidation.Status.APPROVED):
        """Crea `quantity` actividades con una imagen y una validación en `status` (None = sin revisar)."""
        # Una a una: en MySQL bulk_create no devuelve las PK que necesitan las evidencias.
        activities = [
            Activity.objects.create(code=f"T-{next(SERIAL)}", official=official, item=self.items[item_name], date=day,
                                    record_type=Activity.RecordType.FIELD)
            for _ in range(quantity)
        ]
        evidences = [
            Evidence.objects.create(activity=activity, file_url="x.png", file_format="png", size_kb=1)
            for activity in activities
        ]
        if status:
            EvidenceValidation.objects.bulk_create([
                EvidenceValidation(evidence=evidence, verifier=self.verifier, status=status, validated_at=timezone.now())
                for evidence in evidences
            ])
        return activities

    @staticmethod
    def rows(result):
        return {row.item.item_name: row for row in result.items}


class KnownCaseTests(CalculatorFixture, TestCase):
    """Conjunto conocido calculado a mano (guía §15.3)."""

    def test_apoyo_administrativo_with_real_goals_and_weights(self):
        official = self.official("Apoyo", "Apoyo administrativo")
        self.record(official, "Atención de usuario teléfono y presencial", 314)
        self.record(official, "Informe de inventarios", 1)
        result = Calc.calculate(official, self.period, END)
        rows = self.rows(result)

        attention = rows["Atención de usuario teléfono y presencial"]
        self.assertEqual((attention.goal, attention.weight, attention.progress), (240, 20, 314))
        self.assertEqual(q2(attention.compliance), Decimal("130.83"))
        self.assertEqual(q2(attention.weighted), Decimal("26.17"))
        inventory = rows["Informe de inventarios"]
        self.assertEqual((q2(inventory.compliance), q2(inventory.weighted)), (Decimal("100.00"), Decimal("25.00")))
        for name in ("Llamadas preventivas a usuarios", "Informe a comunicaciones", "Emergencia"):
            self.assertEqual(rows[name].compliance, 0)
            self.assertEqual(rows[name].traffic_light, IndicatorSnapshot.TrafficLight.RED)
        # 314/240 x 20 + 1/1 x 25 = 26,1667 + 25 (precisión interna; se redondea al mostrar).
        self.assertEqual(q2(result.total), Decimal("51.17"))
        self.assertEqual(attention.traffic_light, IndicatorSnapshot.TrafficLight.GREEN)
        self.assertEqual(q2(attention.expected_units), Decimal("240.00"))
        self.assertEqual(q2(attention.difference), Decimal("74.00"))
        self.assertEqual(result.total_traffic_light, IndicatorSnapshot.TrafficLight.RED)

    def test_coordinator_compliance_is_capped_at_the_configured_maximum(self):
        official = self.official("Coordinador", "Coordinador de servicios comunitarios")
        self.record(official, "Operativo Diserco", 104)
        row = self.rows(Calc.calculate(official, self.period, END))["Operativo Diserco"]
        self.assertEqual(q2(row.raw_compliance), Decimal("866.67"))
        self.assertEqual((row.compliance, row.weighted), (Decimal("150"), Decimal("15")))

        revision = create_revision(self.plans["Coordinador de servicios comunitarios"], date(2026, 9, 1))
        revision.max_computable = Decimal("200")
        revision.save(update_fields=["max_computable"])
        publish_version(revision)
        row = self.rows(Calc.calculate(official, self.period, END))["Operativo Diserco"]
        self.assertEqual((row.compliance, row.weighted), (Decimal("200"), Decimal("20")))
        row = self.rows(Calc.calculate(official, self.period, date(2026, 8, 31)))["Operativo Diserco"]
        self.assertEqual(row.compliance, Decimal("150"))  # antes de la revisión rige el tope anterior

    def test_guide_lots_cal_a_and_cal_b(self):
        plan = self.make_plan("Prueba CAL", (("I01 de prueba", "40", 10), ("I02 de prueba", "60", 20)))
        official = self.official("Caso CAL", "Prueba CAL")
        self.record(official, "I01 de prueba", 8)
        self.record(official, "I02 de prueba", 10)
        self.record(official, "I01 de prueba", 3, status=EvidenceValidation.Status.REJECTED)
        self.record(official, "I01 de prueba", 3, status=None)
        result = Calc.calculate(official, self.period, END)
        self.assertEqual(self.rows(result)["I01 de prueba"].raw_compliance, 80)  # CAL-01: 8 de 10
        self.assertEqual(self.rows(result)["I02 de prueba"].raw_compliance, 50)  # 10 de 20
        self.assertEqual(result.total, 62)  # CAL-A: 32 + 30
        self.record(official, "I01 de prueba", 12)
        result = Calc.calculate(official, self.period, END)
        self.assertEqual(self.rows(result)["I01 de prueba"].raw_compliance, 200)
        self.assertEqual(result.total, 90)  # CAL-B: 60 + 30 con tope 150 %
        self.assertTrue(plan.versions.get().is_published)


class ExpectedGoalAndTrafficLightTests(CalculatorFixture, TestCase):
    def test_guide_example_of_computable_days(self):
        self.assertEqual(computable_days(self.period), 91)
        self.assertEqual(computable_days(self.period, until=date(2026, 8, 26)), 56)
        self.assertEqual(Calc.calculate_expected_goal_to_date(self.period, date(2026, 8, 26)), Decimal("61.54"))
        self.assertEqual(Calc.calculate_expected_goal_to_date(self.period, date(2026, 6, 1)), 0)
        self.assertEqual(Calc.calculate_expected_goal_to_date(self.period, START), 0)
        self.assertEqual(Calc.calculate_expected_goal_to_date(self.period, date(2026, 12, 1)), 100)

    def test_inclusive_count_of_cal_d_test_lot(self):
        october = Period(start_date=date(2026, 10, 1), end_date=date(2026, 10, 30))
        self.assertEqual(computable_days(october, include_start_day=True), 30)
        self.assertEqual(computable_days(october, until=date(2026, 10, 15), include_start_day=True), 15)
        expected = [
            Calc.calculate_expected_goal_to_date(october, day, include_start_day=True)
            for day in (date(2026, 9, 30), date(2026, 10, 1), date(2026, 10, 15), date(2026, 10, 30), date(2026, 11, 2))
        ]
        self.assertEqual(expected, [0, Decimal("3.33"), 50, 100, 100])  # CAL-04
        # El mismo período con el conteo por defecto diverge: 29 días y 14 transcurridos al 15/10.
        self.assertEqual(Calc.calculate_expected_goal_to_date(october, date(2026, 10, 15)), Decimal("48.28"))
        self.assertEqual(computable_days(self.period, include_start_day=True), 92)

    def test_cal_d_complete_result_with_inclusive_count(self):
        october = Period.objects.create(start_date=date(2026, 10, 1), end_date=date(2026, 10, 30))
        self.make_plan("Prueba CAL-D", (("I01 CAL-D", "100", 10),), period=october)
        official = self.official("Caso CAL-D", "Prueba CAL-D")
        self.record(official, "I01 CAL-D", 5, day=date(2026, 10, 10))
        result = Calc.calculate(official, october, date(2026, 10, 15), include_start_day=True)
        row = self.rows(result)["I01 CAL-D"]
        self.assertEqual(result.expected_percentage, 50)  # 15/30
        self.assertEqual((row.expected_units, row.compliance, row.difference), (5, 50, 0))
        self.assertEqual((row.traffic_light, result.total_traffic_light), ("GREEN", "GREEN"))
        for day, expected in ((date(2026, 9, 30), 0), (date(2026, 10, 1), Decimal("3.33")),
                              (date(2026, 10, 30), 100), (date(2026, 11, 5), 100)):
            result = Calc.calculate(official, october, day, include_start_day=True)
            self.assertEqual(q2(result.expected_percentage), expected, day)
        default = Calc.calculate(official, october, date(2026, 10, 15))
        self.assertEqual(q2(default.expected_percentage), Decimal("48.28"))  # 14/29: convención por defecto
        self.assertEqual(self.rows(default)["I01 CAL-D"].traffic_light, "GREEN")

    def test_presentation_rounding_is_half_up_and_internal_precision_is_kept(self):
        self.assertEqual(q2(Decimal("5.545")), Decimal("5.55"))
        self.assertEqual(q2(Decimal("5.544999")), Decimal("5.54"))
        plan = self.make_plan("Prueba redondeo", (("I01 redondeo", "33.27", 6), ("I02 redondeo", "66.73", 1)))
        official = self.official("Caso redondeo", "Prueba redondeo")
        self.record(official, "I01 redondeo", 1)
        row = self.rows(Calc.calculate(official, self.period, END))["I01 redondeo"]
        self.assertEqual(row.weighted, Decimal("33.27") * (Decimal(1) / 6 * 100) / 100)  # sin redondeo intermedio
        self.assertEqual(q2(row.weighted), Decimal("5.55"))
        self.assertTrue(plan.versions.get().is_published)

    def test_cal_e_boundaries_are_evaluated_without_rounding(self):
        version = self.plans["Apoyo administrativo"].versions.get()
        expected = Decimal("50")
        lights = [traffic_light(Decimal(value), expected, version) for value in ("29.99", "30", "49.99", "50")]
        self.assertEqual(lights, ["RED", "AMBER", "AMBER", "GREEN"])
        self.assertEqual(traffic_light(Decimal("29.999"), expected, version), "RED")
        version.amber_threshold = Decimal("50")
        self.assertEqual(traffic_light(Decimal("29.99"), expected, version), "AMBER")

    def test_expected_units_follow_the_date(self):
        official = self.official("Apoyo", "Apoyo administrativo")
        self.record(official, "Informe a comunicaciones", 4, day=date(2026, 7, 15))
        row = self.rows(Calc.calculate(official, self.period, date(2026, 8, 26)))["Informe a comunicaciones"]
        # Meta 12 x 61,54 % = 7,38 esperadas; 4 aprobadas = 33,33 % (54 % de lo esperado: rojo).
        self.assertEqual(q2(row.expected_units), Decimal("7.38"))
        self.assertEqual(row.traffic_light, "RED")
        row = self.rows(Calc.calculate(official, self.period, date(2026, 7, 31)))["Informe a comunicaciones"]
        self.assertEqual(row.traffic_light, "GREEN")
        row = self.rows(Calc.calculate(official, self.period, date(2026, 7, 14)))["Informe a comunicaciones"]
        self.assertEqual(row.progress, 0)  # lo registrado después de la fecha de cálculo aún no cuenta


class ProgressRulesTests(CalculatorFixture, TestCase):
    def setUp(self):
        self.official_ = self.official("Gestora", "Gestor social")

    def progress(self, item="Visita terreno", on_date=END):
        return self.rows(Calc.calculate(self.official_, self.period, on_date))[item].progress

    def test_only_approved_evidence_counts_and_annulment_reverts(self):
        self.record(self.official_, "Visita terreno", 2, status=None)
        self.record(self.official_, "Visita terreno", 1, status=EvidenceValidation.Status.REJECTED)
        self.record(self.official_, "Visita terreno", 1, status=EvidenceValidation.Status.CORRECTION_REQUESTED)
        self.assertEqual(self.progress(), 0)
        pending = Evidence.objects.filter(validations__isnull=True).first()
        EvidenceValidation.objects.create(evidence=pending, verifier=self.verifier,
                                          status=EvidenceValidation.Status.APPROVED)
        self.assertEqual(self.progress(), 1)
        Evidence.objects.create(activity=pending.activity, file_url="y.png", file_format="png", size_kb=1)
        self.assertEqual(self.progress(), 1)  # una actividad cuenta una vez
        EvidenceValidation.objects.filter(evidence=pending).update(deleted_at=timezone.now())
        self.assertEqual(self.progress(), 0)

    def test_second_approved_image_on_the_same_activity_does_not_duplicate_progress(self):
        # CAL-01 / HU-06: una evidencia adicional aprobada en la misma actividad no duplica el avance.
        [activity] = self.record(self.official_, "Visita terreno", 1)
        self.assertEqual(self.progress(), 1)
        second = Evidence.objects.create(activity=activity, file_url="z.png", file_format="png", size_kb=1)
        EvidenceValidation.objects.create(evidence=second, verifier=self.verifier,
                                          status=EvidenceValidation.Status.APPROVED)
        self.assertEqual(EvidenceValidation.objects.filter(
            evidence__activity=activity, status=EvidenceValidation.Status.APPROVED).count(), 2)
        self.assertEqual(self.progress(), 1)
        self.assertEqual(Calc.calculate_current_progress(self.official_, self.items["Visita terreno"], self.period), 1)
        # Al anular una de las dos aprobaciones, la actividad sigue contando una vez.
        EvidenceValidation.objects.filter(evidence=second).update(deleted_at=timezone.now())
        self.assertEqual(self.progress(), 1)

    def test_activity_outside_the_period_or_archived_does_not_count(self):
        [activity] = self.record(self.official_, "Visita terreno", 1)
        self.assertEqual(self.progress(), 1)
        Activity.objects.filter(pk=activity.pk).update(date=END + timedelta(days=1))
        self.assertEqual(self.progress(), 0)
        Activity.objects.filter(pk=activity.pk).update(date=END, deleted_at=timezone.now())
        self.assertEqual(self.progress(), 0)

    def test_items_outside_the_plan_and_revisions_use_the_ruling_version(self):
        self.record(self.official_, "Informe de inventarios", 3)  # ítem de otro cargo
        result = Calc.calculate(self.official_, self.period, END)
        self.assertNotIn("Informe de inventarios", self.rows(result))

        plan = self.plans["Gestor social"]
        revision = create_revision(plan, date(2026, 9, 1))
        revision.items.filter(item=self.items["Visita terreno"]).update(goal=24)
        revision.items.filter(item=self.items["Entrega beneficio"]).delete()
        revision.items.filter(item=self.items["Entrega informe"]).update(weight=40)
        publish_version(revision)
        self.record(self.official_, "Entrega beneficio", 2, day=date(2026, 8, 31))
        self.record(self.official_, "Entrega beneficio", 5, day=date(2026, 9, 1))
        self.record(self.official_, "Visita terreno", 6, day=date(2026, 9, 15))

        before = self.rows(Calc.calculate(self.official_, self.period, date(2026, 8, 31)))
        self.assertEqual(before["Entrega beneficio"].progress, 2)  # lo posterior al cambio no cuenta
        self.assertEqual(before["Visita terreno"].goal, 12)
        after = self.rows(Calc.calculate(self.official_, self.period, END))
        self.assertNotIn("Entrega beneficio", after)
        self.assertEqual((after["Visita terreno"].goal, after["Visita terreno"].progress), (24, 6))

    def test_individual_adjustment_overrides_goal_and_weight(self):
        version = self.plans["Gestor social"].versions.get()
        attention = version.items.get(item=self.items["Atención social a usuario presencial"])
        visit = version.items.get(item=self.items["Visita terreno"])
        MeasurementAdjustment.objects.create(line=attention, official=self.official_, goal=30, weight=30)
        MeasurementAdjustment.objects.create(line=visit, official=self.official_, weight=15)
        self.record(self.official_, "Atención social a usuario presencial", 15)
        rows = self.rows(Calc.calculate(self.official_, self.period, END))
        row = rows["Atención social a usuario presencial"]
        self.assertEqual((row.goal, row.weight, row.compliance, row.weighted), (30, 30, 50, 15))
        self.assertTrue(row.individual)
        self.assertEqual((rows["Visita terreno"].goal, rows["Visita terreno"].weight), (12, 15))
        other = self.official("Otra gestora", "Gestor social")
        self.assertEqual(self.rows(Calc.calculate(other, self.period, END))["Visita terreno"].weight, 20)

    def test_invalid_goal_does_not_divide_by_zero(self):
        self.plans["Gestor social"].versions.get().items.filter(item=self.items["Visita terreno"]).update(goal=0)
        self.record(self.official_, "Visita terreno", 2)
        row = self.rows(Calc.calculate(self.official_, self.period, END))["Visita terreno"]
        self.assertEqual((row.compliance, row.weighted, row.traffic_light), (0, 0, None))
        self.assertIn("Meta no válida", row.notice)

    def test_percentage_item_uses_done_commitments_cal_f(self):
        row = self.rows(Calc.calculate(self.official_, self.period, END))[PERCENTAGE_ITEM]
        self.assertIsNone(row.progress)
        self.assertEqual(row.weighted, 0)
        self.assertIn("Sin compromisos", row.notice)
        for index in range(10):
            Commitment.objects.create(
                responsible=self.official_, requester="Vecino ficticio", territory="Centro",
                committed_date=date(2026, 8, 1), creation_date=timezone.make_aware(datetime(2026, 7, 15)),
                current_status=(
                    Commitment.Status.DONE if index < 8 else Commitment.Status.PENDING),
            )
        Commitment.objects.create(responsible=self.official_, requester="Fuera", territory="Centro",
                                  committed_date=date(2026, 10, 1), current_status=Commitment.Status.PENDING)
        row = self.rows(Calc.calculate(self.official_, self.period, END))[PERCENTAGE_ITEM]
        self.assertEqual((row.progress, row.compliance, row.weighted), (80, 100, 10))

    def test_percentage_item_respects_the_calculation_date(self):
        def at(day, hour=10):
            return timezone.make_aware(datetime.combine(day, time(hour)))

        early = Commitment.objects.create(responsible=self.official_, requester="Vecino", territory="Centro",
                                          committed_date=date(2026, 9, 1), creation_date=at(date(2026, 7, 2)))
        late = Commitment.objects.create(responsible=self.official_, requester="Vecina", territory="Centro",
                                         committed_date=date(2026, 9, 1), creation_date=at(date(2026, 8, 10)),
                                         current_status=Commitment.Status.DONE)
        CommitmentStatusHistory.objects.create(commitment=early, author=self.verifier, date=at(date(2026, 7, 20)),
                                               previous_status="ENTERED", new_status="DONE")
        CommitmentStatusHistory.objects.create(commitment=early, author=self.verifier, date=at(date(2026, 8, 20)),
                                               previous_status="DONE", new_status="PENDING")
        Commitment.objects.filter(pk=early.pk).update(current_status=Commitment.Status.PENDING)

        def progress(day):
            return self.rows(Calc.calculate(self.official_, self.period, day))[PERCENTAGE_ITEM].progress

        self.assertIsNone(progress(date(2026, 7, 1)))  # aún no existía ningún compromiso
        self.assertEqual(progress(date(2026, 7, 10)), 0)  # 0 de 1: el primero seguía ingresado
        self.assertEqual(progress(date(2026, 7, 20)), 100)  # realizado ese día
        self.assertEqual(progress(date(2026, 8, 10)), 100)  # el segundo, sin historial, cuenta con su estado
        self.assertEqual(progress(date(2026, 8, 25)), 50)  # el primero volvió a pendiente
        self.assertEqual(late.current_status, Commitment.Status.DONE)

    def test_closed_period_percentage_does_not_change_after_its_end(self):
        def at(day):
            return timezone.make_aware(datetime.combine(day, time(10)))

        pending = Commitment.objects.create(responsible=self.official_, requester="Vecino", territory="Centro",
                                            committed_date=date(2026, 9, 15), creation_date=at(date(2026, 9, 1)))
        CommitmentStatusHistory.objects.create(commitment=pending, author=self.verifier, date=at(date(2026, 10, 5)),
                                               previous_status="ENTERED", new_status="DONE")
        Commitment.objects.filter(pk=pending.pk).update(current_status=Commitment.Status.DONE)
        Commitment.objects.create(responsible=self.official_, requester="Tardío", territory="Centro",
                                  committed_date=date(2026, 9, 20), creation_date=at(date(2026, 10, 3)),
                                  current_status=Commitment.Status.DONE)
        for day in (END, date(2026, 10, 6), date(2026, 12, 31)):
            row = self.rows(Calc.calculate(self.official_, self.period, day))[PERCENTAGE_ITEM]
            self.assertEqual(row.progress, 0, day)  # estado al 30/09; lo creado después no entra

    def test_archived_versions_do_not_rule_goals_or_progress(self):
        plan = self.plans["Gestor social"]
        revision = create_revision(plan, date(2026, 9, 1))
        revision.items.filter(item=self.items["Visita terreno"]).update(goal=24)
        revision.items.filter(item=self.items["Entrega beneficio"]).delete()
        revision.items.filter(item=self.items["Entrega informe"]).update(weight=40)
        publish_version(revision)
        self.record(self.official_, "Entrega beneficio", 2, day=date(2026, 9, 10))
        rows = self.rows(Calc.calculate(self.official_, self.period, END))
        self.assertEqual(rows["Visita terreno"].goal, 24)
        self.assertNotIn("Entrega beneficio", rows)

        revision.deleted_at = timezone.now()
        revision.save(update_fields=["deleted_at"])
        rows = self.rows(Calc.calculate(self.official_, self.period, END))
        self.assertEqual(rows["Visita terreno"].goal, 12)
        self.assertEqual(rows["Entrega beneficio"].progress, 2)

    def test_plan_search_is_limited_to_the_given_period(self):
        other = Period.objects.create(start_date=date(2026, 10, 1), end_date=date(2026, 12, 31))
        result = Calc.calculate(self.official_, other, date(2026, 10, 5))
        self.assertIsNone(result.version)
        self.assertIn("No hay un plan", result.notice)
        result = Calc.calculate(self.official_, self.period, date(2026, 10, 5))  # fecha fuera: se acota al término
        self.assertEqual(result.version.plan.period, self.period)

    def test_archived_revision_does_not_block_a_new_publication(self):
        plan = self.plans["Gestor social"]
        archived = create_revision(plan, date(2026, 9, 15))
        publish_version(archived)
        archived.deleted_at = timezone.now()
        archived.save(update_fields=["deleted_at"])
        archived.items.filter(item=self.items["Visita terreno"]).update(goal=99)
        revision = create_revision(plan, date(2026, 9, 1))
        publish_version(revision)  # válida respecto de la última versión no archivada (1/07)
        self.assertTrue(revision.is_published)
        self.assertEqual(revision.number, 3)
        self.assertEqual(revision.items.get(item=self.items["Visita terreno"]).goal, 12)  # copia de la v1

    def test_official_without_position_or_plan_gets_a_notice(self):
        result = Calc.calculate(self.official("Sin cargo"), self.period, END)
        self.assertEqual((result.items, result.total), ([], 0))
        self.assertIn("no tiene cargo", result.notice)
        official = self.official("Sin plan")
        official.position = Position.objects.create(position_name="Cargo sin plan")
        result = Calc.calculate(official, self.period, END)
        self.assertIn("No hay un plan", result.notice)
        self.assertIsNone(result.total_traffic_light)

    def test_snapshots_persist_the_calculated_rows(self):
        self.record(self.official_, "Visita terreno", 6)
        snapshots = Calc.generate_snapshots(self.official_, self.period, END)
        self.assertEqual(len(snapshots), len(POSITION_PLANS["Gestor social"]))
        visit = IndicatorSnapshot.objects.get(item=self.items["Visita terreno"])
        self.assertEqual((visit.goal, visit.progress, visit.compliance, visit.applied_weighting, visit.traffic_light),
                         (12, 6, 50, 20, "RED"))
        self.assertIsNone(Calc.generate_snapshot(self.official_, self.period, self.items["Informe de inventarios"]))

    def test_query_count_does_not_grow_with_activities(self):
        self.record(self.official_, "Visita terreno", 2)
        with CaptureQueriesContext(connection) as small:
            Calc.calculate(self.official_, self.period, END)
        for name in POSITION_PLANS["Gestor social"][:5]:
            self.record(self.official_, name[0], 20, day=date(2026, 7, 15))
        with CaptureQueriesContext(connection) as large:
            Calc.calculate(self.official_, self.period, END)
        self.assertEqual(len(small), len(large))
