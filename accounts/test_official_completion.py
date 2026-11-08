"""Detalle y archivado del CRUD de Funcionarios, con las cuentas y ámbitos de la pauta."""
from datetime import date
from io import BytesIO
from unittest.mock import patch

from asgiref.sync import async_to_sync, sync_to_async
from channels.testing import WebsocketCommunicator
from django import forms
from django.conf import settings
from django.contrib.auth import authenticate
from django.contrib.auth.models import Group, Permission, User
from django.db import IntegrityError, transaction
from django.test import Client, TestCase, TransactionTestCase, override_settings
from django.urls import reverse
from openpyxl import load_workbook

from accounts.forms import OfficialForm
from accounts.models import Delegation, GroupProfile, Official, Role
from common.demo_data import demo_rut
from configuration.models import AuditLog, Item, Period
from activities.models import Activity
from config.asgi import application

PASSWORD = 'Funcionario-Prueba-2026'


class OfficialFixture:
    def setUp(self):
        from django.core.cache import cache
        cache.clear()
        self.a = Delegation.objects.create(delegation_name='Las Compañías', address='Calle A', commune='La Serena')
        self.b = Delegation.objects.create(delegation_name='Antena', address='Calle B', commune='La Serena')
        self.users = {}
        for index, (name, delegation, actions) in enumerate((
            ('admin', self.a, ('view', 'add', 'change', 'archive')),
            ('editor', self.a, ('view', 'add', 'change')),
            ('readerA', self.a, ('view',)), ('readerB', self.b, ('view',)),
        )):
            user = User.objects.create_user(name, f'{name}@example.test', PASSWORD)
            official = Official.objects.create(user=user, full_name=f'Persona {name}',
                national_id=demo_rut(72000000+index), email=user.email, delegation=delegation)
            role = Role.objects.create(role_name=f'Perfil {name}', scope=Role.Scope.DELEGATION)
            role.permissions.set(Permission.objects.filter(content_type__app_label='accounts',
                codename__in=[f'{action}_official' for action in actions]))
            official.roles.add(role)
            self.users[name] = user
        self.target_user = User.objects.create_user('target', 'target@example.test', PASSWORD)
        self.target = Official.objects.create(user=self.target_user, full_name='Funcionario Objetivo',
            national_id=demo_rut(72000100), email=self.target_user.email, delegation=self.a)
        self.foreign = Official.objects.create(full_name='Funcionario Ajeno', national_id=demo_rut(72000101),
            email='foreign@example.test', delegation=self.b)
        self.client.force_login(self.users['admin'])

    def archive(self, target=None, **kwargs):
        return self.client.post(reverse('official_archive', args=[(target or self.target).pk]), **kwargs)

    def edit_payload(self, **overrides):
        return dict(full_name=self.target.full_name, national_id=self.target.national_id,
                    email=self.target.email, delegation=self.a.pk, status='ACTIVE', **overrides)


