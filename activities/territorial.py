from django.db.models import Q

from accounts.models import Delegation, Role
from common.scopes import delegation_ids, permission_scope


def activities_in_delegations(queryset, ids):
    return queryset.filter(
        Q(social_attentions__delegation_id__in=ids)
        | Q(social_attentions__isnull=True, registration_delegation_id__in=ids)
    )


def registration_delegations(official, user, permission):
    if official is None:
        return Delegation.objects.none()
    choices = Delegation.objects.filter(status=Delegation.Status.ACTIVE, deleted_at__isnull=True).filter(
        Q(pk=official.delegation_id) | Q(pk__in=official.authorized_delegations.values("pk")),
    )
    scope = permission_scope(user, permission)
    if scope == Role.Scope.ALL:
        return choices
    if scope in (Role.Scope.DELEGATION, Role.Scope.OWN):
        return choices.filter(pk__in=delegation_ids(user))
    return choices.none()
