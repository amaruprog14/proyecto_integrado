from io import BytesIO
from uuid import uuid4

from django import forms
from django.conf import settings
from django.contrib import messages
from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from django.core.files.storage import FileSystemStorage
from django.db import transaction
from django.db.models import F, Prefetch, Q
from django.http import FileResponse, Http404
from django.shortcuts import redirect
from django.urls import reverse
from django.utils import timezone
from django.views import View
from PIL import Image, ImageOps

from agenda.alerts import notify_evidence_reviewers, resolve_evidence_alerts
from common.access import ProtectedViewMixin, get_scoped_object_or_404
from common.realtime import publish
from common.text import clean_description_text
from configuration.models import Period
from configuration.period_services import lock_open_period, lock_period_registry
from configuration.services import AuditoriaService

from .models import Activity, Evidence, EvidenceBatch, EvidenceBatchAnnulment, EvidenceValidation


VIEW_ACTIVITY = "activities.view_activity"
VIEW_EVIDENCE = "activities.view_evidence"
ADD_EVIDENCE = "activities.add_evidence"
REVIEW_EVIDENCE = "activities.add_evidencevalidation"
ANNUL_EVIDENCE = "activities.change_evidencevalidation"
MAX_IMAGES = 10
MAX_IMAGE_BYTES = Evidence.MAX_SIZE_KB * 1024
MAX_IMAGE_PIXELS = 20_000_000
IMAGE_FORMATS = {"JPEG": ("jpg", "image/jpeg"), "PNG": ("png", "image/png")}


def evidence_activities(user, permission):
    from common.maintainers import activity_queryset

    readable = activity_queryset(user, VIEW_ACTIVITY, include_archived=True)
    archived = activity_queryset(user, "activities.archive_activity", include_archived=True)
    readable = readable.filter(Q(deleted_at__isnull=True) | Q(pk__in=archived.values("pk")))
    return activity_queryset(user, permission, include_archived=True).filter(pk__in=readable.values("pk"))


class MultipleImagesInput(forms.ClearableFileInput):
    allow_multiple_selected = True


class EvidenceImagesField(forms.Field):
    widget = MultipleImagesInput(attrs={
        "class": "form-control", "accept": "image/jpeg,image/png", "aria-describedby": "activity-evidence-formats",
    })

    def clean(self, uploads):
        super().clean(uploads)
        if len(uploads) > MAX_IMAGES:
            raise ValidationError(f"Selecciona hasta {MAX_IMAGES} imágenes por registro.")
        if any(upload.size > MAX_IMAGE_BYTES for upload in uploads):
            raise ValidationError("Cada imagen puede pesar hasta 5 MiB.")
        return [self.prepare_image(upload) for upload in uploads]

    @staticmethod
    def prepare_image(upload):
        try:
            with Image.open(upload, formats=list(IMAGE_FORMATS)) as source:
                if source.width * source.height > MAX_IMAGE_PIXELS:
                    raise ValidationError(f"{upload.name}: la imagen supera 20 megapíxeles.")
                if getattr(source, "is_animated", False):
                    raise ValidationError(f"{upload.name}: elige una imagen fija.")
                image_format = source.format
                image = ImageOps.exif_transpose(source)
                image = image.convert("RGBA" if image_format == "PNG" else "RGB")
                image.info.clear()
                output = BytesIO()
                image.save(output, format=image_format)
        except (OSError, ValueError, Image.DecompressionBombError) as error:
            raise ValidationError(f"{upload.name}: selecciona una imagen JPG o PNG válida.") from error
        if output.tell() > MAX_IMAGE_BYTES:
            raise ValidationError(f"{upload.name}: la imagen procesada supera 5 MiB.")
        extension, _ = IMAGE_FORMATS[image_format]
        return upload.name, extension, output.getvalue()


class EvidenceUploadForm(forms.Form):
    stage = forms.ChoiceField(label="Etapa del trabajo", choices=[("", "Selecciona una etapa"), *EvidenceBatch.Stage.choices],
                              widget=forms.Select(attrs={"class": "form-select"}))
    description = forms.CharField(label="Descripción de lo realizado", max_length=500,
                                  widget=forms.Textarea(attrs={"class": "form-control", "rows": 3}))
    images = EvidenceImagesField(label="Imágenes de respaldo")

    def clean_description(self):
        description = clean_description_text(self.cleaned_data["description"], 500)
        if not description.strip():
            raise ValidationError("Describe lo que se hizo o constató en esta etapa.")
        return description


