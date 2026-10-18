"""
CRUD de Roles (persistencia real).

Los roles son un catálogo transversal: no pertenecen a una delegación, por lo que el listado
no se filtra por ámbito. Sí se filtra la lista de funcionarios asignados que se muestra en el
detalle (scoped_officials). Los roles no se eliminan: se desactivan y reactivan.
"""

from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse_lazy
from django.views.generic import CreateView, DetailView, ListView, UpdateView, View

from common.access import ProtectedViewMixin, register_denied_access
from common.exports import xlsx_response

from .models import Role
from .role_forms import (
    ROLE_STATUS_CHOICES,
    RoleForm,
    active_official_filter,
    active_officials,
    can_grant_privileged_permissions,
    combined_roles_message,
    format_snapshot,
    group_permissions,
    is_global_administrator,
    last_global_administrator,
    last_global_administrator_message,
    normalize_spaces,
    officials_combining_roles,
    officials_phrase,
    permission_action,
    permission_label,
    role_snapshot,
)
from .views import ClampedPaginationMixin, _registrar_auditoria, scoped_officials


def roles_queryset():
    return Role.objects.filter(deleted_at__isnull=True)


def annotate_roles(queryset):
    return queryset.annotate(
        permission_count=Count("permissions", distinct=True),
        active_official_count=Count(
            "officials", filter=active_official_filter("officials__"), distinct=True
        ),
    )


def filter_roles(queryset, params):
    """Búsqueda parcial (nombre, descripción, alcance o permiso) y filtro por estado."""
    query = normalize_spaces(params.get("q"))
    status = (params.get("status") or "").strip()
    if query:
        scopes = [value for value, label in Role.Scope.choices if query.lower() in label.lower()]
        matches = Role.objects.filter(
            Q(role_name__icontains=query)
            | Q(description__icontains=query)
            | Q(scope__in=scopes)
            | Q(permissions__name__icontains=query)
            | Q(permissions__codename__icontains=query)
        )
        queryset = queryset.filter(pk__in=matches.values("pk"))
    if status == "ACTIVE":
        queryset = queryset.filter(is_active=True)
    elif status == "INACTIVE":
        queryset = queryset.filter(is_active=False)
    return queryset


def listed_roles(params):
    return annotate_roles(filter_roles(roles_queryset(), params)).order_by("role_name", "pk")


class RoleListView(ClampedPaginationMixin, ProtectedViewMixin, ListView):
    permission_required = "accounts.view_role"
    template_name = "accounts/role_list.html"
    context_object_name = "roles"
    paginate_by = 10

    def get_queryset(self):
        return listed_roles(self.request.GET)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        params = self.request.GET.copy()
        params.pop(self.page_kwarg, None)
        can_change = self.request.user.has_perm("accounts.change_role")
        protected = last_global_administrator() if can_change else None
        context.update(
            maintainer_title="Roles y permisos",
            maintainer_kind="roles",
            query=normalize_spaces(self.request.GET.get("q")),
            selected_status=(self.request.GET.get("status") or "").strip(),
            status_choices=ROLE_STATUS_CHOICES,
            querystring=params.urlencode(),
            total=context["paginator"].count,
            can_add=self.request.user.has_perm("accounts.add_role"),
            can_change=can_change,
            protected_role_pk=protected.pk if protected else None,
        )
        return context


class RoleExportView(ProtectedViewMixin, View):
    permission_required = "accounts.view_role"

    def get(self, request):
        roles = listed_roles(request.GET).prefetch_related("permissions__content_type")
        rows = (
            [
                role.role_name,
                role.description,
                role.get_scope_display(),
                "; ".join(
                    permission_label(permission)
                    for _, permissions in group_permissions(role.permissions.all())
                    for permission in permissions
                ),
                role.active_official_count,
                "Activo" if role.is_active else "Inactivo",
            ]
            for role in roles
        )
        return xlsx_response(
            "roles",
            ["Nombre", "Descripción", "Alcance", "Permisos", "Funcionarios activos", "Estado"],
            rows,
            sheet_title="Roles",
        )


class RoleDetailView(ProtectedViewMixin, DetailView):
    permission_required = "accounts.view_role"
    model = Role
    template_name = "accounts/role_detail.html"
    context_object_name = "role"

    def get_queryset(self):
        return roles_queryset()

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        role = self.object
        can_change = self.request.user.has_perm("accounts.change_role")
        protected = last_global_administrator() if can_change else None
        context.update(
            maintainer_title="Detalle de rol",
            permission_groups=[
                (label, ", ".join(permission_action(permission) for permission in permissions))
                for label, permissions in group_permissions(role.permissions.select_related("content_type"))
            ],
            is_global_administrator=is_global_administrator(role.scope, role.permissions.all()),
            active_official_count=active_officials(role).count(),
            assigned_officials=scoped_officials(self.request.user)
            .filter(roles=role)
            .select_related("delegation")
            .order_by("full_name"),
            can_change=can_change,
            is_protected=protected is not None and protected.pk == role.pk,
        )
        return context


