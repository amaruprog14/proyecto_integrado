from django.contrib import admin

from .models import Actividad


@admin.register(Actividad)
class ActividadAdmin(admin.ModelAdmin):
    list_display = ("id", "funcionario", "item", "fecha", "tipo_registro", "created_at", "deleted_at")
    list_filter = ("item", "fecha", "tipo_registro")
    search_fields = ("descripcion_accion", "funcionario__nombre_completo", "item__nombre_item")
    ordering = ("-fecha",)
    list_select_related = ("funcionario", "item")
    autocomplete_fields = ("funcionario", "item")