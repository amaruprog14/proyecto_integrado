from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncJsonWebsocketConsumer
from django.contrib.auth import get_user_model, HASH_SESSION_KEY
from django.contrib.sessions.models import Session
from django.utils import timezone
from django.utils.crypto import constant_time_compare

from common.realtime import can_read, group_name, subscribe, unsubscribe


class MaintainerListConsumer(AsyncJsonWebsocketConsumer):
    module = None
    @database_sync_to_async
    def authorized(self):
        session_key = self.scope['session'].session_key
        session = Session.objects.filter(session_key=session_key, expire_date__gt=timezone.now()).first()
        if not session:
            return False
        data = session.get_decoded()
        user = get_user_model().objects.filter(pk=data.get('_auth_user_id')).first()
        if not user or not constant_time_compare(data.get(HASH_SESSION_KEY, ''), user.get_session_auth_hash()):
            return False
        if not can_read(user, self.module):
            return False
        modules = [self.module]
        if self.module == 'activity' and can_read(user, 'staff_request'):
            modules.append('staff_request')
        return user.pk, modules

    async def update_subscriptions(self, modules):
        for module in self.joined.keys() - set(modules):
            unsubscribe(self.user_id, module)
            await self.channel_layer.group_discard(self.joined.pop(module), self.channel_name)
        for module in set(modules) - self.joined.keys():
            group = group_name(self.user_id, module)
            await self.channel_layer.group_add(group, self.channel_name)
            subscribe(self.user_id, module)
            self.joined[module] = group

    async def connect(self):
        from common.realtime import MODELS
        self.module = self.module or self.scope['url_route']['kwargs']['module']
        if self.module not in MODELS:
            await self.close(code=4404)
            return
        authorization = await self.authorized()
        self.joined = {}
        if not authorization:
            await self.close(code=4403)
            return
        self.user_id, modules = authorization
        await self.update_subscriptions(modules)
        await self.accept()

    async def disconnect(self, code):
        if getattr(self, 'joined', None):
            await self.update_subscriptions(())

    async def receive_json(self, content, **kwargs):
        # La conexión solo recibe avisos: no acepta suscripciones del navegador.
        await self.close(code=4400)

    async def maintainer_changed(self, event):
        authorization = await self.authorized()
        if not authorization or authorization[0] != self.user_id:
            await self.close(code=4403)
            return
        await self.update_subscriptions(authorization[1])
        await self.send_json({'type': 'activities.changed' if self.module == 'activity' else 'maintainer.changed'})

    activities_changed = maintainer_changed


class ActivityListConsumer(MaintainerListConsumer):
    module = 'activity'
