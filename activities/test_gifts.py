"""Flujo de regalos por las rutas públicas, con control territorial, historial y duplicados."""
from datetime import date
from io import BytesIO

from django.contrib.auth.models import Permission, User
from django.db import IntegrityError, transaction
from django.test import TestCase, TransactionTestCase, override_settings, skipUnlessDBFeature
from django.urls import reverse
from django.utils import timezone
from openpyxl import load_workbook

from accounts.models import Delegation, Official, Role, Territory
from activities.gift_models import GIFT_PERMISSIONS, GiftCampaign, GiftRegistration, canonical_gift_rut
from common.demo_data import demo_rut
from common.testing_edit import post_with_revision, revision_from_form
from configuration.models import AuditLog


class GiftFixture:
    def setUp(self):
        self.a = Delegation.objects.create(delegation_name="Las Compañías", address="Demo", commune="La Serena")
        self.b = Delegation.objects.create(delegation_name="Antena", address="Demo", commune="La Serena")
        self.ta = Territory.objects.create(territory_name="Latorre", delegation=self.a)
        self.tb = Territory.objects.create(territory_name="Ceres", delegation=self.b)
        self.user = self.make_user("delegado", self.a, "DELEGATION")
        self.global_user = self.make_user("coordinador", self.b, "ALL")
        self.client.force_login(self.user)
        today = timezone.localdate()
        self.campaign = GiftCampaign.objects.create(name="Navidad", year=today.year, celebration="CHRISTMAS",
            start_date=date(today.year, 1, 1), end_date=date(today.year, 12, 31))
        self.campaign.delegations.add(self.a, self.b)
        self.create_url = reverse("gift_registration_create", args=[self.campaign.pk])

    def make_user(self, name, delegation, scope):
        user = User.objects.create_user(username=name)
        official = Official.objects.create(full_name="Funcionario de prueba", national_id=demo_rut(70000000 + User.objects.count()),
            user=user, delegation=delegation, email=f"{name}@example.invalid")
        role = Role.objects.create(role_name=f"Perfil {name}", scope=scope)
        role.permissions.set(Permission.objects.filter(content_type__app_label="activities",
            codename__in=[name.split(".")[1] for name in GIFT_PERMISSIONS]))
        official.roles.add(role)
        return user

    def data(self, **changes):
        data = {"child_rut": demo_rut(72000001), "child_name": "Menor Ficticio", "guardian_rut": demo_rut(71000001),
                "guardian_name": "Adulto Ficticio", "phone": "912345678", "territory": str(self.ta.pk), "notes": "Prueba"}
        data.update(changes)
        return data

    def register(self, **changes):
        response = self.client.post(self.create_url, self.data(**changes))
        self.assertEqual(response.status_code, 302, response.context and response.context["form"].errors)
        return GiftRegistration.objects.latest("pk")


