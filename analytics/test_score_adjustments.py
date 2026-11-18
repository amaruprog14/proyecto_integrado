from datetime import date
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth.models import Permission, User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import Delegation, Role
from analytics.measurement import create_revision, publish_version
from analytics.models import ScoreAdjustment
from analytics.services import CalculadorDesempenoService as Calc
from analytics.test_performance_calculator import CalculatorFixture, END, START
from configuration.models import AuditLog


class ScoreAdjustmentTests(CalculatorFixture, TestCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.subject = cls.official("Funcionario de prueba", "Apoyo administrativo")
        cls.external = cls.official("Otra delegación", "Apoyo administrativo")
        cls.external.delegation = Delegation.objects.create(
            delegation_name="Antena", address="Calle 2", commune="La Serena",
        )
        cls.external.save(update_fields=["delegation"])
        cls.operator = cls.staff("operador-ajustes", Role.Scope.DELEGATION)
        cls.coordinator = cls.staff("coordinador-ajustes", Role.Scope.ALL, review=True)
        # Segregación: quien registra no valida lo suyo; otra cuenta con permiso de validación sí.
        cls.reviewer = cls.staff("validador-ajustes", Role.Scope.ALL, review=True)

    @classmethod
    def staff(cls, name, scope, review=False):
        user = User.objects.create_user(name)
        official = cls.official(name)
        official.user = user
        official.save(update_fields=["user"])
        role = Role.objects.create(role_name=name, scope=scope)
        codenames = ["view_scoreadjustment", "add_scoreadjustment", "view_indicatorsnapshot"]
        if review:
            codenames.extend(["review_scoreadjustment", "view_team_performance"])
        role.permissions.add(*Permission.objects.filter(content_type__app_label="analytics", codename__in=codenames))
        official.roles.add(role)
        return user

    def create(self, **overrides):
        values = {
            "official": self.subject.pk, "occurred_on": START.isoformat(),
            "kind": ScoreAdjustment.Kind.COMPLAINT, "channel": ScoreAdjustment.Channel.EMAIL,
            "reason": "Motivo de prueba", "written_support": "Correo del vecino, folio de prueba.",
            **overrides,
        }
        return self.client.post(reverse("score_adjustment_create"), values)

    def review(self, record, decision=ScoreAdjustment.Status.APPROVED, note=""):
        return self.client.post(reverse("score_adjustment_detail", args=[record.pk]), {"decision": decision, "note": note})

    @patch("analytics.score_adjustments.timezone.localdate", return_value=END)
    def test_register_within_scope_and_only_approval_changes_result(self, _today):
        self.client.force_login(self.operator)
        self.assertContains(self.client.get(reverse("score_adjustment_list")), "Nuevo registro")
        self.assertContains(self.create(official=self.external.pk), "opción válida")
        self.assertFalse(ScoreAdjustment.objects.exists())
        self.assertEqual(self.create(status="APPROVED", points="150").status_code, 302)
        record = ScoreAdjustment.objects.get()
        self.assertEqual(record.status, ScoreAdjustment.Status.PENDING)
        self.assertEqual(record.recorded_by, self.operator)
        self.assertEqual(Calc.calculate(self.subject, self.period, END).total, 0)
        self.assertEqual(self.review(record).status_code, 403)

        self.client.force_login(self.coordinator)
        self.assertContains(self.client.get(reverse("score_adjustment_detail", args=[record.pk])), "Correo del vecino")
        self.assertEqual(self.review(record).status_code, 302)
        self.assertContains(self.review(record), "Este registro ya fue revisado.")
        record.refresh_from_db()
        self.assertEqual((record.points, record.reviewed_by), (Decimal("-20"), self.coordinator))
        result = Calc.calculate(self.subject, self.period, END)
        self.assertEqual((result.score_adjustment_total, result.total), (-20, 0))  # piso del resultado final
        panel = self.client.get(reverse("my_performance"), {"period": self.period.pk, "official": self.subject.pk})
        self.assertContains(panel, "Ver reclamos y felicitaciones aprobados")
        self.assertContains(panel, "-20,00 puntos")
        self.assertEqual(AuditLog.objects.filter(
            affected_table=ScoreAdjustment._meta.db_table, affected_record_id=record.pk,
        ).count(), 2)

    @patch("analytics.score_adjustments.timezone.localdate", return_value=END)
    def test_plan_revision_sets_value_by_date_and_rejected_entries_do_not_score(self, _today):
        plan = self.plans["Apoyo administrativo"]
        change_date = date(2026, 8, 1)
        draft = create_revision(plan, change_date)
        draft.complaint_points = Decimal("30")
        draft.save(update_fields=["complaint_points"])
        publish_version(draft)
        self.assertEqual(create_revision(plan, date(2026, 9, 1)).complaint_points, 30)

        self.client.force_login(self.coordinator)
        self.assertEqual(self.create(occurred_on=change_date.isoformat()).status_code, 302)
        record = ScoreAdjustment.objects.latest("pk")
        self.client.force_login(self.reviewer)
        self.assertEqual(self.review(record).status_code, 302)
        record.refresh_from_db()
        self.assertEqual((record.version, record.points), (draft, Decimal("-30")))
        self.client.force_login(self.coordinator)
        self.assertEqual(self.create().status_code, 302)
        rejected = ScoreAdjustment.objects.latest("pk")
        self.client.force_login(self.reviewer)
        self.assertContains(self.review(rejected, ScoreAdjustment.Status.REJECTED), "Indica el motivo del rechazo.")
        self.assertEqual(self.review(rejected, ScoreAdjustment.Status.REJECTED, "Sin respaldo verificable").status_code, 302)
        rejected.refresh_from_db()
        self.assertIsNone(rejected.points)
        result = Calc.calculate(self.subject, self.period, END)
        self.assertEqual((result.score_adjustment_total, result.total), (-30, 0))

    def test_three_approved_congratulations_and_final_cap_are_preserved_at_close(self):
        for _ in range(4):
            ScoreAdjustment.objects.create(
                official=self.subject, period=self.period, occurred_on=START,
                channel=ScoreAdjustment.Channel.EMAIL, kind=ScoreAdjustment.Kind.CONGRATULATION,
                reason="Agradecimiento", written_support="Correo", recorded_by=self.coordinator,
                reviewed_by=self.coordinator, reviewed_at=timezone.now(), status=ScoreAdjustment.Status.APPROVED,
                points=Decimal("50"),
            )
        self.record(self.subject, "Informe de inventarios", 1)
        result = Calc.calculate(self.subject, self.period, END)
        self.assertEqual((result.base_total, result.score_adjustment_total, result.total), (25, 150, 150))
        self.assertTrue(result.score_adjustments[-1]["excluded"])
        self.period.close_period()
        self.period.refresh_from_db()
        ScoreAdjustment.objects.filter(official=self.subject).update(points=1)
        frozen = Calc.result_for(self.subject, self.period)
        self.assertTrue(frozen.frozen)
        self.assertEqual((frozen.base_total, frozen.score_adjustment_total, frozen.total), (25, 150, 150))
        self.assertEqual(frozen.score_adjustments, result.score_adjustments)

    @patch("analytics.score_adjustments.timezone.localdate", return_value=END)
    def test_closed_period_rejects_registration_and_review(self, _today):
        self.client.force_login(self.coordinator)
        self.assertEqual(self.create().status_code, 302)
        record = ScoreAdjustment.objects.get()
        self.period.close_period()
        expected = "La fecha debe pertenecer a un período abierto."
        self.assertContains(self.create(), expected)
        self.client.force_login(self.reviewer)
        self.assertContains(self.review(record), expected)
        record.refresh_from_db()
        self.assertEqual(record.status, ScoreAdjustment.Status.PENDING)

    @patch("analytics.score_adjustments.timezone.localdate", return_value=END)
    def test_who_records_cannot_review_own_record(self, _today):
        self.client.force_login(self.coordinator)  # tiene registrar y validar
        self.assertEqual(self.create().status_code, 302)
        own = ScoreAdjustment.objects.get()
        url = reverse("score_adjustment_detail", args=[own.pk])
        page = self.client.get(url)
        self.assertIsNone(page.context["form"])
        self.assertContains(page, "data-own-record")
        self.assertNotContains(page, "Guardar decisión")
        response = self.client.post(url, {"decision": ScoreAdjustment.Status.APPROVED, "note": ""},
                                    REMOTE_ADDR="192.0.2.10")
        self.assertEqual(response.status_code, 403)
        self.assertContains(response, "No puedes validar un registro que ingresaste tú", status_code=403)
        own.refresh_from_db()
        self.assertEqual((own.status, own.points, own.reviewed_by), (ScoreAdjustment.Status.PENDING, None, None))
        attempt = AuditLog.objects.get(action="Intento de validar un registro propio", affected_record_id=own.pk)
        self.assertEqual((attempt.actor_username, attempt.origin_ip), (self.coordinator.username, "192.0.2.10"))
        self.assertEqual((attempt.affected_table, attempt.previous_value), (ScoreAdjustment._meta.db_table, "Estado: Pendiente"))
        self.assertEqual(attempt.new_value.splitlines()[:2], [
            "Estado: Pendiente", "Rechazado: quien registra no puede validar su propio registro"])
        self.assertIn(f"Cuenta responsable: {self.coordinator.pk}", attempt.new_value)

        # Otra cuenta con permiso de validación sí puede validarlo.
        self.client.force_login(self.reviewer)
        self.assertIsNotNone(self.client.get(url).context["form"])
        self.assertEqual(self.review(own).status_code, 302)
        own.refresh_from_db()
        self.assertEqual((own.status, own.reviewed_by), (ScoreAdjustment.Status.APPROVED, self.reviewer))

        # Un registro ajeno sigue funcionando para quien registró el anterior.
        self.client.force_login(self.reviewer)
        self.assertEqual(self.create(kind=ScoreAdjustment.Kind.CONGRATULATION).status_code, 302)
        foreign = ScoreAdjustment.objects.latest("pk")
        self.client.force_login(self.coordinator)
        self.assertEqual(self.review(foreign).status_code, 302)
        foreign.refresh_from_db()
        self.assertEqual(foreign.reviewed_by, self.coordinator)

    @patch("analytics.score_adjustments.timezone.localdate", return_value=END)
    def test_affected_official_cannot_review_a_record_about_themselves(self, _today):
        affected = self.reviewer.official  # tiene permiso de validación y alcance global
        affected.position = self.positions["Apoyo administrativo"]
        affected.save(update_fields=["position"])
        record = ScoreAdjustment.objects.create(
            official=affected, period=self.period, occurred_on=START, kind=ScoreAdjustment.Kind.CONGRATULATION,
            channel=ScoreAdjustment.Channel.EMAIL, reason="Agradecimiento de un vecino",
            written_support="Correo ficticio", recorded_by=self.operator)  # lo registró otra persona
        url = reverse("score_adjustment_detail", args=[record.pk])
        self.client.force_login(self.reviewer)
        page = self.client.get(url)
        self.assertIsNone(page.context["form"])
        self.assertContains(page, "data-subject-record")
        self.assertNotContains(page, "Guardar decisión")
        response = self.client.post(url, {"decision": ScoreAdjustment.Status.APPROVED, "note": ""},
                                    REMOTE_ADDR="192.0.2.20")
        self.assertEqual(response.status_code, 403)
        self.assertContains(response, "No puedes validar un reclamo o felicitación sobre ti", status_code=403)
        record.refresh_from_db()
        self.assertEqual((record.status, record.points, record.reviewed_by), (ScoreAdjustment.Status.PENDING, None, None))
        attempt = AuditLog.objects.get(action="Intento de validar un registro sobre sí mismo", affected_record_id=record.pk)
        self.assertEqual((attempt.actor_username, attempt.origin_ip, attempt.previous_value),
                         (self.reviewer.username, "192.0.2.20", "Estado: Pendiente"))
        self.assertIn("Rechazado: el funcionario afectado no puede validar", attempt.new_value)
        self.assertEqual(Calc.calculate(affected, self.period, END).score_adjustments, [])

        # Otra cuenta autorizada, que no es el afectado ni quien registró, sí puede validarlo.
        self.client.force_login(self.coordinator)
        self.assertEqual(self.review(record).status_code, 302)
        record.refresh_from_db()
        self.assertEqual((record.status, record.reviewed_by), (ScoreAdjustment.Status.APPROVED, self.coordinator))