@override_settings(PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'], ALLOWED_HOSTS=['testserver', 'localhost'])
class OfficialCompletionTests(OfficialFixture, TestCase):
    def test_form_is_modelform_and_deferred_save_keeps_account_and_relations(self):
        form = OfficialForm(dict(full_name='Funcionario Nuevo', national_id=demo_rut(72000200),
            email='new@example.test', delegation=self.a.pk, status='ACTIVE', create_account='on',
            username='new', password1=PASSWORD, password2=PASSWORD), actor=self.users['admin'],
            delegation_queryset=Delegation.objects.filter(pk=self.a.pk))
        self.assertIsInstance(form, forms.ModelForm)
        self.assertTrue(form.is_valid(), form.errors)
        with transaction.atomic():
            official = form.save(commit=False)
            self.assertIsNone(official.pk)
            self.assertFalse(User.objects.filter(username='new').exists())
            official.save()
            form.save_m2m()
        self.assertEqual(official.user.username, 'new')
        self.assertTrue(official.user.check_password(PASSWORD))

    def test_reader_can_view_detail_without_edit_or_archive_actions(self):
        self.client.force_login(self.users['readerA'])
        response = self.client.get(reverse('official_detail', args=[self.target.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.target.full_name)
        self.assertContains(response, 'Volver al listado')
        self.assertNotContains(response, reverse('official_update', args=[self.target.pk]))
        self.assertNotContains(response, reverse('official_archive', args=[self.target.pk]))
        self.assertNotContains(response, self.target_user.password)
        self.assertEqual(self.client.get(reverse('official_detail', args=[self.foreign.pk])).status_code, 404)
        self.assertEqual(self.client.get(reverse('official_detail', args=[999999])).status_code, 404)

    def test_admin_only_sees_archive_for_other_authorized_officials(self):
        response = self.client.get(reverse('official_maintainer'))
        self.assertContains(response, reverse('official_detail', args=[self.target.pk]))
        self.assertContains(response, reverse('official_archive', args=[self.target.pk]))
        self.assertNotContains(response, reverse('official_archive', args=[self.users['admin'].official.pk]))
        self.assertNotContains(response, reverse('official_detail', args=[self.foreign.pk]))
        self.assertContains(response, 'data-swal-confirm-text="Sí, archivar"')
        self.assertContains(response, 'csrfmiddlewaretoken')
        self.client.force_login(self.users['editor'])
        response = self.client.get(reverse('official_maintainer'))
        self.assertContains(response, reverse('official_update', args=[self.target.pk]))
        self.assertNotContains(response, reverse('official_archive', args=[self.target.pk]))

    def test_editor_and_readers_cannot_archive_by_direct_post(self):
        for name in ('editor', 'readerA', 'readerB'):
            with self.subTest(account=name):
                self.client.force_login(self.users[name])
                self.assertEqual(self.archive().status_code, 403)
                self.target.refresh_from_db()
                self.assertIsNone(self.target.deleted_at)
        self.assertFalse(AuditLog.objects.filter(action='Archivado de funcionario').exists())

    def test_editor_cannot_grant_archival_through_role_assignment(self):
        self.client.force_login(self.users['editor'])
        role = Role.objects.get(role_name='Perfil admin')
        response = self.client.post(reverse('official_update', args=[self.target.pk]),
                                    self.edit_payload(roles=[role.pk]))
        self.assertEqual(response.status_code, 403)
        self.assertFalse(self.target.roles.filter(pk=role.pk).exists())

    def test_archived_official_cannot_be_revived_by_editing(self):
        self.archive()
        self.assertEqual(self.client.post(reverse('official_update', args=[self.target.pk]),
                                          self.edit_payload()).status_code, 404)
        self.target.refresh_from_db()
        self.assertIsNotNone(self.target.deleted_at)

    def test_account_creation_collision_rolls_back_official_and_returns_modal_errors(self):
        payload = dict(full_name='Funcionario Nuevo', national_id=demo_rut(74000000),
                       email='new@example.test', delegation=self.a.pk, status='ACTIVE',
                       create_account='on', username='new', password1=PASSWORD, password2=PASSWORD)
        with patch('django.contrib.auth.models.User.save', side_effect=IntegrityError('colisión simulada')):
            response = self.client.post(reverse('official_create'), payload, HTTP_X_MODAL_REQUEST='true')
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context['form'].non_field_errors())
        self.assertEqual(response.context['form']['full_name'].value(), 'Funcionario Nuevo')
        self.assertFalse(Official.objects.filter(national_id=payload['national_id']).exists())
        self.assertFalse(User.objects.filter(username='new').exists())

    def test_archive_requires_post_and_csrf_and_does_not_happen_when_opening_detail(self):
        url = reverse('official_archive', args=[self.target.pk])
        self.assertEqual(self.client.get(url).status_code, 405)
        self.assertEqual(self.client.get(reverse('official_detail', args=[self.target.pk])).status_code, 200)
        self.target.refresh_from_db()
        self.assertIsNone(self.target.deleted_at)
        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.force_login(self.users['admin'])
        self.assertEqual(csrf_client.post(url).status_code, 403)
        page = csrf_client.get(reverse('official_detail', args=[self.target.pk]))
        token = page.cookies['csrftoken'].value
        self.assertEqual(csrf_client.post(url, HTTP_X_CSRFTOKEN=token).status_code, 302)
        self.target.refresh_from_db()
        self.assertIsNotNone(self.target.deleted_at)

    def test_archive_preserves_history_and_excludes_official_from_lists_exports_and_selectors(self):
        item = Item.objects.create(item_name='Visita')
        activity = Activity.objects.create(official=self.target, item=item, date=date(2026,11,8), record_type='Terreno')
        original_status = self.target.status
        self.assertRedirects(self.archive(), reverse('official_maintainer'))
        self.target.refresh_from_db()
        self.assertIsNotNone(self.target.deleted_at)
        self.assertEqual(self.target.status, original_status)
        self.assertEqual(Activity.objects.get(pk=activity.pk).official_id, self.target.pk)
        self.assertNotContains(self.client.get(reverse('official_maintainer')), self.target.email)
        export = self.client.get(reverse('official_export'))
        self.assertEqual(export.status_code, 200)
        self.assertNotIn(self.target.email, str(list(load_workbook(BytesIO(export.content)).active.values)))
        from common.maintainer_forms import ActivityForm
        form = ActivityForm(actor=self.users['admin'])
        self.assertFalse(form.fields['official'].queryset.filter(pk=self.target.pk).exists())
        self.assertEqual(self.client.get(reverse('official_detail', args=[self.target.pk])).status_code, 404)
        self.assertEqual(self.client.get(reverse('official_update', args=[self.target.pk]), HTTP_X_MODAL_REQUEST='true').status_code, 404)
        self.assertEqual(self.archive().status_code, 404)
        log = AuditLog.objects.get(action='Archivado de funcionario')
        self.assertEqual(log.affected_record_id, self.target.pk)
        self.assertEqual((log.previous_value, log.new_value), ('Archivado: No', 'Archivado: Sí'))

    def test_archived_account_cannot_login_and_existing_session_stops_working(self):
        role = Role.objects.get(role_name='Perfil readerA')
        self.target.roles.add(role)
        logged_in = Client()
        logged_in.force_login(self.target_user)
        self.assertEqual(logged_in.get(reverse('official_maintainer')).status_code, 200)
        self.archive()
        self.assertIsNone(authenticate(username='target', password=PASSWORD))
        self.assertEqual(logged_in.get(reverse('official_maintainer')).status_code, 302)
        self.target_user.refresh_from_db()
        self.assertTrue(self.target_user.is_active)  # El bloqueo procede del perfil archivado, sin borrar la cuenta.

    def test_archive_out_of_scope_is_404_and_audited(self):
        self.assertEqual(self.archive(self.foreign).status_code, 404)
        self.foreign.refresh_from_db()
        self.assertIsNone(self.foreign.deleted_at)
        self.assertTrue(AuditLog.objects.filter(action='Acceso denegado', affected_record_id=self.foreign.pk).exists())

    def test_cannot_archive_self(self):
        self.assertEqual(self.archive(self.users['admin'].official).status_code, 403)
        self.users['admin'].official.refresh_from_db()
        self.assertIsNone(self.users['admin'].official.deleted_at)

    def test_last_global_administrator_is_protected(self):
        role = Role.objects.create(role_name='Administrador Global', scope=Role.Scope.ALL)
        role.permissions.add(Permission.objects.get(content_type__app_label='accounts', codename='change_role'))
        self.target.roles.add(role)
        response = self.archive(follow=True)
        self.assertContains(response, 'último Administrador global')
        self.target.refresh_from_db()
        self.assertIsNone(self.target.deleted_at)

    def test_last_global_group_administrator_is_protected(self):
        group = Group.objects.create(name='Administración global')
        GroupProfile.objects.update_or_create(group=group, defaults={"scope": Role.Scope.ALL})
        group.permissions.add(Permission.objects.get(content_type__app_label='accounts', codename='change_role'))
        self.target_user.groups.add(group)
        response = self.archive(follow=True)
        self.assertContains(response, 'administrador global')
        self.target.refresh_from_db()
        self.assertIsNone(self.target.deleted_at)

    def test_audit_failure_rolls_back_archive(self):
        with patch('accounts.views._registrar_auditoria', side_effect=RuntimeError('fallo de prueba')):
            with self.assertRaises(RuntimeError):
                self.archive()
        self.target.refresh_from_db()
        self.assertIsNone(self.target.deleted_at)

    def test_list_state_survives_detail_and_archive_clamps_removed_last_page(self):
        for index in range(6):
            Official.objects.create(full_name=f'Persona Paginable {index}', national_id=demo_rut(73000000+index),
                email=f'page{index}@example.test', delegation=self.a)
        self.client.get(reverse('official_maintainer'), {'q':'Paginable', 'page_size':5, 'sort':'name', 'direction':'asc'})
        page = self.client.get(reverse('official_maintainer'), {'page':2})
        target = page.context['page_obj'].object_list[0]
        self.client.get(reverse('official_detail', args=[target.pk]))
        restored = self.client.get(reverse('official_maintainer'))
        self.assertEqual(restored.context['page_obj'].number, 2)
        self.assertEqual(restored.context['selected_sort'], 'name')
        self.assertEqual(restored.context['query'], 'Paginable')
        self.archive(target)
        page = self.client.get(reverse('official_maintainer'))
        self.assertEqual(page.context['page_obj'].number, 1)
        self.assertEqual(page.context['page_obj'].paginator.count, 5)


@override_settings(PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'], ALLOWED_HOSTS=['localhost','testserver'])
class OfficialArchiveRealtimeTests(OfficialFixture, TransactionTestCase):
    def test_archive_notifies_only_authorized_reader_after_commit_and_rollback_is_silent(self):
        from channels.db import database_sync_to_async

        async def scenario():
            sockets = []
            try:
                for name in ('readerA', 'readerB'):
                    client = Client()
                    await sync_to_async(client.force_login)(self.users[name])
                    cookie = client.cookies[settings.SESSION_COOKIE_NAME].value
                    socket = WebsocketCommunicator(application, '/ws/maintainers/official/',
                        headers=[(b'cookie', f'{settings.SESSION_COOKIE_NAME}={cookie}'.encode()),
                                 (b'origin', b'http://localhost')])
                    self.assertTrue((await socket.connect())[0])
                    sockets.append(socket)
                def rolled_back():
                    with transaction.atomic():
                        response = self.archive()
                        self.assertEqual(response.status_code, 302)
                        transaction.set_rollback(True)
                await database_sync_to_async(rolled_back)()
                for socket in sockets:
                    self.assertTrue(await socket.receive_nothing(timeout=.05))
                response = await database_sync_to_async(self.archive)()
                self.assertEqual(response.status_code, 302)
                self.assertEqual(await sockets[0].receive_json_from(), {'type':'maintainer.changed'})
                self.assertTrue(await sockets[1].receive_nothing(timeout=.05))
                page = await database_sync_to_async(self.client.get)(reverse('official_maintainer'))
                self.assertNotContains(page, self.target.email)
            finally:
                for socket in sockets:
                    await socket.disconnect()
        async_to_sync(scenario)()
