"""Panel «Mi desempeño», semáforo accesible y congelamiento de períodos cerrados (Fase 2).

RF-008, RF-027, RF-028, RF-038, RN-013, HU-06, HU-16, HU-17, CA-05, CA-10.
"""
from datetime import date, datetime, time
from decimal import Decimal
from io import StringIO
from unittest.mock import patch

from django.contrib.auth.models import Permission, User
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connection
from django.test import TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from accounts.models import Delegation, Function, Role
from activities.models import (Activity, AttentionCase, Evidence, EvidenceBatch, EvidenceValidation, ServiceRecipient,
                               SocialAttention)
from agenda.models import Commitment
from analytics.measurement import publish_version
from analytics.models import IndicatorSnapshot, MeasurementItem, MeasurementPlan, MeasurementVersion
from analytics.services import CalculadorDesempenoService as Calc
from analytics.test_performance_calculator import END, CalculatorFixture
from common.sgr_seed_data import PERCENTAGE_ITEM
from configuration.models import AttentionType, AuditLog, Period, SubattentionType

TODAY = date(2026, 8, 26)
URL = reverse("my_performance")


def permissions(*names):
    return [Permission.objects.get(content_type__app_label=name.split(".")[0], codename=name.split(".")[1])
            for name in names]


@override_settings(PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"])
@patch("analytics.views.timezone.localdate", return_value=TODAY)
class PerformancePanelTests(CalculatorFixture, TestCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.other_delegation = Delegation.objects.create(delegation_name="Sur", address="Calle 2", commune="La Serena")
        own = Role.objects.create(role_name="Funcionario panel", scope=Role.Scope.DELEGATION)
        own.permissions.set(permissions("analytics.view_indicatorsnapshot", "activities.view_activity"))
        team = Role.objects.create(role_name="Delegado panel", scope=Role.Scope.DELEGATION)
        team.permissions.set(permissions("analytics.view_indicatorsnapshot", "analytics.view_team_performance"))
        global_team = Role.objects.create(role_name="Coordinación panel", scope=Role.Scope.ALL)
        global_team.permissions.set(permissions("analytics.view_indicatorsnapshot", "analytics.view_team_performance"))

        cls.worker = cls.with_user(cls.official("Gestora panel", "Gestor social"), "gestora", own)
        cls.colleague = cls.with_user(cls.official("Colega panel", "Apoyo administrativo"), "colega", own)
        cls.delegate = cls.with_user(cls.official("Delegada panel"), "delegada", team)
        cls.coordinator = cls.with_user(cls.official("Coordinadora panel"), "coordinadora", global_team)
        cls.outsider = cls.official("Funcionario Sur", "Gestor social")
        cls.outsider.delegation = cls.other_delegation
        cls.outsider.save(update_fields=["delegation"])
        cls.no_permission = cls.with_user(cls.official("Sin permiso"), "sinpermiso", None)

    @classmethod
    def with_user(cls, official, username, role):
        official.user = User.objects.create_user(username, password="Clave-Panel-2026")
        official.save(update_fields=["user"])
        if role:
            official.roles.add(role)
        return official

    def view(self, user, **params):
        self.client.force_login(user.user)
        return self.client.get(URL, {"period": self.period.pk, **params})

    def batch(self, activity, status=None):
        batch = EvidenceBatch.objects.create(activity=activity, author=activity.official,
                                             stage=EvidenceBatch.Stage.COMPLETED, description="Respaldo")
        image = Evidence.objects.create(activity=activity, batch=batch, file_url="z.png", file_format="png", size_kb=1)
        if status:
            EvidenceValidation.objects.create(evidence=image, verifier=self.verifier, status=status,
                                              observation="Motivo")
        return batch

    # --- Acceso y alcance -------------------------------------------------------------------

    def test_anonymous_is_redirected_and_without_permission_is_forbidden(self, _today):
        response = self.client.get(URL)
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("login"), response["Location"])
        self.assertEqual(self.view(self.no_permission).status_code, 403)

    def test_official_sees_only_own_result(self, _today):
        response = self.view(self.worker)
        self.assertContains(response, "Mi desempeño")
        self.assertContains(response, "Visita terreno")
        self.assertNotContains(response, 'id="performance-official"')
        before = AuditLog.objects.filter(action="Acceso denegado").count()
        self.assertEqual(self.view(self.worker, official=self.colleague.pk).status_code, 404)
        self.assertEqual(AuditLog.objects.filter(action="Acceso denegado").count(), before + 1)
        self.assertEqual(self.view(self.worker, official=self.worker.pk).status_code, 200)

    def test_delegation_scope_can_choose_officials_of_its_delegation_only(self, _today):
        response = self.view(self.delegate, official=self.colleague.pk)
        self.assertContains(response, "Desempeño de Colega panel")
        self.assertContains(response, 'id="performance-official"')
        self.assertNotContains(response, "Funcionario Sur")
        before = AuditLog.objects.filter(action="Acceso denegado").count()
        self.assertEqual(self.view(self.delegate, official=self.outsider.pk).status_code, 404)
        self.assertEqual(AuditLog.objects.filter(action="Acceso denegado").count(), before + 1)
        self.assertEqual(self.view(self.delegate, official="abc").status_code, 404)

    def test_global_scope_reaches_other_delegations(self, _today):
        self.assertContains(self.view(self.coordinator, official=self.outsider.pk), "Desempeño de Funcionario Sur")

    def test_official_without_position_or_plan_gets_a_clear_message(self, _today):
        response = self.view(self.delegate)
        self.assertContains(response, "El funcionario no tiene cargo asignado.")
        self.assertNotContains(response, "Resultado por ítem")

    # --- Contenido y semáforo -----------------------------------------------------------------

    def test_rows_show_text_and_icon_traffic_lights_and_link_to_source_activities(self, _today):
        self.record(self.worker, "Visita terreno", 12, day=date(2026, 7, 20))
        response = self.view(self.worker)
        rows = {row["row"].item.item_name: row for row in response.context["rows"]}
        self.assertEqual(rows["Visita terreno"]["row"].traffic_light, "GREEN")
        self.assertContains(response, "Verde: en meta")
        self.assertContains(response, "Rojo: bajo el umbral")
        self.assertContains(response, 'data-traffic-light="GREEN"')
        link = rows["Visita terreno"]["link"]
        self.assertIn(f"official={self.worker.pk}", link)
        self.assertIn(f"item={self.items['Visita terreno'].pk}", link)
        self.assertIn("evidence=counted", link)
        self.assertIn("date_from=2026-07-01", link)
        self.assertIn("date_to=2026-08-26", link)  # mismo corte que el avance: hoy, en un período abierto
        self.assertIsNone(rows[PERCENTAGE_ITEM]["link"])  # el tubo no viene de actividades
        self.assertEqual(round(response.context["result"].expected_percentage, 2), Decimal("61.54"))

    def test_red_result_shows_last_record_and_days_without_records(self, _today):
        self.record(self.worker, "Visita terreno", 1, day=date(2026, 8, 6))
        response = self.view(self.worker)
        self.assertEqual(response.context["total_light"], "RED")
        self.assertContains(response, "Desviación: resultado bajo el umbral")
        self.assertContains(response, "06-08-2026")
        self.assertEqual(response.context["deviation"]["days_without"], 20)

    def test_counters_of_evidence_and_commitments(self, _today):
        [first, second, third, fourth] = self.record(self.worker, "Visita terreno", 4, status=None)
        self.batch(first)
        self.batch(second, EvidenceValidation.Status.REJECTED)
        self.batch(third, EvidenceValidation.Status.CORRECTION_REQUESTED)
        self.batch(fourth, EvidenceValidation.Status.APPROVED)
        Commitment.objects.create(responsible=self.worker, requester="Vecino", territory="Centro",
                                  committed_date=date(2026, 8, 1))
        Commitment.objects.create(responsible=self.worker, requester="Vecina", territory="Centro",
                                  committed_date=date(2026, 9, 1), current_status=Commitment.Status.DONE)
        Commitment.objects.create(responsible=self.worker, requester="Otro período", territory="Centro",
                                  committed_date=date(2026, 10, 5))
        response = self.view(self.worker)
        self.assertEqual(response.context["evidence"], {"pending": 1, "rejected": 1, "correction": 1})
        self.assertEqual(response.context["commitments"], {"open": 1, "overdue": 1, "done": 1})

    def test_result_changes_when_evidence_is_approved_and_not_when_rejected(self, _today):
        [activity] = self.record(self.worker, "Visita terreno", 1, day=date(2026, 7, 10), status=None)

        def progress():
            rows = self.view(self.worker).context["rows"]
            return next(r["row"].progress for r in rows if r["row"].item.item_name == "Visita terreno")

        self.assertEqual(progress(), 0)
        rejected = self.batch(activity, EvidenceValidation.Status.REJECTED)
        self.assertEqual(progress(), 0)
        EvidenceValidation.objects.filter(evidence__batch=rejected).update(status=EvidenceValidation.Status.APPROVED)
        self.assertEqual(progress(), 1)

    def test_query_count_does_not_grow_with_records(self, _today):
        self.record(self.worker, "Visita terreno", 1)
        self.client.force_login(self.worker.user)
        self.client.get(URL, {"period": self.period.pk})  # calienta sesión y caché de permisos
        with CaptureQueriesContext(connection) as small:
            self.client.get(URL, {"period": self.period.pk})
        for name in ("Visita terreno", "Entrega informe", "Entrega beneficio"):
            self.record(self.worker, name, 15, day=date(2026, 7, 15))
        with CaptureQueriesContext(connection) as large:
            self.client.get(URL, {"period": self.period.pk})
        # El caso pequeño queda en rojo y consulta además el último registro (desviación); el
        # grande no puede necesitar más consultas pese a tener 45 registros más.
        self.assertLessEqual(len(large), len(small))
        self.assertLess(len(large), 40)

    # --- Congelamiento (RN-013) ---------------------------------------------------------------

    def close(self):
        self.period.close_period()
        self.period.refresh_from_db()

    def test_closing_freezes_weighted_and_tube_progress_and_later_changes_do_not_alter_it(self, _today):
        self.record(self.worker, "Visita terreno", 6, day=date(2026, 8, 1))
        stamp = timezone.make_aware(datetime.combine(date(2026, 8, 1), time(9)))
        done = Commitment.objects.create(responsible=self.worker, requester="Vecino", territory="Centro",
                                         committed_date=date(2026, 9, 1), creation_date=stamp,
                                         current_status=Commitment.Status.DONE)
        Commitment.objects.create(responsible=self.worker, requester="Vecina", territory="Centro",
                                  committed_date=date(2026, 9, 2), creation_date=stamp)
        live = Calc.calculate(self.worker, self.period, END)
        self.close()

        frozen = IndicatorSnapshot.objects.get(official=self.worker, item=self.items[PERCENTAGE_ITEM], is_frozen=True)
        self.assertEqual((frozen.progress, frozen.weighted), (50, live_row(live, PERCENTAGE_ITEM).weighted))
        visit = IndicatorSnapshot.objects.get(official=self.worker, item=self.items["Visita terreno"], is_frozen=True)
        self.assertEqual(visit.weighted, live_row(live, "Visita terreno").weighted)

        # Después del cierre: se archiva un compromiso, se reasigna otro, se aprueba más evidencia
        # y se cambia el plan. El resultado del período cerrado no cambia.
        done.deleted_at = timezone.now()
        done.save(update_fields=["deleted_at"])
        Commitment.objects.filter(responsible=self.worker).update(responsible=self.colleague)
        self.record(self.worker, "Visita terreno", 6, day=date(2026, 8, 2))
        self.plans["Gestor social"].versions.get().items.filter(item=self.items["Visita terreno"]).update(goal=99)

        result = Calc.result_for(self.worker, self.period, END)
        self.assertTrue(result.frozen)
        self.assertEqual(result.total, live.total)
        self.assertEqual(live_row(result, PERCENTAGE_ITEM).progress, 50)
        self.assertEqual((live_row(result, "Visita terreno").goal, live_row(result, "Visita terreno").progress), (12, 6))
        self.assertNotEqual(Calc.calculate(self.worker, self.period, END).total, live.total)  # el vivo sí cambiaría

        response = self.view(self.worker)
        self.assertContains(response, "Congelado al cierre")
        self.assertEqual(response.context["result"].total, live.total)

    def test_reclosing_after_reopening_replaces_the_frozen_result(self, _today):
        self.close()
        first = set(Calc.frozen_snapshots(self.period).values_list("pk", flat=True))
        self.assertTrue(first)
        Period.objects.filter(pk=self.period.pk).update(status=Period.Status.OPEN)
        self.period.refresh_from_db()
        self.record(self.worker, "Visita terreno", 3)
        self.close()
        self.assertFalse(Calc.frozen_snapshots(self.period).filter(pk__in=first).exists())
        second = set(Calc.frozen_snapshots(self.period).values_list("pk", flat=True))
        self.period.close_period()  # cerrar un período ya cerrado no vuelve a congelar
        self.assertEqual(set(Calc.frozen_snapshots(self.period).values_list("pk", flat=True)), second)
        self.assertEqual(IndicatorSnapshot.objects.filter(pk__in=first, deleted_at__isnull=False).count(), len(first))
        self.assertEqual(live_row(Calc.frozen_result(self.worker, self.period), "Visita terreno").progress, 3)

    def test_freeze_period_command_is_idempotent_for_periods_closed_before(self, _today):
        Period.objects.filter(pk=self.period.pk).update(status=Period.Status.CLOSED)  # cierre previo a la fase
        self.period.refresh_from_db()
        self.assertIsNone(self.period.frozen_at)
        self.colleague.deleted_at = timezone.now()  # funcionario archivado: no se congela
        self.colleague.save(update_fields=["deleted_at"])
        result = Calc.result_for(self.worker, self.period, END)
        self.assertIn("freeze_period", result.notice)
        self.assertEqual(result.items, [])

        out = StringIO()
        call_command("freeze_period", self.period.pk, stdout=out)
        created = Calc.frozen_snapshots(self.period).count()
        self.assertGreater(created, 0)
        self.assertIn("indicadores congelados", out.getvalue())
        self.assertTrue(AuditLog.objects.filter(action="Congelamiento de indicadores").exists())
        self.assertFalse(Calc.frozen_snapshots(self.period).filter(official=self.colleague).exists())
        self.assertTrue(Calc.frozen_snapshots(self.period).filter(official=self.worker).exists())
        self.period.refresh_from_db()
        self.assertIsNotNone(self.period.frozen_at)
        call_command("freeze_period", self.period.pk, stdout=out)
        self.assertEqual(Calc.frozen_snapshots(self.period).count(), created)
        self.assertIn("sin cambios", out.getvalue())

        other = Period.objects.create(start_date=date(2026, 10, 1), end_date=date(2026, 12, 31))
        with self.assertRaises(CommandError):
            call_command("freeze_period", other.pk, stdout=out)
        with self.assertRaises(CommandError):
            call_command("freeze_period", 999999, stdout=out)

    def test_closing_without_measurable_officials_marks_the_period_and_never_adds_results_later(self, _today):
        later = Period.objects.create(start_date=date(2027, 1, 1), end_date=date(2027, 3, 31))
        plan = self.make_plan("Cargo sin funcionarios", (("Visita terreno", "100", 10),), period=later)
        later.close_period()
        later.refresh_from_db()
        self.assertIsNotNone(later.frozen_at)
        self.assertFalse(Calc.frozen_snapshots(later).exists())

        # Después del cierre se asigna el cargo: el período cerrado no gana resultados.
        self.colleague.position = plan.position
        self.colleague.save(update_fields=["position"])
        out = StringIO()
        call_command("freeze_period", later.pk, stdout=out)
        self.assertIn("sin cambios", out.getvalue())
        self.assertFalse(Calc.frozen_snapshots(later).exists())
        self.assertEqual(Calc.freeze_period(later), 0)
        self.assertFalse(Calc.frozen_snapshots(later).exists())
        result = Calc.result_for(self.colleague, later, date(2027, 4, 1))
        self.assertTrue(result.frozen)
        self.assertEqual(result.items, [])
        self.assertIn("no tenía un plan de medición aplicable", result.notice)

    def test_close_period_uses_the_dates_of_the_locked_row(self, _today):
        stale = Period.objects.get(pk=self.period.pk)
        Period.objects.filter(pk=self.period.pk).update(end_date=date(2026, 10, 15))  # cambio concurrente
        self.record(self.worker, "Visita terreno", 2, day=date(2026, 10, 10))
        stale.close_period()
        self.assertEqual((stale.status, stale.end_date), (Period.Status.CLOSED, date(2026, 10, 15)))
        self.assertIsNotNone(stale.frozen_at)
        visit = Calc.frozen_snapshots(self.period).get(official=self.worker, item=self.items["Visita terreno"])
        self.assertEqual(visit.progress, 2)

    def test_closed_period_keeps_goal_weight_and_total_light_after_later_plan_changes(self, _today):
        # RF-038: cambios de meta, ponderador y umbral en un período posterior (y aun en la versión
        # del período cerrado) no alteran el resultado congelado, incluido el semáforo total.
        self.record(self.worker, "Visita terreno", 12, day=date(2026, 8, 1))
        self.close()
        before = Calc.result_for(self.worker, self.period, END)
        self.assertEqual(before.total_traffic_light, "RED")  # 20 puntos frente al 100 % esperado
        frozen_rows = {(r.item.pk, r.goal, r.weight, r.weighted, r.traffic_light) for r in before.items}

        position = self.positions["Gestor social"]
        following = Period.objects.create(start_date=date(2026, 10, 1), end_date=date(2026, 12, 31))
        plan = MeasurementPlan.objects.create(period=following, position=position)
        version = plan.versions.create(number=1, effective_from=following.start_date,
                                       amber_threshold=Decimal("10"), green_threshold=Decimal("15"))
        MeasurementItem.objects.create(version=version, function=Function.objects.filter(positions=position).first(),
                                       item=self.items["Visita terreno"], goal=4, weight=Decimal("100"))
        publish_version(version)
        MeasurementVersion.objects.filter(plan__period=self.period, plan__position=position).update(
            amber_threshold=Decimal("10"), green_threshold=Decimal("15"))
        MeasurementItem.objects.filter(version__plan__period=self.period, version__plan__position=position).update(
            goal=1, weight=Decimal("50"))

        after = Calc.result_for(self.worker, self.period, END)
        self.assertEqual({(r.item.pk, r.goal, r.weight, r.weighted, r.traffic_light) for r in after.items}, frozen_rows)
        self.assertEqual((after.total, after.total_traffic_light), (before.total, "RED"))
        self.assertNotEqual(Calc.calculate(self.worker, self.period, END).total_traffic_light, "RED")  # en vivo sí cambiaría
        response = self.view(self.worker)
        self.assertEqual(response.context["total_light"], "RED")

        # El período siguiente sí usa la meta, el ponderador y los umbrales nuevos.
        self.record(self.worker, "Visita terreno", 1, day=date(2026, 10, 5))
        upcoming = Calc.calculate(self.worker, following, date(2026, 12, 31))
        row = live_row(upcoming, "Visita terreno")
        self.assertEqual((row.goal, row.weight, upcoming.total), (4, 100, 25))
        self.assertEqual(upcoming.total_traffic_light, "GREEN")

    # --- Delegación, períodos y enlace a las actividades (RF-008, RF-028, HU-06) ----------------

    def test_panel_shows_the_delegation_and_defaults_to_the_current_period(self, _today):
        previous = Period.objects.create(start_date=date(2026, 4, 1), end_date=date(2026, 6, 30))
        Period.objects.create(start_date=date(2026, 10, 1), end_date=date(2026, 12, 31))
        self.worker.authorized_delegations.add(self.other_delegation)
        self.client.force_login(self.worker.user)
        response = self.client.get(URL)
        self.assertEqual(response.context["period"], self.period)  # el vigente al 26-08-2026
        self.assertContains(response, "data-performance-delegation")
        self.assertContains(response, "Centro")
        self.assertContains(response, "También autorizado en: Sur")
        self.assertContains(response, "Gestora panel · Gestor social")  # funcionario y cargo

        # Cambio de período con el selector.
        response = self.client.get(URL, {"period": previous.pk})
        self.assertEqual(response.context["period"], previous)
        self.assertContains(response, f'<option value="{previous.pk}" selected>')
        self.assertContains(response, "No hay un plan de medición publicado para el cargo en este período.")
        self.assertEqual(self.client.get(URL, {"period": 999999}).status_code, 404)

    def test_selector_shows_goals_and_progress_of_each_period_with_plan(self, _today):
        # ACT-03: mismo funcionario, dos períodos con plan; al cambiar de período cambian las metas,
        # el avance y el total del período elegido.
        position = self.positions["Gestor social"]
        previous = Period.objects.create(start_date=date(2026, 4, 1), end_date=date(2026, 6, 30))
        plan = MeasurementPlan.objects.create(period=previous, position=position)
        version = plan.versions.create(number=1, effective_from=previous.start_date)
        MeasurementItem.objects.create(version=version, function=Function.objects.filter(positions=position).first(),
                                       item=self.items["Visita terreno"], goal=4, weight=Decimal("100"))
        publish_version(version)
        self.record(self.worker, "Visita terreno", 2, day=date(2026, 5, 10))
        self.record(self.worker, "Visita terreno", 6, day=date(2026, 7, 10))

        def rows(period):
            response = self.client.get(URL, {"period": period.pk})
            self.assertEqual(response.context["period"], period)
            return response.context["result"], {r["row"].item.item_name: r["row"] for r in response.context["rows"]}

        self.client.force_login(self.worker.user)
        current, current_rows = rows(self.period)
        earlier, earlier_rows = rows(previous)
        self.assertEqual((current_rows["Visita terreno"].goal, current_rows["Visita terreno"].progress), (12, 6))
        self.assertEqual(len(current_rows), 6)
        self.assertEqual(set(earlier_rows), {"Visita terreno"})
        self.assertEqual((earlier_rows["Visita terreno"].goal, earlier_rows["Visita terreno"].progress), (4, 2))
        self.assertEqual(earlier.total, 50)  # 2 de 4 con ponderador 100
        self.assertEqual(current.total, 10)  # 6 de 12 con ponderador 20
        self.assertEqual(earlier.expected_percentage, 100)  # período terminado

    def test_link_to_activities_lists_exactly_the_progress_of_the_item(self, _today):
        self.record(self.worker, "Visita terreno", 4, day=date(2026, 7, 20))
        self.record(self.worker, "Visita terreno", 2, day=date(2026, 7, 21), status=None)
        self.record(self.worker, "Visita terreno", 1, day=date(2026, 7, 22), status=EvidenceValidation.Status.REJECTED)
        self.record(self.worker, "Visita terreno", 1, day=date(2026, 8, 27))  # posterior a hoy: aún no cuenta
        # Registrada con un cargo cuyo plan no incluye el ítem (cambio de cargo): aprobada, pero no cuenta.
        [moved] = self.record(self.worker, "Visita terreno", 1, day=date(2026, 7, 23))
        Activity.objects.filter(pk=moved.pk).update(registration_position=self.positions["Apoyo administrativo"])
        response = self.view(self.worker)
        entry = next(r for r in response.context["rows"] if r["row"].item.item_name == "Visita terreno")
        self.assertEqual(entry["row"].progress, 4)
        listing = self.client.get(entry["link"])
        self.assertEqual(listing.status_code, 200)
        self.assertEqual(listing.context["total"], entry["row"].progress)

    def test_shared_official_total_is_complete_but_activity_detail_is_limited_to_the_scope(self, _today):
        # Convención: el desempeño es del funcionario completo; el detalle respeta el alcance.
        role = Role.objects.create(role_name="Delegado con actividades", scope=Role.Scope.DELEGATION)
        role.permissions.set(permissions("analytics.view_indicatorsnapshot", "analytics.view_team_performance",
                                         "activities.view_activity"))
        viewer = self.with_user(self.official("Delegado Centro"), "delegadocentro", role)
        shared = self.official("Funcionaria compartida", "Gestor social")
        shared.delegation = self.other_delegation
        shared.save(update_fields=["delegation"])
        shared.authorized_delegations.add(self.delegation)

        self.record(shared, "Visita terreno", 3, day=date(2026, 7, 10))
        recipient = ServiceRecipient.objects.create(full_name="Persona ficticia", national_id="12345678-5")
        kind = AttentionType.objects.create(name="Orientación panel", activity_item=self.items["Visita terreno"])
        sub = SubattentionType.objects.create(name="Derivación panel", attention_type=kind)
        case = AttentionCase.objects.create(recipient=recipient, delegation=self.other_delegation, subject="Visita")
        for activity in self.record(shared, "Visita terreno", 2, day=date(2026, 7, 11)):
            SocialAttention.objects.create(case=case, activity=activity, recipient=recipient, attention_type=kind,
                                           subattention_type=sub, delegation=self.other_delegation,
                                           responsible=shared, date=activity.date)

        # Atención en la otra delegación con un ítem fuera del plan del cargo: no cuenta ni se avisa.
        [outside] = self.record(shared, "Informe de inventarios", 1, day=date(2026, 7, 12))
        SocialAttention.objects.create(case=case, activity=outside, recipient=recipient, attention_type=kind,
                                       subattention_type=sub, delegation=self.other_delegation,
                                       responsible=shared, date=outside.date)

        response = self.view(viewer, official=shared.pk)
        entry = next(r for r in response.context["rows"] if r["row"].item.item_name == "Visita terreno")
        self.assertEqual(sum(r["hidden"] for r in response.context["rows"]), 2)
        self.assertEqual(entry["row"].progress, 5)  # el total incluye las atenciones de la otra delegación
        self.assertEqual(entry["hidden"], 2)
        self.assertContains(response, "Incluye 2 actividades de otra delegación que no puedes ver.")
        listing = self.client.get(entry["link"])
        self.assertEqual(listing.context["total"], 3)
        self.assertEqual(listing.context["total"] + entry["hidden"], entry["row"].progress)

        # Con alcance global no hay actividades ocultas.
        global_role = Role.objects.create(role_name="Global con actividades", scope=Role.Scope.ALL)
        global_role.permissions.set(permissions("analytics.view_indicatorsnapshot", "analytics.view_team_performance",
                                                "activities.view_activity"))
        coordinator = self.with_user(self.official("Coordinación total"), "coordinaciontotal", global_role)
        response = self.view(coordinator, official=shared.pk)
        self.assertNotContains(response, "de otra delegación que no puedes ver")
        entry = next(r for r in response.context["rows"] if r["row"].item.item_name == "Visita terreno")
        self.assertEqual(self.client.get(entry["link"]).context["total"], 5)

    def test_closed_period_without_plan_for_official_shows_message(self, _today):
        self.close()
        response = self.view(self.coordinator, official=self.delegate.pk)
        self.assertContains(response, "no tenía un plan de medición aplicable")


def live_row(result, name):
    return next(row for row in result.items if row.item.item_name == name)

