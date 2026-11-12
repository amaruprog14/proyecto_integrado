from django.db.models import F, Q
from django.utils import timezone

from accounts.models import Role
from common.scopes import delegation_ids, permission_scope
from configuration.services import AuditoriaService

from .models import AttentionCase, AttentionCaseEvent, ClientRequest, ClientRequestEvent


VIEW_CASE = "activities.view_socialattention"
CHANGE_CASE = "activities.change_socialattention"
ADD_ATTENTION = "activities.add_socialattention"


def scoped_cases(user, permission=VIEW_CASE):
    cases = AttentionCase.objects.filter(deleted_at__isnull=True).filter(
        Q(client_request__isnull=True) | Q(client_request__deleted_at__isnull=True,
            client_request__recipient_id=F("recipient_id"), client_request__delegation_id=F("delegation_id")),
    ).select_related("recipient", "delegation", "responsible", "client_request")
    scope = permission_scope(user, permission)
    if scope == Role.Scope.ALL:
        return cases
    if scope == Role.Scope.DELEGATION:
        return cases.filter(delegation_id__in=delegation_ids(user))
    if scope == Role.Scope.OWN:
        official = user.official
        own = Q(responsible=official)
        own |= Q(direct_status=AttentionCase.DirectStatus.RECORDED, attentions__responsible=official,
                 attentions__deleted_at__isnull=True)
        return cases.filter(Q(client_request__isnull=True) & own).distinct()
    return cases.none()


def change_request_status(case, status, actor, response=None):
    origin = case.client_request
    if response is not None:
        origin.response = response
    origin.status = status
    origin.save(update_fields=["status", "response", "updated_at"])
    ClientRequestEvent.objects.create(request=origin, status=status, response=response or "", actor=actor)


def assign_case(case, actor):
    if case.responsible_id is None:
        case.responsible = actor
    if case.client_request_id:
        if case.status == ClientRequest.Status.RECEIVED:
            change_request_status(case, ClientRequest.Status.REVIEW, actor)
    else:
        case.direct_status = AttentionCase.DirectStatus.REVIEW


def record_case_event(case, actor, title, detail="", public_text=""):
    AttentionCaseEvent.objects.create(case=case, actor=actor, title=title, detail=detail, public_text=public_text)
    AuditoriaService.register_change(actor, title, case, new_value=detail or case.identifier)


def case_timeline(case, public=False):
    entries = []
    if case.client_request_id:
        for event in case.client_request.events.select_related("actor"):
            entries.append({"when": event.created_at, "title": event.get_status_display(),
                            "detail": event.response, "actor": None if public else event.actor})
        if not entries:
            entries.append({"when": case.client_request.created_at, "title": "Solicitud recibida"})
    elif case.direct_status != AttentionCase.DirectStatus.RECORDED:
        entries.append({"when": case.created_at, "title": "Caso presencial registrado"})
    for attention in case.attentions.filter(deleted_at__isnull=True).select_related("attention_type", "responsible"):
        when = timezone.localtime(attention.registered_at)
        if public:
            entries.append({"when": when, "effective_date": attention.date, "title": "Gestión registrada"})
        else:
            entries.append({"when": when, "effective_date": attention.date, "title": str(attention.attention_type),
                            "detail": attention.result or attention.description, "actor": attention.responsible,
                            "attention_id": attention.pk, "attention_code": attention.identifier})
    for event in case.events.select_related("actor"):
        if public and not event.public_text:
            continue
        entries.append({"when": event.created_at, "title": "Actualización del caso" if public else event.title,
                        "detail": event.public_text if public else event.detail,
                        "actor": None if public else event.actor})
    return sorted(entries, key=lambda event: event["when"], reverse=True)
