"""
URL configuration for config project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/6.1/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.urls import path, reverse_lazy
from django.views.generic import RedirectView
from .views import AttentionDetailView, AttentionEntryView, AttentionRequestLookupView

urlpatterns = []
urlpatterns += [
    path('solicitudes/', RedirectView.as_view(
        url=reverse_lazy('activity_maintainer', query={
            'record_source': 'request', 'status': '', 'official': '', 'item': '', 'record_type': '',
        }),
    ), name='activity_requests'),
    path('atenciones/nueva/', AttentionEntryView.as_view(), name='attention_entry'),
    path('atenciones/buscar-solicitudes/', AttentionRequestLookupView.as_view(), name='attention_request_lookup'),
    path('atenciones/<int:pk>/', AttentionDetailView.as_view(), name='attention_detail'),
]

from common.maintainers import maintainer_urls
urlpatterns += maintainer_urls('activity', '')
