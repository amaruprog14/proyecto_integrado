"""Contrato de Actividades: editor sin archivado, historial administrativo y exportación segura."""
from datetime import timedelta
from io import BytesIO
from unittest.mock import patch

from asgiref.sync import async_to_sync
from channels.db import database_sync_to_async
from channels.testing import WebsocketCommunicator
from django import forms
from django.conf import settings
from django.contrib.auth.models import Permission
from django.db import transaction
from django.test import Client, TestCase, TransactionTestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from openpyxl import load_workbook

from accounts.models import Role, ServiceRecipient
from accounts.test_official_completion import OfficialFixture
from activities.models import Activity, SocialAttention
from common.maintainer_forms import ActivityForm
from configuration.models import Item, Period, AttentionType, SubattentionType, AuditLog
from config.asgi import application


class ActivityFixture(OfficialFixture):
    def setUp(self):
        super().setUp()
        for name, actions in (('admin', ('view','add','change','archive')), ('editor', ('view','add','change')),
                              ('readerA', ('view',)), ('readerB', ('view',))):
            Role.objects.get(role_name=f'Perfil {name}').permissions.add(*Permission.objects.filter(
                content_type__app_label='activities', codename__in=[f'{action}_activity' for action in actions]))
        self.today = timezone.localdate()
        self.period = Period.objects.create(start_date=self.today-timedelta(days=10), end_date=self.today+timedelta(days=10))
        self.item = Item.objects.create(item_name='Visita territorial')
        self.other_item = Item.objects.create(item_name='Reunión')
        self.activity = Activity.objects.create(official=self.target, item=self.item, date=self.today,
            record_type=Activity.RecordType.FIELD, action_description='Visita de demostración')
        self.foreign_activity = Activity.objects.create(official=self.foreign, item=self.item, date=self.today,
            record_type=Activity.RecordType.FIELD)
        self.archived = Activity.objects.create(official=self.target, item=self.item, date=self.today,
            record_type=Activity.RecordType.MONTHLY, deleted_at=timezone.now())

    def payload(self, **changes):
        data = dict(official=self.target.pk, item=self.item.pk, date=self.today.isoformat(),
                    record_type=Activity.RecordType.FIELD, action_description='Visita validada')
        data.update(changes)
        return data

    def mutate(self, operation, activity=None, **kwargs):
        return self.client.post(reverse('activity_'+operation, args=[(activity or self.activity).pk]), **kwargs)


