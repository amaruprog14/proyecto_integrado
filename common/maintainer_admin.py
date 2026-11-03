"""El Admin remite al mantenedor para compartir validación, alcance y auditoría."""
from django.contrib import admin
from django.shortcuts import redirect


class MaintainerAdmin(admin.ModelAdmin):
    maintainer_key = None
    actions = None

    def changelist_view(self, request, extra_context=None):
        if not self.has_view_or_change_permission(request):
            from django.core.exceptions import PermissionDenied
            raise PermissionDenied
        return redirect(f"{self.maintainer_key}_maintainer")

    def changeform_view(self, request, object_id=None, form_url="", extra_context=None):
        from django.core.exceptions import PermissionDenied
        if object_id is None and not self.has_add_permission(request):
            raise PermissionDenied
        if request.method == "POST" and not self.has_change_permission(request):
            raise PermissionDenied
        return self.changelist_view(request, extra_context)

    def has_delete_permission(self, request, obj=None):
        return False
