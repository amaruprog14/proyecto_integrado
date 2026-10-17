from django.contrib.auth.mixins import PermissionRequiredMixin
from django.utils.cache import add_never_cache_headers

from configuration.services import AuditoriaService


def register_denied_access(request, required_permissions):
    """Deja en la auditoría el intento de acceso a una ruta sin autorización."""
    match = request.resolver_match
    AuditoriaService.register_event(
        official=getattr(request.user, "official", None),
        action="Acceso denegado",
        entity=(match.view_name if match else request.path)[:100],
        new_value=f"{request.method} {request.path} · requiere: {', '.join(required_permissions)}",
        origin_ip=request.META.get("REMOTE_ADDR") or None,
    )


class ProtectedViewMixin(PermissionRequiredMixin):
    """
    Control de acceso en el servidor para las pantallas del SGR.

    - Sin sesión: redirige al login conservando `next`.
    - Con sesión: exige `permission_required` (permisos propios, de grupo o de roles vigentes)
      y, salvo para el superusuario, un funcionario habilitado. La falta de contexto nunca
      amplía el acceso. Cada rechazo queda registrado en la auditoría (403).
    - Las respuestas no se guardan en caché, para que tras cerrar sesión el botón Atrás
      no muestre datos protegidos.
    """

    def has_permission(self):
        user = self.request.user
        if not user.is_superuser:
            official = getattr(user, "official", None)
            if official is None or not official.is_enabled:
                return False
        return super().has_permission()

    def handle_no_permission(self):
        if self.request.user.is_authenticated:
            register_denied_access(self.request, self.get_permission_required())
        return super().handle_no_permission()

    def dispatch(self, request, *args, **kwargs):
        response = super().dispatch(request, *args, **kwargs)
        add_never_cache_headers(response)
        return response