@override_settings(PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'], ALLOWED_HOSTS=['localhost','testserver'])
class ActivityCompletionTests(ActivityFixture, TestCase):
    def test_editor_has_complete_create_detail_edit_modal_flow_without_archival(self):
        self.client.force_login(self.users['editor'])
        response = self.client.get(reverse('activity_create'), HTTP_X_MODAL_REQUEST='true')
        self.assertEqual(response.status_code, 200)
        self.assertIsInstance(response.context['form'], forms.ModelForm)
        response = self.client.post(reverse('activity_create'), self.payload(), HTTP_X_MODAL_REQUEST='true')
        self.assertEqual(response.status_code, 204)
        created = Activity.objects.get(action_description='Visita validada')
        detail = self.client.get(reverse('activity_detail', args=[created.pk]))
        self.assertEqual(detail.status_code, 200)
        self.assertContains(detail, reverse('activity_update', args=[created.pk]))
        self.assertNotContains(detail, reverse('activity_deactivate', args=[created.pk]))
        response = self.client.post(reverse('activity_update', args=[created.pk]),
            self.payload(action_description='Descripción editada'), HTTP_X_MODAL_REQUEST='true')
        self.assertEqual(response.status_code, 204)
        created.refresh_from_db()
        self.assertEqual(created.action_description, 'Descripción editada')
        self.assertTrue(AuditLog.objects.filter(action='Actividades: update', affected_record_id=created.pk).exists())

    def test_invalid_required_date_type_and_foreign_relations_do_not_write(self):
        self.client.force_login(self.users['editor'])
        inactive = Item.objects.create(item_name='Ítem inactivo', is_active=False)
        cases = ({'official':''}, {'item':''}, {'date':'inexistente'}, {'date':(self.today+timedelta(days=20)).isoformat()},
                 {'official':self.foreign.pk}, {'item':inactive.pk}, {'record_type':Activity.RecordType.ATTENTION})
        before = Activity.objects.count()
        for changes in cases:
            with self.subTest(changes=changes):
                response = self.client.post(reverse('activity_create'), self.payload(**changes), HTTP_X_MODAL_REQUEST='true')
                self.assertEqual(response.status_code, 200)
                self.assertTrue(response.context['form'].errors)
                self.assertEqual(response.context['form']['action_description'].value(), 'Visita validada')
                self.assertEqual(Activity.objects.count(), before)

    def test_editor_and_readers_cannot_archive_restore_or_query_archived(self):
        for name in ('editor','readerA','readerB'):
            self.client.force_login(self.users[name])
            for operation, obj in (('deactivate', self.activity), ('activate', self.archived)):
                self.assertEqual(self.mutate(operation, obj).status_code, 403)
            self.assertEqual(self.client.get(reverse('activity_maintainer'), {'status':'INACTIVE'}).status_code, 403)
            self.assertEqual(self.client.get(reverse('activity_detail', args=[self.archived.pk])).status_code, 404)
        self.activity.refresh_from_db(); self.archived.refresh_from_db()
        self.assertIsNone(self.activity.deleted_at)
        self.assertIsNotNone(self.archived.deleted_at)

    def test_regular_list_and_excel_always_exclude_archived_and_other_scope(self):
        for name in ('admin','editor','readerA'):
            self.client.force_login(self.users[name])
            response = self.client.get(reverse('activity_maintainer'))
            self.assertEqual({obj.pk for obj in response.context['page_obj'].object_list}, {self.activity.pk})
            export = self.client.get(reverse('activity_export'))
            self.assertEqual(export.status_code, 200)
            rows = list(load_workbook(BytesIO(export.content)).active.values)
            self.assertEqual(len(rows), 2)
            self.assertEqual(rows[1][0], self.activity.code)

    def test_filtered_export_includes_all_pages_and_state_survives_detail_and_archive(self):
        for _ in range(31):
            Activity.objects.create(official=self.target, item=self.item, date=self.today, record_type=Activity.RecordType.FIELD)
        Activity.objects.create(official=self.target, item=self.other_item, date=self.today, record_type=Activity.RecordType.MONTHLY)
        url = reverse('activity_maintainer')
        params = dict(q='Visita', official=self.target.pk, item=self.item.pk,
                      record_type=Activity.RecordType.FIELD, date_from=self.today.isoformat(),
                      date_to=self.today.isoformat(), page_size=5, sort='code', direction='asc')
        self.client.get(url, params)
        page = self.client.get(url, {'page':7})
        self.assertEqual(page.context['page_obj'].paginator.count, 32)
        last_rows = list(page.context['page_obj'].object_list)
        self.client.get(reverse('activity_detail', args=[last_rows[0].pk]))
        self.assertEqual(self.client.get(url).context['page_obj'].number, 7)
        for obj in last_rows:
            self.assertEqual(self.mutate('deactivate', obj).status_code, 302)
        page = self.client.get(url)
        self.assertEqual(page.context['page_obj'].number, 6)
        self.assertEqual(page.context['page_obj'].paginator.count, 30)
        self.assertEqual(page.context['selected_sort'], 'code')
        self.assertEqual(page.context['query'], 'Visita')
        export = self.client.get(reverse('activity_export'))
        self.assertEqual(export.status_code, 200)
        rows = list(load_workbook(BytesIO(export.content)).active.values)
        self.assertEqual(len(rows), 31)
        self.assertEqual([row[0] for row in rows[1:]], sorted(row[0] for row in rows[1:]))
        self.assertFalse({obj.code for obj in last_rows} & {row[0] for row in rows[1:]})

    def test_archive_and_restore_preserve_record_and_history(self):
        self.assertEqual(self.mutate('deactivate').status_code, 302)
        self.activity.refresh_from_db()
        self.assertIsNotNone(self.activity.deleted_at)
        self.assertEqual(self.activity.action_description, 'Visita de demostración')
        history = self.client.get(reverse('activity_maintainer'), {'status':'INACTIVE'})
        self.assertContains(history, reverse('activity_activate', args=[self.activity.pk]))
        self.assertNotContains(history, reverse('activity_update', args=[self.activity.pk]))
        self.assertEqual(self.client.get(reverse('activity_detail', args=[self.activity.pk])).status_code, 200)
        self.assertEqual(self.mutate('activate').status_code, 302)
        self.activity.refresh_from_db()
        self.assertIsNone(self.activity.deleted_at)
        self.assertTrue(AuditLog.objects.filter(action='Actividades: deactivate', affected_record_id=self.activity.pk).exists())
        self.assertTrue(AuditLog.objects.filter(action='Actividades: activate', affected_record_id=self.activity.pk).exists())

    def test_archived_history_cannot_be_exported(self):
        response = self.client.get(reverse('activity_export'), {'status':'INACTIVE'})
        self.assertEqual(response.status_code, 302)
        self.assertNotIn('Content-Disposition', response)

    def test_archived_activity_cannot_be_edited_or_archived_again(self):
        response = self.client.post(reverse('activity_update', args=[self.archived.pk]), self.payload())
        self.assertEqual(response.status_code, 404)
        self.assertEqual(self.mutate('deactivate', self.archived).status_code, 404)
        self.assertEqual(self.mutate('activate').status_code, 404)

    def test_archive_restore_require_post_and_csrf(self):
        for op, obj in (('deactivate',self.activity), ('activate',self.archived)):
            url = reverse('activity_'+op, args=[obj.pk])
            self.assertEqual(self.client.get(url).status_code, 405)
            secured = Client(enforce_csrf_checks=True)
            secured.force_login(self.users['admin'])
            self.assertEqual(secured.post(url).status_code, 403)
            page = secured.get(reverse('activity_detail', args=[obj.pk]))
            self.assertEqual(secured.post(url, HTTP_X_CSRFTOKEN=page.cookies['csrftoken'].value).status_code, 302)

    def test_foreign_detail_update_archive_and_restore_are_rejected(self):
        self.assertEqual(self.client.get(reverse('activity_detail',args=[self.foreign_activity.pk])).status_code, 404)
        self.assertEqual(self.mutate('deactivate', self.foreign_activity).status_code, 404)
        self.foreign_activity.deleted_at=timezone.now(); self.foreign_activity.save()
        self.assertEqual(self.mutate('activate', self.foreign_activity).status_code, 404)

    def test_archive_permission_scope_is_enforced_in_actions_and_history(self):
        role = Role.objects.get(role_name='Perfil admin')
        role.permissions.remove(Permission.objects.get(codename='archive_activity'))
        own_role = Role.objects.create(role_name='Archivo propio', scope=Role.Scope.OWN)
        own_role.permissions.add(Permission.objects.get(codename='archive_activity'))
        self.users['admin'].official.roles.add(own_role)
        response = self.client.get(reverse('activity_maintainer'))
        self.assertNotContains(response, reverse('activity_deactivate',args=[self.activity.pk]))
        self.assertEqual(self.mutate('deactivate').status_code, 404)
        self.assertEqual(self.client.get(reverse('activity_detail',args=[self.archived.pk])).status_code, 404)
        history = self.client.get(reverse('activity_maintainer'), {'status':'INACTIVE'})
        self.assertEqual(history.context['total'], 0)

    def test_closed_period_prevents_edit_archive_and_restore(self):
        self.period.close_period()
        for operation, obj in (('deactivate', self.activity), ('activate', self.archived)):
            response = self.mutate(operation, obj, follow=True)
            self.assertContains(response, 'período cerrado')
        response = self.client.post(reverse('activity_update',args=[self.activity.pk]),self.payload(action_description='No guardar'))
        self.activity.refresh_from_db(); self.archived.refresh_from_db()
        self.assertIsNone(self.activity.deleted_at)
        self.assertIsNotNone(self.archived.deleted_at)
        self.assertNotEqual(self.activity.action_description, 'No guardar')

    def test_social_attention_activity_is_readonly(self):
        kind=AttentionType.objects.create(name='Social', activity_item=self.item)
        sub=SubattentionType.objects.create(name='Orientación', attention_type=kind)
        recipient=ServiceRecipient.objects.create(full_name='Persona ficticia', national_id='12345678-5')
        SocialAttention.objects.create(activity=self.activity, recipient=recipient, attention_type=kind,
            subattention_type=sub, delegation=self.a, responsible=self.target, date=self.today)
        self.assertEqual(self.mutate('deactivate').status_code, 302)
        self.activity.refresh_from_db()
        self.assertIsNone(self.activity.deleted_at)
        detail=self.client.get(reverse('activity_detail',args=[self.activity.pk]))
        self.assertNotContains(detail, reverse('activity_update',args=[self.activity.pk]))
        self.assertNotContains(detail, reverse('activity_deactivate',args=[self.activity.pk]))

    def test_editor_cannot_grant_archive_activity_via_official_role(self):
        role=Role.objects.create(role_name='Archivo restringido')
        role.permissions.add(Permission.objects.get(codename='archive_activity'))
        self.client.force_login(self.users['editor'])
        response=self.client.post(reverse('official_update',args=[self.target.pk]),self.edit_payload(roles=[role.pk]))
        self.assertEqual(response.status_code, 403)
        self.assertFalse(self.target.roles.filter(pk=role.pk).exists())

    def test_failed_audit_rolls_back_archive(self):
        with patch('common.maintainers.AuditoriaService.register_change', side_effect=RuntimeError('fallo simulado')):
            with self.assertRaises(RuntimeError): self.mutate('deactivate')
        self.activity.refresh_from_db()
        self.assertIsNone(self.activity.deleted_at)

    def test_revoked_history_permission_does_not_trap_saved_session(self):
        self.client.get(reverse('activity_maintainer'), {'status':'INACTIVE'})
        role=Role.objects.get(role_name='Perfil admin')
        role.permissions.remove(Permission.objects.get(codename='archive_activity'))
        response=self.client.get(reverse('activity_maintainer'))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['selected_status'], '')
        self.assertEqual(response.context['total'], 1)


