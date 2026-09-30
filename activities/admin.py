from django.contrib import admin

from .models import Activity


@admin.register(Activity)
class ActivityAdmin(admin.ModelAdmin):
    list_display = ("id", "official", "item", "date", "record_type", "created_at", "deleted_at")
    list_filter = ("item", "date", "record_type")
    search_fields = ("action_description", "official__full_name", "item__item_name")
    ordering = ("-date",)
    list_select_related = ("official", "item")
    autocomplete_fields = ("official", "item")