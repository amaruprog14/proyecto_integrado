from django.urls import path

from analytics.score_adjustments import ScoreAdjustmentCreate, ScoreAdjustmentDetail, ScoreAdjustmentList
from analytics.support_views import IndicatorSupportView
from analytics.views import DelegationPerformanceView, MyPerformanceView, PositionPerformanceView, TerritorialActivityDetailView

urlpatterns = [
    path("mi-desempeno/", MyPerformanceView.as_view(), name="my_performance"),
    path("desempeno-delegacion/", DelegationPerformanceView.as_view(), name="delegation_performance"),
    path("desempeno-delegacion/actividades/", TerritorialActivityDetailView.as_view(), name="territorial_activity_detail"),
    path("mi-desempeno/respaldo/<int:period_pk>/<int:official_pk>/", IndicatorSupportView.as_view(),
         name="indicator_support"),
    path("desempeno-cargos/", PositionPerformanceView.as_view(), name="position_performance"),
    path("reclamos-y-felicitaciones/", ScoreAdjustmentList.as_view(), name="score_adjustment_list"),
    path("reclamos-y-felicitaciones/nuevo/", ScoreAdjustmentCreate.as_view(), name="score_adjustment_create"),
    path("reclamos-y-felicitaciones/<int:pk>/", ScoreAdjustmentDetail.as_view(), name="score_adjustment_detail"),
]
