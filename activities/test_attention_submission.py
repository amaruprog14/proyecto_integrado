"""
Ingreso de atención: prevención de doble envío en el servidor (ACT-06, anexo C6) y consulta de la
atención registrada con su identificador, limitada a las delegaciones autorizadas (SEG-01).
"""

from unittest import mock

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import TestCase
from django.urls import reverse

from accounts.models import Delegation, Official, ServiceRecipient
from activities import views as activity_views
from activities.models import SocialAttention
from configuration.models import AttentionType, AuditLog, SubattentionType

User = get_user_model()
PASSWORD = "Clave-Atencion-123"
TOKEN = "0123456789abcdef0123456789abcdef"


class AttentionSubmissionTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.delegation = Delegation.objects.create(delegation_name="Centro", address="Calle 1", commune="La Serena")
        cls.user = User.objects.create_user("operador.envio", "operador.envio@example.test", PASSWORD)
        cls.official = Official.objects.create(
            user=cls.user,
            full_name="Operador Envío",
            national_id="RUT-OP-ENVIO",
            email="operador.envio@example.test",
            delegation=cls.delegation,
        )
        cls.user.user_permissions.add(
            *Permission.objects.filter(
                content_type__app_label="activities", codename__in=["add_socialattention", "view_socialattention"]
            )
        )
        cls.attention_type = AttentionType.objects.create(name="Social")
        cls.subattention_type = SubattentionType.objects.create(name="Orientación", attention_type=cls.attention_type)

    def setUp(self):
        self.client.force_login(self.user)

    def payload(self, **overrides):
        data = {
            "recipient_national_id": "RUT-SOL-001",
            "recipient_full_name": "Persona Solicitante",
            "delegation": self.delegation.pk,
            "attention_type": self.attention_type.pk,
            "subattention_type": self.subattention_type.pk,
            "description": "Consulta presencial.",
            "submission_token": TOKEN,
        }
        data.update(overrides)
        return data

    def test_form_carries_a_fresh_single_use_token(self):
        first = self.client.get(reverse("attention_entry")).context["form"].initial["submission_token"]
        second = self.client.get(reverse("attention_entry")).context["form"].initial["submission_token"]

        self.assertRegex(first, r"^[0-9a-f]{32}$")
        self.assertNotEqual(first, second)
        self.assertContains(self.client.get(reverse("attention_entry")), 'name="submission_token"')

    def test_repeated_submission_creates_a_single_attention(self):
        first = self.client.post(reverse("attention_entry"), self.payload())
        second = self.client.post(reverse("attention_entry"), self.payload(), follow=True)

        self.assertRedirects(first, reverse("attention_entry"))
        attention = SocialAttention.objects.get()
        self.assertEqual(attention.submission_token, TOKEN)
        self.assertContains(second, f"La atención {attention.identifier} ya estaba registrada")
        self.assertEqual(ServiceRecipient.objects.count(), 1)
        self.assertEqual(AuditLog.objects.filter(action="Creación de atención").count(), 1)

    def test_simultaneous_submission_is_resolved_by_the_database(self):
        self.client.post(reverse("attention_entry"), self.payload())
        existing = SocialAttention.objects.get()

        # Simula el segundo envío que llegó antes de que el primero quedara guardado: la consulta
        # previa no lo ve, la restricción única lo rechaza y se informa la atención existente.
        with mock.patch.object(activity_views, "registered_attention", side_effect=[None, existing]):
            response = self.client.post(reverse("attention_entry"), self.payload(), follow=True)

        self.assertEqual(SocialAttention.objects.count(), 1)
        self.assertContains(response, f"La atención {existing.identifier} ya estaba registrada")

    def test_each_new_form_registers_its_own_attention(self):
        self.client.post(reverse("attention_entry"), self.payload())
        self.client.post(
            reverse("attention_entry"),
            self.payload(submission_token="fedcba9876543210fedcba9876543210", description="Segunda gestión."),
        )

        self.assertEqual(SocialAttention.objects.count(), 2)

    def test_invalid_submission_keeps_the_token_for_the_corrected_retry(self):
        invalid = self.client.post(reverse("attention_entry"), self.payload(description=""))
        self.assertEqual(invalid.status_code, 200)
        self.assertContains(invalid, f'value="{TOKEN}"')

        self.client.post(reverse("attention_entry"), self.payload())

        self.assertEqual(SocialAttention.objects.count(), 1)

    def test_after_saving_the_entry_page_links_to_the_registered_attention(self):
        response = self.client.post(reverse("attention_entry"), self.payload(), follow=True)

        attention = SocialAttention.objects.get()
        self.assertContains(response, f"Atención registrada: {attention.identifier}")
        self.assertContains(response, f'href="{reverse("attention_detail", args=[attention.pk])}"')
        self.assertContains(self.client.get(reverse("attention_entry")), "Ingreso de atención")
        self.assertNotContains(self.client.get(reverse("attention_entry")), "Atención registrada:")


class AttentionDetailTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.own = Delegation.objects.create(delegation_name="Centro", address="Calle 1", commune="La Serena")
        cls.foreign = Delegation.objects.create(delegation_name="Norte", address="Calle 2", commune="La Serena")
        attention_type = AttentionType.objects.create(name="Social")
        subattention_type = SubattentionType.objects.create(name="Orientación", attention_type=attention_type)
        recipient = ServiceRecipient.objects.create(full_name="Persona Ficticia", national_id="P001")
        foreign_official = Official.objects.create(
            full_name="Funcionaria Norte", national_id="RUT-NORTE", email="norte@example.test", delegation=cls.foreign
        )
        cls.user = User.objects.create_user("consulta.atencion", "consulta.atencion@example.test", PASSWORD)
        cls.official = Official.objects.create(
            user=cls.user,
            full_name="Funcionario Centro",
            national_id="RUT-CENTRO",
            email="consulta.atencion@example.test",
            delegation=cls.own,
        )
        cls.user.user_permissions.add(
            Permission.objects.get(content_type__app_label="activities", codename="view_socialattention")
        )
        common = {
            "recipient": recipient,
            "attention_type": attention_type,
            "subattention_type": subattention_type,
            "description": "Detalle de la gestión.",
        }
        cls.own_attention = SocialAttention.objects.create(delegation=cls.own, responsible=cls.official, **common)
        cls.foreign_attention = SocialAttention.objects.create(
            delegation=cls.foreign, responsible=foreign_official, **common
        )

    def setUp(self):
        self.client.force_login(self.user)

    def test_detail_shows_the_registered_data(self):
        response = self.client.get(reverse("attention_detail", args=[self.own_attention.pk]))

        self.assertEqual(response.status_code, 200)
        for value in (
            self.own_attention.identifier,
            "Persona Ficticia",
            "Orientación",
            f"{self.own.code} · Centro",
            "Funcionario Centro",
            "Detalle de la gestión.",
        ):
            self.assertContains(response, value)

    def test_attention_of_another_delegation_is_hidden_and_the_attempt_audited(self):
        response = self.client.get(reverse("attention_detail", args=[self.foreign_attention.pk]))

        self.assertEqual(response.status_code, 404)
        log = AuditLog.objects.get(action="Acceso denegado")
        self.assertEqual(log.affected_record_id, self.foreign_attention.pk)
        self.assertIn("fuera del ámbito de delegación", log.new_value)

    def test_detail_requires_view_permission(self):
        self.user.user_permissions.clear()

        response = self.client.get(reverse("attention_detail", args=[self.own_attention.pk]))

        self.assertEqual(response.status_code, 403)
