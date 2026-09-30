from django.contrib import admin

from .models import Item, Period


@admin.register(Item)
class ItemAdmin(admin.ModelAdmin):
    list_display = ("item_name", "is_active", "created_at", "updated_at", "deleted_at")
    list_filter = ("is_active",)
    search_fields = ("item_name",)
    ordering = ("item_name",)


@admin.register(Period)
class PeriodAdmin(admin.ModelAdmin):
    list_display = ("start_date", "end_date", "status", "created_at", "updated_at")
    list_filter = ("status",)
    search_fields = ("status",)
    ordering = ("-start_date",)
    date_hierarchy = "start_date"
    actions = ("close_periods",)

    @admin.action(description="Cerrar períodos seleccionados")
    def close_periods(self, request, queryset):
        for period in queryset.iterator():
            period.close_period()