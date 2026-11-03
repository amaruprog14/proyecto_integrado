from contextvars import ContextVar
current_permission = ContextVar("sgr_permission", default=None)

from django.db.models import Q
from accounts.models import Role


def permission_scope(user, permission):
    if user.is_superuser:
        return Role.Scope.ALL
    official = getattr(user, "official", None)
    if not user.is_authenticated or official is None or not official.is_enabled:
        return None
    app, code = permission.split(".")
    match = dict(permissions__content_type__app_label=app, permissions__codename=code)
    scopes = set(official.roles.filter(is_active=True, deleted_at__isnull=True, **match).values_list("scope", flat=True))
    scopes.update(user.groups.filter(sgr_profile__is_active=True,
        sgr_profile__deleted_at__isnull=True, **match).values_list("sgr_profile__scope", flat=True))
    if user.user_permissions.filter(content_type__app_label=app, codename=code).exists():
        scopes.add(Role.Scope.DELEGATION)
    return next((scope for scope in (Role.Scope.ALL, Role.Scope.DELEGATION, Role.Scope.OWN) if scope in scopes), None)


def delegation_ids(user):
    official = getattr(user, "official", None)
    if official is None:
        return set()
    ids = set(official.authorized_delegations.values_list("pk", flat=True))
    if official.delegation_id:
        ids.add(official.delegation_id)
    return ids


def scope_officials(queryset, user, permission):
    scope = permission_scope(user, permission)
    if scope == Role.Scope.ALL:
        return queryset
    if scope == Role.Scope.OWN:
        return queryset.filter(user=user)
    if scope == Role.Scope.DELEGATION:
        ids = delegation_ids(user)
        return queryset.filter(Q(delegation_id__in=ids) | Q(authorized_delegations__in=ids)).distinct()
    return queryset.none()
