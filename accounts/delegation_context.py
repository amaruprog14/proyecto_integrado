from accounts.models import Delegation, Role

ACTIVE_DELEGATION_SESSION_KEY = "active_delegation_id"


def authorized_active_delegations(user):
    if not user.is_authenticated:
        return Delegation.objects.none()
    if user.is_superuser:
        return Delegation.objects.filter(
            status=Delegation.Status.ACTIVE,
            deleted_at__isnull=True,
        ).order_by("delegation_name", "pk")

    official = getattr(user, "official", None)
    if official is None or not official.is_enabled:
        return Delegation.objects.none()
    if official.roles.filter(
        is_active=True,
        deleted_at__isnull=True,
        scope=Role.Scope.ALL,
    ).exists():
        return Delegation.objects.filter(
            status=Delegation.Status.ACTIVE,
            deleted_at__isnull=True,
        ).order_by("delegation_name", "pk")
    delegation_ids = set(
        official.authorized_delegations.values_list("pk", flat=True)
    )
    if official.delegation_id:
        delegation_ids.add(official.delegation_id)
    return Delegation.objects.filter(
        pk__in=delegation_ids,
        status=Delegation.Status.ACTIVE,
        deleted_at__isnull=True
    ).order_by("delegation_name", "pk")


def get_active_delegation(request, authorized_delegations=None):
    allowed = list(
        authorized_delegations
        if authorized_delegations is not None
        else authorized_active_delegations(request.user)
    )
    if len(allowed) == 1:
        delegation = allowed[0]
        request.session[ACTIVE_DELEGATION_SESSION_KEY] = delegation.pk
        return delegation

    selected_id = request.session.get(ACTIVE_DELEGATION_SESSION_KEY)
    if selected_id is not None:
        delegation = next((item for item in allowed if str(item.pk) == str(selected_id)), None)
        if delegation is not None:
            return delegation
        request.session.pop(ACTIVE_DELEGATION_SESSION_KEY, None)

    official = getattr(request.user, "official", None)
    if official is not None and official.delegation_id:
        delegation = next(
            (item for item in allowed if item.pk == official.delegation_id), None
        )
        if delegation is not None:
            request.session[ACTIVE_DELEGATION_SESSION_KEY] = delegation.pk
            return delegation
    if allowed and official is not None:
        request.session[ACTIVE_DELEGATION_SESSION_KEY] = allowed[0].pk
        return allowed[0]
    return None


def active_delegation_context(request):
    delegations = list(authorized_active_delegations(request.user))
    active_delegation = get_active_delegation(request, delegations)
    return {
        "active_delegation": active_delegation,
        "authorized_active_delegations": delegations,
        "can_select_active_delegation": len(delegations) > 1,
    }
