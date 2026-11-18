from urllib.parse import urlencode

from django.core.exceptions import ValidationError
from django.db import transaction
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views import View
from django import forms
from django.core.paginator import Paginator
from django.http import Http404

from accounts.models import Official, OfficialAbsence
from common.access import ProtectedViewMixin, get_scoped_object_or_404
from common.edit_concurrency import edit_conflict, edit_is_current, edit_revision
from common.maintainer_forms import MaintainerForm
from common.modal_forms import ModalFormOnlyMixin, add_form_success
from common.scopes import scope_officials
from configuration.period_services import lock_period_registry
from configuration.services import AuditoriaService

VIEW = "accounts.view_officialabsence"
MANAGE = "accounts.manage_absence"


class AbsenceForm(MaintainerForm):
    class Meta:
        model = OfficialAbsence
        fields = ("official", "kind", "start_date", "end_date", "reason")

    def __init__(self, *args, actor, **kwargs):
        super().__init__(*args, actor=actor, **kwargs)
        # Misma intersección que load(): solo funcionarios que el actor puede ver y gestionar.
        readable = scope_officials(Official.objects.filter(deleted_at__isnull=True), actor, VIEW)
        self.fields["official"].queryset = scope_officials(readable, actor, MANAGE)


class AbsenceList(ProtectedViewMixin, View):
    permission_required = VIEW

    def get(self, request):
        officials = scope_officials(Official.objects.all(), request.user, VIEW)
        rows = OfficialAbsence.objects.filter(official__in=officials, deleted_at__isnull=True).select_related("official")
        filters = {}
        if official_id := request.GET.get("official", ""):
            if not official_id.isascii() or not official_id.isdecimal() or len(official_id) > 19:
                raise Http404("No se encontró el funcionario solicitado.")
            official = get_scoped_object_or_404(request, officials, pk=official_id)
            rows = rows.filter(official=official)
            filters["official"] = official.pk
        return render(request, "accounts/absence_list.html", {
            "page_obj": Paginator(rows, 25).get_page(request.GET.get("page")),
            # Solo los filtros válidos, sin `page`: la paginación los conserva.
            "filter_query": urlencode(filters),
            "officials": officials, "can_manage": request.user.has_perm(MANAGE),
        })


class AbsenceEdit(ProtectedViewMixin, ModalFormOnlyMixin, View):
    permission_required = (VIEW, MANAGE)
    archive = False

    def load(self, request, pk=None, lock=False):
        if pk is None:
            return OfficialAbsence(registered_by=getattr(request.user, "official", None))
        readable = scope_officials(Official.objects.all(), request.user, VIEW)
        writable = scope_officials(readable, request.user, MANAGE)
        rows = OfficialAbsence.objects.filter(official__in=writable, deleted_at__isnull=True)
        return get_scoped_object_or_404(request, rows.select_for_update() if lock else rows, pk=pk)

    def display(self, request, obj, form, revision=None):
        return render(request, "analytics/operation_form.html", {"form": form,
            "maintainer_title": "Archivar ausencia" if self.archive else "Registrar o editar ausencia",
            "back_url": reverse("absence_list"), "edit_revision": revision, "sidebar_active": "absences"})

    def get(self, request, pk=None):
        obj = self.load(request, pk)
        form = forms.Form() if self.archive else AbsenceForm(instance=obj, actor=request.user)
        return self.display(request, obj, form, edit_revision(obj) if obj.pk else None)

    def post(self, request, pk=None):
        with transaction.atomic():
            lock_period_registry()
            obj = self.load(request, pk, lock=True)
            # Edición simultánea (#52): si otro usuario guardó antes, no se pisa su cambio.
            if obj.pk and not edit_is_current(request, edit_revision(obj)):
                return edit_conflict()
            previous = str(obj) if obj.pk else ""
            form = forms.Form(request.POST) if self.archive else AbsenceForm(request.POST, instance=obj, actor=request.user)
            # Quien actúa (no quien registró la ausencia) debe ser un funcionario: queda en la auditoría.
            actor = getattr(request.user, "official", None)
            if actor is None:
                form.add_error(None, "Tu usuario no tiene un funcionario asociado para registrar la ausencia.")
            if form.is_valid():
                try:
                    if self.archive:
                        obj.delete()
                    else:
                        obj = form.save()
                    AuditoriaService.register_change(actor,
                        "Ausencia archivada" if self.archive else "Ausencia guardada", obj,
                        previous_value=previous, new_value=f"{obj} · {obj.reason}",
                        origin_ip=request.META.get("REMOTE_ADDR") or None, actor=request.user)
                except ValidationError as error:
                    form.add_error(None, error)
                else:
                    add_form_success(request, "Ausencia archivada correctamente." if self.archive else "Ausencia guardada correctamente.")
                    return redirect("absence_list")
            return self.display(request, obj, form, request.POST.get("edit_revision"))
