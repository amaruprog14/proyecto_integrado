import json

from django.http import JsonResponse
from django.utils.crypto import constant_time_compare, salted_hmac


def edit_revision(instance, *, memberships=()):
    """Versión opaca del estado persistido, incluidas las relaciones editables."""
    values = [str(getattr(instance, field.attname)) for field in instance._meta.concrete_fields]
    state = json.dumps([instance._meta.label_lower, values, [sorted(ids) for ids in memberships]])
    return salted_hmac("sgr.edit_revision", state, algorithm="sha256").hexdigest()


def edit_is_current(request, revision):
    return constant_time_compare(request.POST.get("edit_revision", ""), revision)


def edit_conflict():
    return JsonResponse({"code": "edit_conflict"}, status=409)
