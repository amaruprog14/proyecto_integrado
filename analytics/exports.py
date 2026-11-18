from datetime import date
from decimal import Decimal

from django.utils import timezone

from analytics.models import MeasurementItem
from analytics.services import TrafficLight
from common.exports import xlsx_report_response
from configuration.models import Period


def local_excel_time(value):
    return timezone.localtime(value).replace(tzinfo=None)


def report(title, filename, period, cutoff, filters, metrics, tables):
    generated = local_excel_time(timezone.now())
    closed = period.status == Period.Status.CLOSED
    if closed:
        source = "Resultados congelados" if period.frozen_at else "Cerrado sin resultados congelados"
    else:
        source = "Cálculo al corte"
    summary = [
        ("Informe", title),
        ("Inicio del período", period.start_date),
        ("Término del período", period.end_date),
        ("Estado del período", period.get_status_display()),
        ("Fecha de corte", cutoff),
        ("Fecha de generación", generated),
        ("Zona horaria", timezone.get_current_timezone_name()),
        ("Origen de las cifras de desempeño", source),
    ]
    if closed and period.frozen_at:
        summary.append(("Fecha de congelamiento", local_excel_time(period.frozen_at)))
    summary.extend(filters)
    summary.extend(metrics)
    return xlsx_report_response(
        f"{filename}_{period.start_date.isoformat()}_{period.end_date.isoformat()}",
        [("Resumen", ("Campo", "Valor"), summary), *tables],
    )


def light_label(light):
    return TrafficLight(light).label if light else "Sin semáforo"


def personal_export(period, today, result):
    delegation = result.closing_delegation if result.frozen else result.official.delegation
    filters = [
        ("Funcionario", result.official.full_name),
        ("Delegación", str(delegation) if delegation else "Sin delegación registrada"),
    ]
    metrics = [
        ("Cargo", str(result.position) if result.position else "Sin cargo"),
        ("Días computables", result.computable_days),
        ("Días transcurridos", result.elapsed_days),
    ]
    if result.items:
        metrics.extend([
            ("Meta esperada (%)", result.expected_percentage),
            ("Total ponderado base (puntos)", result.base_total),
            ("Ajustes computables (puntos)", result.score_adjustment_total),
            ("Tope del resultado final (puntos)", result.max_final_score),
            ("Piso del resultado final (puntos)", result.min_final_score),
            ("Resultado final (puntos)", result.total),
            ("Semáforo", light_label(result.total_traffic_light)),
        ])
    if result.notice:
        metrics.append(("Observación", result.notice))
    if result.plan_coverage_notice:
        metrics.append(("Cobertura del plan", result.plan_coverage_notice))
    tables = [
        ("Resultado por ítem",
         ("Ítem", "Tipo de meta", "Meta", "Avance", "Cumplimiento (%)", "Ponderador (%)",
          "Ponderado (puntos)", "Meta esperada", "Diferencia", "Semáforo", "Observación"),
         ((row.item.item_name, MeasurementItem.GoalType(row.goal_type).label if row.goal_type else "",
           row.goal, row.progress, row.compliance, row.weight, row.weighted,
           row.expected_units, row.difference, row.traffic_light_label, row.notice) for row in result.items)),
    ]
    if len(result.segments) > 1:
        tables.append((
            "Tramos de cargo",
            ("Cargo", "Inicio", "Término", "Días computables", "Días transcurridos",
             "Plan publicado", "Resultado del tramo (puntos)", "Meta esperada (%)", "Semáforo", "Observación"),
            ((segment["position"], date.fromisoformat(segment["start_date"]), date.fromisoformat(segment["end_date"]),
              segment["days"], segment["elapsed_days"], "Sí" if segment["version_id"] else "Sin plan publicado",
              Decimal(segment["total"]), Decimal(segment["expected"]) if segment["expected"] is not None else None,
              light_label(segment["traffic_light"]), segment["notice"]) for segment in result.segments),
        ))
    if result.score_adjustments:
        tables.append((
            "Ajustes aprobados", ("Tipo", "Fecha", "Puntos autorizados", "Puntos computables", "Observación"),
            ((entry["kind"], date.fromisoformat(entry["date"]), Decimal(entry["points"]), Decimal(entry["applied_points"]),
              "Fuera del límite de felicitaciones" if entry["excluded"] else "") for entry in result.score_adjustments),
        ))
    return report("Mi desempeño", "mi_desempeno", period, result.on_date if result.frozen else min(today, period.end_date),
                  filters, metrics, tables)


