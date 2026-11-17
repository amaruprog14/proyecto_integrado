from datetime import datetime, time, timedelta
from uuid import uuid4

from django.contrib.auth.models import Permission
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.models import Area, ServiceRecipient
from agenda.models import Commitment

from .models import AttentionCase, ClientRequest, OfficeLetter, SocialAttention
from .test_case_follow_up import CaseFixture


@override_settings(PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"])
class OfficeLetterAndFollowUpTests(CaseFixture, TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.create_fixture()
        cls.staff.user_permissions.add(*Permission.objects.filter(content_type__app_label="activities",
            codename__in=["view_officeletter", "add_officeletter", "change_officeletter"]))
        cls.area = Area.objects.create(area_name="Oficina de Prueba")
        cls.received = timezone.localdate()
        cls.recipient = ServiceRecipient.objects.create(full_name="Persona Ficticia", national_id="11.111.111-1")

    def letter_data(self, **updates):
        return {
            "delegation": self.delegation.pk, "received_on": self.received.isoformat(), "addressee": "Oficina municipal",
            "sender": "Organización de prueba", "subject": "Solicitud ficticia",
            "status": OfficeLetter.Status.IN_PROGRESS, **updates,
        }

    def test_creation_number_scope_and_history(self):
        url = reverse("office_letter_create")
        for _ in range(2):
            self.assertEqual(self.client.post(url, self.letter_data()).status_code, 302)
        self.assertEqual(OfficeLetter.objects.filter(external_number__isnull=True).count(), 2)
        self.assertEqual(self.client.post(url, self.letter_data(external_number=" p-001 ")).status_code, 302)
        number = OfficeLetter.objects.get(external_number="P-001")
        self.assertEqual(number.received_year, self.received.year)
        duplicate = self.client.post(url, self.letter_data(external_number="p-001", subject="Datos conservados"))
        self.assertContains(duplicate, "Ya existe una carta con ese número")
        self.assertContains(duplicate, "Datos conservados")
        previous_year = self.received.replace(year=self.received.year - 1, day=1).isoformat()
        self.assertEqual(self.client.post(url, self.letter_data(
            external_number="P-001", received_on=previous_year)).status_code, 302)
        edit = reverse("office_letter_edit", args=[number.pk])
        self.assertEqual(self.client.post(edit, self.letter_data(external_number="P-001", referred_to="Unidad externa",
            status=OfficeLetter.Status.APPROVED, responsible_area=self.area.pk)).status_code, 302)
        event = number.events.first()
        self.assertEqual(event.actor, self.official)
        self.assertIn({"field": "Estado", "before": "En proceso", "after": "Aprobada"}, event.changes)
        self.assertIn({"field": "Derivada a", "before": "", "after": "Unidad externa"}, event.changes)
        self.official.authorized_delegations.add(self.other_delegation)
        self.assertEqual(self.client.post(edit, self.letter_data(
            external_number="P-001", delegation=self.other_delegation.pk)).status_code, 302)
        number.refresh_from_db()
        self.assertEqual(number.delegation, self.other_delegation)

    def test_scope_responsible_and_counts_use_filtered_set(self):
        url = reverse("office_letter_create")
        denied = self.client.post(url, self.letter_data(delegation=self.other_delegation.pk))
        self.assertTrue(denied.context["form"].errors.get("delegation"))
        both = self.client.post(url, self.letter_data(responsible=self.official.pk, responsible_area=self.area.pk))
        self.assertContains(both, "Selecciona un funcionario o un área como encargado")
        sample = {
            OfficeLetter.Status.IN_PROGRESS: 7, OfficeLetter.Status.APPROVED: 2,
            OfficeLetter.Status.FINALIZED: 3, OfficeLetter.Status.NOT_APPLICABLE: 15,
        }
        for status, count in sample.items():
            for _ in range(count):
                OfficeLetter.objects.create(delegation=self.delegation, received_on=self.received,
                    addressee="Oficina", sender="Persona ficticia", subject="Carta de ejemplo", status=status)
        hidden = OfficeLetter.objects.create(delegation=self.other_delegation, received_on=self.received,
            external_number="P-001", addressee="Oficina", sender="Remitente externo", subject="Registro reservado")
        listing = reverse("office_letter_list")
        response = self.client.get(listing, {"page_size": 10, "start": self.received.isoformat()})
        self.assertEqual(response.context["total"], 27)
        self.assertEqual(response.context["applicable"], 12)
        self.assertEqual(dict(response.context["status_counts"]),
                         {"En proceso": 7, "Aprobada": 2, "Finalizada": 3, "No aplica": 15})
        self.assertTrue(response.context["page_obj"].has_next())
        self.assertNotContains(response, hidden.subject)
        self.assertEqual(self.client.get(reverse("office_letter_detail", args=[hidden.pk])).status_code, 404)
        self.assertEqual(self.client.post(reverse("office_letter_edit", args=[hidden.pk]), self.letter_data()).status_code, 404)
        self.assertEqual(self.client.get(listing, {"status": OfficeLetter.Status.APPROVED}).context["total"], 2)

    def test_link_only_visible_case_in_same_delegation(self):
        letter = OfficeLetter.objects.create(delegation=self.delegation, received_on=self.received,
            addressee="Oficina", sender="Persona ficticia", subject="Carta para vincular")
        case = AttentionCase.objects.create(recipient=self.recipient, delegation=self.delegation, subject="Caso local")
        outside = AttentionCase.objects.create(recipient=self.recipient, delegation=self.other_delegation,
            subject="Caso remoto reservado")
        url = reverse("office_letter_case", args=[letter.pk])
        detail = reverse("office_letter_detail", args=[letter.pk])
        for iteration in (False, True):
            if iteration:
                self.official.authorized_delegations.add(self.other_delegation)
            response = self.client.post(url, {"folio": outside.identifier})
            self.assertContains(response, "No se encontró un caso autorizado")
            self.assertNotContains(response, outside.subject)
        self.assertRedirects(self.client.post(url, {"folio": case.identifier}), detail)
        self.assertContains(self.client.get(detail), case.identifier)
        change = self.client.post(reverse("office_letter_edit", args=[letter.pk]),
                                  self.letter_data(delegation=self.other_delegation.pk))
        self.assertContains(change, "Desvincula el caso social antes de cambiar la delegación.")
        case_url = reverse("attention_case_detail", args=[case.pk])
        self.assertContains(self.client.get(case_url), letter.identifier)
        view_cases = Permission.objects.get(content_type__app_label="activities", codename="view_socialattention")
        self.staff.user_permissions.remove(view_cases)
        self.assertNotContains(self.client.get(detail), case.identifier)
        self.assertEqual(self.client.post(url, {"action": "unlink"}).status_code, 403)
        self.staff.user_permissions.add(view_cases)
        self.assertRedirects(self.client.post(url, {"action": "unlink"}), detail)
        letter.refresh_from_db()
        self.assertIsNone(letter.case)
        self.assertEqual(letter.status, OfficeLetter.Status.IN_PROGRESS)
        self.assertEqual(case.status, AttentionCase.DirectStatus.REVIEW)

    def test_direct_milestones_calculate_intervals_and_agenda(self):
        entered = self.received - timedelta(days=30)
        case = AttentionCase.objects.create(recipient=self.recipient, delegation=self.delegation,
            subject="Seguimiento ficticio", responsible=self.official)
        for offset in range(3):
            SocialAttention.objects.create(case=case, recipient=self.recipient, delegation=self.delegation,
                responsible=self.official, attention_type=self.kind, subattention_type=self.sub,
                date=entered + timedelta(days=offset), result=f"Resultado ficticio {offset + 1}")
        values = {"requires_visit": "true", "observation": "Esta observación es interna."}
        for field, offset in (("scheduled_visit_on", 10), ("visited_on", 8), ("report_delivered_on", 13),
                              ("benefit_delivered_on", 17)):
            values[field] = (entered + timedelta(days=offset)).isoformat()
        detail = reverse("attention_case_detail", args=[case.pk])
        action = reverse("attention_case_action", args=[case.pk, "hitos"])
        self.assertRedirects(self.client.post(action, values), detail)
        response = self.client.get(detail)
        self.assertEqual(response.context["entry_date"], entered)
        self.assertEqual([interval["days"] for interval in response.context["intervals"]], [10, -2, 5, 4, 17])
        self.assertContains(response, "Adelantada")
        self.assertContains(response, "Fuera de plazo")
        self.assertContains(response, "Resultado ficticio 3")
        event = case.events.get(title="Hitos de seguimiento actualizados", actor=self.official)
        self.assertIn("Requiere visita: de Sin registrar a Sí", event.detail)
        self.assertIn(f"Visita programada: de Sin registrar a {entered + timedelta(days=10):%d/%m/%Y}", event.detail)
        self.assertEqual(case.events.get(title="Observación de seguimiento").public_text, "")
        commitment = Commitment.objects.create(origin_case=case, delegation=self.delegation, responsible=self.official,
            requester="Persona ficticia", territory="Territorio de prueba", committed_date=self.received)
        commitment_url = reverse("commitment_detail", args=[commitment.pk])
        self.assertNotContains(response, commitment_url)
        self.staff.user_permissions.add(Permission.objects.get(content_type__app_label="agenda", codename="view_commitment"))
        self.assertContains(self.client.get(detail), commitment_url)
        filtered = self.client.get(reverse("attention_cases"), {"entry_start": entered.isoformat(), "visit": "yes",
            "entry_end": entered.isoformat(), "responsible": self.official.pk})
        self.assertEqual(list(filtered.context["page_obj"]), [case])
        invalid = self.client.post(action, {**values, "report_delivered_on": entered.isoformat()})
        self.assertContains(invalid, "al hito previo registrado")
        case.refresh_from_db()
        self.assertEqual(case.report_delivered_on, entered + timedelta(days=13))

    def test_portal_case_uses_request_date_and_can_skip_visit_and_report(self):
        origin = ClientRequest.objects.create(recipient=self.recipient, delegation=self.delegation,
            attention_type=self.kind, subattention_type=self.sub, subject="Solicitud ficticia", submission_token=uuid4())
        entered_late = timezone.make_aware(datetime.combine(self.received, time(23, 30)))
        ClientRequest.objects.filter(pk=origin.pk).update(created_at=entered_late)
        case = origin.attention_case
        action = reverse("attention_case_action", args=[case.pk, "hitos"])
        detail = reverse("attention_case_detail", args=[case.pk])
        self.assertRedirects(self.client.post(action, {"requires_visit": "false",
            "benefit_delivered_on": self.received.isoformat()}), detail)
        response = self.client.get(detail)
        self.assertEqual(response.context["entry_date"], self.received)
        filters = {"entry_start": self.received.isoformat(), "entry_end": self.received.isoformat(), "visit": "no"}
        listing = self.client.get(reverse("attention_cases"), filters)
        self.assertEqual(list(listing.context["page_obj"]), [case])
        self.assertEqual([interval["days"] for interval in response.context["intervals"]], [None, None, None, None, 0])
        case.refresh_from_db()
        self.assertIs(case.requires_visit, False)
        self.client.post(reverse("attention_case_action", args=[case.pk, "cerrar"]), {"response": "Solicitud resuelta."})
        self.assertRedirects(self.client.post(action, {"requires_visit": "true"}), detail)
        case.refresh_from_db()
        self.assertTrue(case.is_closed)
        self.assertIs(case.requires_visit, False)
