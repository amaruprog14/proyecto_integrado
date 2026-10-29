from django.core.exceptions import ValidationError
from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from accounts.models import Delegation, Official, ServiceRecipient
from accounts.delegation_context import ACTIVE_DELEGATION_SESSION_KEY
from activities.models import SocialAttention
from configuration.models import AttentionType, AuditLog, Item, SubattentionType


class SocialAttentionRulesTests(TestCase):
    def setUp(self):
        self.d1 = Delegation.objects.create(delegation_name="Centro", address="Calle 1", commune="La Serena")
        self.d2 = Delegation.objects.create(delegation_name="Norte", address="Calle 2", commune="La Serena")
        self.official = Official.objects.create(
            full_name="Ana", national_id="1-9", email="ana@example.test", delegation=self.d1
        )
        self.recipient = ServiceRecipient.objects.create(full_name="Persona P001", national_id="9-9")
        self.social = AttentionType.objects.create(name="Social")
        self.other = AttentionType.objects.create(name="Otro")
        self.orientation = SubattentionType.objects.create(attention_type=self.social, name="Orientación")
        self.other_sub = SubattentionType.objects.create(attention_type=self.other, name="Derivación")

    def build(self, **overrides):
        data = dict(
            recipient=self.recipient,
            attention_type=self.social,
            subattention_type=self.orientation,
            delegation=self.d1,
            responsible=self.official,
            description="Consulta",
        )
        data.update(overrides)
        return SocialAttention(**data)

    def test_valid_attention_saves_with_identifier_and_defaults(self):
        attention = self.build()
        attention.full_clean()
        attention.save()
        self.assertTrue(attention.identifier.startswith("AS-"))
        self.assertIsNotNone(attention.registered_at)
        self.assertIsNone(attention.activity)

    def test_subattention_must_belong_to_the_selected_type(self):
        with self.assertRaises(ValidationError) as ctx:
            self.build(subattention_type=self.other_sub).full_clean()
        self.assertIn("subattention_type", ctx.exception.message_dict)

    def test_inactive_subattention_is_rejected(self):
        self.orientation.deactivate_from_catalog()
        with self.assertRaises(ValidationError) as ctx:
            self.build().full_clean()
        self.assertIn("subattention_type", ctx.exception.message_dict)

    def test_delegation_must_be_authorized_for_the_responsible(self):
        with self.assertRaises(ValidationError) as ctx:
            self.build(delegation=self.d2).full_clean()
        self.assertIn("delegation", ctx.exception.message_dict)

    def test_limit_of_three_attentions_per_recipient(self):
        for _ in range(SocialAttention.MAX_ATTENTIONS_PER_RECIPIENT):
            self.build().save()
        with self.assertRaises(ValidationError) as ctx:
            self.build().full_clean()
        self.assertIn("recipient", ctx.exception.message_dict)


class CatalogCodesTests(TestCase):
    def test_codes_are_generated_per_catalog(self):
        item = Item.objects.create(item_name="Atención ciudadana")
        social = AttentionType.objects.create(name="Social")
        sub = SubattentionType.objects.create(attention_type=social, name="Orientación")
        self.assertTrue(item.code.startswith("ITM-"))
        self.assertTrue(social.code.startswith("TAT-"))
        self.assertTrue(sub.code.startswith("SAT-"))

    def test_manual_code_is_respected(self):
        item = Item.objects.create(item_name="Visitas", code="VIS-01")
        self.assertEqual(Item.objects.get(pk=item.pk).code, "VIS-01")


class SocialAttentionEntryTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_superuser(
            "attention.admin", "attention.admin@example.test", "Clave-Admin-1"
        )
        self.delegation = Delegation.objects.create(
            delegation_name="Delegación de ingreso",
            address="Calle 1",
            commune="La Serena",
        )
        self.official = Official.objects.create(
            user=self.user,
            full_name="Funcionario responsable",
            national_id="RUT-ATTN-OFFICIAL",
            email="attention.official@example.test",
            delegation=self.delegation,
        )
        self.attention_type = AttentionType.objects.create(
            name="Orientación ciudadana"
        )
        self.subattention_type = SubattentionType.objects.create(
            name="Orientación general",
            attention_type=self.attention_type,
        )
        self.client.force_login(self.user)

    def payload(self, **overrides):
        data = {
            "recipient_national_id": "12.345.678-5",
            "recipient_full_name": "Persona solicitante real",
            "delegation": self.delegation.pk,
            "attention_type": self.attention_type.pk,
            "subattention_type": self.subattention_type.pk,
            "description": "Solicitud ingresada por ventanilla.",
        }
        data.update(overrides)
        return data

    def test_get_uses_active_database_catalogues_and_no_hardcoded_people(self):
        response = self.client.get(reverse("attention_entry"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.attention_type.code)
        self.assertContains(response, self.subattention_type.code)
        self.assertContains(response, "No se registra a la persona hasta guardar la atención.")
        self.assertNotContains(response, "Ana Ejemplo")
        self.assertNotContains(response, "Seleccione una persona de ejemplo")

    def test_post_creates_recipient_and_persists_attention_with_server_context(self):
        response = self.client.post(
            reverse("attention_entry"), self.payload(), follow=True
        )

        recipient = ServiceRecipient.objects.get(national_id="12345678-5")
        attention = SocialAttention.objects.get(recipient=recipient)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(recipient.full_name, "Persona solicitante real")
        self.assertEqual(attention.responsible, self.official)
        self.assertEqual(attention.delegation, self.delegation)
        self.assertEqual(attention.attention_type, self.attention_type)
        self.assertEqual(attention.subattention_type, self.subattention_type)
        self.assertEqual(attention.description, "Solicitud ingresada por ventanilla.")
        self.assertTrue(attention.identifier.startswith("AS-"))
        self.assertIsNotNone(attention.date)
        self.assertIsNotNone(attention.registered_at)
        self.assertContains(response, f"La atención {attention.identifier} se registró correctamente.")
        self.assertTrue(
            AuditLog.objects.filter(
                action="Creación de atención",
                affected_record_id=attention.pk,
            ).exists()
        )

    def test_post_rejects_an_arbitrary_recipient_identifier(self):
        response = self.client.post(
            reverse("attention_entry"),
            self.payload(recipient_national_id="RUT-RECIPIENT-INVALID"),
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Ingresa un RUT o RUN chileno válido")
        self.assertFalse(ServiceRecipient.objects.exists())
        self.assertFalse(SocialAttention.objects.exists())

    def test_post_reuses_existing_recipient_by_identifier(self):
        recipient = ServiceRecipient.objects.create(
            full_name="Persona ya registrada",
            national_id="12345678-5",
        )

        response = self.client.post(
            reverse("attention_entry"),
            self.payload(recipient_full_name=""),
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(ServiceRecipient.objects.count(), 1)
        self.assertTrue(SocialAttention.objects.filter(recipient=recipient).exists())

    def test_entry_form_and_post_follow_the_active_delegation_in_session(self):
        second_delegation = Delegation.objects.create(
            delegation_name="Delegación activa seleccionada",
            address="Calle 2",
            commune="La Serena",
        )
        self.official.authorized_delegations.add(second_delegation)
        session = self.client.session
        session[ACTIVE_DELEGATION_SESSION_KEY] = second_delegation.pk
        session.save()

        form_response = self.client.get(reverse("attention_entry"))
        form = form_response.context["form"]

        self.assertEqual(
            list(form.fields["delegation"].queryset), [second_delegation]
        )
        self.assertEqual(
            form.fields["delegation"].initial, second_delegation.pk
        )

        response = self.client.post(
            reverse("attention_entry"),
            self.payload(delegation=second_delegation.pk),
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(
            SocialAttention.objects.filter(delegation=second_delegation).exists()
        )

    def test_existing_recipient_name_cannot_be_overwritten_by_intake(self):
        recipient = ServiceRecipient.objects.create(
            full_name="Nombre registrado",
            national_id="12345678-5",
        )

        response = self.client.post(
            reverse("attention_entry"),
            self.payload(recipient_full_name="Nombre distinto"),
        )

        recipient.refresh_from_db()
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "El RUT ya está asociado a otro nombre.")
        self.assertEqual(recipient.full_name, "Nombre registrado")
        self.assertFalse(SocialAttention.objects.exists())

    def test_post_rejects_subattention_from_another_type(self):
        other_type = AttentionType.objects.create(name="Atención jurídica")
        other_subattention = SubattentionType.objects.create(
            name="Derivación jurídica",
            attention_type=other_type,
        )

        response = self.client.post(
            reverse("attention_entry"),
            self.payload(subattention_type=other_subattention.pk),
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "asociada al Tipo de Atención elegido")
        self.assertFalse(ServiceRecipient.objects.exists())
        self.assertFalse(SocialAttention.objects.exists())

    def test_post_rejects_delegation_outside_official_scope(self):
        other_delegation = Delegation.objects.create(
            delegation_name="Otra delegación",
            address="Calle 2",
            commune="La Serena",
        )

        response = self.client.post(
            reverse("attention_entry"),
            self.payload(delegation=other_delegation.pk),
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["form"].has_error("delegation"))
        self.assertFalse(ServiceRecipient.objects.exists())
        self.assertFalse(SocialAttention.objects.exists())

    def test_post_rejects_inactive_catalogue_entries(self):
        self.subattention_type.is_active = False
        self.subattention_type.save(update_fields=("is_active", "updated_at"))

        response = self.client.post(reverse("attention_entry"), self.payload())

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["form"].has_error("subattention_type"))
        self.assertFalse(ServiceRecipient.objects.exists())
        self.assertFalse(SocialAttention.objects.exists())

    def test_post_enforces_maximum_of_three_attentions_for_recipient(self):
        recipient = ServiceRecipient.objects.create(
            full_name="Persona con atenciones",
            national_id="12345678-5",
        )
        for _ in range(SocialAttention.MAX_ATTENTIONS_PER_RECIPIENT):
            SocialAttention.objects.create(
                recipient=recipient,
                attention_type=self.attention_type,
                subattention_type=self.subattention_type,
                description="Atención previa",
                delegation=self.delegation,
                responsible=self.official,
            )

        response = self.client.post(
            reverse("attention_entry"),
            self.payload(recipient_full_name=""),
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "ya tiene 3 gestiones registradas")
        self.assertEqual(SocialAttention.objects.filter(recipient=recipient).count(), 3)

    def test_opening_form_does_not_create_recipient_or_attention(self):
        response = self.client.get(reverse("attention_entry"))

        self.assertEqual(response.status_code, 200)
        self.assertFalse(ServiceRecipient.objects.exists())
        self.assertFalse(SocialAttention.objects.exists())

    def crlf_description(self, length):
        """Texto de `length` caracteres para el navegador: 49 letras y un salto "\r\n" por línea."""
        lines = (length - 1) // 50
        text = ("a" * 49 + "\r\n") * lines + "a" * (length - 50 * lines)
        self.assertEqual(len(text.replace("\r\n", "\n")), length)
        return text

    def test_description_of_5000_characters_with_crlf_is_accepted_and_kept(self):
        description = self.crlf_description(5000)
        self.assertGreater(len(description), 5000)  # más de 5000 contando cada "\r\n" como 2

        self.client.post(reverse("attention_entry"), self.payload(description=description))

        attention = SocialAttention.objects.get()
        self.assertEqual(attention.description, description)

    def test_description_of_5001_characters_is_rejected(self):
        response = self.client.post(
            reverse("attention_entry"), self.payload(description=self.crlf_description(5001))
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn("description", response.context["form"].errors)
        self.assertFalse(SocialAttention.objects.exists())

    def test_description_textarea_keeps_maxlength_5000(self):
        response = self.client.get(reverse("attention_entry"))

        self.assertContains(response, 'maxlength="5000"')
