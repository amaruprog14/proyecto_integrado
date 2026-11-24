from datetime import timedelta
from uuid import uuid4

from django.contrib.auth.models import Permission, User
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.models import Official, Role, Territory
from activities.models import SocialAttention
from activities.test_case_follow_up import CaseFixture
from analytics.services import CalculadorDesempenoService
from configuration.models import Period

from .alerts import refresh_commitment_alerts
from .models import Alert, Commitment


def grant(user, *codenames):
    user.user_permissions.add(*Permission.objects.filter(content_type__app_label="agenda", codename__in=codenames))


@override_settings(PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"], COMMITMENT_DUE_WARNING_DAYS=3)
class CommitmentWorkflowTests(CaseFixture, TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.create_fixture()
        grant(cls.staff, "view_commitment", "add_commitment", "change_commitment")
        cls.territory = Territory.objects.create(delegation=cls.delegation, territory_name="Territorio Centro")
        cls.other_territory = Territory.objects.create(delegation=cls.other_delegation, territory_name="Territorio Sur")
        cls.other_user = User.objects.create_user("otra-delegacion")
        cls.other_official = Official.objects.create(user=cls.other_user, delegation=cls.other_delegation,
            full_name="Funcionario Sur", national_id="OTRA", email="otra@demo.invalid")
        grant(cls.other_user, "view_commitment", "add_commitment", "change_commitment", "assign_commitment")

    def data(self, **changes):
        return {
            "submission_token": uuid4(), "requester": "Solicitante ficticio",
            "territory_ref": self.territory.pk, "responsible": self.official.pk,
            "committed_date": timezone.localdate().isoformat(), "description": "Coordinar la visita.",
            **changes,
        }

    def test_peer_can_consult_but_cannot_update_or_reassign_a_commitment(self):
        self.other_official.delegation = self.delegation
        self.other_official.save(update_fields=["delegation"])
        self.client.post(reverse("commitment_create"), self.data())
        record = Commitment.objects.get()
        self.client.force_login(self.other_user)
        detail = self.client.get(reverse("commitment_detail", args=[record.pk]))
        self.assertEqual(detail.status_code, 200)
        self.assertNotIn("status_form", detail.context)
        self.assertNotIn("assign_form", detail.context)
        self.assertEqual(self.client.post(reverse("commitment_status", args=[record.pk]), {
            "status": "DONE", "observation": "Gestión entre pares",
        }).status_code, 404)
        self.assertEqual(self.client.post(reverse("commitment_assign", args=[record.pk]), {
            "responsible": self.other_official.pk, "reason": "Reasignación entre pares",
        }).status_code, 404)
        record.refresh_from_db()
        self.assertEqual((record.responsible_id, record.current_status), (self.official.pk, Commitment.Status.ENTERED))
        self.assertFalse(record.status_history.exists())

    def test_delegate_can_manage_a_peers_open_commitment_in_scope(self):
        self.client.post(reverse("commitment_create"), self.data())
        record = Commitment.objects.get()
        role = Role.objects.create(role_name="Delegado", scope=Role.Scope.DELEGATION)
        self.other_official.roles.add(role)
        self.other_official.authorized_delegations.add(self.delegation)
        self.client.force_login(self.other_user)
        status = reverse("commitment_status", args=[record.pk])
        assign = reverse("commitment_assign", args=[record.pk])
        self.assertEqual(self.client.post(status, {"status": "IN_PROGRESS", "observation": "Visita"}).status_code, 302)
        self.assertEqual(self.client.post(assign, {"responsible": self.other_official.pk, "reason": "Turno"}).status_code, 302)
        record.refresh_from_db()
        self.assertEqual((record.responsible_id, record.current_status),
                         (self.other_official.pk, Commitment.Status.IN_PROGRESS))

    def test_case_creation_measurement_scope_and_deadline_alert(self):
        self.client.post(reverse("attention_entry"), self.attention_data())
        attention = SocialAttention.objects.get()
        url = reverse("commitment_from_case", args=[attention.case_id])
        self.assertContains(self.client.get(url), "Persona Demo")
        data = self.data()
        self.assertEqual(self.client.post(url, data).status_code, 302)
        self.assertEqual(self.client.post(url, data).status_code, 302)
        record = Commitment.objects.get()
        self.assertEqual(record.origin_case_id, attention.case_id)
        self.assertEqual(record.requester, attention.recipient.full_name)
        self.assertEqual(record.delegation, self.delegation)
        alert = Alert.objects.get(commitment=record)
        self.assertEqual(alert.official, self.official)
        refresh_commitment_alerts()
        self.assertEqual(Alert.objects.filter(commitment=record).count(), 1)
        self.assertContains(self.client.get(reverse("alert_list")), record.identifier)
        self.assertContains(self.client.get(reverse("commitment_list")), "Vence hoy")
        details = reverse("commitment_detail", args=[record.pk])
        status_url = reverse("commitment_status", args=[record.pk])
        self.assertContains(self.client.get(details), "Ver registro de origen")
        self.assertEqual(CalculadorDesempenoService.percentage_progress(self.official, Period.objects.get()), 0)
        self.assertRedirects(self.client.post(status_url, {"status": "DONE", "observation": "Visita completada."}), details)
        self.client.post(status_url, {"status": "DONE", "observation": "Reintento."})
        self.assertEqual(record.status_history.count(), 1)
        self.assertEqual(CalculadorDesempenoService.percentage_progress(self.official, Period.objects.get()), 100)
        alert.refresh_from_db()
        self.assertIsNotNone(alert.resolved_at)
        self.client.force_login(self.other_user)
        self.assertEqual(self.client.get(url).status_code, 404)
        self.assertEqual(self.client.get(details).status_code, 404)
        self.assertEqual(self.client.post(status_url, {"status": "DONE", "observation": "Fuera de ámbito"}).status_code, 404)

    def test_cancelling_with_justification_closes_the_commitment_and_its_alert(self):
        self.client.post(reverse("attention_entry"), self.attention_data())
        attention = SocialAttention.objects.get()
        self.client.post(reverse("commitment_from_case", args=[attention.case_id]), self.data())
        record = Commitment.objects.get()
        alert = Alert.objects.get(commitment=record)
        status_url = reverse("commitment_status", args=[record.pk])
        self.client.post(status_url, {"status": "CANCELLED", "observation": "Corto"})
        record.refresh_from_db()
        self.assertNotEqual(record.current_status, Commitment.Status.CANCELLED)  # exige justificación
        self.client.post(status_url, {"status": "CANCELLED", "observation": "El vecino desistió de la solicitud."})
        record.refresh_from_db()
        alert.refresh_from_db()
        self.assertEqual(record.current_status, Commitment.Status.CANCELLED)
        self.assertIsNotNone(alert.resolved_at)
        Commitment.objects.filter(pk=record.pk).update(committed_date=timezone.localdate() - timedelta(days=5))
        record.refresh_from_db()
        self.assertFalse(record.is_overdue())
        refresh_commitment_alerts()
        self.assertFalse(Alert.objects.filter(commitment=record, resolved_at__isnull=True).exists())

    def test_internal_creation_validates_catalog_scope_and_reassignment_is_audited(self):
        url = reverse("commitment_create")
        response = self.client.post(url, self.data(territory_ref=self.other_territory.pk))
        self.assertEqual(response.context["form"].errors.as_data()["territory_ref"][0].code, "invalid_choice")
        self.client.post(url, self.data(responsible=self.other_official.pk))
        self.assertFalse(Commitment.objects.exists())
        self.client.post(url, self.data())
        record = Commitment.objects.get()
        assign = reverse("commitment_assign", args=[record.pk])
        self.assertEqual(self.client.post(assign, {"responsible": self.other_official.pk, "reason": "Licencia"}).status_code, 403)
        grant(self.staff, "assign_commitment")
        self.other_official.authorized_delegations.add(self.delegation)
        self.assertEqual(self.client.post(assign, {"responsible": self.other_official.pk, "reason": "Licencia"}).status_code, 302)
        record.refresh_from_db()
        self.assertEqual(record.responsible, self.other_official)
        self.assertContains(self.client.get(reverse("commitment_detail", args=[record.pk])), "Licencia")

    def test_overdue_and_late_completion_remain_visible_for_closed_period(self):
        period = Period.objects.get()
        period.close_period()
        record = Commitment.objects.create(
            responsible=self.official, delegation=self.delegation, requester="Vecino",
            territory=str(self.territory), territory_ref=self.territory, committed_date=timezone.localdate() - timedelta(days=1),
        )
        refresh_commitment_alerts()
        self.assertContains(self.client.get(reverse("commitment_list")), "Vencido")
        status_url = reverse("commitment_status", args=[record.pk])
        self.assertEqual(self.client.post(status_url, {"status": "DONE", "observation": "Atención realizada."}).status_code, 302)
        self.assertContains(self.client.get(reverse("commitment_list"), {"estado": "DONE"}), "Realizado fuera de plazo")
        period.refresh_from_db()
        self.assertIsNotNone(period.frozen_at)

    def test_creation_requires_a_responsible_official(self):
        response = self.client.post(reverse("commitment_create"), self.data(responsible=""))
        self.assertEqual(response.context["form"].errors.as_data()["responsible"][0].code, "required")
        self.assertFalse(Commitment.objects.exists())

    def test_alert_shows_reason_date_and_working_link_before_due_date(self):
        due = timezone.localdate() + timedelta(days=2)
        self.assertEqual(self.client.post(reverse("commitment_create"),
                                          self.data(committed_date=due.isoformat())).status_code, 302)
        record = Commitment.objects.get()
        alert = Alert.objects.get(commitment=record, official=self.official)
        detail = reverse("commitment_detail", args=[record.pk])
        self.assertEqual(alert.reference_link, detail)
        self.assertIn("Próximo a vencer", alert.reason)
        self.assertIn(due.strftime("%d-%m-%Y"), alert.reason)
        page = self.client.get(reverse("alert_list"))
        self.assertContains(page, alert.reason)
        self.assertContains(page, f'href="{detail}"')
        self.assertContains(self.client.get(detail), record.identifier)

    def test_every_status_transition_preserves_consistent_history(self):
        allowed = {
            "ENTERED": {"PENDING", "IN_PROGRESS", "DONE", "CANCELLED"},
            "PENDING": {"IN_PROGRESS", "DONE", "CANCELLED"},
            "IN_PROGRESS": {"PENDING", "DONE", "CANCELLED"},
            "DONE": set(), "CANCELLED": set(),
        }
        for previous, targets in allowed.items():
            for new in allowed:
                with self.subTest(previous=previous, new=new):
                    record = Commitment.objects.create(
                        responsible=self.official, delegation=self.delegation, requester="Persona ficticia",
                        territory_ref=self.territory, committed_date=timezone.localdate(), current_status=previous,
                    )
                    response = self.client.post(reverse("commitment_status", args=[record.pk]),
                                                {"status": new, "observation": "Cambio de estado de prueba."})
                    record.refresh_from_db()
                    if new in targets:
                        self.assertEqual(response.status_code, 302)
                        self.assertEqual(record.current_status, new)
                        event = record.status_history.get()
                        self.assertEqual((event.previous_status, event.new_status, event.author),
                                         (previous, new, self.official))
                    else:
                        self.assertEqual(record.current_status, previous)
                        self.assertFalse(record.status_history.exists())

    def test_creation_from_activity_keeps_origin_and_rejects_a_past_due_date(self):
        self.client.post(reverse("attention_entry"), self.attention_data())
        activity = SocialAttention.objects.get().activity
        url = reverse("commitment_from_activity", args=[activity.pk])
        response = self.client.post(url, self.data(committed_date=timezone.localdate() - timedelta(days=1)))
        self.assertIn("committed_date", response.context["form"].errors)
        response = self.client.post(url, self.data())
        self.assertEqual(response.status_code, 302)
        record = Commitment.objects.get()
        self.assertEqual(record.origin_activity_id, activity.pk)
        self.assertIsNone(record.origin_case_id)
