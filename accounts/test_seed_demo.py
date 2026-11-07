"""Semilla pública: volúmenes, integridad, repetibilidad y aislamiento de evaluación."""
from io import StringIO

from django.contrib.auth.models import Group, User
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db.models import Count, F
from django.test import TestCase, override_settings
from django.urls import reverse

from accounts.models import Area, Delegation, Function, GroupProfile, Official, Position, Role, ServiceRecipient, Territory
from activities.models import Activity, ClientRequest, ClientRequestEvent, SocialAttention
from configuration.models import AttentionType, Item, Period, SubattentionType
from common.demo_data import DEMO_PASSWORD, demo_rut
from common.sgr_seed_data import GEOGRAPHY, POSITIONS

PASSWORD = DEMO_PASSWORD
MODELS = (User, Group, GroupProfile, Area, Delegation, Function, Official, Position, Role, ServiceRecipient, Territory,
          Activity, ClientRequest, ClientRequestEvent, SocialAttention, AttentionType, Item, Period, SubattentionType)


def seed(**kwargs):
    output = StringIO()
    call_command("seed_demo", no_input=True, stdout=output, **kwargs)
    return output.getvalue()


def counts():
    return {model.__name__: model.objects.count() for model in MODELS}


@override_settings(PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"], ALLOWED_HOSTS=["testserver"])
class SeedDemoTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.output = seed()

    def test_exactly_two_thousand_operational_records_without_padding_catalogs(self):
        for model, expected in ((Official, 100), (Activity, 1200), (ServiceRecipient, 300), (SocialAttention, 300), (ClientRequest, 100)):
            self.assertEqual(model.objects.count(), expected, model.__name__)
        self.assertEqual(Delegation.objects.count(), 2)
        self.assertEqual(Territory.objects.count(), 8)
        self.assertEqual(Position.objects.count(), 7)
        self.assertEqual(Function.objects.count(), 7)
        self.assertEqual(Item.objects.count(), 22)
        self.assertEqual(AttentionType.objects.count(), 2)
        self.assertEqual(SubattentionType.objects.count(), 7)
        self.assertIn("Negocio: 2000", self.output)
        self.assertIn("Contraseña de demostración: demo1234", self.output)

    def test_source_catalogs_and_all_personal_data_are_synthetic(self):
        for name, names in GEOGRAPHY.items():
            self.assertSetEqual(set(Territory.objects.filter(delegation__delegation_name=name).values_list("territory_name", flat=True)), set(names))
        self.assertSetEqual(set(Position.objects.values_list("position_name", flat=True)), set(POSITIONS))
        self.assertFalse(Official.objects.exclude(email__endswith="@sgr.example.invalid").exists())
        self.assertFalse(ServiceRecipient.objects.exclude(email__endswith="@sgr.example.invalid").exists())
        for official in Official.objects.all():
            official.full_clean()
        for recipient in ServiceRecipient.objects.all():
            recipient.full_clean()
        for entry in SocialAttention.objects.all():
            entry.full_clean()
            self.assertEqual(entry.responsible_id, entry.activity.official_id)
            self.assertEqual(entry.delegation_id, entry.recipient.delegation_id)
        self.assertFalse(SocialAttention.objects.values("recipient").annotate(n=Count("pk")).filter(n__gt=3).exists())
        self.assertFalse(ClientRequest.objects.exclude(delegation_id=F("territory__delegation_id")).exists())
        self.assertFalse(Activity.objects.filter(date__lt="2026-07-01").exists())
        self.assertFalse(Activity.objects.filter(date__gt="2026-10-31").exists())

    def test_repeat_preserves_records_and_resets_only_demo_passwords(self):
        foreign = User.objects.create_user("otro_usuario", password="Clave-privada-ajena-2026")
        before = counts()
        user = User.objects.get(username="editorA")
        user.set_password("Clave-cambiada-local-2026")
        user.save(update_fields=["password"])
        activity = Activity.objects.first()
        activity.action_description = "Descripción modificada por el usuario"
        activity.save(update_fields=["action_description"])
        output = seed()
        self.assertEqual(before, counts())
        user.refresh_from_db()
        activity.refresh_from_db()
        self.assertTrue(user.check_password("demo1234"))
        foreign.refresh_from_db()
        self.assertTrue(foreign.check_password("Clave-privada-ajena-2026"))
        self.assertEqual(activity.action_description, "Descripción modificada por el usuario")
        self.assertIn("Usuarios nuevos: 0", output)

    def test_each_delegation_has_fifty_officials_and_multiple_activity_pages(self):
        for username, delegation in (("readerA", "Las Compañías"), ("readerB", "Antena")):
            self.client.force_login(User.objects.get(username=username))
            response = self.client.get(reverse("official_maintainer"), {"page_size": 30})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.context["page_obj"].paginator.count, 50)
            self.assertEqual(response.context["page_obj"].paginator.num_pages, 2)
            self.assertTrue(all(row.delegation.delegation_name == delegation for row in response.context["page_obj"].object_list))
            response = self.client.get(reverse("activity_maintainer"), {"page_size": 30})
            self.assertGreaterEqual(response.context["page_obj"].paginator.count, 50)
            self.assertTrue(all(row.official.delegation.delegation_name == delegation for row in response.context["page_obj"].object_list))
            self.assertEqual(self.client.get(reverse("attention_entry")).status_code, 403)

    def test_six_accounts_and_effective_permissions(self):
        self.assertSetEqual(set(User.objects.values_list("username", flat=True)), {"adminA", "editorA", "readerA", "readerB", "clientA", "clientB"})
        admin = User.objects.get(username="adminA")
        self.assertFalse(admin.is_superuser)
        self.assertTrue(admin.has_perm("accounts.change_official"))
        editor = User.objects.get(username="editorA")
        for permission in ("accounts.add_official", "accounts.change_official", "activities.add_activity", "activities.change_activity"):
            self.assertTrue(editor.has_perm(permission), permission)
        for username in ("readerA", "readerB", "clientA", "clientB"):
            user = User.objects.get(username=username)
            self.assertFalse(user.has_perm("activities.change_activity"))
        a = User.objects.get(username="clientA").service_recipient
        b = User.objects.get(username="clientB").service_recipient
        self.assertNotEqual(a.delegation_id, b.delegation_id)
        self.assertEqual(a.requests.count(), 50)
        self.assertEqual(b.requests.count(), 50)
        for request in ClientRequest.objects.all():
            self.assertTrue(request.events.filter(status=request.status).exists())

    def test_clients_cannot_open_each_others_requests(self):
        a = User.objects.get(username="clientA")
        b = User.objects.get(username="clientB")
        own = a.service_recipient.requests.first()
        foreign = b.service_recipient.requests.first()
        self.client.force_login(a)
        response = self.client.get(reverse("client_requests"), {"page_size": 30})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["page_obj"].paginator.count, 50)
        self.assertTrue(all(row.recipient_id == a.service_recipient.pk for row in response.context["page_obj"]))
        self.assertEqual(self.client.get(reverse("client_request_detail", args=[own.pk])).status_code, 200)
        self.assertEqual(self.client.get(reverse("client_request_detail", args=[foreign.pk])).status_code, 404)
        self.assertEqual(self.client.get(reverse("activity_maintainer")).status_code, 403)

    def test_all_visible_maintainers_have_data_and_admin_sees_both_delegations(self):
        admin = User.objects.get(username="adminA")
        self.client.force_login(admin)
        routes = ("delegation_list", "role_list", "user_maintainer", "official_maintainer",
                  "position_maintainer", "territory_maintainer", "area_maintainer", "group_maintainer",
                  "activity_maintainer", "item_maintainer", "attention_type_maintainer",
                  "subattention_type_maintainer", "period_maintainer", "staff_client_requests")
        for route in routes:
            with self.subTest(route=route):
                response = self.client.get(reverse(route))
                self.assertEqual(response.status_code, 200)
                self.assertGreater(response.context["page_obj"].paginator.count, 0)
        response = self.client.get(reverse("home"))
        self.assertTrue(response.context["can_select_active_delegation"])
        self.assertSetEqual({d.delegation_name for d in response.context["authorized_active_delegations"]}, set(GEOGRAPHY))
        visible_ids = set()
        for delegation in Delegation.objects.all():
            response = self.client.post(reverse("active_delegation_select"), {"delegation_id": delegation.pk})
            self.assertEqual(response.status_code, 302)
            response = self.client.get(reverse("official_maintainer"), {"page_size": 30})
            self.assertEqual(response.context["page_obj"].paginator.count, 50)
            paginator = response.context["page_obj"].paginator
            for page_number in paginator.page_range:
                response = self.client.get(reverse("official_maintainer"), {"page_size": 30, "page": page_number})
                rows = response.context["page_obj"].object_list
                self.assertTrue(all(row.delegation_id == delegation.pk for row in rows))
                visible_ids.update(row.pk for row in rows)
        self.assertEqual(len(visible_ids), 100)
        group = Group.objects.get(name="Consulta SGR")
        self.assertSetEqual(set(group.user_set.values_list("username", flat=True)), {"readerA", "readerB"})
        self.assertEqual(group.sgr_profile.scope, Role.Scope.DELEGATION)
        self.assertFalse(group.permissions.exclude(codename__startswith="view_").exists())

    def test_attention_form_accepts_only_correct_type_subtype_pairs(self):
        from activities.forms import SocialAttentionForm
        admin = User.objects.get(username="adminA")
        recipient = ServiceRecipient.objects.first()
        subtype = SubattentionType.objects.first()
        data = {"recipient_national_id": recipient.national_id, "recipient_full_name": recipient.full_name,
                "delegation": recipient.delegation_id, "attention_type": subtype.attention_type_id,
                "subattention_type": subtype.pk, "description": "Prueba de relación de catálogos"}
        form = SocialAttentionForm(data, official=admin.official)
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.fields["attention_type"].queryset.count(), 2)
        self.assertEqual(form.fields["subattention_type"].queryset.count(), 7)
        data["attention_type"] = AttentionType.objects.exclude(pk=subtype.attention_type_id).get().pk
        form = SocialAttentionForm(data, official=admin.official)
        self.assertFalse(form.is_valid())
        self.assertIn("subattention_type", form.errors)

    def test_existing_closed_period_causes_atomic_failure(self):
        Period.objects.filter(start_date="2026-07-01").update(status=Period.Status.CLOSED)
        before = counts()
        with self.assertRaisesMessage(CommandError, "cerrado"):
            seed()
        self.assertEqual(counts(), before)

    def test_foreign_records_are_preserved(self):
        foreign = Delegation.objects.create(delegation_name="Otra delegación", address="Dirección externa 123", commune="La Serena")
        seed()
        foreign.refresh_from_db()
        self.assertEqual(foreign.address, "Dirección externa 123")
        self.assertEqual(Delegation.objects.count(), 3)


