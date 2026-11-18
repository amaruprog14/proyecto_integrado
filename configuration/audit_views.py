import re
from datetime import date, datetime, time

from django import forms
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db.models import Q
from django.shortcuts import get_object_or_404, render
from django.utils import timezone
from django.views import View
from django.views.csrf import csrf_failure as default_csrf_failure

from accounts.models import Role
from common.access import ProtectedViewMixin
from common.scopes import permission_scope
from configuration.models import AuditLog
from configuration.services import AuditoriaService

VIEW_AUDIT = "configuration.view_auditlog"
AUDIT_ROUTES = {"audit_list", "audit_detail"}
READ_METHODS = {"GET", "HEAD", "OPTIONS"}

# La bitácora histórica guarda texto. Se muestran campos operativos conocidos y
# se reservan cuerpos de mensajes, datos de contacto, credenciales y notas libres.
OPERATIONAL_FIELDS = {
    "área", "archivado", "cargo", "código", "cuenta activa", "acceso al admin", "alcance",
    "comuna", "delegación", "delegación principal", "delegaciones autorizadas", "estado",
    "fecha", "función", "funcionario", "inicio", "ítem", "meta", "meta individual", "período",
    "permisos", "ponderador (%)", "ponderador individual (%)", "puntos autorizados",
    "puntos a descontar por reclamo", "puntos por felicitación", "tope del resultado final (puntos)", "responsable", "roles",
    "respuesta actualizada", "término", "tipo de atención", "tipo de meta", "tope computable (%)",
    "umbral colectivo (%)", "umbral naranjo (%)", "umbral verde (%)", "versión", "vigente", "vigente desde",
    "próximo paso registrado", "fecha de próximo paso", "requiere visita", "visita programada",
    "visita realizada", "entrega de informe", "entrega de beneficio", "recepción", "fecha de recepción",
    "fecha de actividad", "área responsable", "caso", "atención", "subatención",
}
# Catálogos operativos: se muestran todos sus campos (nombre, código, descripción, vigencia...)
# salvo los sensibles. Fuera de estas tablas rige la lista explícita de arriba.
CATALOG_TABLES = {
    "accounts_delegation", "accounts_position", "accounts_area", "accounts_function", "accounts_territory",
    "configuration_item", "configuration_activitytype", "configuration_servicetype",
    "configuration_attentiontype", "configuration_subattentiontype",
    "activities_giftcampaign",
}
# Palabras que reservan un campo aunque sea de un catálogo: credenciales, rutas de archivos privados
# y datos personales o de contacto.
SENSITIVE_FIELD_WORDS = {
    "contraseña", "password", "clave", "token", "secreto", "secret", "correo", "email", "teléfono",
    "telefono", "celular", "rut", "run", "archivo", "ruta", "foto", "url", "ip",
}
TECHNICAL_FIELDS = {"id", "creado en", "actualizado en", "name key"}
STATUS_EVENTS = {
    "Evidencia revisada": {"PENDING", "APPROVED", "REJECTED", "CORRECTION_REQUESTED"},
    "Aprobación de evidencia anulada": {"Aprobada", "Anulada"},
    "Validación de reclamo o felicitación": {"Pendiente", "Aprobado", "Rechazado"},
    "Estado de compromiso actualizado": {"Ingresado", "Pendiente", "En proceso", "Realizado", "Cancelado con justificación"},
    "Reapertura de período": {"Cerrado", "Abierto"},
}


def can_view_audit(user):
    return permission_scope(user, VIEW_AUDIT) == Role.Scope.ALL


def is_sensitive_field(label):
    return bool(set(re.findall(r"\w+", label.casefold())) & SENSITIVE_FIELD_WORDS)


def visible_field(event, label):
    label = label.strip().casefold()
    if label in OPERATIONAL_FIELDS:
        return True
    return (event.affected_table in CATALOG_TABLES and label not in TECHNICAL_FIELDS
            and not is_sensitive_field(label))


