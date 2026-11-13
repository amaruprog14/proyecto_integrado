from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from io import BytesIO
from threading import Barrier
from unittest.mock import patch
from urllib.parse import urlsplit
from uuid import uuid4

from django.contrib.auth.models import Permission, User
from django.core import mail
from django.core.cache import cache
from django.db import close_old_connections, connection, connections
from django.db.migrations.executor import MigrationExecutor
from django.test import Client, TestCase, TransactionTestCase, override_settings, skipUnlessDBFeature
from django.urls import reverse
from django.utils import timezone
from openpyxl import load_workbook

from accounts.delegation_context import ACTIVE_DELEGATION_SESSION_KEY
from accounts.models import Delegation, Official, ServiceRecipient, Territory
from common.realtime import subscribe, unsubscribe
from configuration.models import AttentionType, AuditLog, Item, Period, SubattentionType

from .models import Activity, AttentionCase, ClientRequest, PortalInvitation, SocialAttention


class CaseFixture:
    @classmethod
    def create_fixture(cls):
        cls.delegation = Delegation.objects.create(delegation_name="Centro", address="Calle 1", commune="La Serena")
        cls.other_delegation = Delegation.objects.create(delegation_name="Sur", address="Calle 2", commune="La Serena")
        cls.staff = User.objects.create_user("funcionario", password="Clave-Test-4132")
        cls.official = Official.objects.create(user=cls.staff, delegation=cls.delegation, full_name="Funcionario Demo",
                                               national_id="FUNC-DEMO", email="funcionario@example.test")
        cls.staff.user_permissions.add(*Permission.objects.filter(content_type__app_label="activities",
            codename__in=["view_activity", "view_evidence", "add_activity", "add_socialattention",
                          "view_socialattention", "change_socialattention"]))
        item = Item.objects.create(item_name="Atención social de prueba")
        cls.kind = AttentionType.objects.create(name="Social", activity_item=item)
        cls.sub = SubattentionType.objects.create(name="Orientación", attention_type=cls.kind)
        today = timezone.localdate()
        Period.objects.create(start_date=today - timedelta(days=1), end_date=today)

    def setUp(self):
        self.client.force_login(self.staff)

    def attention_data(self, **updates):
        data = {"recipient_national_id": "12.345.678-5", "recipient_full_name": "Persona Demo",
                "delegation": self.delegation.pk, "attention_type": self.kind.pk, "subattention_type": self.sub.pk,
                "description": "Detalle interno reservado", "result": "Resultado interno reservado",
                "case_subject": "Orientación municipal", "submission_token": uuid4().hex}
        return {**data, **updates}


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
                   PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"])
