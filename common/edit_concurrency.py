import json

from django.http import JsonResponse
from django.utils.crypto import constant_time_compare, salted_hmac


def edit_revision(instance, *, memberships=(), exclude=()):
    """Versión opaca del estado persistido, incluidas las relaciones editables.

    `exclude` omite campos que cambian sin una edición real (p. ej. `last_login` de la cuenta).
    """
    values = [str(getattr(instance, field.attname)) for field in instance._meta.concrete_fields
              if field.attname not in exclude]
    state = json.dumps([instance._meta.label_lower, values, [sorted(ids) for ids in memberships]])
    return salted_hmac("sgr.edit_revision", state, algorithm="sha256").hexdigest()


def edit_is_current(request, revision):
    return constant_time_compare(request.POST.get("edit_revision", ""), revision)


def edit_conflict():
    return JsonResponse({"code": "edit_conflict"}, status=409)