def visible_value(event, value):
    if not value:
        return ""
    if event.action in STATUS_EVENTS:
        state = value.split(" · ", 1)[0].split(". Motivo:", 1)[0]
        if state in STATUS_EVENTS[event.action]:
            return state
    if event.action == "Intento de alterar la bitácora" and value in {"POST", "PUT", "PATCH", "DELETE", "TRACE", "CONNECT"}:
        return value
    if value in {"Sin cambios", "Activo", "Inactivo", "Activa", "Inactiva", "Abierto", "Cerrado", "Eliminado"}:
        return value
    if event.affected_table == "activities_attentioncase" and event.action != "Actualización de seguimiento de caso":
        return "Detalle reservado"
    rows = [line for line in value.splitlines()
            if ": " in line and visible_field(event, line.split(": ", 1)[0])]
    return "\n".join(rows) or "Detalle reservado"


def log_mutation_attempt(request, pk=None):
    AuditoriaService.register_event(
        official=getattr(request.user, "official", None),
        action="Intento de alterar la bitácora", entity=AuditLog._meta.db_table,
        record_id=pk if pk is not None and 0 < pk <= 2147483647 else None,
        new_value=request.method, origin_ip=request.META.get("REMOTE_ADDR") or None, actor=request.user,
    )


def csrf_failure(request, reason=""):
    match = request.resolver_match
    if match and match.url_name in AUDIT_ROUTES and request.method not in READ_METHODS:
        log_mutation_attempt(request, match.kwargs.get("pk"))
    return default_csrf_failure(request, reason=reason)


class AuditFilterForm(forms.Form):
    since = forms.DateField(label="Desde", required=False, widget=forms.DateInput(format="%Y-%m-%d", attrs={"type": "date"}))
    until = forms.DateField(label="Hasta", required=False, widget=forms.DateInput(format="%Y-%m-%d", attrs={"type": "date"}))
    actor = forms.CharField(label="Usuario o funcionario", required=False, max_length=150)
    action = forms.CharField(label="Acción", required=False, max_length=100)
    entity = forms.CharField(label="Entidad", required=False, max_length=100)
    record = forms.IntegerField(label="ID del registro afectado", required=False, min_value=1, max_value=2147483647)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs["class"] = "form-control"

    def clean(self):
        data = super().clean()
        if data.get("since") and data.get("until") and data["since"] > data["until"]:
            self.add_error("until", "El término debe ser igual o posterior al inicio.")
        return data

    def results(self, records):
        if not self.is_valid():
            return records.none()
        data = self.cleaned_data
        if data["since"]:
            records = records.filter(date__gte=timezone.make_aware(datetime.combine(data["since"], time.min)))
        if data["until"] and data["until"] != date.max:
            records = records.filter(date__lte=timezone.make_aware(datetime.combine(data["until"], time.max)))
        if data["actor"]:
            historical = Q(official__full_name__icontains=data["actor"]) & ~Q(action="Solicitud de recuperación de contraseña")
            records = records.filter(Q(actor_username__icontains=data["actor"]) | historical)
        for field, lookup in (("action", "action__icontains"), ("entity", "affected_table__icontains"),
                              ("record", "affected_record_id")):
            if data[field]:
                records = records.filter(**{lookup: data[field]})
        return records


class AuditAccess(ProtectedViewMixin, View):
    permission_required = VIEW_AUDIT

    def has_permission(self):
        return super().has_permission() and can_view_audit(self.request.user)

    def dispatch(self, request, *args, **kwargs):
        if request.method not in READ_METHODS:
            log_mutation_attempt(request, kwargs.get("pk"))
            raise PermissionDenied("La bitácora es de solo lectura.")
        return super().dispatch(request, *args, **kwargs)

    def records(self):
        return AuditLog.objects.filter(deleted_at__isnull=True).select_related("official")


class AuditList(AuditAccess):
    def get(self, request):
        form = AuditFilterForm(request.GET)
        records = form.results(self.records()).defer("previous_value", "new_value").order_by("-date", "-pk")
        return render(request, "configuration/audit_list.html", {
            "form": form, "page_obj": Paginator(records, 25).get_page(request.GET.get("page")),
        })


class AuditDetail(AuditAccess):
    def get(self, request, pk):
        event = get_object_or_404(self.records(), pk=pk)
        return render(request, "configuration/audit_detail.html", {
            "event": event, "before": visible_value(event, event.previous_value),
            "after": visible_value(event, event.new_value),
        })