class EvidenceReviewForm(forms.Form):
    status = forms.ChoiceField(label="Decisión", choices=[
        ("", "Selecciona una decisión"),
        *((status, label) for status, label in EvidenceValidation.Status.choices if status != EvidenceValidation.Status.PENDING),
    ], widget=forms.Select(attrs={"class": "form-select"}))
    observation = forms.CharField(label="Observación", max_length=500, required=False,
                                  widget=forms.Textarea(attrs={"class": "form-control", "rows": 2}))

    def clean(self):
        data = super().clean()
        if data.get("status") in (EvidenceValidation.Status.REJECTED, EvidenceValidation.Status.CORRECTION_REQUESTED):
            if not data.get("observation") and "observation" not in self.errors:
                self.add_error("observation", "Indica el motivo de la decisión.")
        return data


ANNULMENT_REASON_REQUIRED = "Indica el motivo de la anulación."


class EvidenceAnnulmentForm(forms.Form):
    reason = forms.CharField(label="Motivo de la anulación", max_length=500,
                            error_messages={"required": ANNULMENT_REASON_REQUIRED},
                            widget=forms.Textarea(attrs={"class": "form-control", "rows": 2}))

    def clean_reason(self):
        reason = clean_description_text(self.cleaned_data["reason"], 500)
        if not reason:
            raise ValidationError(ANNULMENT_REASON_REQUIRED)
        return reason


def evidence_context(user, activity):
    if not user.has_perm(VIEW_EVIDENCE) or not evidence_activities(user, VIEW_EVIDENCE).filter(pk=activity.pk).exists():
        return {}
    review_queryset = EvidenceValidation.objects.filter(
        Q(deleted_at__isnull=True)
        | Q(status=EvidenceValidation.Status.APPROVED, deleted_at=F("evidence__batch__annulment__annulled_at")),
    ).select_related("verifier").order_by("-created_at", "-pk")
    batches = activity.evidence_batches.filter(deleted_at__isnull=True).select_related(
        "author", "annulment__actor",
    ).prefetch_related(
        Prefetch("images", queryset=Evidence.objects.filter(deleted_at__isnull=True).order_by("pk").prefetch_related(
            Prefetch("validations", queryset=review_queryset, to_attr="visible_reviews"),
        ), to_attr="active_images"),
    )
    actor = getattr(user, "official", None)
    writable = actor is not None and actor.is_enabled and activity.deleted_at is None and Period.objects.filter(
        start_date__lte=activity.date, end_date__gte=activity.date, deleted_at__isnull=True, status=Period.Status.OPEN,
    ).exists()
    can_upload = writable and user.has_perm(ADD_EVIDENCE) and evidence_activities(user, ADD_EVIDENCE).filter(pk=activity.pk).exists()
    can_review = writable and user.has_perm(REVIEW_EVIDENCE) and evidence_activities(user, REVIEW_EVIDENCE).filter(pk=activity.pk).exists()
    can_annul = writable and user.has_perm(ANNUL_EVIDENCE) and evidence_activities(user, ANNUL_EVIDENCE).filter(pk=activity.pk).exists()
    visible_batches = []
    for batch in batches:
        if not batch.active_images:
            continue
        annulment = getattr(batch, "annulment", None)
        reviews = [review for image in batch.active_images for review in image.visible_reviews]
        batch.review = next((review for review in reviews
                             if annulment is None or review.deleted_at == annulment.annulled_at), None)
        if can_review and annulment is None and batch.author_id != actor.pk and not reviews:
            batch.review_form = EvidenceReviewForm(auto_id=f"review_{batch.pk}_%s")
        if can_annul and annulment is None and batch.author_id != actor.pk and any(
            review.status == EvidenceValidation.Status.APPROVED for review in reviews
        ):
            batch.annulment_form = EvidenceAnnulmentForm(auto_id=f"annul_{batch.pk}_%s")
        visible_batches.append(batch)
    return {
        "show_evidence": True, "evidence_activity": activity, "evidence_batches": visible_batches,
        "evidence_upload_form": EvidenceUploadForm() if can_upload else None, "evidence_max_images": MAX_IMAGES,
    }


