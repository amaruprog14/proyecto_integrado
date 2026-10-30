"""Contratos comunes y semillas completas; siempre usa la base aislada de Django."""
from io import StringIO

from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.test import RequestFactory, TestCase, SimpleTestCase
from django.test.html import parse_html
from django.urls import reverse

from accounts.forms import DelegationForm
from accounts.models import Official, Area, Position, Delegation, Role, ServiceRecipient
from common.demo_data import demo_accounts
from common.field_validation import clean_catalog_name, clean_address, clean_code
from common.chilean_rut import normalize_chilean_rut
from common.pagination import ClampedPaginationMixin
from configuration.models import AttentionType, SubattentionType, ActivityType, ServiceType, Item, Period
from activities.models import SocialAttention, Activity


class FieldValidationTests(SimpleTestCase):
    def test_field_specific_characters(self):
        self.assertEqual(clean_catalog_name("  Área   Ñuble-Sur  "), "Área Ñuble-Sur")
        for value in ("Sector 2", "Nombre@", "Nombre_"):
            with self.assertRaises(ValidationError):
                clean_catalog_name(value)
        self.assertEqual(clean_address("Av. Perú #123"), "Av. Perú #123")
        self.assertEqual(clean_code("abc_12-3"), "ABC_12-3")
        with self.assertRaises(ValidationError):
            clean_code("ABC/@")

    def test_demo_ruts_are_valid(self):
        for account in demo_accounts():
            self.assertEqual(normalize_chilean_rut(account["national_id"]), account["national_id"])

    def test_page_size_allowlist(self):
        view = ClampedPaginationMixin()
        view.paginate_by = 10
        for value, expected in (("25", 25), ("3", 10), ("0", 10), ("9999", 10), ("no", 10)):
            view.request = RequestFactory().get("/", {"page_size": value})
            self.assertEqual(view.get_paginate_by(None), expected)


class MaintainerDataTests(TestCase):
    def test_all_maintainers_share_toolbar_order_and_valid_html(self):
        call_command("seed_demo", stdout=StringIO())
        self.client.force_login(Official.objects.get(user__username="admin_demo").user)
        routes = ("delegation_list", "role_list", "user_maintainer", "official_maintainer",
                  "position_maintainer", "area_maintainer", "group_maintainer",
                  "activity_maintainer", "item_maintainer", "attention_type_maintainer",
                  "subattention_type_maintainer", "period_maintainer")
        for route in routes:
            with self.subTest(route=route):
                response = self.client.get(reverse(route))
                self.assertEqual(response.status_code, 200)
                html = response.content.decode()
                parse_html(html)
                toolbar = html.split('class="maintainer-tools"', 1)[1].split('class="table-responsive', 1)[0]
                self.assertLess(toolbar.index('id="maintainer-search"'), toolbar.index('>Buscar</button>'))
                self.assertLess(toolbar.index('>Buscar</button>'), toolbar.index('maintainer-export-button'))
                if 'id="maintainer-status"' in toolbar:
                    self.assertLess(toolbar.index('maintainer-export-button'), toolbar.index('id="maintainer-status"'))
                self.assertIn('aria-label="Registros por página"', toolbar)
                self.assertNotIn('<option value="3"', toolbar)

    def test_commune_is_fixed_for_create_and_edit(self):
        data = dict(delegation_name="Prueba", address="Calle 123", status="ACTIVE")
        form = DelegationForm(data)
        self.assertTrue(form.is_valid(), form.errors)
        delegation = form.save()
        self.assertEqual(delegation.commune, "La Serena")
        data["commune"] = "Otra ciudad"
        form = DelegationForm(data, instance=delegation)
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.save().commune, "La Serena")

    def test_lengths_are_enforced_without_truncation(self):
        data = dict(delegation_name="Á" * 100, address="C" * 100, status="ACTIVE")
        self.assertTrue(DelegationForm(data).is_valid())
        data["delegation_name"] += "a"
        self.assertIn("delegation_name", DelegationForm(data).errors)

    def test_complete_seed_is_repeatable_and_preserves_passwords(self):
        call_command("seed_demo", stdout=StringIO())
        user = Official.objects.get(user__username="funcionario1").user
        user.set_password("ClaveExistente-123")
        user.save(update_fields=["password"])
        models = (ActivityType, ServiceType, AttentionType, SubattentionType, SocialAttention,
                  Area, Position, Delegation, Role, ServiceRecipient, Item, Period, Activity)
        before = [model.objects.count() for model in models]
        call_command("seed_demo", stdout=StringIO())
        self.assertEqual(before, [model.objects.count() for model in models])
        self.assertEqual(before[:5], [5] * 5)
        user.refresh_from_db()
        self.assertTrue(user.check_password("ClaveExistente-123"))
        new_official = Official.objects.get(user__username="funcionario1_lote_b")
        original = Official.objects.get(user=user)
        self.assertEqual(new_official.delegation_id, original.delegation_id)
        self.assertEqual(new_official.area_id, original.area_id)
        self.assertEqual(new_official.position_id, original.position_id)
        self.assertEqual(list(new_official.roles.all()), list(original.roles.all()))
        for official in Official.objects.all():
            self.assertTrue(official.phone and official.area_id and official.position_id)
            normalize_chilean_rut(official.national_id)
        for attention in SocialAttention.objects.all():
            attention.full_clean()
        for catalog in AttentionType.objects.all():
            self.assertTrue(catalog.description and catalog.service_type_id)
