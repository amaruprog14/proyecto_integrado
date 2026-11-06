"""Mantenedores persistentes con contratos comunes de interfaz y auditoría."""
from django.contrib import messages
from django.contrib.auth.models import Group
from django.core.exceptions import ValidationError, PermissionDenied
from django.db import transaction, IntegrityError
from django.db.models import Q
from django.http import HttpResponse
from django.shortcuts import render, redirect
from django.urls import path, reverse
from django.views import View
from common.pagination import ClampedPaginationMixin
from common.list_state import ordered, query_params
from accounts.models import Position, Area, GroupProfile, Role, Territory
from common.access import ProtectedViewMixin, get_scoped_object_or_404
from common.exports import xlsx_response
from common.text import normalize_spaces, describe_changes
from common.scopes import permission_scope, delegation_ids
from common.maintainer_forms import PositionForm, AreaForm, GroupForm, PeriodForm, ActivityForm, TerritoryForm, protect_last_group_administrator
from configuration.models import Period
from configuration.services import AuditoriaService
from configuration.period_services import lock_open_period, lock_activity_periods, lock_period_registry
from activities.models import Activity

CATALOGS = {
    "territory": (Territory, TerritoryForm, "Territorios", "territories", ("code", "territory_name", "delegation__delegation_name", "description")),
    "position": (Position, PositionForm, "Cargos", "positions", ("position_name", "description")),
    "area": (Area, AreaForm, "Áreas", "areas", ("area_name",)),
    "group": (Group, GroupForm, "Grupos", "groups", ("name",)),
    "period": (Period, PeriodForm, "Períodos", "periods", ("start_date", "end_date")),
    "activity": (Activity, ActivityForm, "Actividades", "activities", ("code", "official__full_name", "item__item_name", "date", "record_type")),
}


def snapshot(obj):
    data = {str(f.verbose_name): str(getattr(obj, f.name)) for f in obj._meta.fields
            if f.name not in ("created_at", "updated_at")}
    if isinstance(obj, Group):
        profile = getattr(obj, "sgr_profile", None)
        data.update(Permisos=", ".join(obj.permissions.order_by("pk").values_list("codename", flat=True)),
            Miembros=", ".join(obj.user_set.order_by("pk").values_list("username", flat=True)),
            Alcance=profile.scope if profile else "DELEGATION",
            Vigente=str(profile.is_active) if profile else "False",
            Descripción=profile.description if profile else "")
    return data


def activity_queryset(user, permission):
    qs = Activity.objects.select_related("official", "item", "social_attentions__delegation")
    scope = permission_scope(user, permission)
    if scope == Role.Scope.ALL:
        return qs
    official = getattr(user, "official", None)
    if scope == Role.Scope.OWN:
        return qs.filter(official=official)
    if scope == Role.Scope.DELEGATION:
        ids = delegation_ids(user)
        return qs.filter(Q(social_attentions__delegation_id__in=ids) |
            Q(social_attentions__isnull=True, official__delegation_id__in=ids) |
            Q(social_attentions__isnull=True, official__authorized_delegations__in=ids)).distinct()
    return qs.none()


def state(obj):
    if isinstance(obj, Period):
        return obj.status, obj.get_status_display()
    if isinstance(obj, Activity):
        return ("INACTIVE", "Archivada") if obj.deleted_at else ("ACTIVE", "Vigente")
    active = getattr(getattr(obj, "sgr_profile", None), "is_active", False) if isinstance(obj, Group) else obj.is_active
    return ("ACTIVE", "Vigente") if active else ("INACTIVE", "No vigente")


