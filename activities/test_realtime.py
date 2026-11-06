from asgiref.sync import async_to_sync, sync_to_async
from channels.testing import WebsocketCommunicator
from django.conf import settings
from django.contrib.auth.models import User, Permission, Group
from django.db import transaction
from django.test import Client, TransactionTestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.models import Official, Delegation, Role, GroupProfile
from activities.models import Activity
from configuration.models import Item, Period
from config.asgi import application


@override_settings(ALLOWED_HOSTS=['localhost', 'testserver'])
class ActivityRealtimeTests(TransactionTestCase):
    def test_socket_refresh_keeps_state_and_clamps_removed_last_page(self):
        for _ in range(6):
            Activity.objects.create(official=self.users[0].official, item=self.item,
                date=self.today, record_type=Activity.RecordType.FIELD)
        url = reverse('activity_maintainer')
        self.clients[1].get(url, {'page_size': 5, 'sort': 'code', 'direction': 'asc',
            'status': 'ACTIVE', 'record_type': Activity.RecordType.FIELD})
        response = self.clients[1].get(url, {'page': 2})
        last_page = list(response.context['page_obj'].object_list)
        self.assertEqual(response.context['page_obj'].number, 2)

        def archive_last_page():
            with transaction.atomic():
                for obj in last_page:
                    obj.deleted_at = timezone.now()
                    obj.save()

        async def scenario():
            reader, outsider = self.socket(), self.socket(2)
            try:
                await reader.connect()
                await outsider.connect()
                await sync_to_async(archive_last_page)()
                self.assertEqual(await reader.receive_json_from(), {'type': 'activities.changed'})
                self.assertTrue(await outsider.receive_nothing(timeout=.1))
                refreshed = await sync_to_async(self.clients[1].get)(url, HTTP_X_LIVE_SEARCH='1')
                self.assertEqual(refreshed.context['page_obj'].number, 1)
                self.assertEqual(refreshed.context['page_obj'].paginator.per_page, 5)
                self.assertEqual(refreshed.context['selected_sort'], 'code')
                self.assertEqual(refreshed.context['selected_direction'], 'asc')
                self.assertEqual(refreshed.context['selected_status'], 'ACTIVE')
                self.assertIn('page=1', refreshed['X-List-URL'])
            finally:
                await reader.disconnect()
                await outsider.disconnect()
        async_to_sync(scenario)()

    def setUp(self):
        self.a = Delegation.objects.create(delegation_name='A')
        self.b = Delegation.objects.create(delegation_name='B')
        self.role = Role.objects.create(role_name='Lector', scope=Role.Scope.DELEGATION)
        self.role.permissions.add(Permission.objects.get(codename='view_activity'))
        self.users = []
        self.clients = []
        for i, delegation in enumerate([self.a, self.a, self.b]):
            user = User.objects.create_user(f'ws{i}', password='Websocket-123')
            official = Official.objects.create(user=user, full_name=f'Persona {i}',
                email=f'ws{i}@example.test', national_id=f'ws-{i}', delegation=delegation)
            official.roles.add(self.role)
            client = Client()
            client.force_login(user)
            self.users.append(user)
            self.clients.append(client)
        editor = Role.objects.create(role_name='Editor', scope=Role.Scope.DELEGATION)
        editor.permissions.add(*Permission.objects.filter(codename__in=['add_activity', 'change_activity']))
        self.users[0].official.roles.add(editor)
        self.item = Item.objects.create(item_name='Trabajo')
        self.today = timezone.localdate()
        Period.objects.create(start_date=self.today, end_date=self.today)
        self.activity = Activity.objects.create(official=self.users[0].official,
            item=self.item, date=self.today, record_type=Activity.RecordType.FIELD)

    def socket(self, index=1, origin=b'http://localhost'):
        headers = [(b'origin', origin)]
        if index is not None:
            value = self.clients[index].cookies[settings.SESSION_COOKIE_NAME].value
            headers.append((b'cookie', f'{settings.SESSION_COOKIE_NAME}={value}'.encode()))
        return WebsocketCommunicator(application, '/ws/activities/', headers=headers)

    def payload(self, **extra):
        return dict(official=self.users[0].official.pk, item=self.item.pk,
            date=self.today.isoformat(), record_type=Activity.RecordType.FIELD, **extra)

    def test_editor_updates_only_authorized_reader_after_http_save(self):
        async def scenario():
            a, b = self.socket(), self.socket(2)
            self.assertTrue((await a.connect())[0])
            self.assertTrue((await b.connect())[0])
            response = await sync_to_async(self.clients[0].post)(
                reverse('activity_update', args=[self.activity.pk]),
                self.payload(action_description='Actualizada'))
            self.assertEqual(response.status_code, 302)
            self.assertEqual(await a.receive_json_from(), {'type': 'activities.changed'})
            self.assertTrue(await b.receive_nothing(timeout=.15))
            await a.disconnect()
            await b.disconnect()
        async_to_sync(scenario)()
        self.activity.refresh_from_db()
        self.assertEqual(self.activity.action_description, 'Actualizada')

    def test_invalid_form_rollback_and_forbidden_save_emit_nothing(self):
        def rollback():
            try:
                with transaction.atomic():
                    self.activity.action_description = 'No debe persistir'
                    self.activity.save()
                    raise ValueError()
            except ValueError:
                pass
        async def scenario():
            reader = self.socket()
            await reader.connect()
            await sync_to_async(self.clients[0].post)(reverse('activity_create'), {})
            response = await sync_to_async(self.clients[1].post)(reverse('activity_create'), self.payload())
            self.assertEqual(response.status_code, 403)
            await sync_to_async(rollback)()
            self.assertTrue(await reader.receive_nothing(timeout=.15))
            await reader.disconnect()
        async_to_sync(scenario)()

    def test_anonymous_and_foreign_origin_rejected(self):
        async def scenario():
            for socket in [self.socket(None), self.socket(origin=b'http://evil.example')]:
                self.assertFalse((await socket.connect())[0])
                await socket.disconnect()
        async_to_sync(scenario)()

    def test_revoked_permission_and_logout_close_existing_connection(self):
        async def scenario():
            reader = self.socket()
            await reader.connect()
            await sync_to_async(self.clients[1].logout)()
            from channels.layers import get_channel_layer
            from activities.realtime import group_name
            await get_channel_layer().group_send(group_name(self.users[1].pk), {'type': 'activities.changed'})
            message = await reader.receive_output()
            self.assertEqual(message['type'], 'websocket.close')
            self.assertEqual(message['code'], 4403)
            await reader.disconnect()
        async_to_sync(scenario)()

    def test_permission_revocation_rejected_even_with_cached_socket(self):
        async def scenario():
            reader = self.socket()
            await reader.connect()
            await sync_to_async(self.role.permissions.clear)()
            from channels.layers import get_channel_layer
            from activities.realtime import group_name
            await get_channel_layer().group_send(group_name(self.users[1].pk), {'type': 'activities.changed'})
            self.assertEqual((await reader.receive_output())['code'], 4403)
            await reader.disconnect()
            rejected = self.socket()
            self.assertFalse((await rejected.connect())[0])
            await rejected.disconnect()
        async_to_sync(scenario)()

    def test_additional_delegations_and_group_permissions(self):
        self.users[2].official.authorized_delegations.add(self.a)
        self.users[2].official.roles.clear()
        group = Group.objects.create(name='Consulta')
        GroupProfile.objects.update_or_create(group=group, defaults={'scope': Role.Scope.DELEGATION})
        group.permissions.add(Permission.objects.get(codename='view_activity'))
        self.users[2].groups.add(group)
        async def scenario():
            reader = self.socket(2)
            self.assertTrue((await reader.connect())[0])
            await sync_to_async(self.activity.save)()
            self.assertEqual(await reader.receive_json_from(), {'type': 'activities.changed'})
            await reader.disconnect()
        async_to_sync(scenario)()

    def test_move_refreshes_old_and_new_readers(self):
        async def scenario():
            a, b = self.socket(), self.socket(2)
            await a.connect()
            await b.connect()
            self.activity.official = self.users[2].official
            await sync_to_async(self.activity.save)()
            self.assertEqual(await a.receive_json_from(), {'type': 'activities.changed'})
            self.assertEqual(await b.receive_json_from(), {'type': 'activities.changed'})
            await a.disconnect()
            await b.disconnect()
        async_to_sync(scenario)()
        self.assertNotContains(self.clients[1].get(reverse('activity_maintainer')), self.activity.code)
        self.assertContains(self.clients[2].get(reverse('activity_maintainer')), self.activity.code)

    def test_own_scope_does_not_receive_other_official_activity(self):
        own = Role.objects.create(role_name='Propio', scope=Role.Scope.OWN)
        own.permissions.add(Permission.objects.get(codename='view_activity'))
        self.users[1].official.roles.set([own])
        async def scenario():
            reader = self.socket()
            await reader.connect()
            await sync_to_async(self.activity.save)()
            self.assertTrue(await reader.receive_nothing(timeout=.15))
            self.activity.official = self.users[1].official
            await sync_to_async(self.activity.save)()
            self.assertEqual(await reader.receive_json_from(), {'type': 'activities.changed'})
            await reader.disconnect()
        async_to_sync(scenario)()

    def test_create_archive_restore_events_and_filtered_http(self):
        async def scenario():
            reader = self.socket()
            await reader.connect()
            for url, data in [
                (reverse('activity_create'), self.payload()),
                (reverse('activity_deactivate', args=[self.activity.pk]), {}),
                (reverse('activity_activate', args=[self.activity.pk]), {}),
            ]:
                self.assertEqual((await sync_to_async(self.clients[0].post)(url, data)).status_code, 302)
                self.assertEqual(await reader.receive_json_from(), {'type': 'activities.changed'})
            await reader.disconnect()
        async_to_sync(scenario)()
        response = self.clients[1].get(reverse('activity_maintainer'), {'status': 'INACTIVE'})
        self.assertEqual(response.context['total'], 0)

    def test_no_subscription_from_browser(self):
        async def scenario():
            reader = self.socket()
            await reader.connect()
            await reader.send_json_to({'delegation': self.b.pk})
            self.assertEqual((await reader.receive_output())['code'], 4400)
            await reader.disconnect()
        async_to_sync(scenario)()

    def test_http_refresh_keeps_filters_size_and_clamps_removed_page(self):
        for _ in range(5):
            Activity.objects.create(official=self.users[0].official, item=self.item,
                date=self.today, record_type=Activity.RecordType.FIELD)
        params = {'record_type': Activity.RecordType.FIELD, 'status': 'ACTIVE', 'page_size': 5, 'page': 2}
        response = self.clients[1].get(reverse('activity_maintainer'), params)
        self.assertEqual(response.context['page_obj'].number, 2)
        self.assertEqual(response.context['page_obj'].paginator.per_page, 5)
        last = response.context['page_obj'].object_list[0]
        last.deleted_at = timezone.now()
        last.save()
        response = self.clients[1].get(reverse('activity_maintainer'), params)
        self.assertEqual(response.context['page_obj'].number, 1)
        self.assertEqual(response.context['total'], 5)
        self.assertContains(response, 'data-current-page="1"')

    def test_archived_official_rejected(self):
        self.users[1].official.deleted_at = timezone.now()
        self.users[1].official.save(update_fields=['deleted_at'])
        async def scenario():
            rejected = self.socket()
            self.assertFalse((await rejected.connect())[0])
            await rejected.disconnect()
        async_to_sync(scenario)()
