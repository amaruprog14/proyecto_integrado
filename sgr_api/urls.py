from django.conf import settings
from django.http import Http404
from django.urls import path
from django.views.decorators.cache import never_cache
from drf_spectacular.utils import OpenApiResponse, extend_schema, extend_schema_view
from drf_spectacular.views import SpectacularAPIView, SpectacularRedocView, SpectacularSwaggerView
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView

from sgr_api import views
from sgr_api.serializers import (
    AccessTokenSerializer, SGRTokenRefreshSerializer, TokenCredentialsSerializer, TokenErrorSerializer,
    TokenPairSerializer,
)


@extend_schema_view(post=extend_schema(
    tags=["Autenticación"], summary="Obtener tokens del SGR", auth=[],
    request=TokenCredentialsSerializer,
    responses={200: TokenPairSerializer, 400: OpenApiResponse(description="Datos de acceso incompletos."),
               401: OpenApiResponse(TokenErrorSerializer, description="Credenciales inválidas o cuenta no habilitada.")},
))
class SGRTokenObtainView(TokenObtainPairView):
    serializer_class = TokenCredentialsSerializer


@extend_schema_view(post=extend_schema(
    tags=["Autenticación"], summary="Renovar el token de acceso", auth=[],
    request=SGRTokenRefreshSerializer,
    responses={200: AccessTokenSerializer, 400: OpenApiResponse(description="Falta el token de renovación."),
               401: OpenApiResponse(TokenErrorSerializer, description="Token inválido o cuenta no habilitada.")},
))
class SGRTokenRefreshView(TokenRefreshView):
    serializer_class = SGRTokenRefreshSerializer


def documentation(view):
    @never_cache
    def show(request, *args, **kwargs):
        if not (settings.DEBUG or settings.SGR_API_DOCS_ENABLED):
            raise Http404
        return view(request, *args, **kwargs)
    return show


app_name = "sgr_api"
urlpatterns = [
    path("token/", never_cache(SGRTokenObtainView.as_view()), name="token"),
    path("token/refresh/", never_cache(SGRTokenRefreshView.as_view()), name="token_refresh"),
    path("v1/periodos/", never_cache(views.periods), name="periods"),
    path("v1/mi-desempeno/", never_cache(views.personal_performance), name="personal_performance"),
    path("v1/delegaciones/<int:delegation_id>/desempeno/", never_cache(views.delegation_performance),
         name="delegation_performance"),
    path("schema/", documentation(SpectacularAPIView.as_view()), name="schema"),
    path("swagger/", documentation(SpectacularSwaggerView.as_view(url_name="sgr_api:schema")), name="swagger"),
    path("redoc/", documentation(SpectacularRedocView.as_view(url_name="sgr_api:schema")), name="redoc"),
]
