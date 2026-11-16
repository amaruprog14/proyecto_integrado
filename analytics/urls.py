from django.urls import path

from analytics.views import DelegationPerformanceView, MyPerformanceView, PositionPerformanceView

urlpatterns = [
    path("mi-desempeno/", MyPerformanceView.as_view(), name="my_performance"),
    path("desempeno-delegacion/", DelegationPerformanceView.as_view(), name="delegation_performance"),
    path("desempeno-cargos/", PositionPerformanceView.as_view(), name="position_performance"),
]
