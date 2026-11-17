from django import forms
from django.contrib import messages
from django.db import IntegrityError, transaction
from django.db.models import Count, Q
from django.shortcuts import redirect, render
from django.views.generic import TemplateView, View

from accounts.models import Area, Delegation, Official, Role
from common.access import ProtectedViewMixin, get_scoped_object_or_404
from common.list_state import positive
from common.pagination import ClampedPaginationMixin
from common.scopes import delegation_ids, permission_scope
from configuration.models import Period
from configuration.services import AuditoriaService

from .cases import VIEW_CASE, scoped_cases
from .models import OfficeLetter, OfficeLetterEvent


VIEW = "activities.view_officeletter"
ADD = "activities.add_officeletter"
CHANGE = "activities.change_officeletter"
DUPLICATE = "Ya existe una carta con ese número en esta delegación y año de recepción."


def scoped_letters(user, permission=VIEW):
    letters = OfficeLetter.objects.filter(deleted_at__isnull=True)
    scope = permission_scope(user, permission)
    if scope == Role.Scope.ALL:
        return letters
    if scope == Role.Scope.DELEGATION:
        return letters.filter(delegation_id__in=delegation_ids(user))
    if scope == Role.Scope.OWN:
        official = user.official
        return letters.filter(delegation_id__in=delegation_ids(user)).filter(
            Q(created_by=official) | Q(responsible=official))
    return letters.none()


def date_widget():
    return forms.DateInput(format="%Y-%m-%d", attrs={"type": "date", "class": "form-control"})


class LetterForm(forms.ModelForm):
    class Meta:
        model = OfficeLetter
        fields = ("delegation", "received_on", "external_number", "addressee", "sender", "phone",
                  "subject", "activity_on", "responsible", "responsible_area", "status",
                  "decision", "referred_to", "notes")
        widgets = {
            "received_on": date_widget(), "activity_on": date_widget(),
            "decision": forms.Textarea(attrs={"rows": 2}), "notes": forms.Textarea(attrs={"rows": 3}),
        }

    def __init__(self, *args, user, **kwargs):
        super().__init__(*args, **kwargs)
        permitted = Q(status=Delegation.Status.ACTIVE, deleted_at__isnull=True)
        write_permission = CHANGE if self.instance.pk else ADD
        if any(permission_scope(user, permission) != Role.Scope.ALL for permission in (VIEW, write_permission)):
            permitted &= Q(pk__in=delegation_ids(user))
        self.fields["delegation"].queryset = Delegation.objects.filter(permitted | Q(pk=self.instance.delegation_id))
        if not self.instance.pk:
            official = getattr(user, "official", None)
            self.fields["delegation"].initial = official.delegation_id if official else None
        delegation_ids_for_form = self.fields["delegation"].queryset.values("pk")
        active = Q(status=Official.Status.ACTIVE, deleted_at__isnull=True, user__is_active=True)
        assigned = Q(delegation__in=delegation_ids_for_form) | Q(authorized_delegations__in=delegation_ids_for_form)
        self.fields["responsible"].queryset = Official.objects.filter(
            (active & assigned) | Q(pk=self.instance.responsible_id)).distinct()
        self.fields["responsible_area"].queryset = Area.objects.filter(
            Q(is_active=True, deleted_at__isnull=True) | Q(pk=self.instance.responsible_area_id))
        self.fields["responsible"].help_text = "Selecciona un funcionario o un área."

    def clean_external_number(self):
        number = self.cleaned_data["external_number"]
        number = (number or "").upper()
        if len(number) > self.fields["external_number"].max_length:
            raise forms.ValidationError("El número externo admite hasta 60 caracteres.")
        return number or None

    def duplicate(self, delegation, date, number):
        return bool(delegation and date and number and OfficeLetter.objects.filter(
            delegation=delegation, received_year=date.year, external_number=number,
        ).exclude(pk=self.instance.pk).exists())

    def clean(self):
        data = super().clean()
        delegation, official, area = (data.get(field) for field in ("delegation", "responsible", "responsible_area"))
        changed_delegation = delegation and delegation.pk != self.instance.delegation_id
        if changed_delegation and self.instance.case_id:
            self.add_error("delegation", "Desvincula el caso social antes de cambiar la delegación.")
        if official and area:
            self.add_error("responsible_area", "Selecciona un funcionario o un área como encargado.")
        if official and delegation and (changed_delegation or official.pk != self.instance.responsible_id):
            belongs = official.delegation_id == delegation.pk or official.authorized_delegations.filter(pk=delegation.pk).exists()
            if not (official.is_enabled and official.user_id and official.user.is_active and belongs):
                self.add_error("responsible", "Selecciona un funcionario habilitado de esta delegación.")
        if self.duplicate(delegation, data.get("received_on"), data.get("external_number")):
            self.add_error("external_number", DUPLICATE)
        return data


