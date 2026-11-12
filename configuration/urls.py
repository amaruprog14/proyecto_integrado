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
from analytics.measurement_views import MeasurementEdit, MeasurementPlanDetail, MeasurementPlanList
from configuration.period_views import PeriodReopenView

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
    AttentionTypeActivateView,
    AttentionTypeCreateView,
    AttentionTypeDeactivateView,
    AttentionTypeDetailView,
    AttentionTypeExportView,
    AttentionTypeMaintainerView,
    AttentionTypeUpdateView,
    SubattentionTypeActivateView,
    SubattentionTypeCreateView,
    SubattentionTypeDeactivateView,
    SubattentionTypeDetailView,
    SubattentionTypeExportView,
    SubattentionTypeMaintainerView,
    SubattentionTypeUpdateView,
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
    path(
        'tipos-atencion/',
        AttentionTypeMaintainerView.as_view(),
        name='attention_type_maintainer',
    ),
    path(
        'tipos-atencion/nuevo/',
        AttentionTypeCreateView.as_view(),
        name='attention_type_create',
    ),
    path(
        'tipos-atencion/exportar/',
        AttentionTypeExportView.as_view(),
        name='attention_type_export',
    ),
    path(
        'tipos-atencion/<int:pk>/',
        AttentionTypeDetailView.as_view(),
        name='attention_type_detail',
    ),
    path(
        'tipos-atencion/<int:pk>/editar/',
        AttentionTypeUpdateView.as_view(),
        name='attention_type_update',
    ),
    path(
        'tipos-atencion/<int:pk>/activar/',
        AttentionTypeActivateView.as_view(),
        name='attention_type_activate',
    ),
    path(
        'tipos-atencion/<int:pk>/desactivar/',
        AttentionTypeDeactivateView.as_view(),
        name='attention_type_deactivate',
    ),
    path(
        'subatenciones/',
        SubattentionTypeMaintainerView.as_view(),
        name='subattention_type_maintainer',
    ),
    path(
        'subatenciones/nueva/',
        SubattentionTypeCreateView.as_view(),
        name='subattention_type_create',
    ),
    path(
        'subatenciones/exportar/',
        SubattentionTypeExportView.as_view(),
        name='subattention_type_export',
    ),
    path(
        'subatenciones/<int:pk>/',
        SubattentionTypeDetailView.as_view(),
        name='subattention_type_detail',
    ),
    path(
        'subatenciones/<int:pk>/editar/',
        SubattentionTypeUpdateView.as_view(),
        name='subattention_type_update',
    ),
    path(
        'subatenciones/<int:pk>/activar/',
        SubattentionTypeActivateView.as_view(),
        name='subattention_type_activate',
    ),
    path(
        'subatenciones/<int:pk>/desactivar/',
        SubattentionTypeDeactivateView.as_view(),
        name='subattention_type_deactivate',
    ),
]

from common.maintainers import maintainer_urls
urlpatterns += maintainer_urls('period', 'periodos/')

period_path = "periodos/<int:period_id>/"
plan_list_path = period_path + "medicion/"
plan_path = plan_list_path + "<int:plan_id>/"
version_path = plan_path + "versiones/<int:version_id>/"
line_path = version_path + "items/<int:line_id>/"
adjustment_path = line_path + "ajustes/<int:adjustment_id>/"

urlpatterns += [
    path(period_path + "reabrir/", PeriodReopenView.as_view(), name="period_reopen"),
    path(plan_list_path, MeasurementPlanList.as_view(), name="measurement_plan_list"),
    path(plan_list_path + "exportar/", MeasurementPlanList.as_view(export=True), name="measurement_plan_export"),
    path(plan_list_path + "nuevo/", MeasurementEdit.as_view(operation="plan"), name="measurement_plan_create"),
    path(plan_path, MeasurementPlanDetail.as_view(), name="measurement_plan_detail"),
    path(plan_path + "nueva-version/", MeasurementEdit.as_view(operation="revision"), name="measurement_revision_create"),
    path(version_path, MeasurementPlanDetail.as_view(), name="measurement_version_detail"),
    path(version_path + "editar/", MeasurementEdit.as_view(operation="version"), name="measurement_version_edit"),
    path(version_path + "publicar/", MeasurementEdit.as_view(operation="publish"), name="measurement_version_publish"),
    path(version_path + "items/nuevo/", MeasurementEdit.as_view(operation="item"), name="measurement_item_create"),
    path(line_path + "editar/", MeasurementEdit.as_view(operation="item"), name="measurement_item_edit"),
    path(line_path + "quitar/", MeasurementEdit.as_view(operation="remove_item"), name="measurement_item_remove"),
    path(line_path + "ajustes/nuevo/", MeasurementEdit.as_view(operation="adjustment"), name="measurement_adjustment_create"),
    path(adjustment_path + "editar/", MeasurementEdit.as_view(operation="adjustment"), name="measurement_adjustment_edit"),
    path(adjustment_path + "quitar/", MeasurementEdit.as_view(operation="remove_adjustment"), name="measurement_adjustment_remove"),
]
