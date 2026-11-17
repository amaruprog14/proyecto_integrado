from django.http import Http404
from django.utils import timezone
from drf_spectacular.utils import OpenApiExample, OpenApiResponse, extend_schema
from rest_framework.decorators import api_view, permission_classes
from rest_framework.exceptions import PermissionDenied
from rest_framework.response import Response

from analytics.queries import (
    VIEW_PERFORMANCE, available_periods, performance_delegations, select_period, summarize_team, team_results,
)
from analytics.services import CalculadorDesempenoService
from common.access import get_scoped_object_or_404, register_denied_access
from configuration.models import Period
from sgr_api.permissions import CanViewPerformance, CanViewTeamPerformance
from sgr_api.serializers import (
    APIErrorSerializer, DelegationPerformanceSerializer, PeriodQueryErrorSerializer, PeriodQuerySerializer,
    PeriodSerializer, PersonalPerformanceSerializer, TokenErrorSerializer,
)


AUTH_ERRORS = {
    401: OpenApiResponse(TokenErrorSerializer, description="Se requiere un token de acceso válido."),
    403: OpenApiResponse(APIErrorSerializer, description="La cuenta carece del permiso requerido."),
}
PERIOD_ERRORS = {
    400: OpenApiResponse(PeriodQueryErrorSerializer, description="El ID del período debe ser un entero positivo."),
    404: OpenApiResponse(APIErrorSerializer, description="El recurso solicitado no está disponible."),
}
PERIOD_EXAMPLE = {"id": 3, "inicio": "2026-10-01", "fin": "2026-12-31", "estado": "OPEN", "congelado_en": None}


def requested_period(request, today):
    params = PeriodQuerySerializer(data=request.query_params.dict())
    params.is_valid(raise_exception=True)
    period = select_period(list(available_periods()), today, params.validated_data.get("periodo"))
    if period is None:
        raise Http404("No hay períodos disponibles.")
    return period


@extend_schema(
    tags=["Desempeño"], summary="Listar períodos", responses={200: PeriodSerializer(many=True), **AUTH_ERRORS},
    examples=[OpenApiExample("Período abierto", value=PERIOD_EXAMPLE, response_only=True)],
)
@api_view(["GET"])
@permission_classes([CanViewPerformance])
def periods(request):
    return Response(PeriodSerializer(available_periods(), many=True).data)


@extend_schema(
    tags=["Desempeño"], summary="Consultar mi desempeño", parameters=[PeriodQuerySerializer],
    responses={200: PersonalPerformanceSerializer, **AUTH_ERRORS, **PERIOD_ERRORS},
    examples=[OpenApiExample("Resultado individual", response_only=True, value={
        "periodo": PERIOD_EXAMPLE, "cargo": "Gestor social", "fecha_corte": "2026-11-16",
        "total_ponderado": "4.17", "semaforo": "RED", "aviso": None,
        "items": [{"id": 12, "nombre": "Visita terreno", "tipo_meta": "QUANTITY", "meta": "12.00",
                   "avance": "1.00", "cumplimiento_pct": "8.33", "ponderador_pct": "50.00",
                   "resultado_ponderado": "4.17", "meta_esperada": "6.07", "diferencia": "-5.07",
                   "semaforo": "RED", "aviso": ""}],
    })],
)
@api_view(["GET"])
@permission_classes([CanViewPerformance])
def personal_performance(request):
    official = getattr(request.user, "official", None)
    if official is None or not official.is_enabled:
        register_denied_access(request, (VIEW_PERFORMANCE,))
        raise PermissionDenied("La cuenta necesita un funcionario habilitado para consultar el resultado personal.")
    today = timezone.localdate()
    period = requested_period(request, today)
    result = CalculadorDesempenoService.result_for(official, period, today)
    data = {
        "periodo": period,
        "cargo": result.position.position_name if result.position else None,
        "fecha_corte": min(result.on_date, period.end_date),
        "total": result.total if result.items else None,
        "semaforo": result.total_traffic_light,
        "items": result.items,
        "computable_days": result.computable_days,
        "expected_percentage": result.expected_percentage,
        "segments": result.segments,
        "aviso": result.notice or ("Sin indicadores para el funcionario en este período." if not result.items else None),
    }
    return Response(PersonalPerformanceSerializer(data).data)


@extend_schema(
    tags=["Desempeño"], summary="Consultar el desempeño de una delegación", parameters=[PeriodQuerySerializer],
    responses={200: DelegationPerformanceSerializer, **AUTH_ERRORS, **PERIOD_ERRORS},
    examples=[OpenApiExample("Resumen de equipo", response_only=True, value={
        "periodo": PERIOD_EXAMPLE, "delegacion": {"id": 2, "nombre": "Las Compañías"},
        "fecha_corte": "2026-11-16", "funcionarios_medidos": 2, "actividades_computadas": 12,
        "promedio_ponderado": "43.00", "meta_esperada_promedio_pct": "50.55",
        "semaforos": {"verde": 1, "ambar": 1, "rojo": 0}, "aviso": None,
    })],
)
@api_view(["GET"])
@permission_classes([CanViewTeamPerformance])
def delegation_performance(request, delegation_id):
    if not 1 <= delegation_id <= 2**63 - 1:
        raise Http404("No se encontró la delegación solicitada.")
    delegations = performance_delegations(request.user)
    delegation = get_scoped_object_or_404(request, delegations, pk=delegation_id)
    today = timezone.localdate()
    period = requested_period(request, today)
    closed = period.status == Period.Status.CLOSED
    summary = summarize_team(team_results(period, today, delegations.filter(pk=delegation.pk).order_by()))
    notice = None
    if closed and period.frozen_at is None:
        notice = "El período está cerrado y aún no tiene resultados congelados."
    elif summary["measured_count"] == 0:
        notice = "La delegación no tiene funcionarios medidos en este período."
    data = {
        **summary, "periodo": period, "delegacion": delegation,
        "fecha_corte": period.end_date if closed else min(today, period.end_date),
        "aviso": notice,
    }
    return Response(DelegationPerformanceSerializer(data).data)
