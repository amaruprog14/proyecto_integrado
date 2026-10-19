from django.contrib.auth import get_user_model
from django.contrib.auth.backends import ModelBackend
from django.contrib.auth.models import Permission

from . import login_security
from .models import Official


def _single(queryset):
    """El único resultado de la consulta, o None si no hay o es ambiguo."""
    matches = list(queryset[:2])
    return matches[0] if len(matches) == 1 else None


def find_user_by_email(email):
    """
    Usuario dueño de un correo. Primero se busca en el funcionario (correo único) y luego
    en el usuario de Django; un correo repetido entre usuarios no identifica a nadie.
    """
    email = (email or "").strip()
    if not email:
        return None
    official = _single(
        Official.objects.filter(email__iexact=email, user__isnull=False).select_related("user")
    )
    if official is not None:
        return official.user
    return _single(get_user_model()._default_manager.filter(email__iexact=email))


class SGRAuthBackend(ModelBackend):
    """
    Autenticación y permisos del SGR (reemplaza a ModelBackend).

    - Ingreso con nombre de usuario o correo electrónico.
    - Bloqueo temporal tras varios intentos fallidos (accounts.login_security). Se aplica aquí
      para que cubra todo ingreso con contraseña, también el del Admin.
    - Un funcionario Inactivo, Suspendido o archivado no puede autenticarse, y una sesión ya
      abierta deja de reconocerse en la siguiente petición (get_user usa la misma regla).
    - Además de los permisos propios y de grupos, otorga los permisos de los roles SGR
      vigentes (activos y no archivados) del funcionario.
    """

    def authenticate(self, request, username=None, password=None, **kwargs):
        UserModel = get_user_model()
        if username is None:
            username = kwargs.get(UserModel.USERNAME_FIELD)
        if username is None or password is None:
            return None

        identifier = username.strip()
        user = self.find_user(identifier)
        key = login_security.throttle_key(identifier, user)
        if login_security.is_locked(key):
            login_security.reject_locked_attempt(request, identifier, user)
            return None
        if user is None:
            # Igual que ModelBackend: se calcula un hash para no revelar por tiempo si la cuenta existe.
            UserModel().set_password(password)
        elif user.check_password(password) and self.user_can_authenticate(user):
            login_security.reset_failures(key)
            return user
        login_security.record_failed_attempt(request, identifier, user, key)
        return None

    @staticmethod
    def find_user(identifier):
        UserModel = get_user_model()
        try:
            return UserModel._default_manager.get_by_natural_key(identifier)
        except UserModel.DoesNotExist:
            pass
        if "@" in identifier:
            return find_user_by_email(identifier)
        return None

    def user_can_authenticate(self, user):
        if not super().user_can_authenticate(user):
            return False
        official = getattr(user, "official", None)
        return official is None or official.is_enabled

    def get_role_permissions(self, user_obj, obj=None):
        """Permisos ("app_label.codename") de los roles SGR vigentes del funcionario."""
        if not user_obj.is_active or user_obj.is_anonymous or obj is not None:
            return set()
        if not hasattr(user_obj, "_role_perm_cache"):
            perms = (
                Permission.objects.filter(
                    sgr_roles__is_active=True,
                    sgr_roles__deleted_at__isnull=True,
                    sgr_roles__officials__user=user_obj,
                    sgr_roles__officials__status=Official.Status.ACTIVE,
                    sgr_roles__officials__deleted_at__isnull=True,
                )
                .values_list("content_type__app_label", "codename")
                .order_by()
            )
            user_obj._role_perm_cache = {f"{app_label}.{codename}" for app_label, codename in perms}
        return user_obj._role_perm_cache

    def get_all_permissions(self, user_obj, obj=None):
        if not user_obj.is_active or user_obj.is_anonymous or obj is not None:
            return set()
        if not hasattr(user_obj, "_sgr_perm_cache"):
            user_obj._sgr_perm_cache = {
                *super().get_all_permissions(user_obj),
                *self.get_role_permissions(user_obj),
            }
        return user_obj._sgr_perm_cache
