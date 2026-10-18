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
from django.urls import path

from .item_views import (
    ItemActivateView,
    ItemCreateView,
    ItemDeactivateView,
    ItemDetailView,
    ItemExportView,
    ItemListView,
    ItemUpdateView,
)
from .views import (
    AttentionTypeMaintainerView,
    PeriodMaintainerView,
    SubattentionTypeMaintainerView,
)

urlpatterns = []
urlpatterns += [
    path('items/', ItemListView.as_view(), name='item_maintainer'),
    path('items/exportar/', ItemExportView.as_view(), name='item_export'),
    path('items/nuevo/', ItemCreateView.as_view(), name='item_create'),
    path('items/<int:pk>/', ItemDetailView.as_view(), name='item_detail'),
    path('items/<int:pk>/editar/', ItemUpdateView.as_view(), name='item_update'),
    path('items/<int:pk>/desactivar/', ItemDeactivateView.as_view(), name='item_deactivate'),
    path('items/<int:pk>/activar/', ItemActivateView.as_view(), name='item_activate'),
    path('periodos/', PeriodMaintainerView.as_view(), name='period_maintainer'),
    path(
        'tipos-atencion/',
        AttentionTypeMaintainerView.as_view(),
        name='attention_type_maintainer',
    ),
    path(
        'subatenciones/',
        SubattentionTypeMaintainerView.as_view(),
        name='subattention_type_maintainer',
    ),
]
