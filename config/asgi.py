"""
ASGI config for config project.

It exposes the ASGI callable as a module-level variable named ``application``.

For more information on this file, see
https://docs.djangoproject.com/en/6.1/howto/deployment/asgi/
"""

import os

from django.core.asgi import get_asgi_application

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')

django_application = get_asgi_application()

from channels.auth import AuthMiddlewareStack
from channels.routing import ProtocolTypeRouter, URLRouter
from channels.security.websocket import AllowedHostsOriginValidator
from django.urls import path
from activities.consumers import ActivityListConsumer, MaintainerListConsumer

application = ProtocolTypeRouter({
    'http': django_application,
    'websocket': AllowedHostsOriginValidator(AuthMiddlewareStack(URLRouter([
        path('ws/activities/', ActivityListConsumer.as_asgi()),
        path('ws/maintainers/<slug:module>/', MaintainerListConsumer.as_asgi()),
    ]))),
})