class CaseFollowUpTests(CaseFixture, TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.create_fixture()

    def test_case_links_to_the_activity_evidence_only_when_authorized(self):
        entry = reverse("attention_entry")
        self.assertRedirects(self.client.post(entry, self.attention_data()), entry)
        attention = SocialAttention.objects.get()
        case_url = reverse("attention_case_detail", args=[attention.case_id])
        activity_url = reverse("activity_detail", args=[attention.activity_id])

        response = self.client.get(case_url)
        self.assertContains(response, f'href="{activity_url}#activity-evidence-title"')
        self.assertContains(response, f"Ver evidencias de {attention.activity.code}")
        self.assertContains(self.client.get(activity_url), 'id="activity-evidence-title"')

        self.staff.user_permissions.remove(Permission.objects.get(
            content_type__app_label="activities", codename="view_evidence",
        ))
        self.assertNotContains(self.client.get(case_url), "Ver evidencias")

    def test_reassignment_saves_responsible_and_history(self):
        entry = reverse("attention_entry")
        self.assertRedirects(self.client.post(entry, self.attention_data()), entry)
        case = AttentionCase.objects.get()
        user = User.objects.create_user("reemplazo")
        responsible = Official.objects.create(user=user, delegation=self.delegation, full_name="Camila Núñez",
            national_id="FUNC-REEMPLAZO", email="reemplazo@example.test")
        action = reverse("attention_case_action", args=[case.pk, "asignar"])
        self.assertRedirects(self.client.post(action, {"responsible": responsible.pk}),
                             reverse("attention_case_detail", args=[case.pk]))
        case.refresh_from_db()
        self.assertEqual(case.responsible, responsible)
        detail = "De Funcionario Demo a Camila Núñez."
        self.assertEqual(case.events.get(title="Responsable actualizado").detail, detail)
        self.assertEqual(AuditLog.objects.get(action="Responsable actualizado").new_value, detail)

    def test_closed_cases_update_activity_list_detail_and_export(self):
        entry = reverse("attention_entry")
        self.assertRedirects(self.client.post(entry, self.attention_data()), entry)
        direct = SocialAttention.objects.get()
        origin = ClientRequest.objects.create(recipient=direct.recipient, delegation=self.delegation,
            attention_type=self.kind, subattention_type=self.sub, subject="Solicitud con actividad", submission_token=uuid4())
        linked_path = f"{entry}?caso={origin.attention_case.pk}"
        self.assertRedirects(self.client.post(linked_path, self.attention_data()),
                             reverse("attention_case_detail", args=[origin.attention_case.pk]))
        linked = origin.attention_case.attentions.get()
        self.assertRedirects(self.client.post(entry, self.attention_data()), entry)
        open_activity = SocialAttention.objects.exclude(pk__in=[direct.pk, linked.pk]).get().activity
        manual = Activity.objects.create(official=self.official, item=self.kind.activity_item,
            date=timezone.localdate(), record_type=Activity.RecordType.FIELD)

        reader = User.objects.create_user("lector-actividades")
        Official.objects.create(user=reader, delegation=self.delegation, full_name="Lector Demo",
            national_id="FUNC-LECTOR", email="lector@example.test")
        reader.user_permissions.add(Permission.objects.get(content_type__app_label="activities", codename="view_activity"))
        subscribe(reader.pk, "activity")
        try:
            for attention in (direct, linked):
                with patch("common.realtime.send_notice") as send_notice, self.captureOnCommitCallbacks(execute=True):
                    response = self.client.post(reverse("attention_case_action", args=[attention.case_id, "cerrar"]),
                                                {"response": "Gestión terminada."})
                    self.assertRedirects(response, reverse("attention_case_detail", args=[attention.case_id]))
                send_notice.assert_called_once_with(reader.pk, "activity")
        finally:
            unsubscribe(reader.pk, "activity")

        listing = reverse("activity_maintainer")
        mixed = self.client.get(listing, {"status": "RESOLVED"})
        self.assertCountEqual(mixed.context["page_obj"], [direct.activity, linked.activity, origin])
        self.assertContains(mixed, '<option value="RESOLVED" selected>Resuelta</option>', html=True, count=1)
        request_page = self.client.get(listing, {"status": "RESOLVED", "record_source": "request"}).context["page_obj"]
        self.assertCountEqual(request_page, [origin])
        activity_reader = Client()
        activity_reader.force_login(reader)
        reader_page = activity_reader.get(listing, {"status": "RESOLVED"}).context["page_obj"]
        self.assertCountEqual(reader_page, [direct.activity, linked.activity])

        self.client.get(listing, {"record_source": ""})
        active_page = self.client.get(listing, {"status": "ACTIVE"}).context["page_obj"]
        self.assertCountEqual(active_page, [open_activity, manual])
        legacy = self.client.get(listing, {"status": "CASE_CLOSED", "record_source": "activity"})
        self.assertEqual(legacy.context["selected_status"], "RESOLVED")
        self.assertCountEqual(legacy.context["page_obj"], [direct.activity, linked.activity])
        for attention in (direct, linked):
            attention.activity.refresh_from_db()
            self.assertIsNone(attention.activity.deleted_at)
            self.assertContains(self.client.get(reverse("activity_detail", args=[attention.activity_id])), "Resuelta")
        cache.delete(f"activity-export:{self.staff.pk}")
        export = self.client.get(reverse("activity_export"))
        rows = list(load_workbook(BytesIO(export.content)).active.values)[1:]
        self.assertCountEqual([(row[0], row[-1]) for row in rows],
                              [(direct.activity.code, "Resuelta"), (linked.activity.code, "Resuelta")])

    def test_presential_reuses_person_and_activation_grants_only_own_history(self):
        entry = reverse("attention_entry")
        self.assertRedirects(self.client.post(entry, self.attention_data()), entry)
        first = SocialAttention.objects.get()
        self.assertIsNone(first.recipient.user_id)
        self.assertEqual(len(mail.outbox), 0)

        with self.captureOnCommitCallbacks(execute=True):
            self.assertRedirects(self.client.post(entry, self.attention_data(
                invite_to_portal="on", identity_verified="on", invitation_email="persona@example.test")), entry)
        self.assertEqual(ServiceRecipient.objects.count(), 1)
        self.assertEqual(AttentionCase.objects.count(), 2)
        self.assertEqual(Activity.objects.count(), 2)
        self.assertEqual(len(mail.outbox), 1)
        link = next(line for line in mail.outbox[0].body.splitlines() if line.startswith("http"))
        path = urlsplit(link).path
        anonymous = Client()
        confirm = reverse("portal_invitation_activate")
        self.assertRedirects(anonymous.get(path), confirm)
        password = "Acceso-Ficticio-4132"
        self.assertRedirects(anonymous.post(confirm, {"new_password1": password, "new_password2": password}), reverse("login"))
        self.assertContains(anonymous.get(path, follow=True), "La invitación ya no está disponible")
        self.assertEqual(PortalInvitation.objects.filter(consumed_at__isnull=False).count(), 1)
        self.assertTrue(anonymous.login(username="persona@example.test", password=password))
        listing = anonymous.get(reverse("client_requests"), {"record_source": "presential"})
        self.assertEqual(len(listing.context["page_obj"]), 2)
        detail = reverse("client_presential_case", args=[first.case_id])
        self.assertContains(anonymous.get(detail), "Gestión registrada")
        self.assertNotContains(anonymous.get(detail), "Resultado interno reservado")
        self.assertNotContains(anonymous.get(detail), self.official.full_name)
        other = User.objects.create_user("otra-persona")
        ServiceRecipient.objects.create(user=other, full_name="Otra Persona", national_id="11111111-1")
        anonymous.force_login(other)
        self.assertEqual(anonymous.get(detail).status_code, 404)

    def test_online_tracking_closes_with_public_response_after_pending_step(self):
        resident = User.objects.create_user("vecina")
        territory = Territory.objects.create(territory_name="Sector Centro", delegation=self.delegation)
        ServiceRecipient.objects.create(user=resident, full_name="Persona Demo", national_id="12345678-5",
                                        territory=territory, address="Calle de prueba")
        portal = Client()
        portal.force_login(resident)
        self.assertRedirects(portal.post(reverse("client_request_create"), {"attention_type": self.kind.pk,
            "subattention_type": self.sub.pk, "subject": "Solicitud de apoyo", "description": "Pido orientación",
            "submission_token": uuid4()}), reverse("client_requests"))
        origin = ClientRequest.objects.get()
        case = origin.attention_case
        public_url = reverse("client_request_detail", args=[origin.pk])
        staff_url = reverse("attention_case_detail", args=[case.pk])
        self.assertContains(portal.get(public_url), "Recibida")
        self.assertContains(self.client.get(reverse("staff_client_request_detail", args=[origin.pk])), "Tomar caso")
        action = lambda name: reverse("attention_case_action", args=[case.pk, name])
        self.assertRedirects(self.client.post(action("tomar")), staff_url)
        self.assertContains(portal.get(public_url), "En revisión")
        entry = f"{reverse('attention_entry')}?caso={case.pk}"
        self.assertRedirects(self.client.post(entry, self.attention_data()), staff_url)
        self.assertContains(self.client.get(staff_url), "Resultado interno reservado")
        self.assertContains(portal.get(public_url), "Gestión registrada")
        self.assertNotContains(portal.get(public_url), "Resultado interno reservado")

        data = {"next_step": "Revisar informe interno", "next_step_date": timezone.localdate().isoformat(),
                "public_next_step": "Te contactaremos para confirmar la visita."}
        self.assertRedirects(self.client.post(action("proximo-paso"), data), staff_url)
        self.assertContains(portal.get(public_url), data["public_next_step"])
        self.assertNotContains(portal.get(public_url), data["next_step"])
        self.assertContains(self.client.post(action("cerrar"), {"response": "Respuesta"}), "Completa o cancela")
        self.assertRedirects(self.client.post(action("completar-paso")), staff_url)
        self.assertRedirects(self.client.post(action("cerrar"), {"response": "Orientación final entregada."}), staff_url)
        self.assertContains(portal.get(public_url), "Resuelta")
        self.assertContains(portal.get(public_url), "Orientación final entregada.")
        self.assertContains(self.client.post(entry, self.attention_data()), "El caso está cerrado.")
        self.assertEqual(SocialAttention.objects.count(), 1)

    def test_existing_case_keeps_delegation_context_when_switching(self):
        self.official.authorized_delegations.add(self.other_delegation)
        recipient = ServiceRecipient.objects.create(full_name="Persona Demo", national_id="12345678-5")
        case = AttentionCase.objects.create(recipient=recipient, delegation=self.other_delegation, subject="Visita")
        detail = self.client.get(reverse("attention_case_detail", args=[case.pk]))
        self.assertContains(detail, "Cambiar a Sur y agregar gestión")
        entry = f"{reverse('attention_entry')}?caso={case.pk}"
        self.assertContains(self.client.get(entry), "delegación activa")
        changed = self.client.post(reverse("active_delegation_select"), {"next": entry, "delegation_id": self.other_delegation.pk})
        self.assertRedirects(changed, entry)
        self.assertEqual(self.client.session[ACTIVE_DELEGATION_SESSION_KEY], self.other_delegation.pk)
        self.assertContains(self.client.get(entry), case.identifier)

    def test_email_failure_preserves_attention_and_resend_invalidates_old_link(self):
        entry = reverse("attention_entry")
        with patch("activities.invitations.send_mail", return_value=0), self.captureOnCommitCallbacks(execute=True):
            self.assertRedirects(self.client.post(entry, self.attention_data(invite_to_portal="on",
                identity_verified="on", invitation_email="persona@example.test")), entry)
        attention = SocialAttention.objects.get()
        self.assertEqual(Activity.objects.count(), 1)
        invitation = PortalInvitation.objects.get()
        self.assertLessEqual(invitation.expires_at, timezone.now())
        detail = reverse("attention_case_detail", args=[attention.case_id])
        self.assertContains(self.client.get(detail), "Reenviar invitación")
        resend = reverse("attention_case_action", args=[attention.case_id, "invitar"])
        data = {"email": invitation.email, "identity_verified": "on"}
        with self.captureOnCommitCallbacks(execute=True):
            self.assertRedirects(self.client.post(resend, data), detail)
        previous_link = urlsplit(next(line for line in mail.outbox[0].body.splitlines() if line.startswith("http"))).path
        PortalInvitation.objects.filter(pk=invitation.pk).update(expires_at=timezone.now() + timedelta(hours=1))
        with self.captureOnCommitCallbacks(execute=True):
            self.assertRedirects(self.client.post(resend, data), detail)
        invitation.refresh_from_db()
        self.assertGreater(invitation.expires_at, timezone.now())
        self.assertEqual(len(mail.outbox), 2)
        self.assertContains(Client().get(previous_link, follow=True), "La invitación ya no está disponible")

    def test_activity_uses_effective_date_and_requires_its_open_period(self):
        entry = reverse("attention_entry")
        yesterday = timezone.localdate() - timedelta(days=1)
        self.assertRedirects(self.client.post(entry, self.attention_data(effective_date=yesterday.isoformat())), entry)
        attention = SocialAttention.objects.get()
        self.assertEqual(attention.date, yesterday)
        self.assertEqual(attention.activity.date, yesterday)
        outside = yesterday - timedelta(days=1)
        self.assertEqual(self.client.post(entry, self.attention_data(effective_date=outside.isoformat())).status_code, 200)
        self.assertEqual(SocialAttention.objects.count(), 1)


class CaseConcurrencyTests(CaseFixture, TransactionTestCase):
    def setUp(self):
        self.create_fixture()
        super().setUp()

    @skipUnlessDBFeature("has_select_for_update")
    def test_simultaneous_third_and_fourth_management_only_create_one(self):
        self.client.post(reverse("attention_entry"), self.attention_data())
        case = AttentionCase.objects.get()
        path = f"{reverse('attention_entry')}?caso={case.pk}"
        self.client.post(path, self.attention_data())
        clients = [Client(), Client()]
        for client in clients:
            client.force_login(self.staff)
        payloads = [self.attention_data(), self.attention_data()]
        barrier = Barrier(2)

        def save(pair):
            client, payload = pair
            close_old_connections()
            try:
                barrier.wait(timeout=10)
                return client.post(path, payload).status_code
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=2) as pool:
            statuses = list(pool.map(save, zip(clients, payloads)))
        self.assertCountEqual(statuses, [302, 200])
        self.assertEqual(case.attentions.count(), 3)
        self.assertEqual(Activity.objects.count(), 3)


