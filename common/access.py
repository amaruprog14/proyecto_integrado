from django.contrib.auth.mixins import PermissionRequiredMixin
from django.http import Http404
from django.utils.cache import add_never_cache_headers

from configuration.services import AuditoriaService


def _denied_entity(request):
    match = request.resolver_match
    return (match.view_name if match else request.path)[:100]


def register_denied_access(request, required_permissions):
    """Deja en la auditoría el intento de acceso a una ruta sin autorización."""
    AuditoriaService.register_event(
        official=getattr(request.user, "official", None),
        action="Acceso denegado",
        entity=_denied_entity(request),
        new_value=f"{request.method} {request.path} · requiere: {', '.join(required_permissions)}",
        origin_ip=request.META.get("REMOTE_ADDR") or None,
    )


def get_scoped_object_or_404(request, scoped_queryset, **lookup):
    """
    Como get_object_or_404 sobre el queryset del ámbito (delegaciones autorizadas). Si el registro
    existe pero está fuera del ámbito, la respuesta es la misma (404, sin revelar nada), pero el
    intento queda en la auditoría como acceso denegado (SEG-01: evento trazable).
    """
    model = scoped_queryset.model
    try:
        return scoped_queryset.get(**lookup)
    except model.DoesNotExist:
        existing = model._default_manager.filter(**lookup).values_list("pk", flat=True).first()
        if existing is not None:
            AuditoriaService.register_event(
                official=getattr(request.user, "official", None),
                action="Acceso denegado",
                entity=_denied_entity(request),
                new_value=(
                    f"{request.method} {request.path} · registro fuera del ámbito de delegación "
                    f"({model._meta.label_lower} {existing})"
                ),
                record_id=existing,
                origin_ip=request.META.get("REMOTE_ADDR") or None,
            )
        raise Http404("No se encontró el registro solicitado.")


class ScopedObjectMixin:
    """get_object() de vistas de detalle y edición con get_scoped_object_or_404."""

    def get_object(self, queryset=None):
        queryset = self.get_queryset() if queryset is None else queryset
        return get_scoped_object_or_404(self.request, queryset, pk=self.kwargs[self.pk_url_kwarg])


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
