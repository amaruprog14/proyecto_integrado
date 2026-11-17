from decimal import ROUND_HALF_UP

from django.contrib.auth import get_user_model
from rest_framework import serializers
from rest_framework.exceptions import AuthenticationFailed
from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer, TokenRefreshSerializer

from analytics.models import MeasurementItem
from analytics.services import TrafficLight
from configuration.models import Period


class SGRTokenRefreshSerializer(TokenRefreshSerializer):
    def validate(self, attrs):
        # La validación estándar de renovación no comprueba el cambio de contraseña.
        # Reutiliza el control de usuario y revocación que también protege las consultas.
        JWTAuthentication().get_user(self.token_class(attrs["refresh"]))
        try:
            return super().validate(attrs)
        except get_user_model().DoesNotExist as error:
            raise AuthenticationFailed(self.error_messages["no_active_account"], "no_active_account") from error


class PeriodIdField(serializers.IntegerField):
    def to_internal_value(self, data):
        if isinstance(data, str) and not (data.isascii() and data.isdecimal()):
            self.fail("invalid")
        return super().to_internal_value(data)


class PeriodQuerySerializer(serializers.Serializer):
    periodo = PeriodIdField(required=False, min_value=1, max_value=2**63 - 1,
                            help_text="ID del período. Si se omite, se usa el período del tablero.")


class PeriodSerializer(serializers.Serializer):
    id = serializers.IntegerField(source="pk")
    inicio = serializers.DateField(source="start_date")
    fin = serializers.DateField(source="end_date")
    estado = serializers.ChoiceField(source="status", choices=Period.Status.choices)
    congelado_en = serializers.DateTimeField(source="frozen_at", allow_null=True)


def decimal_field(source):
    return serializers.DecimalField(
        source=source, max_digits=None, decimal_places=2, allow_null=True,
        coerce_to_string=True, rounding=ROUND_HALF_UP,
    )


class PerformanceItemSerializer(serializers.Serializer):
    id = serializers.IntegerField(source="item.pk")
    nombre = serializers.CharField(source="item.item_name")
    tipo_meta = serializers.ChoiceField(source="goal_type", choices=MeasurementItem.GoalType.choices)
    meta = decimal_field("goal")
    avance = decimal_field("progress")
    cumplimiento_pct = decimal_field("compliance")
    ponderador_pct = decimal_field("weight")
    resultado_ponderado = decimal_field("weighted")
    meta_esperada = decimal_field("expected_units")
    diferencia = decimal_field("difference")
    semaforo = serializers.ChoiceField(source="traffic_light", choices=TrafficLight.choices, allow_null=True)
    aviso = serializers.CharField(source="notice", allow_blank=True)


class ScoreAdjustmentDetailSerializer(serializers.Serializer):
    tipo = serializers.CharField(source="kind", help_text="Felicitación o Reclamo.")
    fecha = serializers.DateField(source="date", help_text="Fecha del hecho.")
    puntos_autorizados = decimal_field("points")
    puntos_computables = decimal_field("applied_points")
    excluido_por_limite = serializers.BooleanField(
        source="excluded", help_text="Felicitación sobre el límite de tres por período: no suma puntos.")


class PersonalPerformanceSerializer(serializers.Serializer):
    periodo = PeriodSerializer()
    cargo = serializers.CharField(allow_null=True)
    fecha_corte = serializers.DateField()
    total_ponderado = serializers.DecimalField(
        source="total", max_digits=None, decimal_places=2, allow_null=True, coerce_to_string=True,
        rounding=ROUND_HALF_UP, help_text="Resultado final: min(total_base + ajustes_computables, tope_resultado_final).")
    total_base = serializers.DecimalField(
        source="base_total", max_digits=None, decimal_places=2, allow_null=True, coerce_to_string=True,
        rounding=ROUND_HALF_UP, help_text="Suma de los resultados ponderados de los ítems, sin ajustes.")
    ajustes_computables = serializers.DecimalField(
        source="adjustment_total", max_digits=None, decimal_places=2, allow_null=True, coerce_to_string=True,
        rounding=ROUND_HALF_UP, help_text="Suma de los puntos computables de reclamos y felicitaciones aprobados.")
    tope_resultado_final = decimal_field("max_final")
    ajustes = ScoreAdjustmentDetailSerializer(many=True, source="adjustments")
    semaforo = serializers.ChoiceField(choices=TrafficLight.choices, allow_null=True)
    items = PerformanceItemSerializer(many=True)
    aviso = serializers.CharField(allow_null=True)
    dias_computables = serializers.IntegerField(source="computable_days", allow_null=True)
    porcentaje_esperado = decimal_field("expected_percentage")
    tramos = serializers.JSONField(source="segments")


class DelegationSerializer(serializers.Serializer):
    id = serializers.IntegerField(source="pk")
    nombre = serializers.CharField(source="delegation_name")


class TrafficLightCountsSerializer(serializers.Serializer):
    verde = serializers.IntegerField(source="GREEN")
    ambar = serializers.IntegerField(source="AMBER")
    rojo = serializers.IntegerField(source="RED")


class DelegationPerformanceSerializer(serializers.Serializer):
    periodo = PeriodSerializer()
    delegacion = DelegationSerializer()
    fecha_corte = serializers.DateField()
    funcionarios_medidos = serializers.IntegerField(source="measured_count")
    actividades_computadas = serializers.IntegerField(source="total_activities")
    promedio_ponderado = decimal_field("average")
    meta_esperada_promedio_pct = decimal_field("expected_average")
    semaforos = TrafficLightCountsSerializer(source="colors")
    aviso = serializers.CharField(allow_null=True)


class APIErrorSerializer(serializers.Serializer):
    detail = serializers.CharField()


class PeriodQueryErrorSerializer(serializers.Serializer):
    periodo = serializers.ListField(child=serializers.CharField())


class TokenCredentialsSerializer(TokenObtainPairSerializer):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields[self.username_field].help_text = "Usuario o correo del SGR."


class AccessTokenSerializer(serializers.Serializer):
    access = serializers.CharField()


class TokenPairSerializer(AccessTokenSerializer):
    refresh = serializers.CharField()


class TokenErrorSerializer(APIErrorSerializer):
    code = serializers.CharField(required=False)
