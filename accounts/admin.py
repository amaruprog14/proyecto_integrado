from django.contrib import admin

from .models import Area, Cargo, Funcionario


@admin.register(Cargo)
class CargoAdmin(admin.ModelAdmin):
    list_display = ("nombre_cargo", "vigente", "created_at")
    list_filter = ("vigente",)
    search_fields = ("nombre_cargo",)


@admin.register(Area)
class AreaAdmin(admin.ModelAdmin):
    list_display = ("nombre_area", "vigente", "created_at")
    list_filter = ("vigente",)
    search_fields = ("nombre_area",)


@admin.register(Funcionario)
class FuncionarioAdmin(admin.ModelAdmin):
    list_display = ("nombre_completo", "rut_identificador", "email", "cargo", "estado")
    list_filter = ("estado", "cargo")
    search_fields = ("nombre_completo", "rut_identificador", "email")