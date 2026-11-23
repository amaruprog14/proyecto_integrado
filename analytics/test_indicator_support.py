"""Respaldo exacto de los indicadores congelados («¿Qué respaldó este resultado?»).

Cada test congela un período y comprueba que el respaldo cuadra con la cifra congelada: cantidad de
actividades = avance; compromisos del numerador / denominador = porcentaje congelado.
"""
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth.models import Permission, User
from django.db.models import Q
from django.forms.models import model_to_dict
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.models import Delegation, OfficialAbsence, OfficialPositionPeriod, Position, Role
from accounts.position_services import change_position
from activities.models import Activity, Evidence, EvidenceBatch, EvidenceValidation
from agenda.models import Commitment
from analytics.measurement import create_revision
from analytics.measurement_forms import VersionForm
from analytics.models import IndicatorSnapshot, IndicatorSupportSnapshot, MeasurementItem
from analytics.services import CalculadorDesempenoService as Calc, q2
from analytics.support_views import PRE_SUPPORT_NOTICE
from analytics.test_performance_calculator import END, START, CalculatorFixture
from common.sgr_seed_data import PERCENTAGE_ITEM

GoalType = MeasurementItem.GoalType
STAMP = timezone.make_aware(datetime.combine(START, time(9)))


@override_settings(PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"])
@patch("analytics.views.timezone.localdate", return_value=END)
class IndicatorSupportTests(CalculatorFixture, TestCase):
    def setUp(self):
        self.worker = self.official("Gestora con respaldo", "Gestor social")
        self.admin = User.objects.create_superuser("respaldo-admin", "admin@respaldo.test", "test-password")
        self.client.force_login(self.admin)

    def commitment(self, status, **kwargs):
        return Commitment.objects.create(responsible=self.worker, requester="Vecino ficticio", territory="Centro",
                                         committed_date=date(2026, 9, 1), creation_date=STAMP, current_status=status,
                                         **kwargs)

    def single_plan(self, kind="QUANTITY", goal=10):
        version = self.plans["Gestor social"].versions.get()
        version.items.exclude(item=self.items["Visita terreno"]).delete()
        line = version.items.get()
        line.goal_type, line.goal, line.weight = kind, goal, 100
        line.save()
        return line

    def close(self):
        self.period.close_period()
        self.period.refresh_from_db()

    def frozen(self, item_name, official=None):
        return Calc.frozen_snapshots(self.period).get(official=official or self.worker, item=self.items[item_name])

    def support_url(self, official=None, item_name=None):
        url = reverse("indicator_support", args=[self.period.pk, (official or self.worker).pk])
        return f"{url}?item={self.items[item_name].pk}" if item_name else url

    def assert_support_matches_frozen_figure(self, official=None):
        """Falla si el respaldo diverge de la cifra congelada de cualquier indicador."""
        snapshots = list(Calc.frozen_snapshots(self.period).filter(official=official or self.worker))
        self.assertTrue(snapshots)
        for snapshot in snapshots:
            with self.subTest(item=str(snapshot.item)):
                self.assertTrue(snapshot.support_captured)
                supports = snapshot.supports.all()
                if not snapshot.computable_days:
                    self.assertFalse(supports.exists())
                elif snapshot.goal_type == GoalType.QUANTITY:
                    self.assertEqual(supports.count(), snapshot.progress)
                    self.assertFalse(supports.filter(activity__isnull=True).exists())
                elif supports.exists():
                    self.assertFalse(supports.filter(commitment__isnull=True).exists())
                    numerator = supports.filter(in_numerator=True).count()
                    self.assertEqual(q2(Decimal(numerator) / supports.count() * 100), snapshot.progress)
                else:
                    self.assertIsNone(snapshot.progress)

    def test_quantity_item_support_matches_progress_and_panel_links_to_it(self, _today):
        self.record(self.worker, "Visita terreno", 3)
        self.record(self.worker, "Entrega informe", 2)
        self.record(self.worker, "Visita terreno", 1, status=None)  # sin revisar: no cuenta
        self.record(self.worker, "Visita terreno", 1, status="REJECTED")
        self.close()
        self.assert_support_matches_frozen_figure()
        visits = self.frozen("Visita terreno")
        self.assertEqual((visits.progress, visits.supports.count()), (3, 3))

        panel = self.client.get(reverse("my_performance"), {"period": self.period.pk, "official": self.worker.pk})
        links = [entry["link"] for entry in panel.context["rows"]]
        # Período congelado: todos los enlaces del panel personal llevan al respaldo congelado.
        self.assertEqual(len(links), len(panel.context["result"].items))
        self.assertTrue(all(link and link.startswith(self.support_url()) for link in links))
        self.assertNotIn("evidence=counted", panel.content.decode())  # ningún enlace al listado operativo
        self.assertContains(panel, "¿Qué respaldó este resultado?")

        response = self.client.get(self.support_url(item_name="Visita terreno"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["page_obj"].paginator.count, 3)
        self.assertContains(response, "3 actividades computadas")

    def test_percentage_item_keeps_numerator_and_denominator_at_cutoff(self, _today):
        for status in ("DONE", "DONE", "DONE", "PENDING"):
            self.commitment(status)
        later = self.commitment("PENDING")
        later.creation_date = timezone.make_aware(datetime.combine(date(2026, 10, 2), time(9)))  # después del corte
        later.save(update_fields=["creation_date"])
        self.close()
        self.assert_support_matches_frozen_figure()
        snapshot = self.frozen(PERCENTAGE_ITEM)
        self.assertEqual((snapshot.progress, snapshot.supports.count()), (75, 4))
        self.assertEqual(snapshot.supports.filter(in_numerator=True).count(), 3)

        # Un cambio posterior no altera el estado guardado al corte.
        Commitment.objects.filter(responsible=self.worker).update(current_status="DONE")
        response = self.client.get(self.support_url(item_name=PERCENTAGE_ITEM))
        self.assertContains(response, "3 de 4 compromisos realizados")
        self.assertEqual(sum(1 for row in response.context["supports"] if row["record"].in_numerator), 3)

    def test_pending_in_tube_support_excludes_justified_cancellations(self, _today):
        self.single_plan("MAX_PERCENTAGE", 10)
        for status in [*(["DONE"] * 9), "PENDING"]:
            self.commitment(status)
        cancelled = self.commitment("CANCELLED", cancellation_reason="Cancelado por causa documentada")
        self.close()
        self.assert_support_matches_frozen_figure()
        snapshot = self.frozen("Visita terreno")
        self.assertEqual((snapshot.goal_type, snapshot.progress, snapshot.supports.count()), ("MAX_PERCENTAGE", 10, 10))
        self.assertEqual(snapshot.supports.filter(in_numerator=True).count(), 1)
        self.assertFalse(snapshot.supports.filter(commitment=cancelled).exists())
        self.assertContains(self.client.get(self.support_url()), "1 de 10 compromisos pendiente")

    def test_position_segments_attribute_each_activity_to_its_segment(self, _today):
        self.single_plan()
        plan = self.make_plan("Cargo de respaldo", (("Informe de inventarios", "100", 2),))
        boundary = date(2026, 8, 16)
        change_position(self.worker, plan.position, boundary, self.verifier)
        self.record(self.worker, "Visita terreno", 4, day=date(2026, 8, 15))
        self.record(self.worker, "Visita terreno", 1, day=boundary)  # fuera del plan del segundo tramo
        self.record(self.worker, "Informe de inventarios", 1, day=boundary)
        self.close()
        self.assert_support_matches_frozen_figure()
        visits = self.frozen("Visita terreno")
        self.assertEqual((visits.progress, visits.supports.count()), (4, 4))
        report = self.frozen("Informe de inventarios").supports.get()
        self.assertEqual((report.position_name, report.segment_start, report.segment_end),
                         ("Cargo de respaldo", boundary, END))
        self.assertEqual(set(visits.supports.values_list("segment_end", flat=True)), {date(2026, 8, 15)})

    def test_percentage_with_segments_is_reconciled_per_segment(self, _today):
        plan = self.make_plan("Cargo con tubo", (("Visita terreno", "50", 12), (PERCENTAGE_ITEM, "50", 80)))
        boundary = date(2026, 8, 16)
        change_position(self.worker, plan.position, boundary, self.verifier)
        first = self.commitment("DONE")
        Commitment.objects.filter(pk=first.pk).update(committed_date=date(2026, 8, 1))  # primer tramo
        for _ in range(9):
            self.commitment("PENDING")  # 1/9/2026: segundo tramo
        self.close()
        snapshot = self.frozen(PERCENTAGE_ITEM)
        segments = Calc.frozen_result(self.worker, self.period).segments
        for segment in segments:
            rows = snapshot.supports.filter(segment_start=date.fromisoformat(segment["start_date"]))
            frozen_progress = next(row["progress"] for row in segment["items"] if row["goal_type"] == "PERCENTAGE")
            with self.subTest(segment=segment["position"]):
                self.assertEqual(q2(Decimal(rows.filter(in_numerator=True).count()) / rows.count() * 100), q2(Decimal(frozen_progress)))
        # El integrado pondera por días: no es la razón de los totales (1 de 10).
        days = [segment["days"] for segment in segments]
        self.assertEqual(snapshot.progress, q2(Decimal(100) * days[0] / sum(days)))
        response = self.client.get(self.support_url(item_name=PERCENTAGE_ITEM))
        self.assertContains(response, "data-support-segment", count=2)
        self.assertContains(response, "1 de 1 compromiso realizado")
        self.assertContains(response, "0 de 9 compromisos realizados")

    def test_segment_without_computable_days_keeps_no_commitments(self, _today):
        plan = self.make_plan("Cargo con tubo sin días", ((PERCENTAGE_ITEM, "100", 80),))
        boundary = date(2026, 8, 16)
        OfficialPositionPeriod.objects.create(official=self.worker, position=plan.position, start_date=START,
                                              end_date=boundary - timedelta(days=1))
        OfficialPositionPeriod.objects.create(official=self.worker, position=self.positions["Gestor social"],
                                              start_date=boundary)
        OfficialAbsence.objects.create(official=self.worker, registered_by=self.verifier, kind="LICENCIA",
                                       start_date=START, end_date=boundary - timedelta(days=1), reason="Licencia del tramo")
        early = self.commitment("DONE")
        Commitment.objects.filter(pk=early.pk).update(committed_date=date(2026, 7, 20))
        self.commitment("PENDING")
        self.close()
        snapshot = self.frozen(PERCENTAGE_ITEM)
        self.assertFalse(snapshot.supports.filter(commitment=early).exists())
        self.assertEqual((snapshot.progress, snapshot.supports.count()), (0, 1))

    def test_total_absence_stores_no_support(self, _today):
        self.record(self.worker, "Visita terreno", 2)
        OfficialAbsence.objects.create(official=self.worker, registered_by=self.verifier, kind="LICENCIA",
                                       start_date=START, end_date=END, reason="Licencia del período")
        self.close()
        self.assert_support_matches_frozen_figure()
        self.assertFalse(IndicatorSupportSnapshot.objects.filter(snapshot__official=self.worker).exists())
        response = self.client.get(self.support_url())
        self.assertContains(response, "data-support-not-evaluated")
        self.assertNotContains(response, PRE_SUPPORT_NOTICE)

    def test_activity_edited_or_archived_after_closing_keeps_frozen_values(self, _today):
        edited, archived = self.record(self.worker, "Visita terreno", 2)
        self.close()
        frozen_code = edited.code
        Activity.objects.filter(pk=edited.pk).update(date=date(2026, 9, 20), code="T-EDITADA",
                                                     item=self.items["Entrega informe"])
        Activity.objects.filter(pk=archived.pk).update(deleted_at=timezone.now())
        self.assert_support_matches_frozen_figure()
        response = self.client.get(self.support_url(item_name="Visita terreno"))
        rows = {row["record"].activity_id: row for row in response.context["supports"]}
        self.assertEqual(len(rows), 2)
        self.assertEqual((rows[edited.pk]["record"].code, rows[edited.pk]["record"].date), (frozen_code, date(2026, 8, 1)))
        self.assertTrue(rows[edited.pk]["modified"])
        self.assertTrue(rows[archived.pk]["archived"])
        self.assertContains(response, "data-support-archived")
        self.assertContains(response, "Modificada después del cierre")
        self.assertNotContains(response, "T-EDITADA")

    def test_support_follows_the_performance_scope(self, _today):
        self.record(self.worker, "Visita terreno", 1)
        self.close()
        north = Delegation.objects.create(delegation_name="Norte respaldo", address="Calle 9", commune="La Serena")
        team = Role.objects.create(role_name="Equipo de otra delegación", scope=Role.Scope.DELEGATION)
        team.permissions.set(Permission.objects.filter(
            content_type__app_label="analytics", codename__in=["view_indicatorsnapshot", "view_team_performance"]))
        outsider = self.official("Delegada del norte")
        outsider.delegation = north
        outsider.user = User.objects.create_user("delegada-norte")
        outsider.save(update_fields=["delegation", "user"])
        outsider.roles.add(team)
        self.client.force_login(outsider.user)
        self.assertEqual(self.client.get(self.support_url()).status_code, 404)
        self.assertEqual(self.client.get(self.support_url(item_name="Visita terreno")).status_code, 404)

        # El propio funcionario sí ve su respaldo, pero no el de un colega.
        own = Role.objects.create(role_name="Solo propio respaldo", scope=Role.Scope.OWN)
        own.permissions.set(Permission.objects.filter(content_type__app_label="analytics", codename="view_indicatorsnapshot"))
        self.worker.user = User.objects.create_user("gestora-respaldo")
        self.worker.save(update_fields=["user"])
        self.worker.roles.add(own)
        self.client.force_login(self.worker.user)
        self.assertEqual(self.client.get(self.support_url()).status_code, 200)
        self.assertEqual(self.client.get(self.support_url(official=outsider)).status_code, 404)

    def test_open_period_has_no_frozen_support(self, _today):
        self.record(self.worker, "Visita terreno", 1)
        self.assertEqual(self.client.get(self.support_url()).status_code, 404)
        panel = self.client.get(reverse("my_performance"), {"period": self.period.pk, "official": self.worker.pk})
        visit = next(entry for entry in panel.context["rows"] if entry["row"].item.item_name == "Visita terreno")
        self.assertTrue(visit["link"].startswith(reverse("activity_maintainer")))

    def test_period_frozen_before_this_version_says_there_is_no_support(self, _today):
        self.record(self.worker, "Visita terreno", 1)
        self.close()
        IndicatorSupportSnapshot.objects.all().delete()
        IndicatorSnapshot.objects.update(support_captured=False)
        response = self.client.get(self.support_url())
        self.assertContains(response, PRE_SUPPORT_NOTICE)
        self.assertNotContains(response, "Registros al cierre")

    def test_team_boards_link_to_the_frozen_support(self, _today):
        self.record(self.worker, "Visita terreno", 1)
        self.close()
        modal = self.client.get(reverse("delegation_performance"), {
            "period": self.period.pk, "delegation": self.delegation.pk, "official": self.worker.pk,
            "fragment": "official-result"})
        self.assertContains(modal, self.support_url())
        self.assertTrue(all(entry["activity_link"].startswith(self.support_url()) for entry in modal.context["selected_items"]))
        board = self.client.get(reverse("position_performance"), {
            "period": self.period.pk, "position": self.positions["Gestor social"].pk})
        self.assertContains(board, self.support_url())

    def viewer(self, username, activity_scope=None):
        """Supervisor de la delegación con alcance de equipo y de compromisos; el de actividades se elige."""
        team = Role.objects.create(role_name=f"Equipo {username}", scope=Role.Scope.DELEGATION)
        team.permissions.set(Permission.objects.filter(
            Q(content_type__app_label="analytics", codename__in=["view_indicatorsnapshot", "view_team_performance"])
            | Q(content_type__app_label="agenda", codename="view_commitment")))
        official = self.official(f"Supervisora {username}")
        official.user = User.objects.create_user(username)
        official.save(update_fields=["user"])
        official.roles.add(team)
        if activity_scope:
            activities = Role.objects.create(role_name=f"Actividades {username}", scope=activity_scope)
            activities.permissions.set(Permission.objects.filter(content_type__app_label="activities",
                                                                 codename="view_activity"))
            official.roles.add(activities)
        return official

    def test_rows_follow_the_viewer_scope_but_the_summary_stays_complete(self, _today):
        self.record(self.worker, "Visita terreno", 2)
        for status in ("DONE", "PENDING"):
            self.commitment(status)
        self.close()

        limited = self.viewer("supervisora-propia", activity_scope=Role.Scope.OWN)
        self.client.force_login(limited.user)
        response = self.client.get(self.support_url())
        self.assertEqual(response.status_code, 200)
        kinds = {("activity" if row["record"].activity_id else "commitment") for row in response.context["supports"]}
        self.assertEqual(kinds, {"commitment"})  # sus propias actividades: ninguna del funcionario
        self.assertEqual(response.context["page_obj"].paginator.count, 2)
        self.assertEqual(response.context["hidden"], 2)
        self.assertContains(response, 'data-support-hidden="2"')
        self.assertContains(response, "2 actividades computadas")  # el resumen es del funcionario completo
        self.assertContains(response, "1 de 2 compromisos realizados")

        complete = self.viewer("supervisora-delegacion", activity_scope=Role.Scope.DELEGATION)
        self.client.force_login(complete.user)
        response = self.client.get(self.support_url())
        self.assertEqual((response.context["page_obj"].paginator.count, response.context["hidden"]), (4, 0))
        self.assertNotContains(response, "data-support-hidden")

        # Sin permiso de actividades ni de compromisos no ve filas, solo el resumen y el aviso.
        bare = self.viewer("supervisora-sin-registros")
        bare.roles.get().permissions.remove(Permission.objects.get(content_type__app_label="agenda", codename="view_commitment"))
        self.client.force_login(bare.user)
        response = self.client.get(self.support_url())
        self.assertEqual((response.context["page_obj"].paginator.count, response.context["hidden"]), (0, 4))
        self.assertContains(response, "dentro de tu alcance de consulta")

    def test_annulled_evidence_before_closing_is_not_in_the_support(self, _today):
        kept, annulled = self.record(self.worker, "Visita terreno", 2)
        batch = EvidenceBatch.objects.create(activity=annulled, author=self.worker,
                                             stage=EvidenceBatch.Stage.COMPLETED, description="Respaldo")
        Evidence.objects.filter(activity=annulled).update(batch=batch)
        self.verifier.user = self.admin
        self.verifier.save(update_fields=["user"])
        response = self.client.post(reverse("activity_evidence_annul", args=[annulled.pk, batch.pk]),
                                    {"reason": "La imagen correspondía a otra gestión."})
        self.assertEqual(response.status_code, 302)
        self.assertFalse(EvidenceValidation.objects.filter(evidence__activity=annulled, deleted_at__isnull=True).exists())
        self.close()
        self.assert_support_matches_frozen_figure()
        visits = self.frozen("Visita terreno")
        self.assertEqual(visits.progress, 1)
        self.assertEqual(list(visits.supports.values_list("activity_id", flat=True)), [kept.pk])
        self.assertFalse(IndicatorSupportSnapshot.objects.filter(activity=annulled).exists())

    def test_close_period_takes_the_registry_lock_before_freezing(self, _today):
        calls = []
        with patch("configuration.period_services.lock_period_registry", side_effect=lambda: calls.append("registro")), \
                patch.object(Calc, "freeze_period", side_effect=lambda *args, **kwargs: calls.append("congelar")):
            self.period.close_period()
        self.assertEqual(calls, ["registro", "congelar"])

    def test_final_score_cap_is_configurable_used_and_frozen(self, _today):
        line = self.single_plan(goal=10)  # 15/10 → 150 % (tope computable) x 100 = 150 puntos base
        version = line.version
        self.record(self.worker, "Visita terreno", 15)
        self.assertEqual(Calc.calculate(self.worker, self.period, END).total, 120)  # 150 puntos base quedan en 120

        version.max_final_score = Decimal("150")  # Versión publicada antes del máximo individual.
        version.save(update_fields=["max_final_score"])
        live = Calc.calculate(self.worker, self.period, END)
        self.assertEqual((live.base_total, live.max_final_score, live.total), (150, 120, 120))
        self.assertEqual(create_revision(version.plan, date(2026, 8, 1)).max_final_score, 120)  # la revisión lo copia
        version.plan.versions.filter(published_at__isnull=True).delete()

        self.close()
        snapshot = self.frozen("Visita terreno")
        self.assertEqual(snapshot.score_summary["max_final"], "120.00")
        version.max_final_score = Decimal("200")
        version.save(update_fields=["max_final_score"])
        frozen = Calc.result_for(self.worker, self.period)
        self.assertEqual((frozen.max_final_score, frozen.total), (120, 120))
        panel = self.client.get(reverse("my_performance"), {"period": self.period.pk, "official": self.worker.pk})
        self.assertEqual(panel.context["result"].max_final_score, 120)
        # Recorta sin reclamos ni felicitaciones: el panel distingue la base del resultado final.
        self.assertContains(panel, "data-performance-base>150,00 puntos")
        self.assertContains(panel, "data-performance-cap>120 puntos (aplicado)")

        # Un cierre histórico conserva tanto el resultado como la regla vigente al cerrarlo.
        summary = {**snapshot.score_summary, "total": "145.00", "max_final": "150.00"}
        for explicit_cap in (True, False):
            if not explicit_cap:
                summary.pop("max_final")
            snapshot.score_summary = summary
            snapshot.save(update_fields=["score_summary"])
            historical = Calc.result_for(self.worker, self.period)
            self.assertEqual((historical.max_final_score, historical.total), (150, 145))

    def test_final_score_cap_is_validated_in_the_plan_form(self, _today):
        version = self.plans["Gestor social"].versions.get()
        for value, valid in (("0", False), ("1001", False), ("abc", False), ("1", True), ("119.99", True), ("120", True), ("120.01", False)):
            with self.subTest(value=value):
                data = {**model_to_dict(version, fields=VersionForm.Meta.fields), "max_final_score": value}
                form = VersionForm(data, instance=version)
                self.assertEqual(form.is_valid(), valid, form.errors)
                if not valid:
                    self.assertIn("max_final_score", form.errors)
        self.assertIn("max_final_score", VersionForm.Meta.fields)

    def test_archived_activity_rows_need_the_archive_permission(self, _today):
        kept, archived = self.record(self.worker, "Visita terreno", 2)
        self.close()
        Activity.objects.filter(pk=archived.pk).update(deleted_at=timezone.now())
        supervisor = self.viewer("supervisora-sin-archivo", activity_scope=Role.Scope.DELEGATION)
        self.client.force_login(supervisor.user)
        response = self.client.get(self.support_url(item_name="Visita terreno"))
        self.assertEqual([row["record"].activity_id for row in response.context["supports"]], [kept.pk])
        self.assertEqual(response.context["hidden"], 1)
        self.assertContains(response, "2 actividades computadas")
        self.assertEqual(self.client.get(reverse("activity_detail", args=[archived.pk])).status_code, 404)

        archive = Role.objects.create(role_name="Archivo de actividades", scope=Role.Scope.DELEGATION)
        archive.permissions.set(Permission.objects.filter(content_type__app_label="activities", codename="archive_activity"))
        supervisor.roles.add(archive)
        response = self.client.get(self.support_url(item_name="Visita terreno"))
        self.assertEqual({row["record"].activity_id for row in response.context["supports"]}, {kept.pk, archived.pk})
        self.assertEqual(response.context["hidden"], 0)
        self.assertContains(response, "data-support-archived")

    def test_final_score_cap_survives_a_last_segment_without_plan(self, _today):
        line = self.single_plan(goal=10)
        line.version.max_final_score = Decimal("40")
        line.version.save(update_fields=["max_final_score"])
        self.record(self.worker, "Visita terreno", 15, day=date(2026, 7, 10))
        without_plan = Position.objects.create(position_name="Cargo sin plan de medición")
        change_position(self.worker, without_plan, date(2026, 9, 1), self.verifier)
        live = Calc.calculate(self.worker, self.period, END)
        self.assertGreater(live.base_total, 40)
        self.assertEqual((live.max_final_score, live.total), (40, 40))
        self.close()
        frozen = Calc.result_for(self.worker, self.period)
        self.assertEqual((frozen.max_final_score, frozen.total), (40, 40))
        self.assertEqual(self.frozen("Visita terreno").score_summary["max_final"], "40.00")
