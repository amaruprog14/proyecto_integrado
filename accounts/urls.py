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
from django.contrib.auth import views as auth_views
from django.urls import path

from .forms import SGRAuthenticationForm
from .views import (
    AreaMaintainerView,
    DelegationMaintainerView,
    GroupMaintainerView,
    OfficialMaintainerView,
    PositionMaintainerView,
    RecoveryCodeView,
    RecoveryPasswordView,
    RecoveryRequestView,
    RoleMaintainerView,
    UserMaintainerView,
)

urlpatterns = [
    path(
        'login/',
        auth_views.LoginView.as_view(
            authentication_form=SGRAuthenticationForm,
            redirect_authenticated_user=True,
        ),
        name='login',
    ),
    path('logout/', auth_views.LogoutView.as_view(), name='logout'),
    path('recuperar/', RecoveryRequestView.as_view(), name='recovery_request'),
    path('recuperar/codigo/', RecoveryCodeView.as_view(), name='recovery_code'),
    path('recuperar/nueva-clave/', RecoveryPasswordView.as_view(), name='recovery_password'),
    path('cargos/', PositionMaintainerView.as_view(), name='position_maintainer'),
    path('areas/', AreaMaintainerView.as_view(), name='area_maintainer'),
    path('funcionarios/', OfficialMaintainerView.as_view(), name='official_maintainer'),
    path('usuarios/', UserMaintainerView.as_view(), name='user_maintainer'),
    path('grupos/', GroupMaintainerView.as_view(), name='group_maintainer'),
    path(
        'delegaciones/',
        DelegationMaintainerView.as_view(),
        name='delegation_list',
    ),
    path(
        'roles/',
        RoleMaintainerView.as_view(),
        name='role_list',
    ),
]
