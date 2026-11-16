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

from .comments import InternalCommentView
from .commitment_views import CommitmentCreateView, CommitmentDetailView, CommitmentListView, CommitmentUpdateView
from .views import AlertListView, AlertSeenView


urlpatterns = [
    path("compromisos/", CommitmentListView.as_view(), name="commitment_list"),
    path("compromisos/nuevo/", CommitmentCreateView.as_view(), name="commitment_create"),
    path("compromisos/nuevo/caso/<int:case_id>/", CommitmentCreateView.as_view(), name="commitment_from_case"),
    path("compromisos/nuevo/actividad/<int:activity_id>/", CommitmentCreateView.as_view(), name="commitment_from_activity"),
    path("compromisos/<int:pk>/", CommitmentDetailView.as_view(), name="commitment_detail"),
    path("compromisos/<int:pk>/estado/", CommitmentUpdateView.as_view(operation="status"), name="commitment_status"),
    path("compromisos/<int:pk>/asignar/", CommitmentUpdateView.as_view(operation="assign"), name="commitment_assign"),
    path("compromisos/<int:pk>/comentarios/", InternalCommentView.as_view(target="commitment"), name="commitment_internal_comment"),
    path("alertas/", AlertListView.as_view(), name="alert_list"),
    path("alertas/<int:pk>/revisar/", AlertSeenView.as_view(), name="alert_seen"),
]
