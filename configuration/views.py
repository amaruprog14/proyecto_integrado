from django.contrib import messages
from django.db import transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse_lazy
from django.views.generic import CreateView, DetailView, ListView, TemplateView, UpdateView, View

from common.access import ProtectedViewMixin
from common.exports import xlsx_response
from common.modal_forms import ModalFormOnlyMixin
from common.pagination import ClampedPaginationMixin  # noqa: F401 (también se importaba desde aquí)
from common.text import describe_changes, format_snapshot
from configuration.services import AuditoriaService

from .forms import AttentionTypeForm, SubattentionTypeForm, catalog_snapshot
from .models import AttentionType, Period, SubattentionType


class PeriodMaintainerView(ProtectedViewMixin, TemplateView):
    permission_required = "configuration.view_period"
    template_name = "configuration/period_list.html"
    extra_context = {
        "maintainer_title": "Períodos",
        "maintainer_kind": "periods",
        "columns": ["Fecha de inicio", "Fecha de término", "Estado"],
        "statuses": ["Abierto", "Cerrado"],
        "records": [
            {
                "cells": ["01-01-2026", "31-03-2026", "Cerrado"],
                "status": "Cerrado",
                "status_is_active": False,
            },
            {
                "cells": ["01-04-2026", "30-06-2026", "Cerrado"],
                "status": "Cerrado",
                "status_is_active": False,
            },
            {
                "cells": ["01-07-2026", "30-09-2026", "Cerrado"],
                "status": "Cerrado",
                "status_is_active": False,
            },
            {
                "cells": ["01-10-2026", "31-12-2026", "Abierto"],
                "status": "Abierto",
                "status_is_active": True,
            },
            {
                "cells": ["01-01-2025", "31-03-2025", "Cerrado"],
                "status": "Cerrado",
                "status_is_active": False,
            },
            {
                "cells": ["01-04-2025", "30-06-2025", "Cerrado"],
                "status": "Cerrado",
                "status_is_active": False,
            },
        ],
    }


class CatalogListView(ClampedPaginationMixin, ProtectedViewMixin, ListView):
    paginate_by = 10
    context_object_name = "records"
    search_fields = ()

    def get_queryset(self):
        queryset = self.model.objects.filter(deleted_at__isnull=True).order_by("name", "pk")
        query = (self.request.GET.get("q") or "").strip()
        if query:
            search = Q()
            for field in self.search_fields:
                search |= Q(**{f"{field}__icontains": query})
            queryset = queryset.filter(search)

        selected_status = (self.request.GET.get("status") or "").strip()
        if selected_status in ("1", "0"):
            queryset = queryset.filter(is_active=(selected_status == "1"))
        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        params = self.request.GET.copy()
        params.pop(self.page_kwarg, None)
        context.update(
            maintainer_title=self.maintainer_title,
            maintainer_kind=self.maintainer_kind,
            query=(self.request.GET.get("q") or "").strip(),
            selected_status=(self.request.GET.get("status") or "").strip(),
            querystring=params.urlencode(),
            total=context["paginator"].count,
            can_add=self.request.user.has_perm(self.add_permission),
            can_change=self.request.user.has_perm(self.change_permission),
        )
        return context


class AttentionTypeMaintainerView(CatalogListView):
    permission_required = "configuration.view_attentiontype"
    model = AttentionType
    template_name = "configuration/attention_type_list.html"
    maintainer_title = "Tipos de Atención"
    maintainer_kind = "attention-types"
    add_permission = "configuration.add_attentiontype"
    change_permission = "configuration.change_attentiontype"
    search_fields = ("code", "name", "description")


class SubattentionTypeMaintainerView(CatalogListView):
    permission_required = "configuration.view_subattentiontype"
    model = SubattentionType
    template_name = "configuration/subattention_type_list.html"
    maintainer_title = "Sub Atención"
    maintainer_kind = "subattention-types"
    add_permission = "configuration.add_subattentiontype"
    change_permission = "configuration.change_subattentiontype"
    search_fields = ("code", "name", "attention_type__name")

    def get_queryset(self):
        return super().get_queryset().select_related("attention_type")


class CatalogExportView(ProtectedViewMixin, View):
    """
    Exportación a Excel de un catálogo. Sin permiso por defecto: una subclase que no declare
    permission_required falla (ImproperlyConfigured) en vez de quedar abierta.
    """

    model = None
    search_fields = ()
    filename = ""
    sheet_title = "Registros"
    headings = ()

    def get_queryset(self, request):
        queryset = self.model.objects.filter(deleted_at__isnull=True).order_by("name", "pk")
        query = (request.GET.get("q") or "").strip()
        if query:
            search = Q()
            for field in self.search_fields:
                search |= Q(**{f"{field}__icontains": query})
            queryset = queryset.filter(search)
        selected_status = (request.GET.get("status") or "").strip()
        if selected_status in ("1", "0"):
            queryset = queryset.filter(is_active=(selected_status == "1"))
        return queryset

    def row_values(self, record):
        raise NotImplementedError

    def get(self, request):
        return xlsx_response(
            self.filename,
            self.headings,
            (self.row_values(record) for record in self.get_queryset(request)),
            sheet_title=self.sheet_title,
        )


