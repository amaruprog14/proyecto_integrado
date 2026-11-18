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
from agenda.comments import InternalCommentView
from .case_views import CaseActionView, CaseDetailView, CaseListView
from .eligible_items import ActivityEligibleItemsView
from .evidence import EvidenceAnnulmentView, EvidenceImageView, EvidenceReviewView, EvidenceUploadView
from .letters import LetterCaseView, LetterDetailView, LetterFormView, LetterListView
from .gifts import CampaignList, CampaignEdit, RegistrationList, RegistrationDetail, RegistrationEdit
from .views import AttentionDetailView, AttentionEntryView, AttentionRequestLookupView

urlpatterns = []
urlpatterns += [
    path('regalos/', CampaignList.as_view(), name='gift_campaign_list'),
    path('regalos/campanas/nueva/', CampaignEdit.as_view(), name='gift_campaign_create'),
    path('regalos/campanas/<int:pk>/editar/', CampaignEdit.as_view(), name='gift_campaign_edit'),
    path('regalos/campanas/<int:campaign_id>/', RegistrationList.as_view(), name='gift_registration_list'),
    path('regalos/campanas/<int:campaign_id>/inscribir/', RegistrationEdit.as_view(), name='gift_registration_create'),
    path('regalos/inscripciones/<int:pk>/', RegistrationDetail.as_view(), name='gift_registration_detail'),
    path('regalos/inscripciones/<int:pk>/editar/', RegistrationEdit.as_view(), name='gift_registration_edit'),
    path('regalos/inscripciones/<int:pk>/entregar/', RegistrationEdit.as_view(operation='deliver'), name='gift_registration_deliver'),
    path('regalos/inscripciones/<int:pk>/anular/', RegistrationEdit.as_view(operation='cancel'), name='gift_registration_cancel'),
    path("items-elegibles/", ActivityEligibleItemsView.as_view(), name="activity_eligible_items"),
    path('solicitudes/', RedirectView.as_view(
        url=reverse_lazy('activity_maintainer', query={
            'record_source': 'request', 'status': '', 'official': '', 'item': '', 'record_type': '',
        }),
    ), name='activity_requests'),
    path('atenciones/nueva/', AttentionEntryView.as_view(), name='attention_entry'),
    path('atenciones/buscar-solicitudes/', AttentionRequestLookupView.as_view(), name='attention_request_lookup'),
    path('atenciones/<int:pk>/', AttentionDetailView.as_view(), name='attention_detail'),
    path('cartas/', LetterListView.as_view(), name='office_letter_list'),
    path('cartas/nueva/', LetterFormView.as_view(), name='office_letter_create'),
    path('cartas/<int:pk>/', LetterDetailView.as_view(), name='office_letter_detail'),
    path('cartas/<int:pk>/editar/', LetterFormView.as_view(), name='office_letter_edit'),
    path('cartas/<int:pk>/caso/', LetterCaseView.as_view(), name='office_letter_case'),
    path('casos/', CaseListView.as_view(), name='attention_cases'),
    path('casos/<int:pk>/', CaseDetailView.as_view(), name='attention_case_detail'),
    path('casos/<int:pk>/comentarios/', InternalCommentView.as_view(target="case"), name="case_internal_comment"),
    path('casos/<int:pk>/<slug:action>/', CaseActionView.as_view(), name='attention_case_action'),
    path('<int:pk>/evidencias/nueva/', EvidenceUploadView.as_view(), name='activity_evidence_upload'),
    path('<int:pk>/evidencias/<int:batch_id>/revisar/', EvidenceReviewView.as_view(), name='activity_evidence_review'),
    path('<int:pk>/evidencias/<int:batch_id>/anular/', EvidenceAnnulmentView.as_view(), name='activity_evidence_annul'),
    path('<int:pk>/evidencias/imagen/<int:image_id>/', EvidenceImageView.as_view(), name='activity_evidence_image'),
    path('<int:pk>/comentarios/', InternalCommentView.as_view(target="activity"), name="activity_internal_comment"),
]

from common.maintainers import maintainer_urls
urlpatterns += maintainer_urls('activity', '')
