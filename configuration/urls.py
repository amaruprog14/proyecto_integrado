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

from .views import (
    AttentionTypeMaintainerView,
    ItemMaintainerView,
    PeriodMaintainerView,
    SubattentionTypeMaintainerView,
)

urlpatterns = []
urlpatterns += [
    path('items/', ItemMaintainerView.as_view(), name='item_maintainer'),
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