def activity_evidence_url(activity):
    return reverse("activity_detail", args=[activity.pk], fragment="activity-evidence-title")


class EvidenceMutationView(ProtectedViewMixin, View):
    http_method_names = ["post"]
    operation_permission = None

    def get_permission_required(self):
        return (VIEW_ACTIVITY, VIEW_EVIDENCE, self.operation_permission)

    def get_activity(self, request, pk):
        queryset = evidence_activities(request.user, self.operation_permission).filter(
            deleted_at__isnull=True, pk__in=evidence_activities(request.user, VIEW_EVIDENCE).values("pk"),
        )
        return get_scoped_object_or_404(request, queryset, pk=pk)

    def lock_activity(self, request, activity):
        lock_period_registry()
        activity = get_scoped_object_or_404(request, Activity.objects.select_for_update(), pk=activity.pk)
        self.get_activity(request, activity.pk)
        lock_open_period(activity.date)
        return activity

    def locked_batch(self, request, activity, batch_id):
        return get_scoped_object_or_404(request, activity.evidence_batches.select_for_update().filter(
            deleted_at__isnull=True,
        ), pk=batch_id)

    @staticmethod
    def publish_change(activity):
        transaction.on_commit(lambda: publish("activity", activity.pk, set()))

    @staticmethod
    def report_errors(request, errors):
        for error in errors:
            messages.error(request, error)


