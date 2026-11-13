"""Semilla pública: volúmenes, integridad, repetibilidad y aislamiento de evaluación."""
from datetime import date
from io import StringIO
from unittest.mock import patch
from uuid import uuid4

from django.contrib.auth.models import Group, User
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db.models import Count, F
from django.test import TestCase, override_settings
from django.urls import reverse

from accounts.models import Area, Delegation, Function, GroupProfile, Official, Position, Role, ServiceRecipient, Territory
from activities.models import Activity, ClientRequest, ClientRequestEvent, SocialAttention
from analytics.measurement import create_revision, eligible_items, version_for
from analytics.models import MeasurementAdjustment, MeasurementItem, MeasurementPlan, MeasurementVersion
from configuration.models import AttentionType, AuditLog, Item, Period, SubattentionType
from common.demo_data import demo_rut
from common.sgr_seed_data import GEOGRAPHY, POSITIONS
from common.testing_seed import TEST_SEED_PASSWORD

PASSWORD = TEST_SEED_PASSWORD
MODELS = (User, Group, GroupProfile, Area, Delegation, Function, Official, Position, Role, ServiceRecipient, Territory,
          Activity, ClientRequest, ClientRequestEvent, SocialAttention, AttentionType, Item, Period, SubattentionType,
          MeasurementPlan, MeasurementVersion, MeasurementItem, MeasurementAdjustment)


def seed(**kwargs):
    output = StringIO()
    call_command("seed_demo", no_input=True, stdout=output, **kwargs)
    return output.getvalue()


def counts():
    return {model.__name__: model.objects.count() for model in MODELS}


