"""Cuenta real de la semilla para la pauta: CRUD en A, aislamiento de B y global intacto."""
from io import BytesIO, StringIO

from django.contrib.auth import authenticate
from django.contrib.auth.models import User
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings
from django.urls import reverse
from openpyxl import load_workbook

from accounts.evaluation_admin import PERMISSIONS, ROLE_NAME, USERNAME
from accounts.models import Official, Role
from activities.models import Activity
from common.demo_data import demo_rut
from common.realtime import queryset as realtime_queryset
from common.scopes import permission_scope


@override_settings(PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'], ALLOWED_HOSTS=['testserver'])
class EvaluationAdminTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command('seed_demo', stdout=StringIO())

    def setUp(self):
        from django.core.cache import cache
        cache.clear()
        self.user = User.objects.get(username=USERNAME)
        self.client.force_login(self.user)
        self.a = self.user.official.delegation
        self.target = Official.objects.get(national_id=demo_rut(70000008))
        self.foreign = Official.objects.get(national_id=demo_rut(70000009))
        self.activity = Activity.objects.filter(official=self.target, social_attentions__isnull=True).first()
        self.foreign_activity = Activity.objects.filter(official=self.foreign, social_attentions__isnull=True).first()

    def test_login_exact_permissions_single_delegation_and_global_preserved(self):
        self.assertIsNotNone(authenticate(username=USERNAME, password='demo1234'))
        self.assertFalse(self.user.is_superuser or self.user.is_staff)
        self.assertFalse(self.user.groups.exists() or self.user.user_permissions.exists())
        self.assertSetEqual(set(self.user.official.roles.values_list('role_name', flat=True)), {ROLE_NAME})
        for permission in PERMISSIONS:
            self.assertTrue(self.user.has_perm(permission), permission)
            self.assertEqual(permission_scope(self.user, permission), Role.Scope.DELEGATION)
        self.assertSetEqual(set(self.user.official.get_authorized_delegations()), {self.a})
        global_user = User.objects.get(username='adminA')
        self.assertEqual(permission_scope(global_user, 'accounts.archive_official'), Role.Scope.ALL)
        self.assertEqual(global_user.official.get_authorized_delegations().count(), 2)
        for route in ('role_list', 'user_maintainer', 'group_maintainer'):
            self.assertEqual(self.client.get(reverse(route)).status_code, 403)
        response = self.client.get(reverse('home'))
        self.assertFalse(response.context['can_select_active_delegation'])

    def test_foreign_urls_writes_relations_and_delegation_switch_rejected(self):
        for route in ('official_detail', 'official_update', 'official_archive'):
            url = reverse(route, args=[self.foreign.pk])
            response = self.client.post(url, {}) if route == 'official_archive' else self.client.get(url)
            self.assertEqual(response.status_code, 404)
        for route in ('activity_detail', 'activity_update', 'activity_deactivate', 'activity_activate'):
            url = reverse(route, args=[self.foreign_activity.pk])
            response = self.client.post(url, {}) if route in ('activity_deactivate', 'activity_activate') else self.client.get(url)
            self.assertEqual(response.status_code, 404)
        response = self.client.post(reverse('active_delegation_select'), {'delegation_id': self.foreign.delegation_id})
        self.assertIn(response.status_code, (302, 403))
        self.assertNotEqual(self.client.session.get('active_delegation_id'), self.foreign.delegation_id)
        before = Activity.objects.count()
        data = self.activity_payload(official=self.foreign.pk)
        response = self.client.post(reverse('activity_create'), data)
        self.assertIn('official', response.context['form'].errors)
        self.assertEqual(Activity.objects.count(), before)
        before_officials = Official.objects.count()
        response = self.client.post(reverse('official_create'), dict(
            full_name='Intento Fuera Ámbito', national_id=demo_rut(73000002),
            email='forged@example.invalid', delegation=self.foreign.delegation_id, status='ACTIVE'))
        self.assertIn('delegation', response.context['form'].errors)
        self.assertEqual(Official.objects.count(), before_officials)
        response = self.client.post(reverse('official_update', args=[self.target.pk]), dict(
            full_name=self.target.full_name, national_id=self.target.national_id,
            email=self.target.email, delegation=self.a.pk, status='ACTIVE',
            roles=[Role.objects.get(role_name='Administrador').pk]))
        self.assertEqual(response.status_code, 403)
        self.assertFalse(self.target.roles.filter(scope=Role.Scope.ALL).exists())
        self.foreign.refresh_from_db()
        self.foreign_activity.refresh_from_db()
        self.assertIsNone(self.foreign.deleted_at)
        self.assertIsNone(self.foreign_activity.deleted_at)

    def activity_payload(self, **changes):
        data = dict(official=self.target.pk, item=self.activity.item_id, date=self.activity.date.isoformat(),
                    record_type=self.activity.record_type, action_description='Evaluación ámbito A')
        data.update(changes)
        return data

    def test_both_crud_create_edit_archive_and_activity_restore(self):
        data = dict(full_name='Persona Evaluación Nueva', national_id=demo_rut(73000001),
                    email='nueva@sgr.example.invalid', delegation=self.a.pk, status='ACTIVE')
        self.assertEqual(self.client.post(reverse('official_create'), data).status_code, 302)
        official = Official.objects.get(national_id=data['national_id'])
        data['full_name'] = 'Persona Evaluación Editada'
        self.assertEqual(self.client.post(reverse('official_update', args=[official.pk]), data).status_code, 302)
        self.assertContains(self.client.get(reverse('official_detail', args=[official.pk])), data['full_name'])
        self.assertEqual(self.client.post(reverse('official_archive', args=[official.pk])).status_code, 302)
        official.refresh_from_db()
        self.assertIsNotNone(official.deleted_at)
        self.assertEqual(self.client.post(reverse('activity_create'), self.activity_payload()).status_code, 302)
        activity = Activity.objects.get(action_description='Evaluación ámbito A')
        self.assertEqual(self.client.post(reverse('activity_update', args=[activity.pk]),
            self.activity_payload(action_description='Editada en ámbito A')).status_code, 302)
        self.assertContains(self.client.get(reverse('activity_detail', args=[activity.pk])), 'Editada en ámbito A')
        self.assertEqual(self.client.post(reverse('activity_deactivate', args=[activity.pk])).status_code, 302)
        activity.refresh_from_db()
        self.assertIsNotNone(activity.deleted_at)
        self.assertEqual(self.client.post(reverse('activity_activate', args=[activity.pk])).status_code, 302)
        activity.refresh_from_db()
        self.assertIsNone(activity.deleted_at)

    def test_lists_excel_and_realtime_queries_exclude_b(self):
        for kind in ('official', 'activity'):
            response = self.client.get(reverse(f'{kind}_maintainer'), {'page_size': 30})
            for row in response.context['page_obj']:
                self.assertEqual((row if kind == 'official' else row.official).delegation_id, self.a.pk)
            response = self.client.get(reverse(f'{kind}_export'))
            self.assertEqual(response.status_code, 200)
            rows = list(load_workbook(BytesIO(response.content), read_only=True).active.values)
            self.assertGreater(len(rows), 31)
            if kind == 'official':
                self.assertNotIn(self.foreign.email, str(rows))
            else:
                self.assertNotIn(self.foreign.full_name, str(rows))
            visible = realtime_queryset(kind, self.user)
            self.assertFalse(visible.filter(pk=(self.foreign if kind == 'official' else self.foreign_activity).pk).exists())

    def test_preparation_is_idempotent_without_resetting_password_or_global_role(self):
        self.user.set_password('Personal-Change-2026')
        self.user.save(update_fields=['password'])
        global_role = Role.objects.get(role_name='Administrador')
        before = set(global_role.permissions.values_list('pk', flat=True))
        counts = (User.objects.count(), Official.objects.count(), Activity.objects.count())
        for _ in range(2):
            call_command('prepare_evaluation_admin', stdout=StringIO())
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password('Personal-Change-2026'))
        self.assertEqual(counts, (User.objects.count(), Official.objects.count(), Activity.objects.count()))
        self.assertSetEqual(before, set(global_role.permissions.values_list('pk', flat=True)))
        global_role.refresh_from_db()
        self.assertEqual(global_role.scope, Role.Scope.ALL)

    def test_legacy_seed_profile_upgrade_and_dry_run(self):
        profile = self.user.official
        profile.user = None
        profile.save(update_fields=['user'])
        profile.roles.set([Role.objects.get(role_name='Funcionario')])
        self.user.delete()
        call_command('prepare_evaluation_admin', dry_run=True, stdout=StringIO())
        self.assertFalse(User.objects.filter(username=USERNAME).exists())
        profile.refresh_from_db()
        self.assertIsNone(profile.user_id)
        call_command('prepare_evaluation_admin', stdout=StringIO())
        profile.refresh_from_db()
        self.assertEqual(profile.user.username, USERNAME)
        self.assertEqual(Official.objects.count(), 100)

    def test_permission_drift_is_not_silently_overwritten(self):
        role = Role.objects.get(role_name=ROLE_NAME)
        role.scope = Role.Scope.ALL
        role.save(update_fields=['scope'])
        with self.assertRaises(CommandError):
            call_command('prepare_evaluation_admin', stdout=StringIO())
        role.refresh_from_db()
        self.assertEqual(role.scope, Role.Scope.ALL)

    def test_existing_unrelated_account_is_not_taken_over(self):
        profile = self.user.official
        profile.user = None
        profile.save(update_fields=['user'])
        profile.roles.set([Role.objects.get(role_name='Funcionario')])
        self.user.email = 'personal@example.invalid'
        self.user.save(update_fields=['email'])
        with self.assertRaises(CommandError):
            call_command('prepare_evaluation_admin', stdout=StringIO())
        profile.refresh_from_db()
        self.user.refresh_from_db()
        self.assertIsNone(profile.user_id)
        self.assertEqual(self.user.email, 'personal@example.invalid')