class AttentionTypeExportView(CatalogExportView):
    permission_required = "configuration.view_attentiontype"
    model = AttentionType
    search_fields = ("code", "name", "description")
    filename = "tipos-de-atencion"
    sheet_title = "Tipos de atención"
    headings = ("Código", "Nombre", "Descripción", "Estado")

    def row_values(self, record):
        return (record.code, record.name, record.description, "Activo" if record.is_active else "Inactivo")




class CatalogCreateView(ProtectedViewMixin, ModalFormOnlyMixin, CreateView):
    model = None
    form_class = None
    template_name = ""
    success_url = ""
    maintainer_title = ""
    list_url = ""
    audit_label = ""
    created_message = ""

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(
            maintainer_title=self.maintainer_title,
            form_mode="create",
            list_url=self.list_url,
        )
        return context

    def form_valid(self, form):
        with transaction.atomic():
            response = super().form_valid(form)
            AuditoriaService.register_change(
                official=getattr(self.request.user, "official", None),
                action=f"Creación de {self.audit_label}",
                instance=self.object,
                new_value=format_snapshot(catalog_snapshot(self.object)),
                origin_ip=self.request.META.get("REMOTE_ADDR") or None,
            )
        messages.success(self.request, self.created_message)
        return response

    def form_invalid(self, form):
        messages.error(self.request, "No se pudo guardar el registro. Revisa los datos ingresados.")
        return super().form_invalid(form)


class CatalogUpdateView(ProtectedViewMixin, ModalFormOnlyMixin, UpdateView):
    model = None
    form_class = None
    template_name = ""
    success_url = ""
    maintainer_title = ""
    list_url = ""
    audit_label = ""
    updated_message = ""

    def get_queryset(self):
        return self.model.objects.filter(deleted_at__isnull=True)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(
            maintainer_title=self.maintainer_title,
            form_mode="edit",
            list_url=self.list_url,
        )
        return context

    def form_valid(self, form):
        # self.object ya trae los valores del formulario: el anterior se lee de la base.
        previous_snapshot = catalog_snapshot(self.model.objects.get(pk=self.object.pk))
        with transaction.atomic():
            response = super().form_valid(form)
            previous, new = describe_changes(previous_snapshot, catalog_snapshot(self.object))
            AuditoriaService.register_change(
                official=getattr(self.request.user, "official", None),
                action=f"Actualización de {self.audit_label}",
                instance=self.object,
                previous_value=previous,
                new_value=new,
                origin_ip=self.request.META.get("REMOTE_ADDR") or None,
            )
        messages.success(self.request, self.updated_message)
        return response

    def form_invalid(self, form):
        messages.error(self.request, "No se pudo guardar el registro. Revisa los datos ingresados.")
        return super().form_invalid(form)


class CatalogDetailView(ProtectedViewMixin, DetailView):
    model = None
    template_name = ""
    context_object_name = "record"
    maintainer_title = ""
    change_permission = ""
    list_url = ""
    update_url = ""

    def get_queryset(self):
        return self.model.objects.filter(deleted_at__isnull=True)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(
            maintainer_title=self.maintainer_title,
            can_change=self.request.user.has_perm(self.change_permission),
            list_url=self.list_url,
            update_url=self.update_url,
        )
        return context


class CatalogSetActiveView(ProtectedViewMixin, View):
    model = None
    list_url = ""
    audit_label = ""
    # Sujeto con artículo para el mensaje de resultado, p. ej. "La subatención".
    record_label = ""
    feminine = False
    target_active = False

    def post(self, request, pk):
        record = get_object_or_404(self.model.objects.filter(deleted_at__isnull=True), pk=pk)
        if record.is_active == self.target_active:
            messages.info(
                request,
                "El registro ya estaba activo." if self.target_active else "El registro ya estaba inactivo.",
            )
            return redirect(self.list_url)

        if self.target_active and isinstance(record, SubattentionType) and not record.attention_type.is_active:
            messages.error(request, "Activa primero el tipo de atención asociado.")
            return redirect(self.list_url)

        if (
            not self.target_active
            and isinstance(record, AttentionType)
            and record.subattention_types.filter(is_active=True, deleted_at__isnull=True).exists()
        ):
            messages.error(
                request,
                "No se puede desactivar este tipo mientras tenga subatenciones activas.",
            )
            return redirect(self.list_url)

        previous = "Estado: Activo" if record.is_active else "Estado: Inactivo"
        record.is_active = self.target_active
        record.save(update_fields=("is_active", "updated_at"))
        current = "Estado: Activo" if record.is_active else "Estado: Inactivo"
        AuditoriaService.register_change(
            official=getattr(request.user, "official", None),
            action=f"{'Activación' if self.target_active else 'Desactivación'} de {self.audit_label}",
            instance=record,
            previous_value=previous,
            new_value=current,
            origin_ip=request.META.get("REMOTE_ADDR") or None,
        )
        state = "activad" if self.target_active else "desactivad"
        messages.success(
            request,
            f"{self.record_label} {record.name} fue {state}{'a' if self.feminine else 'o'} correctamente.",
        )
        return redirect(self.list_url)


