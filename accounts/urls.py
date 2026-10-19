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
from .role_views import (
    RoleActivateView,
    RoleCreateView,
    RoleDeactivateView,
    RoleDetailView,
    RoleExportView,
    RoleListView,
    RoleUpdateView,
)
from .views import (
    AreaMaintainerView,
    DelegationActivateView,
    DelegationCreateView,
    DelegationDeactivateView,
    DelegationDetailView,
    DelegationExportView,
    DelegationListView,
    DelegationUpdateView,
    GroupMaintainerView,
    OfficialCreateView,
    OfficialMaintainerView,
    OfficialUpdateView,
    OwnOfficialProfileView,
    PositionMaintainerView,
    RecoveryCodeView,
    RecoveryPasswordView,
    RecoveryRequestView,
    ActiveDelegationSelectView,
    UserActivateView,
    UserCreateView,
    UserDeactivateView,
    UserDetailView,
    UserExportView,
    UserListView,
    UserUpdateView,
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
    path('delegacion-activa/', ActiveDelegationSelectView.as_view(), name='active_delegation_select'),
    path('recuperar/', RecoveryRequestView.as_view(), name='recovery_request'),
    path('recuperar/codigo/', RecoveryCodeView.as_view(), name='recovery_code'),
    path('recuperar/nueva-clave/', RecoveryPasswordView.as_view(), name='recovery_password'),
    path('cargos/', PositionMaintainerView.as_view(), name='position_maintainer'),
    path('areas/', AreaMaintainerView.as_view(), name='area_maintainer'),
    path('funcionarios/', OfficialMaintainerView.as_view(), name='official_maintainer'),
    path('funcionarios/nuevo/', OfficialCreateView.as_view(), name='official_create'),
    path('funcionarios/<int:pk>/editar/', OfficialUpdateView.as_view(), name='official_update'),
    path('mi-perfil/', OwnOfficialProfileView.as_view(), name='my_profile'),
    path('usuarios/', UserListView.as_view(), name='user_maintainer'),
    path('usuarios/exportar/', UserExportView.as_view(), name='user_export'),
    path('usuarios/nuevo/', UserCreateView.as_view(), name='user_create'),
    path('usuarios/<int:pk>/', UserDetailView.as_view(), name='user_detail'),
    path('usuarios/<int:pk>/editar/', UserUpdateView.as_view(), name='user_update'),
    path('usuarios/<int:pk>/desactivar/', UserDeactivateView.as_view(), name='user_deactivate'),
    path('usuarios/<int:pk>/activar/', UserActivateView.as_view(), name='user_activate'),
    path('grupos/', GroupMaintainerView.as_view(), name='group_maintainer'),
    path(
        'delegaciones/',
        DelegationListView.as_view(),
        name='delegation_list',
    ),
    path('delegaciones/exportar/', DelegationExportView.as_view(), name='delegation_export'),
    path('delegaciones/nueva/', DelegationCreateView.as_view(), name='delegation_create'),
    path('delegaciones/<int:pk>/', DelegationDetailView.as_view(), name='delegation_detail'),
    path('delegaciones/<int:pk>/editar/', DelegationUpdateView.as_view(), name='delegation_update'),
    path('delegaciones/<int:pk>/desactivar/', DelegationDeactivateView.as_view(), name='delegation_deactivate'),
    path('delegaciones/<int:pk>/activar/', DelegationActivateView.as_view(), name='delegation_activate'),
    path('roles/', RoleListView.as_view(), name='role_list'),
    path('roles/exportar/', RoleExportView.as_view(), name='role_export'),
    path('roles/nuevo/', RoleCreateView.as_view(), name='role_create'),
    path('roles/<int:pk>/', RoleDetailView.as_view(), name='role_detail'),
    path('roles/<int:pk>/editar/', RoleUpdateView.as_view(), name='role_update'),
    path('roles/<int:pk>/desactivar/', RoleDeactivateView.as_view(), name='role_deactivate'),
    path('roles/<int:pk>/activar/', RoleActivateView.as_view(), name='role_activate'),
]
