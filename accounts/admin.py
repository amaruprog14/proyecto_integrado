from django.contrib import admin

from activities.models import Activity
from common.admin_utils import get_user_area
from .models import Area, Official, Position


class ActivityInline(admin.TabularInline):
    model = Activity
    extra = 0
    autocomplete_fields = ("item",)


@admin.register(Position)
class PositionAdmin(admin.ModelAdmin):
    list_display = ("position_name", "is_active", "created_at", "updated_at", "deleted_at")
    list_filter = ("is_active",)
    search_fields = ("position_name",)
    ordering = ("position_name",)
    actions = ("activate_positions", "deactivate_positions")

    @admin.action(description="Activar cargos seleccionados")
    def activate_positions(self, request, queryset):
        for position in queryset.iterator():
            position.activate_position()

    @admin.action(description="Desactivar cargos seleccionados")
    def deactivate_positions(self, request, queryset):
        for position in queryset.iterator():
            position.deactivate_position()


@admin.register(Area)
class AreaAdmin(admin.ModelAdmin):
    list_display = ("area_name", "is_active", "created_at", "updated_at", "deleted_at")
    list_filter = ("is_active",)
    search_fields = ("area_name",)
    ordering = ("area_name",)


@admin.register(Official)
class OfficialAdmin(admin.ModelAdmin):
    list_display = ("full_name", "national_id", "email", "area", "position", "status", "created_at", "deleted_at")
    list_filter = ("status", "area", "position", "deleted_at")
    search_fields = ("full_name", "national_id", "email", "position__position_name", "area__area_name")
    ordering = ("full_name",)
    list_select_related = ("position", "area")
    inlines = (ActivityInline,)

    # --- SCOPING (capa 2: queryset) ---
    def get_queryset(self, request):
        qs = super().get_queryset(request)
        area = get_user_area(request)          # None = superusuario
        if area is None:
            return qs
        return qs.filter(area=area, deleted_at__isnull=True)

    # --- SCOPING (capa 1 por objeto: permiso) ---
    def has_change_permission(self, request, obj=None):
        allowed = super().has_change_permission(request, obj)
        if not allowed:
            return False
        if obj is None or request.user.is_superuser:
            return True
        return obj.area_id == get_user_area(request).id

    def has_delete_permission(self, request, obj=None):
        return request.user.is_superuser and super().has_delete_permission(request, obj)

    # --- SCOPING (capa 3: el area no la decide el navegador) ---
    def save_model(self, request, obj, form, change):
        if not request.user.is_superuser:
            obj.area = get_user_area(request)
        super().save_model(request, obj, form, change)
