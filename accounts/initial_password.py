from django.shortcuts import redirect
from django.utils.deprecation import MiddlewareMixin

from .models import InitialPassword


class InitialPasswordMiddleware(MiddlewareMixin):
    def process_view(self, request, view_func, view_args, view_kwargs):
        if request.resolver_match.view_name in {"password_change", "logout", "recovery_request", "recovery_confirm"}:
            return None
        if InitialPassword.pending(request.user):
            return redirect("password_change")
        return None
