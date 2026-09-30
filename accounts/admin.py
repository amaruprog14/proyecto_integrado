from django.contrib import admin

from activities.models import Activity
from .models import Area, Official, Position


class ActivityInline(admin.TabularInline):
    model = Activity
    extra = 0
    autocomplete_fields = ("item",)


# accounts/admin.py
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
    list_display = ("full_name", "national_id", "email", "position", "status", "created_at", "deleted_at")
    list_filter = ("status", "position", "deleted_at")
    search_fields = ("full_name", "national_id", "email", "position__position_name")
    ordering = ("full_name",)
    list_select_related = ("position",)
    inlines = (ActivityInline,)