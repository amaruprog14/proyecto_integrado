from django.urls import path

from analytics.views import DelegationPerformanceView, MyPerformanceView, PositionPerformanceView, TerritorialActivityDetailView

urlpatterns = [
    path("mi-desempeno/", MyPerformanceView.as_view(), name="my_performance"),
    path("desempeno-delegacion/", DelegationPerformanceView.as_view(), name="delegation_performance"),
    path("desempeno-delegacion/actividades/", TerritorialActivityDetailView.as_view(), name="territorial_activity_detail"),
    path("desempeno-cargos/", PositionPerformanceView.as_view(), name="position_performance"),
]
