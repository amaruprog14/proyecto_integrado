from django.urls import path

from analytics.views import MyPerformanceView

urlpatterns = [
    path("mi-desempeno/", MyPerformanceView.as_view(), name="my_performance"),
]
