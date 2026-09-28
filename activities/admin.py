from django.contrib import admin

from .models import Actividad


@admin.register(Actividad)
class ActividadAdmin(admin.ModelAdmin):
    list_display = ("id", "funcionario", "item", "fecha", "tipo_registro")
    list_filter = ("item", "fecha")
    search_fields = ("descripcion_accion",)
    autocomplete_fields = ("funcionario", "item")