@override_settings(ALLOWED_HOSTS=["testserver"])
class GiftFlowTests(GiftFixture, TestCase):
    def test_create_detail_history_and_audit(self):
        row = self.register()
        self.assertEqual(row.delegation, self.a)
        self.assertEqual(row.events.count(), 1)
        self.assertEqual(row.registered_by, self.user)
        self.assertTrue(AuditLog.objects.filter(affected_table="activities_giftregistration", affected_record_id=row.pk).exists())
        self.assertContains(self.client.get(reverse("gift_registration_detail", args=[row.pk])), row.child_name)
        self.assertContains(self.client.get(reverse("gift_campaign_list")), "Navidad")

    def test_duplicate_between_delegations_and_formats_and_cancelled(self):
        row = self.register()
        self.client.force_login(self.global_user)
        response = self.client.post(self.create_url, self.data(territory=self.tb.pk))
        self.assertContains(response, "Las Compañías")
        self.assertEqual(GiftRegistration.objects.count(), 1)
        self.client.force_login(self.user)
        post_with_revision(self.client, reverse("gift_registration_cancel", args=[row.pk]), {"observation": "Inscripción desistida"})
        number, digit = row.child_rut.split("-")
        formatted_rut = f"{int(number):,}".replace(",", ".") + "-" + digit
        response = self.client.post(self.create_url, self.data(child_rut=formatted_rut))
        self.assertContains(response, "RUT ya ingresado")
        self.assertEqual(GiftRegistration.objects.count(), 1)

    def test_deliver_once_and_reject_stale_or_edit(self):
        row = self.register()
        url = reverse("gift_registration_deliver", args=[row.pk])
        revision = revision_from_form(self.client, url)
        response = self.client.post(url, {"edit_revision": revision, "observation": "Recibido por adulto responsable"})
        self.assertEqual(response.status_code, 302)
        row.refresh_from_db()
        self.assertEqual((row.status, row.delivered_by), ("DELIVERED", self.user))
        self.assertIsNotNone(row.delivered_at)
        self.assertEqual(self.client.post(url, {"edit_revision": revision}).status_code, 409)
        response = post_with_revision(self.client, reverse("gift_registration_edit", args=[row.pk]), self.data(child_name="Otro Nombre"))
        self.assertContains(response, "Solo se pueden modificar")
        row.refresh_from_db()
        self.assertEqual(row.child_name, "Menor Ficticio")
        self.assertEqual(row.events.count(), 2)

    def test_cancel_requires_reason_and_preserves_history(self):
        row = self.register()
        url = reverse("gift_registration_cancel", args=[row.pk])
        self.assertEqual(post_with_revision(self.client, url, {}).status_code, 200)
        row.refresh_from_db()
        self.assertEqual(row.status, "REGISTERED")
        self.assertEqual(post_with_revision(self.client, url, {"observation": "Desistimiento"}).status_code, 302)
        row.refresh_from_db()
        self.assertEqual(row.cancellation_reason, "Desistimiento")
        self.assertEqual(row.events.count(), 2)

    def test_foreign_registration_is_hidden_and_forged_territory_rejected(self):
        self.client.force_login(self.global_user)
        row = self.register(territory=self.tb.pk)
        self.client.force_login(self.user)
        self.assertEqual(self.client.get(reverse("gift_registration_detail", args=[row.pk])).status_code, 404)
        self.assertEqual(self.client.post(self.create_url, self.data(territory=self.tb.pk)).status_code, 200)
        self.assertEqual(GiftRegistration.objects.count(), 1)
        url = reverse("gift_registration_list", args=[self.campaign.pk])
        self.assertNotContains(self.client.get(url), row.child_name)

    def test_filters_summary_and_excel_have_same_scope(self):
        row = self.register()
        self.client.force_login(self.global_user)
        self.register(territory=self.tb.pk, child_rut=demo_rut(72000002), child_name="Otra Persona")
        self.client.force_login(self.user)
        url = reverse("gift_registration_list", args=[self.campaign.pk])
        response = self.client.get(url)
        self.assertEqual(response.context["total"], 1)
        response = self.client.get(url, {"export": "xlsx"})
        sheet = load_workbook(BytesIO(response.content)).active
        self.assertEqual(sheet.max_row, 2)
        self.assertEqual(sheet.cell(2, 4).value, row.child_name)
        self.assertEqual(self.client.get(url, {"status": "DELIVERED"}).context["total"], 0)

    def test_closed_campaign_rejects_registration_and_delivery(self):
        row = self.register()
        self.campaign.is_open = False
        self.campaign.save()
        response = self.client.post(self.create_url, self.data(child_rut=demo_rut(72000002)))
        self.assertContains(response, "La campaña debe estar abierta")
        response = post_with_revision(self.client, reverse("gift_registration_deliver", args=[row.pk]), {})
        self.assertContains(response, "La campaña debe estar abierta")
        row.refresh_from_db()
        self.assertEqual(row.status, "REGISTERED")

    def test_new_campaign_allows_same_child_and_bad_ruts_are_rejected(self):
        self.register()
        self.campaign.pk = None
        self.campaign.celebration = "CHILDREN"
        self.campaign.save()
        self.campaign.delegations.add(self.a)
        self.create_url = reverse("gift_registration_create", args=[self.campaign.pk])
        self.register()
        self.assertEqual(GiftRegistration.objects.count(), 2)
        response = self.client.post(self.create_url, self.data(child_rut="123-4"))
        self.assertEqual(response.status_code, 200)
        self.assertIn("child_rut", response.context["form"].errors)

    def test_campaign_edits_require_full_scope_and_preserve_registered_delegation(self):
        url = reverse("gift_campaign_edit", args=[self.campaign.pk])
        self.assertEqual(self.client.get(url, HTTP_X_MODAL_REQUEST="true").status_code, 404)
        self.register()
        self.client.force_login(self.global_user)
        data = {"name": "Navidad actualizada", "celebration": "CHRISTMAS", "year": self.campaign.year,
                "start_date": self.campaign.start_date, "end_date": self.campaign.end_date,
                "is_open": "True", "delegations": [self.b.pk]}
        response = post_with_revision(self.client, url, data)
        self.assertContains(response, "Conserva las delegaciones")
        data["delegations"] = [self.a.pk, self.b.pk]
        self.assertEqual(post_with_revision(self.client, url, data).status_code, 302)

    def test_concurrent_edit_revision_is_required(self):
        row = self.register()
        url = reverse("gift_registration_edit", args=[row.pk])
        revision = revision_from_form(self.client, url)
        self.assertEqual(self.client.post(url, self.data(notes="Primera edición", edit_revision=revision)).status_code, 302)
        self.assertEqual(self.client.post(url, self.data(notes="Segunda edición", edit_revision=revision)).status_code, 409)
        row.refresh_from_db()
        self.assertEqual(row.notes, "Primera edición")

    def test_no_permissions_or_client_cannot_open_module(self):
        from django.test import Client
        anonymous = Client()
        self.assertEqual(anonymous.get(reverse("gift_campaign_list")).status_code, 302)
        user = User.objects.create_user(username="sin_permisos")
        self.client.force_login(user)
        self.assertEqual(self.client.get(reverse("gift_campaign_list")).status_code, 403)
        self.assertEqual(self.client.post(self.create_url, self.data()).status_code, 403)

    def test_unique_constraint_and_state_constraint(self):
        row = self.register()
        with self.assertRaises(IntegrityError), transaction.atomic():
            GiftRegistration.objects.filter(pk=row.pk).update(status="DELIVERED")
        row.pk = None
        with self.assertRaises(IntegrityError), transaction.atomic():
            row.save()

    def test_delivery_preserves_original_delegation_after_territory_transfer(self):
        row = self.register()
        Territory.objects.filter(pk=self.ta.pk).update(delegation=self.b)
        self.client.force_login(self.global_user)
        response = post_with_revision(self.client, reverse("gift_registration_deliver", args=[row.pk]), {})
        self.assertEqual(response.status_code, 302)
        row.refresh_from_db()
        self.assertEqual(row.status, "DELIVERED")
        self.assertEqual(row.delegation_id, self.a.pk)
        event = row.events.latest("pk")
        self.assertEqual(event.previous["delegation"], str(self.a.pk))
        self.assertEqual(event.current["delegation"], str(self.a.pk))
        self.client.force_login(self.user)
        self.assertEqual(self.client.get(reverse("gift_registration_detail", args=[row.pk])).status_code, 200)
        other = self.make_user("delegado-antena", self.b, "DELEGATION")
        self.client.force_login(other)
        self.assertEqual(self.client.get(reverse("gift_registration_detail", args=[row.pk])).status_code, 404)

    def test_inactive_territory_does_not_prevent_cancellation(self):
        row = self.register()
        Territory.objects.filter(pk=self.ta.pk).update(is_active=False)
        response = post_with_revision(self.client, reverse("gift_registration_cancel", args=[row.pk]), {
            "observation": "Desistimiento del adulto responsable",
        })
        self.assertEqual(response.status_code, 302)
        row.refresh_from_db()
        self.assertEqual(row.status, "CANCELLED")
        self.assertEqual(row.delegation_id, self.a.pk)
        self.assertEqual(row.events.count(), 2)

    def test_global_coordinator_can_close_campaign_with_inactive_participant(self):
        self.register()
        Delegation.objects.filter(pk=self.b.pk).update(status="INACTIVE")
        self.client.force_login(self.global_user)
        url = reverse("gift_campaign_edit", args=[self.campaign.pk])
        response = self.client.get(url, HTTP_X_MODAL_REQUEST="true")
        self.assertEqual(response.status_code, 200)
        payload = {"name": self.campaign.name, "celebration": "CHRISTMAS", "year": self.campaign.year,
                   "start_date": self.campaign.start_date, "end_date": self.campaign.end_date,
                   "is_open": "False", "delegations": [self.a.pk, self.b.pk]}
        response = post_with_revision(self.client, url, payload)
        self.assertEqual(response.status_code, 302, response.context and response.context["form"].errors)
        self.campaign.refresh_from_db()
        self.assertFalse(self.campaign.is_open)
        self.assertEqual(set(self.campaign.delegations.values_list("pk", flat=True)), {self.a.pk, self.b.pk})

    def test_existing_registration_can_be_edited_after_territory_transfer_without_changing_owner(self):
        row = self.register()
        Territory.objects.filter(pk=self.ta.pk).update(delegation=self.b)
        url = reverse("gift_registration_edit", args=[row.pk])
        response = post_with_revision(self.client, url, self.data(notes="Contacto actualizado"))
        self.assertEqual(response.status_code, 302, response.context and response.context["form"].errors)
        row.refresh_from_db()
        self.assertEqual((row.delegation_id, row.notes), (self.a.pk, "Contacto actualizado"))
        self.client.force_login(self.global_user)
        response = post_with_revision(self.client, url, self.data(territory=self.tb.pk))
        self.assertEqual(response.status_code, 200)
        row.refresh_from_db()
        self.assertEqual((row.delegation_id, row.territory_id), (self.a.pk, self.ta.pk))

    def test_inactive_original_delegation_keeps_history_and_allows_cancellation(self):
        row = self.register()
        Delegation.objects.filter(pk=self.a.pk).update(status="INACTIVE")
        listing = self.client.get(reverse("gift_registration_list", args=[self.campaign.pk]))
        self.assertEqual(listing.status_code, 200)
        self.assertEqual(listing.context["total"], 1)
        response = post_with_revision(self.client, reverse("gift_registration_cancel", args=[row.pk]), {"observation": "Registro desistido"})
        self.assertEqual(response.status_code, 302)
        row.refresh_from_db()
        self.assertEqual((row.status, row.delegation_id), ("CANCELLED", self.a.pk))
        response = self.client.post(self.create_url, self.data(child_rut=demo_rut(72000002)))
        self.assertEqual(response.status_code, 200)
        self.assertIn("territory", response.context["form"].errors)
        self.assertEqual(GiftRegistration.objects.count(), 1)

    def test_inactive_participant_does_not_expand_local_campaign_permissions(self):
        Delegation.objects.filter(pk=self.b.pk).update(status="INACTIVE")
        url = reverse("gift_campaign_edit", args=[self.campaign.pk])
        self.assertEqual(self.client.get(url, HTTP_X_MODAL_REQUEST="true").status_code, 404)
        self.assertEqual(self.client.post(url, {}).status_code, 404)
        self.client.force_login(self.global_user)
        form = self.client.get(reverse("gift_campaign_create"), HTTP_X_MODAL_REQUEST="true").context["form"]
        self.assertNotIn(self.b.pk, form.fields["delegations"].queryset.values_list("pk", flat=True))
        form = self.client.get(url, HTTP_X_MODAL_REQUEST="true").context["form"]
        self.assertIn(self.b.pk, form.fields["delegations"].queryset.values_list("pk", flat=True))

    def test_campaign_with_all_participants_inactive_remains_manageable_globally(self):
        self.register()
        Delegation.objects.filter(pk__in=[self.a.pk, self.b.pk]).update(status="INACTIVE")
        self.client.force_login(self.global_user)
        self.assertContains(self.client.get(reverse("gift_campaign_list")), self.campaign.name)
        payload = {"name": self.campaign.name, "celebration": "CHRISTMAS", "year": self.campaign.year,
                   "start_date": self.campaign.start_date, "end_date": self.campaign.end_date,
                   "is_open": "False", "delegations": [self.a.pk, self.b.pk]}
        response = post_with_revision(self.client, reverse("gift_campaign_edit", args=[self.campaign.pk]), payload)
        self.assertEqual(response.status_code, 302, response.context and response.context["form"].errors)
        self.campaign.refresh_from_db()
        self.assertFalse(self.campaign.is_open)

    def test_campaign_create_from_modal_and_date_validation(self):
        today = timezone.localdate()
        url = reverse("gift_campaign_create")
        form = self.client.get(url, HTTP_X_MODAL_REQUEST="true").context["form"]
        self.assertNotIn("data-field-pattern", form.fields["name"].widget.attrs)
        data = {"name": f"Día del Niño {today.year}", "celebration": "CHILDREN", "year": today.year,
                "start_date": date(today.year, 1, 1), "end_date": date(today.year, 12, 31),
                "is_open": "True", "delegations": [self.a.pk]}
        response = self.client.post(url, data, HTTP_X_MODAL_REQUEST="true")
        self.assertEqual(response.status_code, 204)
        campaign = GiftCampaign.objects.get(celebration="CHILDREN")
        self.assertEqual(list(campaign.delegations.all()), [self.a])
        data["celebration"] = "ANNIVERSARY"
        data["end_date"] = date(today.year - 1, 12, 31)
        self.assertEqual(self.client.post(url, data).status_code, 200)
        self.assertFalse(GiftCampaign.objects.filter(celebration="ANNIVERSARY").exists())

    def test_cannot_repurpose_campaign_with_registrations(self):
        self.register()
        self.client.force_login(self.global_user)
        data = {"name": "Otra campaña", "celebration": "CHILDREN", "year": self.campaign.year,
                "start_date": self.campaign.start_date, "end_date": self.campaign.end_date,
                "is_open": "True", "delegations": [self.a.pk, self.b.pk]}
        response = post_with_revision(self.client, reverse("gift_campaign_edit", args=[self.campaign.pk]), data)
        self.assertContains(response, "Conserva la celebración")
        self.campaign.refresh_from_db()
        self.assertEqual(self.campaign.celebration, "CHRISTMAS")

    def test_optional_activity_belongs_to_same_delegation_and_requires_permission(self):
        from activities.models import Activity
        from configuration.models import Item
        permission = Permission.objects.get(codename="view_activity", content_type__app_label="activities")
        self.user.official.roles.get().permissions.add(permission)
        item = Item.objects.create(item_name="Entrega de regalos")
        activity = Activity.objects.create(official=self.user.official, item=item, date=timezone.localdate(),
            record_type="MANUAL", subject="Jornada de Navidad", registration_delegation=self.a)
        row = self.register(activity=activity.pk)
        self.assertContains(self.client.get(reverse("gift_registration_detail", args=[row.pk])), activity.code)
        activity.registration_delegation = self.b
        activity.save()
        response = self.client.post(self.create_url, self.data(child_rut=demo_rut(72000002), activity=activity.pk))
        self.assertIn("activity", response.context["form"].errors)

    def test_csrf_and_action_permission_are_enforced(self):
        from django.test import Client
        row = self.register()
        secure = Client(enforce_csrf_checks=True)
        secure.force_login(self.user)
        url = reverse("gift_registration_deliver", args=[row.pk])
        self.assertEqual(secure.post(url, {}).status_code, 403)
        self.user.official.roles.get().permissions.remove(Permission.objects.get(
            codename="deliver_giftregistration", content_type__app_label="activities"))
        self.assertEqual(self.client.post(url, {}).status_code, 403)
        row.refresh_from_db()
        self.assertEqual(row.status, "REGISTERED")

    def test_leading_zeros_and_points_share_canonical_rut(self):
        rut = demo_rut(1234567)
        self.assertEqual(canonical_gift_rut("0" + rut), rut)

    def test_permission_migration_is_scoped_to_seed_roles(self):
        import importlib
        from types import SimpleNamespace
        from django.apps import apps
        from django.db import connection

        migration = importlib.import_module("activities.migrations.0018_gift_seed_permissions")
        seed = Role.objects.create(role_name="Delegado", scope="DELEGATION", description="[SGR seed v1] Perfil")
        custom = Role.objects.create(role_name="Coordinador del sistema", scope="ALL", description="Perfil propio")
        editor = Role.objects.create(role_name="Funcionario", scope="DELEGATION", description="[SGR seed v1] Perfil")
        schema = SimpleNamespace(connection=connection)
        migration.grant(apps, schema)
        migration.grant(apps, schema)
        self.assertEqual(seed.permissions.count(), 8)
        self.assertFalse(custom.permissions.exists())
        self.assertFalse(editor.permissions.exists())


@override_settings(ALLOWED_HOSTS=["testserver"])
class GiftConcurrencyTests(GiftFixture, TransactionTestCase):
    @skipUnlessDBFeature("has_select_for_update")
    def test_two_simultaneous_submissions_only_create_one_registration(self):
        from concurrent.futures import ThreadPoolExecutor
        from threading import Barrier
        from django.db import close_old_connections
        from django.test import Client

        barrier = Barrier(2)
        clients = [Client(), Client()]
        for client in clients:
            client.force_login(self.user)

        def submit(client):
            close_old_connections()
            try:
                barrier.wait(timeout=10)
                return client.post(self.create_url, self.data()).status_code
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=2) as pool:
            statuses = list(pool.map(submit, clients))
        self.assertEqual(sorted(statuses), [200, 302])
        self.assertEqual(GiftRegistration.objects.count(), 1)
        self.assertEqual(GiftRegistration.objects.get().events.count(), 1)