@override_settings(PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"])
class SeedDemoSafetyTests(TestCase):
    def test_dry_run_rolls_back_all_tables(self):
        before = counts()
        self.assertIn("SIMULACIÓN", seed(dry_run=True))
        self.assertEqual(counts(), before)

    def test_collision_does_not_link_or_overwrite_foreign_account_and_rolls_back(self):
        user = User.objects.create_user("adminA", email="externo@example.invalid", password=PASSWORD)
        before = counts()
        with self.assertRaisesMessage(CommandError, "ya existe"):
            seed()
        self.assertEqual(counts(), before)
        user.refresh_from_db()
        self.assertEqual(user.email, "externo@example.invalid")
        self.assertFalse(Official.objects.filter(user=user).exists())

    def test_rut_collision_rolls_back_without_replacing_existing_person(self):
        Official.objects.create(national_id=demo_rut(70000000), full_name="Persona existente", email="externo@example.invalid")
        before = counts()
        with self.assertRaises(CommandError):
            seed()
        self.assertEqual(counts(), before)
        self.assertEqual(Official.objects.get().full_name, "Persona existente")

    def test_default_password_works_without_environment_or_prompts(self):
        seed()
        for user in User.objects.all():
            self.assertTrue(user.check_password("demo1234"), user.username)

    def test_dry_run_does_not_reset_existing_seed_passwords(self):
        seed()
        user = User.objects.get(username="editorA")
        user.set_password("Temporal-distinta-2026")
        user.save(update_fields=["password"])
        seed(dry_run=True)
        user.refresh_from_db()
        self.assertTrue(user.check_password("Temporal-distinta-2026"))