class RoleCreateView(ProtectedViewMixin, CreateView):
    permission_required = "accounts.add_role"
    model = Role
    form_class = RoleForm
    template_name = "accounts/role_form.html"
    success_url = reverse_lazy("role_list")

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["actor"] = self.request.user
        return kwargs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(maintainer_title="Nuevo rol", form_mode="create")
        return context

    def form_valid(self, form):
        if form.grants_privileged_permissions() and not can_grant_privileged_permissions(self.request.user):
            register_denied_access(self.request, ["accounts.change_role"])
            raise PermissionDenied("Asignar permisos privilegiados a un rol requiere accounts.change_role.")
        self.object = form.save()
        _registrar_auditoria(
            self.request, "Creación de rol", self.object, new=format_snapshot(role_snapshot(self.object))
        )
        messages.success(self.request, f"El rol {self.object.role_name} fue creado correctamente.")
        return redirect(self.get_success_url())

    def form_invalid(self, form):
        messages.error(self.request, "No se pudo guardar el rol. Revisa los datos ingresados.")
        return super().form_invalid(form)


class RoleUpdateView(ProtectedViewMixin, UpdateView):
    permission_required = "accounts.change_role"
    model = Role
    form_class = RoleForm
    template_name = "accounts/role_form.html"
    success_url = reverse_lazy("role_list")

    def get_queryset(self):
        return roles_queryset()

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["actor"] = self.request.user
        return kwargs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(maintainer_title=f"Editar rol {self.object.role_name}", form_mode="edit")
        return context

    def form_valid(self, form):
        previous = form.previous_snapshot
        self.object = form.save()
        current = role_snapshot(self.object)
        changed = [key for key in current if current[key] != previous[key]]
        _registrar_auditoria(
            self.request,
            "Actualización de rol",
            self.object,
            previous=format_snapshot(previous, changed) if changed else "Sin cambios",
            new=format_snapshot(current, changed) if changed else "Sin cambios",
        )
        messages.success(self.request, f"El rol {self.object.role_name} fue actualizado correctamente.")
        return redirect(self.get_success_url())

    def form_invalid(self, form):
        messages.error(self.request, "No se pudo guardar el rol. Revisa los datos ingresados.")
        return super().form_invalid(form)


class RoleDeactivateView(ProtectedViewMixin, View):
    """
    Desactiva el rol aunque tenga funcionarios activos, pero la confirmación debe informar
    cuántos pierden sus permisos: el formulario envía la cifra mostrada y, si cambió entre
    tanto, no se desactiva y se vuelve a advertir con la cifra actual.
    """

    permission_required = "accounts.change_role"

    def post(self, request, pk):
        role = get_object_or_404(roles_queryset(), pk=pk)
        if not role.is_active:
            messages.info(request, f"El rol {role.role_name} ya estaba inactivo.")
            return redirect("role_list")
        last = last_global_administrator()
        if last is not None and last.pk == role.pk:
            messages.error(request, last_global_administrator_message(role, "desactivar el rol"))
            return redirect("role_list")

        affected = active_officials(role).count()
        if affected and request.POST.get("affected_officials") != str(affected):
            messages.warning(
                request,
                f"El rol {role.role_name} tiene {officials_phrase(affected)} que perderán sus "
                "permisos. Revisa la cifra y confirma nuevamente la desactivación.",
            )
            return redirect("role_list")

        role.is_active = False
        role.save(update_fields=["is_active", "updated_at"])
        _registrar_auditoria(
            request,
            "Desactivación de rol",
            role,
            previous="Estado: Activo",
            new=f"Estado: Inactivo\nFuncionarios activos que pierden los permisos del rol: {affected}",
        )
        message = f"El rol {role.role_name} fue desactivado correctamente."
        if affected:
            verb = "quedó" if affected == 1 else "quedaron"
            message += f" {officials_phrase(affected)} {verb} sin los permisos de este rol."
        messages.success(request, message)
        return redirect("role_list")


class RoleActivateView(ProtectedViewMixin, View):
    permission_required = "accounts.change_role"

    def post(self, request, pk):
        role = get_object_or_404(roles_queryset(), pk=pk)
        if role.is_active:
            messages.info(request, f"El rol {role.role_name} ya estaba activo.")
            return redirect("role_list")
        if is_global_administrator(role.scope, role.permissions.all()):
            conflicts = officials_combining_roles(role).count()
            if conflicts:
                messages.error(request, combined_roles_message(role, conflicts))
                return redirect("role_list")

        role.is_active = True
        role.save(update_fields=["is_active", "updated_at"])
        affected = active_officials(role).count()
        _registrar_auditoria(
            request,
            "Activación de rol",
            role,
            previous="Estado: Inactivo",
            new=f"Estado: Activo\nFuncionarios activos que recuperan los permisos del rol: {affected}",
        )
        messages.success(request, f"El rol {role.role_name} fue activado correctamente.")
        return redirect("role_list")
