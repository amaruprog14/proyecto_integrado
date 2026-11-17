"""«¿Qué respaldó este resultado?»: respaldo congelado de los indicadores de un período cerrado.

Solo lectura. Muestra los valores guardados al cierre (código, fecha, ítem, tramo y estado de los
compromisos al corte) aunque el registro se haya editado o archivado después. El alcance es el del
panel individual: nadie ve el respaldo de un funcionario cuyo desempeño no puede ver (404).
"""
from django.core.paginator import Paginator
from django.db.models import Count, Q
from django.http import Http404
from django.shortcuts import get_object_or_404, render
from django.views import View

from agenda.commitments import VIEW as COMMITMENT_VIEW, scoped_commitments
from analytics.models import IndicatorSupportSnapshot, MeasurementItem
from analytics.queries import VIEW_PERFORMANCE
from analytics.services import CalculadorDesempenoService
from analytics.views import VIEW_ACTIVITY, performance_officials
from common.access import ProtectedViewMixin, get_scoped_object_or_404
from common.maintainers import activity_queryset
from configuration.models import Period

ARCHIVE_ACTIVITY = "activities.archive_activity"
PRE_SUPPORT_NOTICE = "Sin respaldo disponible (período congelado antes de esta versión)."


class IndicatorSupportView(ProtectedViewMixin, View):
    permission_required = (VIEW_PERFORMANCE,)

    def get(self, request, period_pk, official_pk):
        period = get_object_or_404(Period, pk=period_pk, deleted_at__isnull=True)
        official = get_scoped_object_or_404(request, performance_officials(request.user), pk=official_pk)
        if period.status != Period.Status.CLOSED or period.frozen_at is None:
            raise Http404("El período no tiene resultados congelados.")
        snapshots = CalculadorDesempenoService.frozen_snapshots(period).filter(official=official).select_related("item")
        item_id = request.GET.get("item", "")
        if item_id:
            if not item_id.isascii() or not item_id.isdecimal() or len(item_id) > 19:
                raise Http404("No se encontró el indicador solicitado.")
            snapshots = snapshots.filter(item_id=item_id)
        snapshots = list(snapshots.order_by("item__item_name", "pk"))
        if not snapshots:
            raise Http404("No se encontró el indicador solicitado.")

        captured = all(snapshot.support_captured for snapshot in snapshots)
        evaluated = bool(snapshots[0].computable_days)
        records = (IndicatorSupportSnapshot.objects.filter(snapshot__in=snapshots)
                   .select_related("snapshot__item", "activity", "commitment")
                   .order_by("snapshot__item__item_name", "snapshot_id", "date", "pk"))
        # Conteos por indicador y por tramo: con varios tramos el porcentaje congelado es el promedio
        # de cada tramo ponderado por sus días, no la razón de los totales; se informa por tramo.
        counts, by_segment = {}, {}
        rows = (records.order_by().values("snapshot_id", "segment_start", "segment_end", "position_name")
                .annotate(total=Count("pk"), numerator=Count("pk", filter=Q(in_numerator=True))))
        for row in rows:
            entry = counts.setdefault(row["snapshot_id"], {"total": 0, "numerator": 0})
            entry["total"] += row["total"]
            entry["numerator"] += row["numerator"]
            by_segment.setdefault(row["snapshot_id"], []).append(row)
        # Las filas se limitan a lo que quien consulta puede ver en la operación, con las mismas reglas
        # que el detalle: actividades de su alcance (las archivadas, solo con el permiso de archivo y
        # su alcance) y compromisos vigentes de su alcance (los archivados no se consultan en la
        # agenda). El resumen de arriba sigue siendo el del funcionario completo y un aviso informa
        # cuántos registros quedan fuera.
        user = request.user
        visible = Q(pk__in=[])
        if user.has_perm(VIEW_ACTIVITY):
            readable = activity_queryset(user, VIEW_ACTIVITY, include_archived=True)
            archived = activity_queryset(user, ARCHIVE_ACTIVITY, include_archived=True)
            readable = readable.filter(Q(deleted_at__isnull=True) | Q(pk__in=archived.order_by().values("pk")))
            visible |= Q(activity__in=readable.order_by().values("pk"))
        if user.has_perm(COMMITMENT_VIEW):
            visible |= Q(commitment__in=scoped_commitments(user).order_by().values("pk"))
        visible_records = records.filter(visible)
        hidden = sum(entry["total"] for entry in counts.values()) - visible_records.count()
        page = Paginator(visible_records, 25).get_page(request.GET.get("page"))
        page_rows = list(page)

        supports = []
        for row in page_rows:
            current = row.activity or row.commitment
            archived = current.deleted_at is not None
            modified = bool(row.activity) and not archived and (
                row.activity.date != row.date or row.activity.item_id != row.snapshot.item_id
                or row.activity.code != row.code)
            supports.append({
                "record": row, "archived": archived, "modified": modified,
                "status": dict(current.Status.choices).get(row.status, row.status) if row.commitment else "",
                # La fila ya pasó las mismas reglas que el detalle operativo (incluido el archivo).
                "can_open": True,
            })
        summaries = []
        for snapshot in snapshots:
            entry = counts.get(snapshot.pk, {"total": 0, "numerator": 0})
            segments = sorted(by_segment.get(snapshot.pk, []), key=lambda row: str(row["segment_start"] or ""))
            summaries.append({
                "snapshot": snapshot, "total": entry["total"], "numerator": entry["numerator"],
                "segments": segments if len(segments) > 1 else [],
                "is_percentage": snapshot.goal_type in (MeasurementItem.GoalType.PERCENTAGE,
                                                        MeasurementItem.GoalType.MAX_PERCENTAGE),
                "is_pending": snapshot.goal_type == MeasurementItem.GoalType.MAX_PERCENTAGE,
            })
        return render(request, "analytics/indicator_support.html", {
            "period": period, "official": official, "item_id": item_id, "page_obj": page,
            "supports": supports, "summaries": summaries, "captured": captured, "evaluated": evaluated,
            "pre_support_notice": PRE_SUPPORT_NOTICE, "hidden": hidden,
        })
