from datetime import timedelta

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db.models import Q
from django.utils import timezone

from accounts.models import Delegation, Official, Role
from common.scopes import delegation_ids, permission_scope
from configuration.models import Period

from .models import Commitment


VIEW = "agenda.view_commitment"
ADD = "agenda.add_commitment"
CHANGE = "agenda.change_commitment"
ASSIGN = "agenda.assign_commitment"


def scoped_commitments(user, permission=VIEW):
    records = Commitment.objects.filter(deleted_at__isnull=True)
    scope = permission_scope(user, permission)
    if scope == Role.Scope.ALL:
        return records
    if scope == Role.Scope.DELEGATION:
        ids = delegation_ids(user)
        return records.filter(Q(delegation_id__in=ids) |
                              Q(delegation_id__isnull=True, responsible__delegation_id__in=ids))
    if scope == Role.Scope.OWN:
        return records.filter(responsible__user=user)
    return records.none()


def scoped_delegations(user, permission=ADD):
    delegations = Delegation.objects.filter(status=Delegation.Status.ACTIVE, deleted_at__isnull=True)
    if permission_scope(user, permission) != Role.Scope.ALL:
        delegations = delegations.filter(pk__in=delegation_ids(user))
    return delegations


def available_responsibles(user, delegation, permission=ASSIGN):
    officials = Official.objects.filter(status=Official.Status.ACTIVE, deleted_at__isnull=True)
    if delegation is None:
        return officials.none()
    officials = officials.filter(Q(delegation=delegation) | Q(authorized_delegations=delegation)).distinct()
    scope = permission_scope(user, permission)
    if scope == Role.Scope.ALL or (scope == Role.Scope.DELEGATION and delegation.pk in delegation_ids(user)):
        return officials
    return officials.filter(user=user)


def validate_commitment_date(date):
    if Period.objects.filter(status=Period.Status.CLOSED, start_date__lte=date, end_date__gte=date,
                             deleted_at__isnull=True).exists():
        raise ValidationError("La fecha comprometida pertenece a un período cerrado.")


def deadline_labels(record, today=None):
    today = today or timezone.localdate()
    if record.current_status == Commitment.Status.DONE:
        if record.completed_on and record.completed_on > record.committed_date:
            return "Realizado fuera de plazo"
        return ""
    if record.current_status == Commitment.Status.CANCELLED:
        return ""
    if record.committed_date < today:
        return "Vencido"
    if record.committed_date == today:
        return "Vence hoy"
    if record.committed_date <= today + timedelta(days=settings.COMMITMENT_DUE_WARNING_DAYS):
        return "Próximo a vencer"
    return ""
