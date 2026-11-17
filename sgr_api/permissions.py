from rest_framework.permissions import BasePermission

from accounts.backends import SGRAuthBackend
from accounts.models import Role
from analytics.queries import TEAM_PERFORMANCE, VIEW_PERFORMANCE
from common.access import register_denied_access
from common.scopes import permission_scope


def api_account_enabled(user):
    if user is None or not user.is_authenticated or not SGRAuthBackend().user_can_authenticate(user):
        return False
    official = getattr(user, "official", None)
    return user.is_superuser or (official is not None and official.is_enabled)


class CanViewPerformance(BasePermission):
    required = (VIEW_PERFORMANCE,)

    def allowed(self, user):
        return api_account_enabled(user) and user.has_perms(self.required)

    def has_permission(self, request, view):
        allowed = self.allowed(request.user)
        if not allowed and request.user.is_authenticated:
            register_denied_access(request, self.required)
        return allowed


class CanViewTeamPerformance(CanViewPerformance):
    required = (VIEW_PERFORMANCE, TEAM_PERFORMANCE)

    def allowed(self, user):
        return super().allowed(user) and permission_scope(user, TEAM_PERFORMANCE) in (
            Role.Scope.ALL, Role.Scope.DELEGATION,
        )