class LetterFilters(forms.Form):
    q = forms.CharField(label="Buscar cartas", required=False, max_length=200,
                        widget=forms.TextInput(attrs={"type": "search", "placeholder": "Número, código, remitente o tema"}))
    period = forms.ModelChoiceField(label="Período de recepción", queryset=Period.objects.none(), required=False)
    start = forms.DateField(label="Recepción desde", required=False, widget=date_widget())
    end = forms.DateField(label="Recepción hasta", required=False, widget=date_widget())
    delegation = forms.ModelChoiceField(label="Delegación", queryset=Delegation.objects.none(), required=False)
    status = forms.ChoiceField(label="Estado", required=False, choices=[("", "Todos los estados"), *OfficeLetter.Status.choices])
    responsible = forms.ChoiceField(label="Encargado", required=False)

    def __init__(self, *args, records, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["period"].queryset = Period.objects.filter(deleted_at__isnull=True).order_by("-start_date")
        self.fields["delegation"].queryset = Delegation.objects.filter(pk__in=records.values("delegation_id"))
        people = Official.objects.filter(pk__in=records.values("responsible_id"))
        areas = Area.objects.filter(pk__in=records.values("responsible_area_id"))
        self.fields["responsible"].choices = [
            ("", "Todos los encargados"), ("unassigned", "Sin asignar"),
            *((f"official:{person.pk}", str(person)) for person in people),
            *((f"area:{area.pk}", f"Área · {area}") for area in areas),
        ]

    def clean(self):
        data = super().clean()
        start, end = data.get("start"), data.get("end")
        if start and end and start > end:
            self.add_error("end", "La fecha hasta debe ser igual o posterior a la fecha desde.")
        return data

    def filter(self, records):
        data = self.cleaned_data
        if query := data.get("q"):
            match = Q(external_number__icontains=query) | Q(sender__icontains=query) | Q(subject__icontains=query)
            if query.upper().startswith("CAR-") and (identifier := positive(query[4:], 0)):
                match |= Q(pk=identifier)
            records = records.filter(match)
        if period := data.get("period"):
            records = records.filter(received_on__range=(period.start_date, period.end_date))
        for field, value in (("received_on__gte", data.get("start")), ("received_on__lte", data.get("end")),
                             ("delegation", data.get("delegation")), ("status", data.get("status"))):
            if value:
                records = records.filter(**{field: value})
        if responsible := data.get("responsible"):
            if responsible == "unassigned":
                return records.filter(responsible__isnull=True, responsible_area__isnull=True)
            kind, identifier = responsible.split(":")
            records = records.filter(**{"responsible_id" if kind == "official" else "responsible_area_id": identifier})
        return records


class LetterListView(ClampedPaginationMixin, ProtectedViewMixin, TemplateView):
    permission_required = VIEW
    template_name = "activities/letter_list.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        records = scoped_letters(self.request.user)
        form = LetterFilters(self.request.GET, records=records)
        if form.is_valid():
            records = form.filter(records)
        counts = dict(records.order_by().values("status").annotate(count=Count("pk")).values_list("status", "count"))
        total = sum(counts.values())
        params = self.request.GET.copy()
        params.pop("page", None)
        return {**context, "filter_form": form, "total": total,
                "applicable": total - counts.get(OfficeLetter.Status.NOT_APPLICABLE, 0),
                "status_counts": [(label, counts.get(value, 0)) for value, label in OfficeLetter.Status.choices],
                "page_obj": self.clamp_page(records.select_related("delegation", "responsible", "responsible_area")),
                "querystring": params.urlencode()}


def record_letter_event(request, letter, title, changes):
    actor = getattr(request.user, "official", None)
    OfficeLetterEvent.objects.create(letter=letter, actor=actor, actor_username=request.user.get_username(),
                                     title=title, changes=changes)
    AuditoriaService.register_change(actor, title, letter, new_value=letter.identifier,
                                     origin_ip=request.META.get("REMOTE_ADDR") or None)


def letter_values(letter):
    return {field: (letter.get_status_display() if field == "status" else str(getattr(letter, field) or ""))
            for field in LetterForm.Meta.fields}


class LetterFormView(ProtectedViewMixin, View):
    def get_permission_required(self):
        return (VIEW, CHANGE if "pk" in self.kwargs else ADD)

    def get(self, request, pk=None):
        return self.form_response(request, pk)

    @transaction.atomic
    def post(self, request, pk=None):
        return self.form_response(request, pk)

    def form_response(self, request, pk):
        letter = None
        if pk is not None:
            visible = scoped_letters(request.user).values("pk")
            allowed = scoped_letters(request.user, CHANGE).filter(pk__in=visible)
            if request.method == "POST":
                allowed = allowed.select_for_update()
            letter = get_scoped_object_or_404(request, allowed, pk=pk)
        form = LetterForm(request.POST if request.method == "POST" else None, user=request.user, instance=letter)
        before = letter_values(letter) if letter else {}
        if request.method == "POST" and form.is_valid():
            record = form.save(commit=False)
            if letter is None:
                record.created_by = getattr(request.user, "official", None)
            after = letter_values(record)
            changes = [{"field": form.fields[field].label, "before": before.get(field, ""), "after": value}
                       for field, value in after.items() if value != before.get(field, "")]
            try:
                with transaction.atomic():
                    record.save()
                    if changes:
                        title = "Carta actualizada" if letter else "Carta registrada"
                        record_letter_event(request, record, title, changes)
            except IntegrityError:
                if not form.duplicate(record.delegation, record.received_on, record.external_number):
                    raise
                form.add_error("external_number", DUPLICATE)
            else:
                messages.success(request, "Carta guardada correctamente.")
                if scoped_letters(request.user).filter(pk=record.pk).exists():
                    return redirect("office_letter_detail", pk=record.pk)
                return redirect("office_letter_list")
        return render(request, "activities/letter_form.html", {"form": form, "letter": letter})


class LetterCaseForm(forms.Form):
    folio = forms.RegexField(label="Folio del caso social", regex=r"(?i)^(CAS|SOL)-[0-9]{1,19}$",
                             max_length=23, help_text="Ejemplo: CAS-000001 o SOL-000001.")

    def __init__(self, *args, cases, **kwargs):
        super().__init__(*args, **kwargs)
        self.cases = cases

    def clean_folio(self):
        prefix, raw_id = self.cleaned_data["folio"].upper().split("-")
        identifier = positive(raw_id, 0)
        lookup = {"pk": identifier, "client_request__isnull": True} if prefix == "CAS" else {"client_request_id": identifier}
        case = self.cases.filter(**lookup).first()
        if case is None:
            raise forms.ValidationError("No se encontró un caso autorizado con ese folio en la delegación de la carta.")
        return case


def render_letter(request, letter, form=None):
    user = request.user
    can_edit = scoped_letters(user, CHANGE).filter(pk=letter.pk).exists()
    case = None
    if letter.case_id and user.has_perm(VIEW_CASE):
        case = scoped_cases(user).filter(pk=letter.case_id, delegation_id=letter.delegation_id).first()
    can_link = can_edit and user.has_perm(VIEW_CASE) and (not letter.case_id or case is not None)
    return render(request, "activities/letter_detail.html", {
        "letter": letter, "events": letter.events.select_related("actor"), "case": case, "can_edit": can_edit,
        "case_form": (form if form is not None else LetterCaseForm(cases=None)) if can_link else None,
    })


class LetterDetailView(ProtectedViewMixin, View):
    permission_required = VIEW

    def get(self, request, pk):
        letter = get_scoped_object_or_404(request, scoped_letters(request.user).select_related(
            "delegation", "responsible", "responsible_area"), pk=pk)
        return render_letter(request, letter)


class LetterCaseView(ProtectedViewMixin, View):
    permission_required = (VIEW, CHANGE, VIEW_CASE)
    http_method_names = ["post"]

    @transaction.atomic
    def post(self, request, pk):
        visible = scoped_letters(request.user).values("pk")
        letter = get_scoped_object_or_404(request, scoped_letters(request.user, CHANGE).filter(
            pk__in=visible).select_for_update(), pk=pk)
        cases = scoped_cases(request.user).filter(delegation_id=letter.delegation_id)
        previous = cases.filter(pk=letter.case_id).first()
        if letter.case_id and previous is None:
            return self.handle_no_permission()
        case = None
        if request.POST.get("action") != "unlink":
            form = LetterCaseForm(request.POST, cases=cases)
            if not form.is_valid():
                return render_letter(request, letter, form)
            case = form.cleaned_data["folio"]
        if previous != case:
            letter.case = case
            letter.save(update_fields=["case", "updated_at"])
            title = "Caso social vinculado" if case else "Caso social desvinculado"
            # El historial de cartas también lo consultan perfiles sin acceso a casos.
            record_letter_event(request, letter, title, [])
            messages.success(request, f"{title} correctamente.")
        return redirect("office_letter_detail", pk=pk)