def delegation_export(period, today, delegation, context, records):
    metrics = []
    rows = context["rows"]
    tables = [
        ("Funcionarios", ("Funcionario", "Cargo", "Actividades individuales", "Meta esperada (%)",
                          "Resultado ponderado (puntos)", "Semáforo", "Observación"),
         ((row["result"].official.full_name, str(row["position"]) if row["position"] else "Sin cargo",
           row["activity_count"] if row["result"].items else None,
           row["result"].expected_percentage if row["result"].items else None,
           row["result"].total if row["result"].items else None,
           light_label(row["light"]), row["result"].notice) for row in rows)),
    ]
    if records is None:
        metrics.append(("Actividades válidas de la delegación", "Sin respaldo disponible para esta consulta"))
    else:
        # El total y su respaldo salen de la misma lectura, incluidas las páginas que no se ven en pantalla.
        support = list(records.order_by("-date", "-pk").values_list("code", "date", "official_name", "item_name", "estimated"))
        metrics.append(("Actividades válidas de la delegación", len(support)))
        tables.append(("Actividades válidas", ("Código", "Fecha", "Funcionario", "Ítem", "Atribución"),
                       ((*row[:4], "Estimada" if row[4] else "Registrada") for row in support)))
    if rows or not context["closed"]:
        metrics.extend([
            ("Funcionarios del equipo", len(rows)),
            ("Funcionarios medidos", context["measured_count"]),
            ("Actividades computadas del equipo", context["total_activities"]),
            ("Resultado del equipo (puntos)", context["average"]),
            ("Meta esperada promedio (%)", context["expected_average"]),
            ("Semáforo verde", context["colors"]["GREEN"]),
            ("Semáforo ámbar", context["colors"]["AMBER"]),
            ("Semáforo rojo", context["colors"]["RED"]),
        ])
    if commitments := context["commitments"]:
        metrics.extend([
            ("Compromisos del período", commitments["total"]),
            ("Compromisos realizados", commitments["done"]),
            ("Compromisos vencidos", commitments["overdue"]),
        ])
    cutoff = period.end_date if context["closed"] else min(today, period.end_date)
    return report("Tablero de delegación", "desempeno_delegacion", period, cutoff,
                  [("Delegación", delegation.delegation_name)], metrics, tables)


def position_export(period, today, delegation, context):
    selected = context.get("selected")
    filters = [
        ("Delegación", delegation.delegation_name if delegation else "Todas las autorizadas"),
        ("Cargo", selected["name"] if selected else "Todos los cargos del ámbito"),
    ]
    metrics = []
    groups = [selected] if selected else context["groups"]
    tables = [
        ("Cargos", ("Cargo", "Funcionarios del equipo", "Funcionarios medidos", "Actividades computadas",
                    "Promedio ponderado (puntos)"),
         ((group["name"], group["staff_count"], group["measured_count"],
           group["activity_count"] if group["measured_count"] else None, group["average"]) for group in groups)),
    ]
    if selected:
        if context["closed"]:
            metrics.append(("Origen de la actividad reciente", "Registros vigentes dentro del ámbito de consulta"))
        metrics.append(("Corte de la actividad reciente", context["activity_cutoff"]))
        tables.extend([
            ("Metas por ítem", ("Ítem", "Unidad", "Meta del equipo", "Avance del equipo"),
             ((row["item"].item_name, "Porcentaje" if row["is_percentage"] else "Cantidad",
               row["goal"], row["progress"]) for row in context["item_totals"])),
            ("Funcionarios", ("Funcionario", "Delegación", "Resultado ponderado (puntos)", "Semáforo",
                              "Última actividad válida", "Días sin registros", "Registros del período",
                              "Promedio diario", "Observación"),
             ((member["result"].official.full_name, str(member["delegation"]) if member["delegation"] else "",
               member["result"].total if member["result"].items else None, light_label(member["result"].total_traffic_light),
               member["recent"]["last_date"], member["recent"]["days_without"],
               member["recent"]["count"] if context["started"] else None,
               member["recent"]["daily_average"] if context["started"] else None, member["result"].notice)
              for member in context["members"])),
        ])
    cutoff = period.end_date if context["closed"] else min(today, period.end_date)
    return report("Vista por cargo", "desempeno_por_cargo", period, cutoff, filters, metrics, tables)
