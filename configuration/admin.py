from django.contrib import admin

from .models import Item, Periodo


@admin.register(Item)
class ItemAdmin(admin.ModelAdmin):
    list_display = ("nombre_item", "vigente", "created_at", "updated_at", "deleted_at")
    list_filter = ("vigente",)
    search_fields = ("nombre_item",)
    ordering = ("nombre_item",)


@admin.register(Periodo)
class PeriodoAdmin(admin.ModelAdmin):
    list_display = ("fecha_inicio", "fecha_termino", "estado", "created_at", "updated_at")
    list_filter = ("estado",)
    search_fields = ("estado",)
    ordering = ("-fecha_inicio",)
    date_hierarchy = "fecha_inicio"
    actions = ("cerrar_periodos",)

    @admin.action(description="Cerrar períodos seleccionados")
    def cerrar_periodos(self, request, queryset):
        for periodo in queryset.iterator():
            periodo.cerrar_periodo()