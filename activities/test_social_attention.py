from django.core.exceptions import ValidationError
from django.test import TestCase

from accounts.models import Delegation, Official, ServiceRecipient
from activities.models import SocialAttention
from configuration.models import AttentionType, Item, SubattentionType


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