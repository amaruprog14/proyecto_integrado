from django.contrib import admin

from activities.models import Actividad
from .models import Area, Cargo, Funcionario


class ActividadInline(admin.TabularInline):
    model = Actividad
    extra = 0
    autocomplete_fields = ("item",)


# accounts/admin.py
@admin.register(Cargo)
class CargoAdmin(admin.ModelAdmin):
    list_display = ("nombre_cargo", "vigente", "created_at", "updated_at", "deleted_at")
    list_filter = ("vigente",)
    search_fields = ("nombre_cargo",)
    ordering = ("nombre_cargo",)
    actions = ("activar_cargos", "desactivar_cargos")

    @admin.action(description="Activar cargos seleccionados")
    def activar_cargos(self, request, queryset):
        for cargo in queryset.iterator():
            cargo.activar_cargo()

    @admin.action(description="Desactivar cargos seleccionados")
    def desactivar_cargos(self, request, queryset):
        for cargo in queryset.iterator():
            cargo.desactivar_cargo()


@admin.register(Area)
class AreaAdmin(admin.ModelAdmin):
    list_display = ("nombre_area", "vigente", "created_at", "updated_at", "deleted_at")
    list_filter = ("vigente",)
    search_fields = ("nombre_area",)
    ordering = ("nombre_area",)


@admin.register(Funcionario)
class FuncionarioAdmin(admin.ModelAdmin):
    list_display = ("nombre_completo", "rut_identificador", "email", "cargo", "estado", "created_at", "deleted_at")
    list_filter = ("estado", "cargo", "deleted_at")
    search_fields = ("nombre_completo", "rut_identificador", "email", "cargo__nombre_cargo")
    ordering = ("nombre_completo",)
    list_select_related = ("cargo",)
    inlines = (ActividadInline,)