class MaintainerView(ClampedPaginationMixin, ProtectedViewMixin, View):
    key = None
    operation = "list"

    @property
    def spec(self):
        return CATALOGS[self.key]

    def get_permission_required(self):
        model = self.spec[0]
        action = "add" if self.operation == "create" else "change" if self.operation in ("update", "activate", "deactivate", "close") else "view"
        return (f"{model._meta.app_label}.{action}_{model._meta.model_name}",)

    def queryset(self):
        model = self.spec[0]
        if self.key == "activity":
            return activity_queryset(self.request.user, self.get_permission_required()[0])
        if self.key == "territory":
            from common.scopes import permission_scope, delegation_ids
            scope = permission_scope(self.request.user, self.get_permission_required()[0])
            qs = Territory.objects.filter(deleted_at__isnull=True).select_related("delegation")
            return qs if scope == Role.Scope.ALL else qs.filter(delegation_id__in=delegation_ids(self.request.user)) if scope == Role.Scope.DELEGATION else qs.none()
        qs = model.objects.all()
        if self.key == "group":
            return qs.select_related("sgr_profile")
        return qs.filter(deleted_at__isnull=True)

    def object(self, pk):
        return get_scoped_object_or_404(self.request, self.queryset(), pk=pk)

    def url(self, operation, pk=None):
        name = f"{self.key}_{'maintainer' if operation == 'list' else operation}"
        return reverse(name, args=[pk] if pk else [])

    def context(self):
        permission = self.get_permission_required()[0].split(".")[0]
        model = self.spec[0]._meta.model_name
        entities = {"territory": "territorio", "position": "cargo", "area": "área", "group": "grupo", "period": "período", "activity": "actividad"}
        entity = entities[self.key]
        feminine = self.key in ("area", "activity")
        form_title = f"Editar {entity}" if self.operation == "update" else f"{'Nueva' if feminine else 'Nuevo'} {entity}"
        notes = {
            "period": "Los períodos cerrados conservan su historial y no se pueden editar ni reabrir.",
            "activity": "Las actividades se archivan y restauran sin eliminar su historial. Las vinculadas a atenciones y las de períodos cerrados son de consulta.",
            "group": "Los grupos se desactivan y reactivan, conservando sus miembros y permisos.",
        }
        return dict(maintainer_title=self.spec[2], maintainer_kind=self.spec[3],
            entity_label=entity, form_title=form_title, form_mode="edit" if self.operation == "update" else "create",
            maintainer_note=notes.get(self.key, "Los registros no se eliminan: se desactivan y reactivan, y conservan su historial."),
            list_url=self.url("list"), export_url=self.url("export"), create_url=self.url("create"),
            can_add=self.request.user.has_perm(f"{permission}.add_{model}"),
            can_change=self.request.user.has_perm(f"{permission}.change_{model}"), key=self.key)

    def filtered(self):
        qs = self.queryset()
        query = normalize_spaces(self.request.GET.get("q"))
        if query:
            match = Q()
            for field in self.spec[4]:
                match |= Q(**{field + "__icontains": query})
            qs = qs.filter(match)
        status = self.request.GET.get("status")
        if self.key == "period" and status in ("OPEN", "CLOSED"):
            qs = qs.filter(status=status)
        elif status in ("ACTIVE", "INACTIVE"):
            if self.key == "activity":
                qs = qs.filter(deleted_at__isnull=status == "ACTIVE")
            elif self.key == "group":
                qs = qs.filter(sgr_profile__is_active=status == "ACTIVE")
            else:
                qs = qs.filter(is_active=status == "ACTIVE")
        if self.key == "activity":
            for param in ("official", "item"):
                value = self.request.GET.get(param, "")
                if value.isdigit():
                    qs = qs.filter(**{param + "_id": value})
            if self.request.GET.get("record_type") in Activity.RecordType.values:
                qs = qs.filter(record_type=self.request.GET["record_type"])
            from django.utils.dateparse import parse_date
            for param, lookup in (("date_from", "date__gte"), ("date_to", "date__lte")):
                try:
                    value = parse_date(self.request.GET.get(param, ""))
                except ValueError:
                    value = None
                if value:
                    qs = qs.filter(**{lookup: value})
        return qs.order_by("pk")

    def row(self, obj):
        from datetime import date
        fields = []
        display_fields = []
        for name in self.spec[4]:
            value = obj
            for part in name.split("__"):
                value = getattr(value, part)
            fields.append(str(value))
            display_fields.append(value.strftime("%d-%m-%Y") if isinstance(value, date) else str(value))
        if self.key == "group":
            profile = getattr(obj, "sgr_profile", None)
            fields.extend([profile.get_scope_display() if profile else "Sin configurar",
                str(obj.user_set.count()), str(obj.permissions.count())])
            display_fields = fields.copy()
        code, label = state(obj)
        mutable = not (self.key == "period" and code == "CLOSED")
        if self.key == "activity":
            mutable = not hasattr(obj, "social_attentions") and Period.objects.filter(
                start_date__lte=obj.date, end_date__gte=obj.date, status=Period.Status.OPEN).exists()
        if self.key == "period":
            confirm_message = f"El período {obj} quedará cerrado. No podrás editarlo, reabrirlo ni modificar las actividades de sus fechas."
        elif self.key == "activity":
            confirm_message = f"La actividad {obj.code} {'se archivará' if code == 'ACTIVE' else 'volverá a estar vigente'}; se conservará su historial."
        elif self.key == "group":
            confirm_message = f"El grupo {obj} {'dejará de otorgar sus permisos' if code == 'ACTIVE' else 'volverá a otorgar sus permisos'}. Sus miembros se conservarán."
        else:
            confirm_message = f"El registro {obj} {'quedará no vigente' if code == 'ACTIVE' else 'volverá a estar vigente'}. Las relaciones existentes y el historial se conservarán."
        return dict(cells=fields + [label], display_cells=display_fields, status_code=code,
            status_label=label, is_active=code in ("ACTIVE", "OPEN"), confirm_message=confirm_message, detail=self.url("detail", obj.pk),
            edit=self.url("update", obj.pk), action=self.url("close" if self.key == "period" else "deactivate" if code == "ACTIVE" else "activate", obj.pk),
            action_label="Cerrar" if self.key == "period" else "Desactivar" if code == "ACTIVE" else "Activar",
            mutable=mutable)

    def get(self, request, pk=None):
        context = self.context()
        if self.operation in ("create", "update"):
            if request.headers.get("X-Modal-Request") != "true":
                from django.http import Http404
                raise Http404
            obj = self.object(pk) if pk else None
            try:
                self.check_mutable(obj)
            except ValidationError as error:
                messages.error(request, "; ".join(error.messages))
                return redirect(self.url("list"))
            context["form"] = self.spec[1](actor=request.user, instance=obj)
            context["current_status"] = state(obj)[1] if obj else ""
            return render(request, "maintainers/form.html", context)
        if self.operation == "detail":
            obj = self.object(pk)
            context.update(values=snapshot(obj), row=self.row(obj), record_title=str(obj))
            for field in obj._meta.fields:
                if field.name in ("id", "is_active", "status", "deleted_at"):
                    context["values"].pop(str(field.verbose_name), None)
            context["values"].pop("Vigente", None)
            if hasattr(obj, "created_at"):
                from django.utils import timezone
                context["values"]["Creado"] = timezone.localtime(obj.created_at).strftime("%d-%m-%Y %H:%M")
                context["values"]["Última actualización"] = timezone.localtime(obj.updated_at).strftime("%d-%m-%Y %H:%M")
            if self.key == "group":
                from common.scopes import scope_officials
                from accounts.models import Official
                members = scope_officials(Official.objects.filter(user__groups=obj), request.user, "auth.view_group")
                context["values"]["Miembros"] = ", ".join(members.values_list("user__username", flat=True))
            if self.key in ("position", "area"):
                context["related_count"] = obj.officials.filter(deleted_at__isnull=True).count()
                if self.key == "area":
                    context["type_count"] = obj.activity_types.filter(deleted_at__isnull=True).count()
            if self.key == "activity" and hasattr(obj, "social_attentions"):
                context["attention_url"] = reverse("attention_detail", args=[obj.social_attentions.pk])
            return render(request, "maintainers/detail.html", context)
        if self.operation != "list" and self.operation != "export":
            return HttpResponse(status=405)
        self.prepare_list_state()
        qs = ordered(self.filtered(), self.key, request.GET)
        headers = [str(self.spec[0]._meta.get_field(f.split("__")[0]).verbose_name) for f in self.spec[4]] + ["Estado"]
        if self.key == "group":
            headers = ["Nombre", "Alcance", "Miembros", "Permisos", "Estado"]
        if self.operation == "export":
            return xlsx_response(self.key, headers, (self.row(obj)["cells"] for obj in qs), sheet_title=self.spec[2])
        page = self.clamp_page(qs)
        size = page.paginator.per_page
        params = request.GET.copy()
        params.pop("page", None)
        context.update(rows=[self.row(obj) for obj in page], headers=headers, page_obj=page,
            total=page.paginator.count, querystring=params.urlencode(), query=request.GET.get("q", ""), selected_status=request.GET.get("status", ""),
            page_size=size, page_sizes=self.page_size_options,
            record_types=Activity.RecordType.values,
            statuses=(("OPEN", "Abierto"), ("CLOSED", "Cerrado")) if self.key == "period" else (("ACTIVE", "Vigente"), ("INACTIVE", "Archivada" if self.key == "activity" else "No vigente")))
        if self.key == "activity":
            from accounts.models import Official
            from configuration.models import Item
            context["officials"] = Official.objects.filter(pk__in=self.queryset().values("official_id"))
            context["items"] = Item.objects.filter(pk__in=self.queryset().values("item_id"))
        template = {"territory": "accounts/territory_list.html", "position": "accounts/position_list.html", "area": "accounts/area_list.html",
            "group": "accounts/group_list.html", "period": "configuration/period_list.html",
            "activity": "activities/activity_list.html"}[self.key]
        context.update(self.list_pagination_context())
        response = render(request, template, context)
        response["X-List-URL"] = request.path + "?" + query_params(request._list_state).urlencode()
        return response

    def check_mutable(self, obj):
        if obj is None:
            return
        if isinstance(obj, Period) and obj.status == Period.Status.CLOSED:
            raise ValidationError("El período está cerrado y no admite cambios.")
        if isinstance(obj, Activity):
            if hasattr(obj, "social_attentions"):
                raise ValidationError("Esta actividad se administra desde su atención de origen.")
            if not Period.objects.filter(start_date__lte=obj.date, end_date__gte=obj.date, status=Period.Status.OPEN).exists():
                raise ValidationError("La actividad pertenece a un período cerrado o sin período abierto.")
        if self.key == "territory":
            from accounts.views import scoped_delegations
            if not scoped_delegations(self.request.user).filter(pk=obj.delegation_id, status="ACTIVE", deleted_at__isnull=True).exists():
                raise PermissionDenied("La delegación del territorio no está autorizada o vigente.")
        if isinstance(obj, Group) and not self.request.user.is_superuser and obj.user_set.filter(pk=self.request.user.pk).exists():
            raise PermissionDenied("No puedes modificar tu propio grupo.")

    def post(self, request, pk=None):
        if self.operation not in ("create", "update", "activate", "deactivate", "close"):
            return HttpResponse(status=405)
        form = None
        try:
            with transaction.atomic():
                if self.key in ("activity", "period"):
                    lock_period_registry()
                obj = self.object(pk) if pk else None
                if self.key == "group":
                    list(GroupProfile.objects.select_for_update().order_by("pk").values_list("pk", flat=True))
                if obj:
                    obj = self.spec[0].objects.select_for_update().get(pk=obj.pk)
                self.check_mutable(obj)
                previous = snapshot(obj) if obj else {}
                if self.operation in ("create", "update"):
                    original_date = obj.date if isinstance(obj, Activity) else None
                    form = self.spec[1](request.POST, actor=request.user, instance=obj)
                    if not form.is_valid():
                        return render(request, "maintainers/form.html", dict(self.context(), form=form, current_status=state(obj)[1] if obj else ""))
                    if self.key == "activity":
                        if obj:
                            lock_open_period(original_date)
                            lock_open_period(form.cleaned_data["date"])
                        else:
                            lock_open_period(form.cleaned_data["date"])
                    obj = form.save()
                elif self.key == "period":
                    obj.close_period()
                elif self.key == "activity":
                    from django.utils import timezone
                    lock_activity_periods(obj)
                    obj.deleted_at = timezone.now() if self.operation == "deactivate" else None
                    obj.save(update_fields=["deleted_at", "updated_at"])
                elif self.key == "group":
                    profile, _ = GroupProfile.objects.get_or_create(group=obj)
                    protect_last_group_administrator(obj, profile.scope, obj.permissions.all(), obj.user_set.all(), self.operation == "activate")
                    profile.is_active = self.operation == "activate"
                    profile.save()
                else:
                    obj.is_active = self.operation == "activate"
                    obj.save(update_fields=["is_active", "updated_at"])
                old, new = describe_changes(previous, snapshot(obj))
                AuditoriaService.register_change(official=getattr(request.user, "official", None),
                    action=f"{self.spec[2]}: {self.operation}", instance=obj, previous_value=old,
                    new_value=new, origin_ip=request.META.get("REMOTE_ADDR") or None)
        except IntegrityError:
            if form:
                form.add_error(None, "Ya existe un registro con esos datos. Revisa el nombre y la delegación.")
                return render(request, "maintainers/form.html", dict(self.context(), form=form, current_status=state(obj)[1] if obj else ""))
            raise
        except ValidationError as error:
            if form:
                form.add_error(None, error)
                return render(request, "maintainers/form.html", dict(self.context(), form=form, current_status=state(obj)[1] if obj else ""))
            messages.error(request, "; ".join(error.messages))
            return redirect(self.url("list"))
        messages.success(request, "Registro guardado correctamente.")
        if request.headers.get("X-Modal-Request") == "true":
            return HttpResponse(status=204)
        return redirect(self.url("list"))


def maintainer_urls(key, prefix):
    routes = [("", "list"), ("exportar/", "export"), ("nuevo/", "create"),
        ("<int:pk>/", "detail"), ("<int:pk>/editar/", "update")]
    routes += [("<int:pk>/cerrar/", "close")] if key == "period" else [
        ("<int:pk>/activar/", "activate"), ("<int:pk>/desactivar/", "deactivate")]
    return [path(prefix + route, MaintainerView.as_view(key=key, operation=operation),
        name=f"{key}_{'maintainer' if operation == 'list' else operation}") for route, operation in routes]