@override_settings(PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"],
                   ALLOWED_HOSTS=["testserver"], SEED_DEMO_PASSWORD=PASSWORD)
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
        self.assertNotIn(PASSWORD, self.output)

    def test_measurement_plans_are_published_and_apply_by_date_and_position(self):
        self.assertEqual(MeasurementPlan.objects.count(), 14)
        versions = MeasurementVersion.objects.all()
        self.assertEqual(versions.count(), 15)
        self.assertFalse(versions.filter(published_at__isnull=True).exists())
        for version in versions.prefetch_related("items"):
            self.assertEqual(sum(line.weight for line in version.items.all()), 100)
        self.assertEqual(AuditLog.objects.filter(action="Publicación de plan de medición").count(), 15)
        official = Official.objects.get(national_id=demo_rut(70000008))
        before = version_for(official.position_id, date(2026, 10, 14))
        after = version_for(official.position_id, date(2026, 10, 15))
        self.assertEqual((before.number, after.number), (1, 2))
        self.assertEqual(before.items.get(item__item_name="Visita terreno").goal, 12)
        self.assertEqual(after.items.get(item__item_name="Visita terreno").goal, 18)
        percentage = after.items.get(item__item_name="Soluciones de ingresos al tubo")
        self.assertEqual((percentage.goal_type, percentage.goal), (MeasurementItem.GoalType.PERCENTAGE, 80))
        self.assertEqual(after.items.get(item__item_name="Atención social a usuario presencial")
                         .adjustments.get(official=official).goal, 24)
        admin = User.objects.get(username="adminA")
        self.assertFalse(eligible_items(admin.official.position_id, date(2026, 11, 12))
                         .filter(item_name="Atención social a usuario presencial").exists())

    def test_seed_allows_attention_outside_measurement_for_global_administrator(self):
        admin = User.objects.get(username="adminA")
        self.client.force_login(admin)
        recipient = ServiceRecipient.objects.filter(territory__delegation=admin.official.delegation).first()
        kind = AttentionType.objects.get(name="Informes sociales")
        token = uuid4().hex
        with patch("activities.forms.timezone.localdate", return_value=date(2026, 11, 12)):
            response = self.client.post(reverse("attention_entry"), {
                "recipient_national_id": recipient.national_id, "recipient_full_name": recipient.full_name,
                "delegation": admin.official.delegation_id, "attention_type": kind.pk,
                "subattention_type": kind.subattention_types.first().pk, "effective_date": "2026-10-15",
                "description": "Atención de prueba", "result": "Orientación entregada",
                "case_subject": "Seguimiento ficticio", "submission_token": token,
            })
        self.assertEqual(response.status_code, 302)
        attention = SocialAttention.objects.get(submission_token=token)
        self.assertContains(self.client.get(reverse("attention_detail", args=[attention.pk])), "Fuera de medición")

    def test_reseed_completes_missing_plans_and_preserves_existing_versions(self):
        missing = MeasurementPlan.objects.get(period__start_date="2026-10-01", position__position_name="Delegado")
        missing.versions.all().delete()
        missing.delete()
        plan = MeasurementPlan.objects.get(period__start_date="2026-10-01", position__position_name="Gestor social")
        draft = create_revision(plan, date(2026, 11, 1))
        draft.items.filter(item__item_name="Visita terreno").update(goal=32)
        output = seed()
        self.assertIn("Planes de medición nuevos: 1. Versiones publicadas: 1. Planes existentes conservados: 13.", output)
        draft.refresh_from_db()
        self.assertFalse(draft.is_published)
        self.assertEqual(draft.items.get(item__item_name="Visita terreno").goal, 32)

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
        self.assertFalse(SocialAttention.objects.values("case").annotate(n=Count("pk")).filter(n__gt=3).exists())
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
        rotated_password = "Fixture-Rotada$3579"
        with override_settings(SEED_DEMO_PASSWORD=rotated_password):
            output = seed()
        self.assertEqual(before, counts())
        activity.refresh_from_db()
        for account in User.objects.exclude(pk=foreign.pk):
            self.assertTrue(account.check_password(rotated_password), account.username)
        self.assertNotIn(rotated_password, output)
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

    def test_evaluation_accounts_and_additional_global_administrator(self):
        self.assertSetEqual(set(User.objects.values_list("username", flat=True)), {"adminEvalA", "adminA", "editorA", "readerA", "readerB", "clientA", "clientB"})
        admin = User.objects.get(username="adminA")
        self.assertFalse(admin.is_superuser)
        self.assertTrue(admin.has_perm("accounts.change_official"))
        self.assertTrue(admin.has_perm("accounts.archive_official"))
        self.assertTrue(admin.has_perm("activities.archive_activity"))
        self.client.force_login(admin)
        period = Period.objects.first()
        self.assertContains(self.client.get(reverse("period_detail", args=[period.pk])), "Configuración de medición")
        self.assertEqual(self.client.get(reverse("measurement_plan_list", args=[period.pk])).status_code, 200)
        editor = User.objects.get(username="editorA")
        self.assertFalse(editor.has_perm("accounts.archive_official"))
        self.assertFalse(editor.has_perm("activities.archive_activity"))
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
        response = self.client.get(reverse("client_requests"), {"page_size": 30, "record_source": "online"})
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
                "subattention_type": subtype.pk, "description": "Prueba de relación de catálogos",
                "result": "Orientación de prueba"}
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

    def test_seed_profiles_can_save_contact_details_without_filling_missing_names(self):
        from accounts.forms import OwnOfficialProfileForm
        from activities.client_portal import ClientProfileForm

        for user in User.objects.all():
            with self.subTest(username=user.username):
                official = getattr(user, "official", None)
                profile = official or user.service_recipient
                form_class = OwnOfficialProfileForm if official else ClientProfileForm
                self.assertTrue(user.first_name and user.last_name)
                self.assertEqual(user.get_full_name(), profile.full_name)
                form = form_class({"first_name": user.first_name, "last_name": user.last_name,
                                   "email": profile.email, "phone": profile.phone}, instance=profile)
                self.assertTrue(form.is_valid(), form.errors)

    def test_reseed_upgrades_only_the_previous_administrator_permissions(self):
        role = Role.objects.get(role_name="Administrador")
        missing = ("view_measurementplan", "add_measurementplan", "change_measurementplan", "publish_measurementplan")
        role.permissions.remove(*role.permissions.filter(codename__in=("archive_official", *missing)))
        seed()
        admin = User.objects.get(username="adminA")
        editor = User.objects.get(username="editorA")
        self.assertTrue(admin.has_perm("accounts.archive_official"))
        self.assertFalse(editor.has_perm("accounts.archive_official"))
        for codename in missing:
            with self.subTest(permission=codename):
                self.assertTrue(admin.has_perm(f"analytics.{codename}"))
                self.assertFalse(editor.has_perm(f"analytics.{codename}"))
                self.assertFalse(User.objects.get(username="adminEvalA").has_perm(f"analytics.{codename}"))

    def test_reseed_completes_legacy_names_but_preserves_edited_names(self):
        legacy = User.objects.get(username="editorA")
        legacy.first_name, legacy.last_name = legacy.username, ""
        legacy.save(update_fields=["first_name", "last_name"])
        edited = User.objects.get(username="readerA")
        edited.first_name, edited.last_name = "Ana", "Rojas"
        edited.save(update_fields=["first_name", "last_name"])
        edited.official.full_name = "Ana Rojas"
        edited.official.save(update_fields=["full_name"])

        seed()

        legacy.refresh_from_db()
        edited.refresh_from_db()
        self.assertTrue(legacy.last_name)
        self.assertEqual(legacy.get_full_name(), legacy.official.full_name)
        self.assertEqual((edited.first_name, edited.last_name), ("Ana", "Rojas"))

    def test_foreign_records_are_preserved(self):
        foreign = Delegation.objects.create(delegation_name="Otra delegación", address="Dirección externa 123", commune="La Serena")
        seed()
        foreign.refresh_from_db()
        self.assertEqual(foreign.address, "Dirección externa 123")
        self.assertEqual(Delegation.objects.count(), 3)


@override_settings(PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"],
                   SEED_DEMO_PASSWORD=PASSWORD)
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

    def test_seed_password_applies_to_all_seed_accounts(self):
        seed()
        for user in User.objects.all():
            self.assertTrue(user.check_password(PASSWORD), user.username)

    @override_settings(SEED_DEMO_PASSWORD="")
    def test_missing_seed_password_stops_before_writing(self):
        before = counts()
        with self.assertRaisesMessage(CommandError, "Configura SEED_DEMO_PASSWORD"):
            seed()
        self.assertEqual(counts(), before)

    def test_dry_run_does_not_reset_existing_seed_passwords(self):
        seed()
        user = User.objects.get(username="editorA")
        user.set_password("Temporal-distinta-2026")
        user.save(update_fields=["password"])
        seed(dry_run=True)
        user.refresh_from_db()
        self.assertTrue(user.check_password("Temporal-distinta-2026"))
