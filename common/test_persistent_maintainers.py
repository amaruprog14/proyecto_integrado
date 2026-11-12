from datetime import timedelta
from unittest.mock import patch
from django.contrib.auth.models import User, Permission, Group
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from accounts.models import Position, Area, Official, Delegation, Role
from activities.models import Activity, SocialAttention
from configuration.models import Item, Period, AttentionType, SubattentionType, AuditLog
from common.maintainer_forms import PositionForm, GroupForm
from common.scopes import permission_scope


class PersistentMaintainerTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_superuser("crud", "crud@example.test", "test")
        self.delegation = Delegation.objects.create(delegation_name="Centro", address="Calle", commune="La Serena")
        self.official = Official.objects.create(user=self.user, full_name="Operador", national_id="12.345.678-5", email="crud@example.test", delegation=self.delegation)
        self.item = Item.objects.create(item_name="Atenciones")
        self.today = timezone.localdate()
        self.period = Period.objects.create(start_date=self.today, end_date=self.today)
        self.client.force_login(self.user)

    def test_catalog_create_duplicate_update_and_lifecycle(self):
        response = self.client.post(reverse("position_create"), {"position_name": "  Jefe   Municipal ", "description": "Descripción", "is_active": "on"})
        self.assertEqual(response.status_code, 302)
        position = Position.objects.get()
        self.assertEqual(position.position_name, "Jefe Municipal")
        form = PositionForm({"position_name": "jefe municipal", "is_active": "on"})
        self.assertFalse(form.is_valid())
        self.client.post(reverse("position_deactivate", args=[position.pk]))
        position.refresh_from_db()
        self.assertFalse(position.is_active)
        self.assertEqual(self.client.get(reverse("position_activate", args=[position.pk])).status_code, 405)
        self.assertTrue(AuditLog.objects.filter(affected_table=Position._meta.db_table).exists())

    def test_all_real_lists_details_and_excel(self):
        objects = {"position": Position.objects.create(position_name="Jefe"), "area": Area.objects.create(area_name="Social"),
            "group": Group.objects.create(name="Lectores"), "period": self.period,
            "activity": Activity.objects.create(official=self.official, item=self.item, date=self.today, record_type=Activity.RecordType.FIELD)}
        for key, obj in objects.items():
            with self.subTest(key=key):
                response = self.client.get(reverse(key + "_maintainer"))
                self.assertEqual(response.status_code, 200)
                self.assertNotContains(response, "maintainer-demo-banner")
                self.assertEqual(self.client.get(reverse(key + "_detail", args=[obj.pk])).status_code, 200)
                export = self.client.get(reverse(key + "_export"))
                self.assertEqual(export.status_code, 200)
                self.assertIn("spreadsheetml", export["Content-Type"])

    def test_period_closure_blocks_manual_activity_mutations(self):
        activity = Activity.objects.create(official=self.official, item=self.item, date=self.today, record_type=Activity.RecordType.FIELD)
        self.client.post(reverse("period_close", args=[self.period.pk]))
        self.client.post(reverse("activity_deactivate", args=[activity.pk]))
        activity.refresh_from_db()
        self.assertIsNone(activity.deleted_at)
        response = self.client.post(reverse("activity_create"), {"official": self.official.pk, "item": self.item.pk,
            "date": self.today.isoformat(), "record_type": Activity.RecordType.FIELD})
        self.assertContains(response, "período abierto")
        self.assertEqual(Activity.objects.count(), 1)

    def test_manual_create_and_move_from_closed_period_is_rejected(self):
        response = self.client.post(reverse("activity_create"), {"official": self.official.pk, "item": self.item.pk,
            "date": self.today.isoformat(), "record_type": Activity.RecordType.MONTHLY})
        self.assertEqual(response.status_code, 302)
        self.assertRegex(Activity.objects.get().code, r"^ACT-\d+$")
        self.client.post(reverse("period_close", args=[self.period.pk]))
        tomorrow = self.today + timedelta(days=1)
        Period.objects.create(start_date=tomorrow, end_date=tomorrow)
        activity = Activity.objects.get()
        self.client.post(reverse("activity_update", args=[activity.pk]), {"official": self.official.pk,
            "item": self.item.pk, "date": tomorrow.isoformat(), "record_type": Activity.RecordType.FIELD})
        activity.refresh_from_db()
        self.assertEqual(activity.date, self.today)

    def attention_payload(self):
        attention_type = AttentionType.objects.create(name="Social", activity_item=self.item)
        sub = SubattentionType.objects.create(name="Orientación", attention_type=attention_type)
        return dict(recipient_national_id="11.111.111-1", recipient_full_name="Persona", delegation=self.delegation.pk,
            attention_type=attention_type.pk, subattention_type=sub.pk, description="Atención presencial",
            result="Orientación entregada.", submission_token="a"*32)

    def test_automatic_activity_once_and_linked_protection(self):
        payload = self.attention_payload()
        self.client.post(reverse("attention_entry"), payload)
        self.client.post(reverse("attention_entry"), payload)
        self.assertEqual(SocialAttention.objects.count(), 1)
        self.assertEqual(Activity.objects.count(), 1)
        attention = SocialAttention.objects.get()
        self.assertEqual(attention.activity.record_type, Activity.RecordType.ATTENTION)
        self.assertEqual(attention.activity.action_description, attention.description)
        self.client.post(reverse("activity_deactivate", args=[attention.activity_id]))
        attention.activity.refresh_from_db()
        self.assertIsNone(attention.activity.deleted_at)

    def test_missing_item_rolls_back_attention_and_activity(self):
        payload = self.attention_payload()
        AttentionType.objects.update(activity_item=None)
        response = self.client.post(reverse("attention_entry"), payload)
        self.assertContains(response, "Configura un ítem vigente")
        self.assertFalse(SocialAttention.objects.exists())
        self.assertFalse(Activity.objects.exists())

    def test_failed_audit_rolls_back_catalog_write(self):
        with patch("common.maintainers.AuditoriaService.register_change", side_effect=RuntimeError("audit")):
            with self.assertRaises(RuntimeError):
                self.client.post(reverse("area_create"), {"area_name": "Social", "is_active": "on"})
        self.assertFalse(Area.objects.exists())

    def test_group_active_permissions_and_permission_specific_scope(self):
        self.user.is_superuser = False
        self.user.save()
        group = Group.objects.create(name="Consulta")
        permission = Permission.objects.get(content_type__app_label="activities", codename="view_activity")
        group.permissions.add(permission)
        group.user_set.add(self.user)
        profile = group.sgr_profile
        profile.scope = Role.Scope.OWN
        profile.save()
        user = User.objects.get(pk=self.user.pk)
        self.assertTrue(user.has_perm("activities.view_activity"))
        self.assertEqual(permission_scope(user, "activities.view_activity"), Role.Scope.OWN)
        self.assertIsNone(permission_scope(user, "activities.change_activity"))
        profile.is_active = False
        profile.save()
        self.assertFalse(User.objects.get(pk=self.user.pk).has_perm("activities.view_activity"))

    def test_own_scope_hides_other_official_activities_and_export(self):
        self.user.is_superuser = False
        self.user.save()
        role = Role.objects.create(role_name="Propios", scope=Role.Scope.OWN)
        role.permissions.add(Permission.objects.get(content_type__app_label="activities", codename="view_activity"))
        self.official.roles.add(role)
        other = Official.objects.create(full_name="Otro", email="other@example.test", national_id="11.111.111-1", delegation=self.delegation)
        activity = Activity.objects.create(official=other, item=self.item, date=self.today, record_type=Activity.RecordType.FIELD)
        response = self.client.get(reverse("activity_detail", args=[activity.pk]))
        self.assertEqual(response.status_code, 404)
        self.assertTrue(AuditLog.objects.filter(action="Acceso denegado").exists())

    def test_period_overlap_including_shared_boundary(self):
        response = self.client.post(reverse("period_create"), {"start_date": self.today.isoformat(), "end_date": (self.today+timedelta(days=2)).isoformat()})
        self.assertContains(response, "solapa")
        self.assertEqual(Period.objects.count(), 1)

    def test_group_crud_preserves_members_permissions_and_lifecycle(self):
        permission = Permission.objects.get(content_type__app_label="activities", codename="view_activity")
        response = self.client.post(reverse("group_create"), {"name": "Consulta municipal", "description": "Consulta",
            "scope": Role.Scope.DELEGATION, "is_active": "on", "permissions": [permission.pk], "members": [self.user.pk]})
        self.assertEqual(response.status_code, 302)
        group = Group.objects.get(name="Consulta municipal")
        self.assertTrue(group.user_set.filter(pk=self.user.pk).exists())
        self.assertTrue(group.permissions.filter(pk=permission.pk).exists())
        self.assertEqual(group.sgr_profile.description, "Consulta")
        self.client.post(reverse("group_deactivate", args=[group.pk]))
        group.sgr_profile.refresh_from_db()
        self.assertFalse(group.sgr_profile.is_active)

    def test_group_cannot_drop_last_administrator(self):
        group = Group.objects.create(name="Administración")
        group.permissions.add(Permission.objects.get(content_type__app_label="accounts", codename="change_role"))
        group.user_set.add(self.user)
        group.sgr_profile.scope = Role.Scope.ALL
        group.sgr_profile.save()
        self.client.post(reverse("group_deactivate", args=[group.pk]))
        group.sgr_profile.refresh_from_db()
        self.assertTrue(group.sgr_profile.is_active)
        response = self.client.post(reverse("group_update", args=[group.pk]), {"name": "Administración", "scope": Role.Scope.ALL})
        self.assertContains(response, "sin un grupo o rol administrador")
        self.assertTrue(group.user_set.filter(pk=self.user.pk).exists())

    def test_unknown_historical_type_stops_migration_without_modifying_data(self):
        from importlib import import_module
        from django.apps import apps
        migration = import_module("activities.migrations.0005_activity_code_alter_activity_record_type_and_more")
        activity = Activity.objects.create(official=self.official, item=self.item, date=self.today, record_type="Desconocido")
        with self.assertRaisesMessage(RuntimeError, "tipos desconocidos"):
            migration.preflight(apps, None)
        activity.refresh_from_db()
        self.assertEqual(activity.record_type, "Desconocido")

    def test_invalid_pagination_and_date_filters_do_not_fail(self):
        response = self.client.get(reverse("activity_maintainer"), {"page": "errónea", "page_size": "erróneo", "date_from": "2026-99-99"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["page_obj"].number, 1)