class EvidenceUploadView(EvidenceMutationView):
    operation_permission = ADD_EVIDENCE

    def post(self, request, pk):
        activity = self.get_activity(request, pk)
        actor = getattr(request.user, "official", None)
        if actor is None or not actor.is_enabled:
            return self.handle_no_permission()
        form = EvidenceUploadForm(request.POST, request.FILES)
        if not form.is_valid():
            self.report_errors(request, (error for errors in form.errors.values() for error in errors))
            return redirect(activity_evidence_url(activity))

        storage = FileSystemStorage(location=settings.EVIDENCE_ROOT)
        saved = []
        try:
            with transaction.atomic():
                activity = self.lock_activity(request, activity)
                batch = EvidenceBatch.objects.create(
                    activity=activity, author=actor, stage=form.cleaned_data["stage"],
                    description=form.cleaned_data["description"],
                )
                for original, extension, content in form.cleaned_data["images"]:
                    name = storage.save(f"{uuid4().hex}.{extension}", ContentFile(content))
                    saved.append(name)
                    Evidence.objects.create(activity=activity, batch=batch, original_name=original, file_url=name,
                                            file_format=extension, size_kb=(len(content) + 1023) // 1024)
                notify_evidence_reviewers(batch)
                AuditoriaService.register_change(actor, "Evidencia adjuntada", batch,
                                                new_value=f"{activity.code} · {batch.get_stage_display()} · {len(saved)} imágenes",
                                                origin_ip=request.META.get("REMOTE_ADDR") or None, actor=request.user)
                self.publish_change(activity)
        except Exception as error:
            for name in saved:
                storage.delete(name)
            if not isinstance(error, (ValidationError, OSError)):
                raise
            errors = error.messages if isinstance(error, ValidationError) else ["No se pudieron guardar las imágenes."]
            self.report_errors(request, errors)
        else:
            messages.success(request, "Evidencia guardada. Quedó pendiente de revisión.")
        return redirect(activity_evidence_url(activity))


class EvidenceReviewView(EvidenceMutationView):
    operation_permission = REVIEW_EVIDENCE

    def post(self, request, pk, batch_id):
        activity = self.get_activity(request, pk)
        actor = getattr(request.user, "official", None)
        if actor is None or not actor.is_enabled:
            return self.handle_no_permission()
        form = EvidenceReviewForm(request.POST)
        try:
            with transaction.atomic():
                activity = self.lock_activity(request, activity)
                batch = self.locked_batch(request, activity, batch_id)
                if batch.author_id == actor.pk:
                    return self.handle_no_permission()
                if not form.is_valid():
                    raise ValidationError(form.errors.as_data())
                images = list(batch.images.filter(activity=activity, deleted_at__isnull=True))
                if (getattr(batch, "annulment", None) or not images
                        or EvidenceValidation.objects.filter(evidence__in=images, deleted_at__isnull=True).exists()):
                    raise ValidationError("Esta evidencia ya no está pendiente de revisión.")
                status = form.cleaned_data["status"]
                observation = form.cleaned_data["observation"]
                EvidenceValidation.objects.bulk_create([
                    EvidenceValidation(evidence=image, verifier=actor, status=status, observation=observation,
                                       validated_at=timezone.now())
                    for image in images
                ])
                resolve_evidence_alerts(batch)
                AuditoriaService.register_change(actor, "Evidencia revisada", batch,
                    previous_value=EvidenceValidation.Status.PENDING, new_value=f"{status} · {observation}",
                    origin_ip=request.META.get("REMOTE_ADDR") or None, actor=request.user)
                self.publish_change(activity)
        except ValidationError as error:
            self.report_errors(request, error.messages)
        else:
            messages.success(request, "Revisión de evidencia guardada.")
        return redirect(activity_evidence_url(activity))


class EvidenceAnnulmentView(EvidenceMutationView):
    operation_permission = ANNUL_EVIDENCE

    def post(self, request, pk, batch_id):
        activity = self.get_activity(request, pk)
        actor = getattr(request.user, "official", None)
        if actor is None or not actor.is_enabled:
            return self.handle_no_permission()
        form = EvidenceAnnulmentForm(request.POST)
        try:
            with transaction.atomic():
                activity = self.lock_activity(request, activity)
                batch = self.locked_batch(request, activity, batch_id)
                if batch.author_id == actor.pk:
                    return self.handle_no_permission()
                if not form.is_valid():
                    raise ValidationError(form.errors.as_data())
                if getattr(batch, "annulment", None):
                    raise ValidationError("La aprobación de esta evidencia ya fue anulada.")
                now = timezone.now()
                approvals = EvidenceValidation.objects.filter(
                    evidence_id__in=batch.images.filter(activity=activity, deleted_at__isnull=True).values("pk"),
                    status=EvidenceValidation.Status.APPROVED, deleted_at__isnull=True,
                )
                if not approvals.update(deleted_at=now, updated_at=now):
                    raise ValidationError("Esta evidencia no tiene una aprobación vigente que se pueda anular.")
                reason = form.cleaned_data["reason"]
                EvidenceBatchAnnulment.objects.create(batch=batch, actor=actor, reason=reason, annulled_at=now)
                AuditoriaService.register_change(actor, "Aprobación de evidencia anulada", batch,
                    previous_value="Aprobada", new_value=f"Anulada · {reason}",
                    origin_ip=request.META.get("REMOTE_ADDR") or None, actor=request.user)
                self.publish_change(activity)
        except ValidationError as error:
            self.report_errors(request, error.messages)
        else:
            messages.success(request, "Aprobación anulada correctamente.")
        return redirect(activity_evidence_url(activity))


class EvidenceImageView(ProtectedViewMixin, View):
    permission_required = (VIEW_ACTIVITY, VIEW_EVIDENCE)

    def get(self, request, pk, image_id):
        activity = get_scoped_object_or_404(request, evidence_activities(request.user, VIEW_EVIDENCE), pk=pk)
        image = get_scoped_object_or_404(request, activity.evidences.filter(
            batch__activity=activity, batch__deleted_at__isnull=True, deleted_at__isnull=True,
        ), pk=image_id)
        content_types = dict(IMAGE_FORMATS.values())
        if image.file_format not in content_types:
            raise Http404
        try:
            source = FileSystemStorage(location=settings.EVIDENCE_ROOT).open(image.file_url, "rb")
        except FileNotFoundError as error:
            raise Http404 from error
        response = FileResponse(source, content_type=content_types[image.file_format], filename=image.original_name)
        response["Cache-Control"] = "private, no-store"
        response["X-Content-Type-Options"] = "nosniff"
        return response
