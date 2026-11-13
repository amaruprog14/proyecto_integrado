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
from .case_views import CaseActionView, CaseDetailView, CaseListView
from .eligible_items import ActivityEligibleItemsView
from .evidence import EvidenceImageView, EvidenceReviewView, EvidenceUploadView
from .views import AttentionDetailView, AttentionEntryView, AttentionRequestLookupView

urlpatterns = []
urlpatterns += [
    path("items-elegibles/", ActivityEligibleItemsView.as_view(), name="activity_eligible_items"),
    path('solicitudes/', RedirectView.as_view(
        url=reverse_lazy('activity_maintainer', query={
            'record_source': 'request', 'status': '', 'official': '', 'item': '', 'record_type': '',
        }),
    ), name='activity_requests'),
    path('atenciones/nueva/', AttentionEntryView.as_view(), name='attention_entry'),
    path('atenciones/buscar-solicitudes/', AttentionRequestLookupView.as_view(), name='attention_request_lookup'),
    path('atenciones/<int:pk>/', AttentionDetailView.as_view(), name='attention_detail'),
    path('casos/', CaseListView.as_view(), name='attention_cases'),
    path('casos/<int:pk>/', CaseDetailView.as_view(), name='attention_case_detail'),
    path('casos/<int:pk>/<slug:action>/', CaseActionView.as_view(), name='attention_case_action'),
    path('<int:pk>/evidencias/nueva/', EvidenceUploadView.as_view(), name='activity_evidence_upload'),
    path('<int:pk>/evidencias/<int:batch_id>/revisar/', EvidenceReviewView.as_view(), name='activity_evidence_review'),
    path('<int:pk>/evidencias/imagen/<int:image_id>/', EvidenceImageView.as_view(), name='activity_evidence_image'),
]

from common.maintainers import maintainer_urls
urlpatterns += maintainer_urls('activity', '')
