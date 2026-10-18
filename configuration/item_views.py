"""
CRUD de Ítems (persistencia real).

Los ítems son un catálogo transversal: no pertenecen a una delegación, por lo que el listado no
se filtra por ámbito. No se eliminan: se desactivan y reactivan. Las metas (GoalThreshold) no
forman parte de este mantenedor.
"""

from django.contrib import messages
from django.db.models import Q
from django.db.models.functions import Lower
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse_lazy
from django.views.generic import CreateView, DetailView, ListView, UpdateView, View

from accounts.views import ClampedPaginationMixin
from common.access import ProtectedViewMixin
from common.exports import xlsx_response
from common.text import describe_changes, format_snapshot, normalize_spaces

from .forms import ITEM_STATUS_CHOICES, ItemForm, item_snapshot
from .models import Item
from .services import AuditoriaService


def register_item_audit(request, action, item, previous="", new=""):
    AuditoriaService.register_change(
        official=getattr(request.user, "official", None),
        action=action,
        instance=item,
        previous_value=previous,
        new_value=new,
        origin_ip=request.META.get("REMOTE_ADDR") or None,
    )


def items_queryset():
    return Item.objects.filter(deleted_at__isnull=True)


def filter_items(queryset, params):
    """Búsqueda parcial (código, nombre o descripción) y filtro por estado."""
    query = normalize_spaces(params.get("q"))
    status = (params.get("status") or "").strip()
    if query:
        queryset = queryset.filter(
            Q(code__icontains=query) | Q(item_name__icontains=query) | Q(description__icontains=query)
        )
    if status == "ACTIVE":
        queryset = queryset.filter(is_active=True)
    elif status == "INACTIVE":
        queryset = queryset.filter(is_active=False)
    return queryset


def listed_items(params):
    """
    Orden por código sin distinguir mayúsculas (los manuales se intercalan alfabéticamente con
    los automáticos) y, en empate, por nombre y pk. El relleno de ITM-NNNN mantiene el orden
    numérico de los códigos automáticos hasta ITM-9999.
    """
    return filter_items(items_queryset(), params).order_by(Lower("code"), Lower("item_name"), "pk")


class ItemListView(ClampedPaginationMixin, ProtectedViewMixin, ListView):
    permission_required = "configuration.view_item"
    template_name = "configuration/item_list.html"
    context_object_name = "items"
    paginate_by = 10

    def get_queryset(self):
        return listed_items(self.request.GET)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        params = self.request.GET.copy()
        params.pop(self.page_kwarg, None)
        context.update(
            maintainer_title="Ítems y metas",
            maintainer_kind="items",
            query=normalize_spaces(self.request.GET.get("q")),
            selected_status=(self.request.GET.get("status") or "").strip(),
            status_choices=ITEM_STATUS_CHOICES,
            querystring=params.urlencode(),
            total=context["paginator"].count,
            can_add=self.request.user.has_perm("configuration.add_item"),
            can_change=self.request.user.has_perm("configuration.change_item"),
        )
        return context


class ItemExportView(ProtectedViewMixin, View):
    permission_required = "configuration.view_item"

    def get(self, request):
        rows = (
            [item.code, item.item_name, item.description, "Activo" if item.is_active else "Inactivo"]
            for item in listed_items(request.GET)
        )
        return xlsx_response(
            "items", ["Código", "Nombre", "Descripción", "Estado"], rows, sheet_title="Ítems"
        )


class ItemDetailView(ProtectedViewMixin, DetailView):
    permission_required = "configuration.view_item"
    model = Item
    template_name = "configuration/item_detail.html"
    context_object_name = "item"

    def get_queryset(self):
        return items_queryset()

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(
            maintainer_title="Detalle de ítem",
            can_change=self.request.user.has_perm("configuration.change_item"),
        )
        return context


class ItemCreateView(ProtectedViewMixin, CreateView):
    permission_required = "configuration.add_item"
    model = Item
    form_class = ItemForm
    template_name = "configuration/item_form.html"
    success_url = reverse_lazy("item_maintainer")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(maintainer_title="Nuevo ítem", form_mode="create")
        return context

    def form_valid(self, form):
        self.object = form.save()
        register_item_audit(
            self.request, "Creación de ítem", self.object, new=format_snapshot(item_snapshot(self.object))
        )
        messages.success(
            self.request,
            f"El ítem {self.object.item_name} fue creado correctamente con el código {self.object.code}.",
        )
        return redirect(self.get_success_url())

    def form_invalid(self, form):
        messages.error(self.request, "No se pudo guardar el ítem. Revisa los datos ingresados.")
        return super().form_invalid(form)


class ItemUpdateView(ProtectedViewMixin, UpdateView):
    permission_required = "configuration.change_item"
    model = Item
    form_class = ItemForm
    template_name = "configuration/item_form.html"
    success_url = reverse_lazy("item_maintainer")

    def get_queryset(self):
        return items_queryset()

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        # El título usa el código guardado, no el que se haya escrito en un envío con errores.
        original_code = context["form"].previous_snapshot["Código"]
        context.update(maintainer_title=f"Editar ítem {original_code}", form_mode="edit")
        return context

    def form_valid(self, form):
        previous_snapshot = form.previous_snapshot
        self.object = form.save()
        previous, new = describe_changes(previous_snapshot, item_snapshot(self.object))
        register_item_audit(self.request, "Actualización de ítem", self.object, previous=previous, new=new)
        messages.success(self.request, f"El ítem {self.object.item_name} fue actualizado correctamente.")
        return redirect(self.get_success_url())

    def form_invalid(self, form):
        messages.error(self.request, "No se pudo guardar el ítem. Revisa los datos ingresados.")
        return super().form_invalid(form)


class ItemDeactivateView(ProtectedViewMixin, View):
    permission_required = "configuration.change_item"

    def post(self, request, pk):
        item = get_object_or_404(items_queryset(), pk=pk)
        if not item.is_active:
            messages.info(request, f"El ítem {item.item_name} ya estaba inactivo.")
            return redirect("item_maintainer")
        item.is_active = False
        item.save(update_fields=["is_active", "updated_at"])
        register_item_audit(request, "Desactivación de ítem", item, previous="Estado: Activo", new="Estado: Inactivo")
        messages.success(request, f"El ítem {item.item_name} fue desactivado correctamente.")
        return redirect("item_maintainer")


class ItemActivateView(ProtectedViewMixin, View):
    permission_required = "configuration.change_item"

    def post(self, request, pk):
        item = get_object_or_404(items_queryset(), pk=pk)
        if item.is_active:
            messages.info(request, f"El ítem {item.item_name} ya estaba activo.")
            return redirect("item_maintainer")
        item.is_active = True
        item.save(update_fields=["is_active", "updated_at"])
        register_item_audit(request, "Activación de ítem", item, previous="Estado: Inactivo", new="Estado: Activo")
        messages.success(request, f"El ítem {item.item_name} fue activado correctamente.")
        return redirect("item_maintainer")