class CaseMigrationTests(TransactionTestCase):
    def test_backfill_preserves_folio_and_keeps_unrelated_presential_records_separate(self):
        old = [("activities", "0009_socialattention_client_request")]
        new = [("activities", "0010_attention_cases")]
        executor = MigrationExecutor(connection)
        executor.migrate(old)
        try:
            apps = executor.loader.project_state(old).apps
            delegation = apps.get_model("accounts", "Delegation").objects.create(code="DEL-T",
                delegation_name="Delegación histórica", address="Calle de prueba", commune="La Serena")
            recipient = apps.get_model("accounts", "ServiceRecipient").objects.create(
                full_name="Persona Demo", national_id="12345678-5")
            official = apps.get_model("accounts", "Official").objects.create(full_name="Funcionario Demo",
                national_id="FUNC-DEMO", email="demo@example.test", delegation=delegation)
            kind = apps.get_model("configuration", "AttentionType").objects.create(code="TAT-T", name="Social")
            sub = apps.get_model("configuration", "SubattentionType").objects.create(code="SAT-T", name="Orientación",
                attention_type=kind)
            fields = {"recipient": recipient, "delegation": delegation, "attention_type": kind, "subattention_type": sub}
            origin = apps.get_model("activities", "ClientRequest").objects.create(subject="Solicitud histórica",
                response="Respuesta histórica", status="RESOLVED", submission_token=uuid4(), **fields)
            attention_model = apps.get_model("activities", "SocialAttention")
            linked = attention_model.objects.create(client_request=origin, responsible=official, **fields)
            direct = [attention_model.objects.create(responsible=official, **fields) for _ in range(2)]
            other = apps.get_model("accounts", "ServiceRecipient").objects.create(
                full_name="Otra persona", national_id="11111111-1")
            attention_model.objects.filter(pk=linked.pk).update(recipient=other)
            try:
                with self.assertRaisesMessage(RuntimeError, "Atenciones con persona o delegación distinta a su folio"):
                    MigrationExecutor(connection).migrate(new)
            finally:
                attention_model.objects.filter(pk=linked.pk).update(recipient=recipient)
        finally:
            executor = MigrationExecutor(connection)
            executor.migrate(executor.loader.graph.leaf_nodes())

        cases = AttentionCase.objects.filter(recipient_id=recipient.pk)
        self.assertEqual(cases.count(), 3)
        linked_case = cases.get(client_request_id=origin.pk)
        self.assertEqual(linked_case.response, "Respuesta histórica")
        self.assertEqual(linked_case.status, "RESOLVED")
        self.assertEqual(linked_case.attentions.get().pk, linked.pk)
        self.assertCountEqual(cases.filter(direct_status="RECORDED").values_list("attentions__pk", flat=True),
                              [item.pk for item in direct])
