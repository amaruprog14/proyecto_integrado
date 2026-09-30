from django.contrib import admin, messages
from django.utils import timezone

from accounts.models import Official
from common.admin_utils import get_user_area
from .models import Activity


@admin.action(description="Archivar actividades seleccionadas", permissions=["change"])
def archive_activities(modeladmin, request, queryset):
    """Borrado lógico: marca deleted_at. El queryset ya viene acotado por área."""
    now = timezone.now()
    updated = queryset.filter(deleted_at__isnull=True).update(deleted_at=now, updated_at=now)
    modeladmin.message_user(request, f"{updated} actividad(es) archivada(s).", level=messages.SUCCESS)


@admin.register(Activity)
class ActivityAdmin(admin.ModelAdmin):
    list_display = ("id", "official", "item", "date", "record_type", "created_at", "deleted_at")
    list_filter = ("item", "date", "record_type")
    search_fields = ("action_description", "official__full_name", "item__item_name")
    ordering = ("-date",)
    list_select_related = ("official", "item")
    autocomplete_fields = ("official", "item")
    actions = (archive_activities,)

    # --- capa 2: queryset (solo actividades de funcionarios de mi área, no archivadas) ---
    def get_queryset(self, request):
        qs = super().get_queryset(request)
        area = get_user_area(request)
        if area is None:
            return qs
        return qs.filter(official__area=area, deleted_at__isnull=True)

    # --- capa 3: el selector solo ofrece funcionarios de mi área ---
    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == "official" and not request.user.is_superuser:
            kwargs["queryset"] = Official.objects.filter(
                area=get_user_area(request), deleted_at__isnull=True
            )
        return super().formfield_for_foreignkey(db_field, request, **kwargs)

    # --- segunda barrera por objeto (cubre acceso directo por URL) ---
    def has_change_permission(self, request, obj=None):
        allowed = super().has_change_permission(request, obj)
        if not allowed:
            return False
        if obj is None or request.user.is_superuser:
            return True
        return obj.official.area_id == get_user_area(request).id

    def has_delete_permission(self, request, obj=None):
        return False   # solo se archiva, no se elimina físicamente