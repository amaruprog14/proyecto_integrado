import json
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth.models import Permission, User
from django.core.exceptions import ValidationError
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.absence_views import AbsenceForm
from accounts.models import Delegation, Official, OfficialAbsence, OfficialPositionPeriod, Role
from activities.models import Activity
from accounts.position_services import change_position
from agenda.models import Commitment
from analytics.measurement import create_revision, publish_version
from analytics.models import MeasurementItem
from analytics.queries import summarize_team
from analytics.services import CalculadorDesempenoService as Calc, computable_days, expected_percentage
from analytics.test_performance_calculator import CalculatorFixture, START, END
from common.maintainer_forms import activity_item_choices
from common.testing_edit import post_with_revision
from configuration.models import AuditLog


@override_settings(PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"])
class MeasurementRulesTests(CalculatorFixture, TestCase):
    def setUp(self):
        self.worker = self.official("Medición por fechas", "Gestor social")
        self.admin = User.objects.create_superuser("medicion-admin", "admin@medicion.test", "test-password")
        self.verifier.user = self.admin
        self.verifier.save(update_fields=["user"])
        self.client.force_login(self.admin)

    def absence(self, start, end, **kwargs):
        return OfficialAbsence.objects.create(official=self.worker, registered_by=self.verifier,
            kind=OfficialAbsence.Kind.LICENCIA, start_date=start, end_date=end, reason="Ausencia de prueba", **kwargs)

    def single_plan(self, kind="QUANTITY", goal=10):
        version = self.plans["Gestor social"].versions.get()
        version.items.exclude(item=self.items["Visita terreno"]).delete()
        line = version.items.get()
        line.goal_type, line.goal, line.weight = kind, goal, 100
        line.save()
        return version, line

    def test_absences_clip_dates_and_preserve_guide_without_official(self):
        self.absence(date(2026, 6, 28), date(2026, 7, 3))
        self.absence(date(2026, 9, 29), date(2026, 10, 5))
        self.assertEqual(computable_days(self.period), 91)
        self.assertEqual(round(expected_percentage(self.period, date(2026, 8, 26)), 2), Decimal("61.54"))
        self.assertEqual(computable_days(self.period, self.worker), 87)
        self.assertEqual(computable_days(self.period, self.worker, date(2026, 7, 2)), 0)
        self.assertEqual(computable_days(self.period, self.worker, date(2026, 6, 1)), 0)
        self.assertEqual(computable_days(self.period, self.worker, include_start_day=True), 87)

    def test_absence_validation_and_soft_deletion(self):
        first = self.absence(date(2026, 7, 10), date(2026, 7, 15))
        for start, end in [(date(2026, 7, 15), date(2026, 7, 17)), (date(2026, 7, 8), date(2026, 7, 20)),
                           (date(2026, 7, 20), date(2026, 7, 19))]:
            with self.assertRaises(ValidationError):
                self.absence(start, end)
        first.delete()
        self.assertIsNotNone(OfficialAbsence.objects.get(pk=first.pk).deleted_at)
        self.absence(date(2026, 7, 10), date(2026, 7, 15))
        with self.assertRaises(ValidationError):
            OfficialAbsence.objects.create(official=self.worker, registered_by=self.verifier, kind="EMERGENCIA",
                start_date=date(2026, 7, 20), end_date=date(2026, 7, 20), reason=" ")

    def test_zero_days_has_no_lights_and_is_excluded_from_team_average(self):
        self.absence(START, END)
        result = Calc.calculate(self.worker, self.period, END)
        self.assertEqual(result.computable_days, 0)
        self.assertIsNone(result.expected_percentage)
        self.assertIsNone(result.total_traffic_light)
        self.assertTrue(all(row.traffic_light is None and row.weighted == 0 for row in result.items))
        self.assertIn("Sin días computables", result.notice)
        self.assertEqual(summarize_team([result])["measured_count"], 0)

    def test_freeze_preserves_days_and_prohibits_all_absence_mutations(self):
        absence = self.absence(date(2026, 7, 10), date(2026, 7, 15))
        self.period.close_period()
        frozen = Calc.result_for(self.worker, self.period)
        self.assertEqual(frozen.computable_days, 85)
        for operation in (lambda: absence.delete(), lambda: self.absence(date(2026, 7, 20), date(2026, 7, 22))):
            with self.assertRaises(ValidationError):
                operation()
        absence.deleted_at = None
        absence.start_date = date(2026, 10, 10)
        absence.end_date = date(2026, 10, 11)
        with self.assertRaises(ValidationError):
            absence.save()
        self.assertEqual(Calc.result_for(self.worker, self.period).computable_days, 85)

    def test_absence_modal_audits_and_requires_permission(self):
        payload = {"official": self.worker.pk, "kind": "VACACIONES", "start_date": "2026-07-10",
                   "end_date": "2026-07-12", "reason": "Vacaciones registradas"}
        response = self.client.post(reverse("absence_create"), payload, HTTP_X_MODAL_REQUEST="true",
                                    REMOTE_ADDR="192.0.2.30")
        self.assertEqual(response.status_code, 204)
        event = AuditLog.objects.get(action="Ausencia guardada")
        self.assertEqual((event.origin_ip, event.actor_username), ("192.0.2.30", self.admin.username))
        self.assertEqual(event.previous_value, "")
        self.assertIn('Motivo: "Vacaciones registradas"', event.new_value)
        outsider = self.official("Sin permisos")
        outsider.user = User.objects.create_user("sin-permiso-ausencias")
        outsider.save(update_fields=["user"])
        self.client.force_login(outsider.user)
        self.assertEqual(self.client.get(reverse("absence_list")).status_code, 403)
        self.assertEqual(self.client.post(reverse("absence_create"), payload).status_code, 403)

    def test_absence_edit_rejects_stale_revision(self):
        absence = self.absence(date(2026, 7, 10), date(2026, 7, 12))
        url = reverse("absence_edit", args=[absence.pk])
        revision = self.client.get(url, HTTP_X_MODAL_REQUEST="true").context["edit_revision"]
        payload = {"official": self.worker.pk, "kind": "VACACIONES", "start_date": "2026-07-10",
                   "end_date": "2026-07-13", "reason": "Primera edición", "edit_revision": revision}
        self.assertEqual(self.client.post(url, payload, HTTP_X_MODAL_REQUEST="true").status_code, 204)
        payload["reason"] = "Edición con versión vencida"
        self.assertEqual(self.client.post(url, payload, HTTP_X_MODAL_REQUEST="true").status_code, 409)
        absence.refresh_from_db()
        self.assertEqual(absence.reason, "Primera edición")
        events = AuditLog.objects.filter(action="Ausencia guardada", affected_record_id=absence.pk,
                                        affected_table=absence._meta.db_table)
        self.assertEqual(events.count(), 1)
        self.assertNotIn("Edición con versión vencida", events.get().new_value)

    def test_absence_edit_audits_previous_reason_dates_and_kind(self):
        absence = self.absence(date(2026, 7, 10), date(2026, 7, 12))
        response = post_with_revision(self.client, reverse("absence_edit", args=[absence.pk]), {
            "official": self.worker.pk, "kind": "VACACIONES", "start_date": "2026-07-11",
            "end_date": "2026-07-14", "reason": "Motivo corregido",
        }, HTTP_X_MODAL_REQUEST="true", REMOTE_ADDR="192.0.2.40")
        self.assertEqual(response.status_code, 204)
        event = AuditLog.objects.get(action="Ausencia guardada")
        for value in ('Motivo: "Ausencia de prueba"', "Tipo de ausencia: Licencia", "Inicio: 2026-07-10", "Término: 2026-07-12"):
            self.assertIn(value, event.previous_value)
        for value in ('Motivo: "Motivo corregido"', "Tipo de ausencia: Vacaciones", "Inicio: 2026-07-11", "Término: 2026-07-14"):
            self.assertIn(value, event.new_value)
        self.assertNotIn("Motivo corregido", event.previous_value)
        self.assertEqual((event.actor_username, event.origin_ip), (self.admin.username, "192.0.2.40"))

    def test_absence_archive_retains_reason_and_records_archive_transition(self):
        absence = self.absence(date(2026, 7, 10), date(2026, 7, 12))
        response = post_with_revision(self.client, reverse("absence_archive", args=[absence.pk]), {}, HTTP_X_MODAL_REQUEST="true")
        self.assertEqual(response.status_code, 204)
        event = AuditLog.objects.get(action="Ausencia archivada")
        self.assertIn('Motivo: "Ausencia de prueba"', event.previous_value)
        self.assertIn('Motivo: "Ausencia de prueba"', event.new_value)
        self.assertIn("Archivado: No", event.previous_value)
        self.assertIn("Archivado: Sí", event.new_value)

    def test_absence_invalid_edit_does_not_change_reason_or_create_event(self):
        absence = self.absence(date(2026, 7, 10), date(2026, 7, 12))
        response = post_with_revision(self.client, reverse("absence_edit", args=[absence.pk]), {
            "official": self.worker.pk, "kind": "VACACIONES", "start_date": "2026-07-15",
            "end_date": "2026-07-10", "reason": "Cambio inválido",
        }, HTTP_X_MODAL_REQUEST="true")
        self.assertEqual(response.status_code, 200)
        absence.refresh_from_db()
        self.assertEqual(absence.reason, "Ausencia de prueba")
        self.assertFalse(AuditLog.objects.filter(action="Ausencia guardada").exists())

    def test_absence_multiline_reasons_remain_reserved_in_audit_view(self):
        from configuration.audit_views import visible_value

        absence = self.absence(date(2026, 7, 10), date(2026, 7, 12))
        previous = 'Razón original\nInicio: dato reservado'
        absence.reason = previous
        absence.save()
        current = 'Motivo actualizado\nEstado: otro dato reservado'
        response = post_with_revision(self.client, reverse("absence_edit", args=[absence.pk]), {
            "official": self.worker.pk, "kind": "LICENCIA", "start_date": "2026-07-10",
            "end_date": "2026-07-12", "reason": current,
        }, HTTP_X_MODAL_REQUEST="true")
        self.assertEqual(response.status_code, 204)
        event = AuditLog.objects.get(action="Ausencia guardada")
        self.assertIn(json.dumps(previous, ensure_ascii=False), event.previous_value)
        self.assertIn(json.dumps(current, ensure_ascii=False), event.new_value)
        self.assertNotIn("dato reservado", visible_value(event, event.previous_value))
        self.assertNotIn("dato reservado", visible_value(event, event.new_value))

    def test_max_percentage_matches_excel_boundaries_and_empty_denominator(self):
        version, line = self.single_plan("MAX_PERCENTAGE", 10)
        for value, compliance in [(Decimal(0), 100), (Decimal(10), 100), (Decimal("10.01"), 50),
                                   (Decimal(50), 50), (Decimal("50.01"), 0), (None, 0)]:
            with self.subTest(value=value):
                result = Calc._build_result(self.worker, self.period, END, False, version, [line], {}, {}, None, value)
                self.assertEqual(result.items[0].compliance, compliance)
                if value is None:
                    self.assertIsNone(result.items[0].traffic_light)
                    self.assertIn("Sin compromisos", result.items[0].notice)

    def test_pending_excludes_justified_cancelled_and_freezes(self):
        self.single_plan("MAX_PERCENTAGE", 10)
        stamp = timezone.make_aware(datetime.combine(START, time(9)))
        for status in [*(["DONE"] * 9), "PENDING", "CANCELLED"]:
            Commitment.objects.create(responsible=self.worker, requester="Vecino ficticio", territory="Centro",
                committed_date=END, creation_date=stamp, current_status=status,
                cancellation_reason="Cancelado por causa documentada" if status == "CANCELLED" else "")
        live = Calc.calculate(self.worker, self.period, END)
        self.assertEqual((live.items[0].progress, live.items[0].compliance), (10, 100))
        self.period.close_period()
        Commitment.objects.filter(responsible=self.worker).update(current_status="PENDING")
        self.assertEqual(Calc.result_for(self.worker, self.period).items[0].progress, 10)

    def test_two_position_segments_distinct_plans_and_boundary(self):
        self.single_plan()
        plan = self.make_plan("Segundo cargo de prueba", (("Informe de inventarios", "100", 2),))
        boundary = date(2026, 8, 16)
        change_position(self.worker, plan.position, boundary, self.verifier)
        self.assertEqual(OfficialPositionPeriod.objects.filter(official=self.worker).count(), 2)
        self.assertTrue(AuditLog.objects.filter(action="Cambio de cargo").exists())
        self.record(self.worker, "Visita terreno", 10, day=date(2026, 8, 15))
        self.record(self.worker, "Visita terreno", 1, day=boundary)  # fuera del plan nuevo
        self.record(self.worker, "Informe de inventarios", 1, day=boundary)
        result = Calc.calculate(self.worker, self.period, END)
        self.assertEqual([s["days"] for s in result.segments], [45, 46])
        self.assertAlmostEqual(result.total, (Decimal(100) * 45 + Decimal(50) * 46) / 91, places=20)
        self.assertEqual(result.activity_count, 11)
        self.assertAlmostEqual(sum(Decimal(s["total"]) * s["days"] for s in result.segments) / 91, result.total, places=20)
        self.assertEqual(result.segments[0]["items"][0]["progress"], "10")
        # El cumplimiento de cada ítem se mide solo en el tramo donde existe (no se diluye por días).
        rows = {row.item.item_name: row for row in result.items}
        self.assertEqual((rows["Visita terreno"].compliance, rows["Informe de inventarios"].compliance), (100, 50))
        self.period.close_period()
        OfficialPositionPeriod.objects.filter(official=self.worker).update(deleted_at=timezone.now())
        frozen = Calc.result_for(self.worker, self.period)
        self.assertEqual(frozen.segments, result.segments)
        self.assertAlmostEqual(frozen.total, result.total, places=5)

    def test_single_historical_segment_matches_legacy_and_rejects_overlap(self):
        self.single_plan()
        self.record(self.worker, "Visita terreno", 5)
        old = Calc.calculate(self.worker, self.period, END)
        OfficialPositionPeriod.objects.create(official=self.worker, position=self.worker.position, start_date=START)
        result = Calc.calculate(self.worker, self.period, END)
        self.assertEqual(result.total, old.total)
        self.assertEqual(result.computable_days, 91)
        self.assertEqual(len(result.segments), 1)
        with self.assertRaises(ValidationError):
            OfficialPositionPeriod.objects.create(official=self.worker, position=self.worker.position,
                                                  start_date=date(2026, 8, 1))

    def test_version_change_without_history_matches_single_segment(self):
        self.single_plan()
        revision = create_revision(self.plans["Gestor social"], date(2026, 8, 1))
        revision.items.update(goal=20)
        publish_version(revision)
        self.record(self.worker, "Visita terreno", 10, day=date(2026, 7, 10))
        legacy = Calc.calculate(self.worker, self.period, END)
        OfficialPositionPeriod.objects.create(official=self.worker, position=self.worker.position, start_date=START)
        segmented = Calc.calculate(self.worker, self.period, END)
        self.assertEqual((segmented.total, segmented.version), (legacy.total, legacy.version))
        self.assertEqual(segmented.items[0].goal, 20)

    def test_activity_items_follow_historical_position(self):
        self.single_plan()
        plan = self.make_plan("Cargo con informes", (("Informe de inventarios", "100", 2),))
        change_position(self.worker, plan.position, date(2026, 8, 16), self.verifier)
        before = set(activity_item_choices(self.worker, date(2026, 8, 15), Activity()).values_list("item_name", flat=True))
        after = set(activity_item_choices(self.worker, date(2026, 8, 16), Activity()).values_list("item_name", flat=True))
        self.assertEqual((before, after), ({"Visita terreno"}, {"Informe de inventarios"}))

    def test_absence_form_intersects_view_and_manage_scopes(self):
        view = Role.objects.create(role_name="Ver ausencias propias", scope=Role.Scope.OWN)
        view.permissions.set(Permission.objects.filter(codename="view_officialabsence"))
        manage = Role.objects.create(role_name="Gestionar ausencias global", scope=Role.Scope.ALL)
        manage.permissions.set(Permission.objects.filter(codename="manage_absence"))
        actor = self.official("Actor de ausencias")
        actor.user = User.objects.create_user("actor-ausencias")
        actor.save(update_fields=["user"])
        actor.roles.add(view, manage)
        choices = AbsenceForm(actor=actor.user).fields["official"].queryset
        self.assertEqual(list(choices), [actor])

    def test_segmented_goal_and_traffic_light_follow_evaluated_segments(self):
        self.single_plan()
        plan = self.make_plan("Cargo con otra meta", (("Visita terreno", "50", 20), ("Informe de inventarios", "50", 2)))
        change_position(self.worker, plan.position, date(2026, 8, 16), self.verifier)
        self.record(self.worker, "Visita terreno", 3, day=date(2026, 7, 10))
        early = Calc.calculate(self.worker, self.period, date(2026, 7, 15))
        rows = {row.item.item_name: row for row in early.items}
        first = {item["item"]: item for item in early.segments[0]["items"]}
        # La meta difiere entre tramos: no se muestra una meta única ni se congela como 0.
        self.assertIsNone(rows["Visita terreno"].goal)
        # Ítem solo evaluado en el primer tramo: su semáforo usa el esperado y la versión de ese tramo.
        self.assertEqual(rows["Visita terreno"].traffic_light, first["Visita terreno"]["traffic_light"])
        self.period.close_period()
        frozen = {row.item.item_name: row for row in Calc.result_for(self.worker, self.period).items}
        self.assertIsNone(frozen["Visita terreno"].goal)

    def delegation_actor(self):
        role = Role.objects.create(role_name="Ausencias de la delegación", scope=Role.Scope.DELEGATION)
        role.permissions.set(Permission.objects.filter(codename__in=["view_officialabsence", "manage_absence"]))
        actor = self.official("Encargada de ausencias")
        actor.user = User.objects.create_user("encargada-ausencias")
        actor.save(update_fields=["user"])
        actor.roles.add(role)
        return actor

    def test_absence_delegation_scope_hides_and_blocks_other_delegations(self):
        actor = self.delegation_actor()
        other = self.official("Funcionario de otra delegación")
        other.delegation = Delegation.objects.create(delegation_name="Norte", address="Calle 3", commune="La Serena")
        other.save(update_fields=["delegation"])
        own = self.absence(date(2026, 7, 10), date(2026, 7, 12))
        foreign = OfficialAbsence.objects.create(official=other, registered_by=self.verifier, kind="VACACIONES",
            start_date=date(2026, 7, 10), end_date=date(2026, 7, 12), reason="Ausencia ajena")
        self.client.force_login(actor.user)
        listing = self.client.get(reverse("absence_list"))
        self.assertEqual(list(listing.context["page_obj"]), [own])
        self.assertEqual(self.client.get(reverse("absence_edit", args=[foreign.pk]), HTTP_X_MODAL_REQUEST="true").status_code, 404)
        payload = {"official": other.pk, "kind": "LICENCIA", "start_date": "2026-08-01", "end_date": "2026-08-02",
                   "reason": "Intento fuera de alcance"}
        response = self.client.post(reverse("absence_create"), payload, HTTP_X_MODAL_REQUEST="true")
        self.assertEqual(response.status_code, 200)
        self.assertIn("official", response.context["form"].errors)
        self.assertFalse(OfficialAbsence.objects.filter(reason="Intento fuera de alcance").exists())

    def test_archive_view_soft_deletes_audits_and_respects_frozen_periods(self):
        absence = self.absence(date(2026, 7, 10), date(2026, 7, 12))
        url = reverse("absence_archive", args=[absence.pk])
        revision = self.client.get(url, HTTP_X_MODAL_REQUEST="true").context["edit_revision"]
        self.assertEqual(self.client.post(url, {"edit_revision": revision}, HTTP_X_MODAL_REQUEST="true",
                                          REMOTE_ADDR="192.0.2.31").status_code, 204)
        self.assertIsNotNone(OfficialAbsence.objects.get(pk=absence.pk).deleted_at)
        event = AuditLog.objects.get(action="Ausencia archivada")
        self.assertEqual((event.origin_ip, event.actor_username), ("192.0.2.31", self.admin.username))
        frozen = self.absence(date(2026, 8, 10), date(2026, 8, 12))
        self.period.close_period()
        url = reverse("absence_archive", args=[frozen.pk])
        revision = self.client.get(url, HTTP_X_MODAL_REQUEST="true").context["edit_revision"]
        response = self.client.post(url, {"edit_revision": revision}, HTTP_X_MODAL_REQUEST="true")
        self.assertContains(response, "período cerrado o congelado")
        self.assertIsNone(OfficialAbsence.objects.get(pk=frozen.pk).deleted_at)

    def test_templates_show_segments_and_days_without_evaluation(self):
        self.single_plan()
        plan = self.make_plan("Cargo de plantilla", (("Informe de inventarios", "100", 2),))
        change_position(self.worker, plan.position, date(2026, 8, 16), self.verifier)
        params = {"period": self.period.pk, "official": self.worker.pk}
        with patch("analytics.views.timezone.localdate", return_value=END):
            personal = self.client.get(reverse("my_performance"), params)
            board = self.client.get(reverse("position_performance"), {"period": self.period.pk, "position": plan.position.pk})
        self.assertContains(personal, "Detalle por tramo de cargo y versión")
        self.assertContains(personal, "Cargo de plantilla")
        self.assertContains(personal, "Resultado calculado por tramos de cargo")
        self.assertContains(board, "data-performance-segments")
        absent = self.official("Ausente todo el período", "Gestor social")
        OfficialAbsence.objects.create(official=absent, registered_by=self.verifier, kind="LICENCIA",
            start_date=START, end_date=END, reason="Licencia del período")
        with patch("analytics.views.timezone.localdate", return_value=END):
            response = self.client.get(reverse("my_performance"), {"period": self.period.pk, "official": absent.pk})
        self.assertContains(response, "Sin días computables")

    def test_plan_form_cites_the_matrix_step_rule(self):
        from analytics.measurement_forms import MeasurementItemForm
        form = MeasurementItemForm(version=self.plans["Gestor social"].versions.get())
        self.assertIn("50 % hasta 50 %", form.fields["goal_type"].help_text)
        self.assertIn("hoja SALON, G23", form.fields["goal_type"].help_text)

    def test_superuser_without_official_gets_a_form_error_not_a_crash(self):
        absence = self.absence(date(2026, 7, 10), date(2026, 7, 12))
        bare = User.objects.create_superuser("super-sin-funcionario", "super@medicion.test", "test-password")
        self.client.force_login(bare)
        url = reverse("absence_archive", args=[absence.pk])
        revision = self.client.get(url, HTTP_X_MODAL_REQUEST="true").context["edit_revision"]
        response = self.client.post(url, {"edit_revision": revision}, HTTP_X_MODAL_REQUEST="true")
        self.assertContains(response, "no tiene un funcionario asociado")
        self.assertIsNone(OfficialAbsence.objects.get(pk=absence.pk).deleted_at)

    def test_expected_percentage_uses_the_official_absences(self):
        self.absence(date(2026, 7, 2), date(2026, 7, 5))  # 4 días dentro del intervalo contado
        on = date(2026, 8, 26)
        elapsed = computable_days(self.period, self.worker, on)
        self.assertEqual((computable_days(self.period, self.worker), elapsed), (87, 52))
        self.assertEqual(expected_percentage(self.period, on, self.worker), Decimal(52) / Decimal(87) * 100)

    def test_max_percentage_half_step_is_red_with_default_thresholds(self):
        version, line = self.single_plan("MAX_PERCENTAGE", 10)
        row = Calc._build_result(self.worker, self.period, END, False, version, [line], {}, {}, None, Decimal(30)).items[0]
        self.assertEqual((row.compliance, row.traffic_light), (50, "RED"))

    def test_absence_list_marks_its_sidebar_link_and_modal_cancel_closes(self):
        listing = self.client.get(reverse("absence_list"))
        self.assertContains(listing, 'aria-current="page">Ausencias</a>')
        form = self.client.get(reverse("absence_create"), HTTP_X_MODAL_REQUEST="true")
        self.assertContains(form, "attention-entry-cancel")

    def test_absence_pagination_keeps_the_official_filter(self):
        other = self.official("Otra persona con ausencias")
        for offset in range(30):
            day = date(2026, 7, 2) + timedelta(days=offset)
            self.absence(day, day)
            OfficialAbsence.objects.create(official=other, registered_by=self.verifier, kind="LICENCIA",
                                           start_date=day, end_date=day, reason="Ausencia de otra persona")
        first = self.client.get(reverse("absence_list"), {"official": self.worker.pk})
        self.assertEqual(first.context["filter_query"], f"official={self.worker.pk}")
        next_link = f'href="?official={self.worker.pk}&amp;page=2"'
        self.assertContains(first, next_link)
        self.assertNotContains(first, "?&amp;")
        second = self.client.get(reverse("absence_list"), {"official": self.worker.pk, "page": 2})
        rows = list(second.context["page_obj"])
        self.assertEqual(len(rows), 5)
        self.assertEqual({row.official_id for row in rows}, {self.worker.pk})
        self.assertContains(second, f'href="?official={self.worker.pk}&amp;page=1"')
        unfiltered = self.client.get(reverse("absence_list"))
        self.assertContains(unfiltered, 'href="?page=2"')
        self.assertEqual(self.client.get(reverse("absence_list"), {"official": "abc"}).status_code, 404)

    def test_absence_default_excludes_archived_officials_from_rows_and_choices(self):
        absence = self.absence(date(2026, 7, 10), date(2026, 7, 12))
        Official.objects.filter(pk=self.worker.pk).update(deleted_at=timezone.now())
        response = self.client.get(reverse("absence_list"))
        self.assertNotIn(self.worker.pk, response.context["officials"].values_list("pk", flat=True))
        self.assertNotIn(absence.pk, [row.pk for row in response.context["page_obj"]])
        form = self.client.get(reverse("absence_create"), HTTP_X_MODAL_REQUEST="true").context["form"]
        self.assertNotIn(self.worker.pk, form.fields["official"].queryset.values_list("pk", flat=True))

    def test_absence_history_is_explicit_and_archived_official_is_read_only(self):
        absence = self.absence(date(2026, 7, 10), date(2026, 7, 12))
        Official.objects.filter(pk=self.worker.pk).update(deleted_at=timezone.now())
        response = self.client.get(reverse("absence_list"), {"include_archived": "1", "official": self.worker.pk})
        self.assertEqual([row.pk for row in response.context["page_obj"]], [absence.pk])
        self.assertEqual(response.context["selected_official"], self.worker.pk)
        self.assertContains(response, "Funcionario archivado")
        self.assertContains(response, "Solo consulta")
        self.assertNotContains(response, reverse("absence_edit", args=[absence.pk]))
        self.assertNotContains(response, reverse("absence_archive", args=[absence.pk]))
        self.assertIsNone(OfficialAbsence.objects.get(pk=absence.pk).deleted_at)

    def test_disabling_history_resets_an_archived_selection(self):
        absence = self.absence(date(2026, 7, 10), date(2026, 7, 12))
        Official.objects.filter(pk=self.worker.pk).update(deleted_at=timezone.now())
        response = self.client.get(reverse("absence_list"), {"official": self.worker.pk})
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.context["selected_official"])
        self.assertNotIn("official=", response.context["filter_query"])
        self.assertNotIn(absence.pk, [row.pk for row in response.context["page_obj"]])
        self.assertContains(response, "Se retiró la selección")

    def test_absence_history_pagination_keeps_both_filters(self):
        for day in range(1, 28):
            self.absence(date(2026, 8, day), date(2026, 8, day))
        Official.objects.filter(pk=self.worker.pk).update(deleted_at=timezone.now())
        url = reverse("absence_list")
        filters = {"official": self.worker.pk, "include_archived": "1"}
        first = self.client.get(url, filters)
        self.assertContains(first, f'?include_archived=1&amp;official={self.worker.pk}&amp;page=2')
        second = self.client.get(url, {**filters, "page": 2})
        self.assertEqual(len(second.context["page_obj"]), 2)
        self.assertEqual({row.official_id for row in second.context["page_obj"]}, {self.worker.pk})
        self.assertContains(second, f'?include_archived=1&amp;official={self.worker.pk}&amp;page=1')

    def test_archived_official_absences_reject_new_edits_and_archive_posts(self):
        absence = self.absence(date(2026, 7, 10), date(2026, 7, 12))
        url = reverse("absence_edit", args=[absence.pk])
        revision = self.client.get(url, HTTP_X_MODAL_REQUEST="true").context["edit_revision"]
        Official.objects.filter(pk=self.worker.pk).update(deleted_at=timezone.now())
        payload = {"official": self.worker.pk, "kind": "VACACIONES", "start_date": "2026-07-10",
                   "end_date": "2026-07-13", "reason": "Cambio rechazado", "edit_revision": revision}
        self.assertEqual(self.client.get(url, HTTP_X_MODAL_REQUEST="true").status_code, 404)
        self.assertEqual(self.client.post(url, payload).status_code, 404)
        self.assertEqual(self.client.post(reverse("absence_archive", args=[absence.pk]), payload).status_code, 404)
        self.assertEqual(self.client.post(reverse("absence_create"), payload).status_code, 200)
        absence.refresh_from_db()
        self.assertEqual(absence.reason, "Ausencia de prueba")
        self.assertIsNone(absence.deleted_at)
        self.assertEqual(OfficialAbsence.objects.count(), 1)
        self.assertFalse(AuditLog.objects.filter(action__in=["Ausencia guardada", "Ausencia archivada"]).exists())

    def test_absence_history_keeps_delegation_scope(self):
        foreign = self.official("Funcionario archivado ajeno", "Gestor social")
        foreign.delegation = Delegation.objects.create(delegation_name="Antena", address="Demo", commune="La Serena")
        foreign.deleted_at = timezone.now()
        foreign.save()
        OfficialAbsence.objects.create(official=foreign, registered_by=self.verifier, kind="LICENCIA",
            start_date=date(2026, 7, 10), end_date=date(2026, 7, 12), reason="Motivo reservado ajeno")
        local_user = User.objects.create_user("lector-ausencias-local")
        local = self.official("Consulta territorial")
        local.user = local_user
        local.save(update_fields=["user"])
        role = Role.objects.create(role_name="Consulta de ausencias local", scope="DELEGATION")
        role.permissions.set(Permission.objects.filter(content_type__app_label="accounts", codename="view_officialabsence"))
        local.roles.add(role)
        self.client.force_login(local_user)
        response = self.client.get(reverse("absence_list"), {"include_archived": "1"})
        self.assertNotContains(response, "Motivo reservado ajeno")
        self.assertNotIn(foreign.pk, response.context["officials"].values_list("pk", flat=True))
        self.assertEqual(self.client.get(reverse("absence_list"), {
            "include_archived": "1", "official": foreign.pk,
        }).status_code, 404)
