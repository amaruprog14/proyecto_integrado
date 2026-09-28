from django.contrib import admin

from .models import Item, Periodo


@admin.register(Item)
class ItemAdmin(admin.ModelAdmin):
    list_display = ("nombre_item", "vigente", "created_at")
    list_filter = ("vigente",)
    search_fields = ("nombre_item",)


@admin.register(Periodo)
class PeriodoAdmin(admin.ModelAdmin):
    list_display = ("fecha_inicio", "fecha_termino", "estado", "created_at")
    list_filter = ("estado",)