@override_settings(PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'], ALLOWED_HOSTS=['localhost','testserver'])
class ActivityArchiveRealtimeTests(ActivityFixture, TransactionTestCase):
    def test_committed_archive_refreshes_reader_not_foreign_and_restore_notifies_again(self):
        async def scenario():
            sockets=[]
            try:
                for name in ('readerA','readerB'):
                    client=Client()
                    await database_sync_to_async(client.force_login)(self.users[name])
                    cookie=client.cookies[settings.SESSION_COOKIE_NAME].value
                    socket=WebsocketCommunicator(application,'/ws/activities/',headers=[
                        (b'origin',b'http://localhost'), (b'cookie',f'{settings.SESSION_COOKIE_NAME}={cookie}'.encode())])
                    self.assertTrue((await socket.connect())[0]); sockets.append(socket)
                def rollback():
                    with transaction.atomic():
                        self.mutate('deactivate'); transaction.set_rollback(True)
                await database_sync_to_async(rollback)()
                for socket in sockets:self.assertTrue(await socket.receive_nothing(timeout=.05))
                for op in ('deactivate','activate'):
                    self.assertEqual((await database_sync_to_async(self.mutate)(op)).status_code,302)
                    self.assertEqual(await sockets[0].receive_json_from(),{'type':'activities.changed'})
                    self.assertTrue(await sockets[1].receive_nothing(timeout=.05))
            finally:
                for socket in sockets:await socket.disconnect()
        async_to_sync(scenario)()
