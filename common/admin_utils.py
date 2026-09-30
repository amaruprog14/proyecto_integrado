from django.core.exceptions import PermissionDenied


def get_user_area(request):
    """
    Devuelve el Area a la que pertenece el usuario autenticado.

    - Superusuario: devuelve None (acceso global, excepcion explicita).
    - Usuario sin Official, sin area, o con Official archivado:
      PermissionDenied. La falta de contexto NUNCA amplia el acceso.
    """
    if request.user.is_superuser:
        return None

    official = getattr(request.user, "official", None)
    if official is None or official.area_id is None or official.deleted_at is not None:
        raise PermissionDenied("El usuario no posee un área asignada.")

    return official.area