class AttentionTypeCreateView(CatalogCreateView):
    permission_required = "configuration.add_attentiontype"
    model = AttentionType
    form_class = AttentionTypeForm
    template_name = "configuration/attention_type_form.html"
    success_url = reverse_lazy("attention_type_maintainer")
    maintainer_title = "Nuevo Tipo de Atención"
    list_url = "attention_type_maintainer"
    audit_label = "tipo de atención"
    created_message = "El tipo de atención fue creado correctamente."


class AttentionTypeUpdateView(CatalogUpdateView):
    permission_required = "configuration.change_attentiontype"
    model = AttentionType
    form_class = AttentionTypeForm
    template_name = "configuration/attention_type_form.html"
    success_url = reverse_lazy("attention_type_maintainer")
    maintainer_title = "Editar Tipo de Atención"
    list_url = "attention_type_maintainer"
    audit_label = "tipo de atención"
    updated_message = "El tipo de atención fue actualizado correctamente."


class AttentionTypeDetailView(CatalogDetailView):
    permission_required = "configuration.view_attentiontype"
    model = AttentionType
    template_name = "configuration/attention_type_detail.html"
    maintainer_title = "Detalle del Tipo de Atención"
    change_permission = "configuration.change_attentiontype"
    list_url = "attention_type_maintainer"
    update_url = "attention_type_update"


class AttentionTypeActivateView(CatalogSetActiveView):
    permission_required = "configuration.change_attentiontype"
    model = AttentionType
    list_url = "attention_type_maintainer"
    audit_label = "tipo de atención"
    record_label = "El tipo de atención"
    target_active = True


class AttentionTypeDeactivateView(CatalogSetActiveView):
    permission_required = "configuration.change_attentiontype"
    model = AttentionType
    list_url = "attention_type_maintainer"
    audit_label = "tipo de atención"
    record_label = "El tipo de atención"


class SubattentionTypeCreateView(CatalogCreateView):
    permission_required = "configuration.add_subattentiontype"
    model = SubattentionType
    form_class = SubattentionTypeForm
    template_name = "configuration/subattention_type_form.html"
    success_url = reverse_lazy("subattention_type_maintainer")
    maintainer_title = "Nueva Sub Atención"
    list_url = "subattention_type_maintainer"
    audit_label = "subatención"
    created_message = "La subatención fue creada correctamente."


class SubattentionTypeUpdateView(CatalogUpdateView):
    permission_required = "configuration.change_subattentiontype"
    model = SubattentionType
    form_class = SubattentionTypeForm
    template_name = "configuration/subattention_type_form.html"
    success_url = reverse_lazy("subattention_type_maintainer")
    maintainer_title = "Editar Sub Atención"
    list_url = "subattention_type_maintainer"
    audit_label = "subatención"
    updated_message = "La subatención fue actualizada correctamente."


class SubattentionTypeDetailView(CatalogDetailView):
    permission_required = "configuration.view_subattentiontype"
    model = SubattentionType
    template_name = "configuration/subattention_type_detail.html"
    maintainer_title = "Detalle de Sub Atención"
    change_permission = "configuration.change_subattentiontype"
    list_url = "subattention_type_maintainer"
    update_url = "subattention_type_update"


class SubattentionTypeActivateView(CatalogSetActiveView):
    permission_required = "configuration.change_subattentiontype"
    model = SubattentionType
    list_url = "subattention_type_maintainer"
    audit_label = "subatención"
    record_label = "La subatención"
    feminine = True
    target_active = True


class SubattentionTypeDeactivateView(CatalogSetActiveView):
    permission_required = "configuration.change_subattentiontype"
    model = SubattentionType
    list_url = "subattention_type_maintainer"
    audit_label = "subatención"
    record_label = "La subatención"
    feminine = True


class SubattentionTypeExportView(CatalogExportView):
    permission_required = "configuration.view_subattentiontype"
    model = SubattentionType
    search_fields = ("code", "name", "attention_type__name")
    filename = "subatenciones"
    sheet_title = "Subatenciones"
    headings = ("Código", "Nombre", "Tipo de Atención asociado", "Estado")

    def get_queryset(self, request):
        return super().get_queryset(request).select_related("attention_type")

    def row_values(self, record):
        return (
            record.code,
            record.name,
            record.attention_type.name,
            "Activo" if record.is_active else "Inactivo",
        )
