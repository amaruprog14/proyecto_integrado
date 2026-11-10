"""Cobertura de todos los listados con la matriz de cuentas y ámbitos del SGR."""
from common.testing_seed import seed_test_data
import os
import uuid
from asgiref.sync import async_to_sync, sync_to_async
from channels.testing import WebsocketCommunicator
from django.conf import settings
from django.contrib.auth.models import User
from django.core.management import call_command
from django.test import Client, TransactionTestCase, override_settings
from django.urls import reverse

from common.realtime import MODELS, ROUTES, can_read, queryset
from config.asgi import application


@override_settings(ALLOWED_HOSTS=['localhost', 'testserver'])
class AllMaintainersRealtimeTests(TransactionTestCase):
    def setUp(self):
        fixture = os.environ.get('REALTIME_ACCOUNT_FIXTURE')
        if fixture:
            call_command('loaddata', fixture, verbosity=0)
            from accounts.models import Official
            from activities.models import Activity
            from configuration.models import Item, Period, AttentionType, SubattentionType
            from django.utils import timezone
            item = Item.objects.create(item_name='Ítem de comprobación')
            Period.objects.create(start_date=timezone.localdate(), end_date=timezone.localdate())
            attention = AttentionType.objects.create(name='Tipo de comprobación')
            SubattentionType.objects.create(name='Subtipo de comprobación', attention_type=attention)
            Activity.objects.create(official=Official.objects.filter(user__is_superuser=True).first(),
                item=item, date=timezone.localdate(), record_type=Activity.RecordType.FIELD)
        else:
            seed_test_data()
        from accounts.models import Territory, Delegation, ServiceRecipient
        from activities.models import ClientRequest
        from configuration.models import SubattentionType
        delegation = Delegation.objects.get(delegation_name="Sur")
        territory = Territory.objects.create(territory_name="Territorio de prueba", delegation=delegation)
        recipient = ServiceRecipient.objects.create(national_id="12345678-5", full_name="Persona de prueba", territory=territory)
        subtype = SubattentionType.objects.first()
        ClientRequest.objects.create(recipient=recipient, delegation=delegation, territory=territory,
            attention_type=subtype.attention_type, subattention_type=subtype, subject="Solicitud de prueba",
            submission_token=uuid.uuid4())
        self.clients = {}
        for user in User.objects.all():
            client = Client()
            client.force_login(user)
            self.clients[user.pk] = client

    def socket(self, key, user):
        cookie = self.clients[user.pk].cookies[settings.SESSION_COOKIE_NAME].value
        return WebsocketCommunicator(application, f'/ws/maintainers/{key}/', headers=[
            (b'origin', b'http://localhost'),
            (b'cookie', f'{settings.SESSION_COOKIE_NAME}={cookie}'.encode()),
        ])

    def test_all_modules_all_accounts_and_rendered_connections(self):
        # Solo se editan copias aisladas; no se cambia ningún permiso para lograr acceso.
        users = list(User.objects.all())
        for key, model in MODELS.items():
            obj = model.objects.first()
            if obj is None:
                self.fail(f'Falta un registro de prueba de {key}')
            if key == 'official':
                obj = model.objects.filter(user=None, deleted_at__isnull=True).first() or obj
            fields = dict(territory='territory_name', activity='record_type', official='full_name', delegation='delegation_name',
                user='username', role='role_name', area='area_name', position='position_name',
                group='name', period='status', item='item_name', attention_type='name', subattention_type='name',
                staff_request='subject')
            field = fields[key]
            old_value = getattr(obj, field)
            new_value = ('Registro mensual' if old_value != 'Registro mensual' else 'Terreno') if key == 'activity' else ('CLOSED' if old_value != 'CLOSED' else 'OPEN') if key == 'period' else f'{old_value} WS'
            if key == 'user':
                new_value = old_value + '_ws'
            expected = {}
            visible_http = {}
            for user in users:
                with self.subTest(module=key, account=user.username, phase='HTTP'):
                    allowed = can_read(user, key)
                    response = self.clients[user.pk].get(reverse(ROUTES[key]))
                    self.assertEqual(response.status_code, 200 if allowed else 403)
                    if allowed:
                        self.assertContains(response, f'data-maintainer-websocket="/ws/maintainers/{key}/"')
                        self.assertContains(response, 'data-live-region="table"')
                        self.assertContains(response, 'data-live-region="footer"')
                        self.assertContains(response, 'data-live-search')
                        self.assertContains(response, 'js/maintainer-states.js')
                    expected[user.pk] = allowed and queryset(key, user).filter(pk=obj.pk).exists()
                    visible_http[user.pk] = allowed and str(old_value).encode() in response.content

            async def scenario():
                connections = []
                try:
                    for user in users:
                        socket = self.socket(key, user)
                        connected, _ = await socket.connect()
                        self.assertEqual(connected, await sync_to_async(can_read)(user, key), (key, user.username))
                        connections.append((user, socket, connected))
                    setattr(obj, field, new_value)
                    await sync_to_async(obj.save)()
                    for user, socket, connected in connections:
                        if not connected:
                            continue
                        if expected[user.pk]:
                            msg = await socket.receive_json_from(timeout=3)
                            self.assertEqual(msg, {'type': 'activities.changed' if key == 'activity' else 'maintainer.changed'})
                        else:
                            # Una edición del contexto propio puede ordenar una reautorización.
                            own_context = (key == 'user' and obj.pk == user.pk)
                            if not own_context:
                                self.assertTrue(await socket.receive_nothing(timeout=.05), (key, user.username))
                        if visible_http[user.pk] and key not in ('period', 'activity'):
                            response = await sync_to_async(self.clients[user.pk].get)(reverse(ROUTES[key]))
                            self.assertContains(response, new_value)
                finally:
                    for _, socket, _ in connections:
                        await socket.disconnect()
            async_to_sync(scenario)()

    def test_staff_request_notice_only_reaches_its_delegation_after_commit(self):
        from accounts.models import Delegation, Official
        from activities.models import ClientRequest
        from django.contrib.auth.models import Permission
        from django.db import transaction

        item = ClientRequest.objects.get(subject="Solicitud de prueba")
        permission = Permission.objects.get(content_type__app_label="activities", codename="view_socialattention")
        users = []
        for index, delegation in enumerate((item.delegation, Delegation.objects.get(delegation_name="Norte"))):
            user = User.objects.create_user(f"lector-solicitud-{index}")
            Official.objects.create(user=user, full_name="Lector de solicitudes",
                national_id=f"lector-solicitud-{index}", email=f"lector-solicitud-{index}@example.test",
                delegation=delegation)
            user.user_permissions.add(permission)
            self.clients[user.pk] = Client()
            self.clients[user.pk].force_login(user)
            users.append(user)

        def save_request(commit):
            with transaction.atomic():
                item.status = ClientRequest.Status.REVIEW
                item.save(update_fields=["status"])
                if not commit:
                    transaction.set_rollback(True)

        async def scenario():
            own, foreign = (self.socket("staff_request", user) for user in users)
            try:
                self.assertTrue((await own.connect())[0])
                self.assertTrue((await foreign.connect())[0])
                await sync_to_async(save_request)(False)
                self.assertTrue(await own.receive_nothing(timeout=.1))
                await sync_to_async(save_request)(True)
                self.assertEqual(await own.receive_json_from(timeout=3), {"type": "maintainer.changed"})
                self.assertTrue(await foreign.receive_nothing(timeout=.1))
            finally:
                await own.disconnect()
                await foreign.disconnect()

        async_to_sync(scenario)()

    def test_creation_is_published_only_after_commit_and_not_rollback(self):
        from django.db import transaction
        from accounts.models import Official, Delegation
        users = list(User.objects.all())
        delegation = Delegation.objects.get(delegation_name='Sur')
        def create(rollback=False):
            with transaction.atomic():
                obj = Official.objects.create(full_name='Prueba nueva Sur', national_id='ws-nuevo',
                    email='nuevo-ws@example.test', delegation=delegation)
                if rollback:
                    transaction.set_rollback(True)
                return obj.pk
        async def scenario():
            connections = []
            try:
                for user in users:
                    socket = self.socket('official', user)
                    connected, _ = await socket.connect()
                    connections.append((user, socket, connected))
                await sync_to_async(create)(True)
                for _, socket, connected in connections:
                    if connected:
                        self.assertTrue(await socket.receive_nothing(timeout=.05))
                pk = await sync_to_async(create)()
                for user, socket, connected in connections:
                    if not connected:
                        continue
                    visible = await sync_to_async(lambda u=user: queryset('official', u).filter(pk=pk).exists())()
                    if visible:
                        self.assertEqual(await socket.receive_json_from(), {'type': 'maintainer.changed'})
                    else:
                        self.assertTrue(await socket.receive_nothing(timeout=.05), user.username)
            finally:
                for _, socket, _ in connections:
                    await socket.disconnect()
        async_to_sync(scenario)()

    def test_permission_loss_closes_the_reader_without_manual_notification(self):
        from django.contrib.auth.models import Permission
        user = User.objects.get(username='consulta_norte')
        role = user.official.roles.get(role_name='Consulta')
        view = Permission.objects.get(content_type__app_label='accounts', codename='view_official')
        async def scenario():
            socket = self.socket('official', user)
            try:
                self.assertTrue((await socket.connect())[0])
                await sync_to_async(role.permissions.remove)(view)
                message = await socket.receive_output(timeout=3)
                self.assertEqual(message, {'type': 'websocket.close', 'code': 4403})
            finally:
                await socket.disconnect()
        async_to_sync(scenario)()

    def test_write_permission_context_does_not_change_reader_scope(self):
        from common.scopes import current_permission
        from django.contrib.auth.models import Permission
        from accounts.models import Official, Role
        user = User.objects.get(username='consulta_norte')
        role = Role.objects.create(role_name='Consulta transversal de prueba', scope=Role.Scope.ALL)
        role.permissions.add(Permission.objects.get(content_type__app_label='accounts', codename='view_official'))
        user.official.roles.add(role)
        token = current_permission.set('accounts.change_official')
        try:
            self.assertEqual(queryset('official', user).count(), Official.objects.filter(deleted_at=None).count())
            self.assertEqual(current_permission.get(), 'accounts.change_official')
        finally:
            current_permission.reset(token)
