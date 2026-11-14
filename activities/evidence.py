from io import BytesIO
from uuid import uuid4

from django import forms
from django.conf import settings
from django.contrib import messages
from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from django.core.files.storage import FileSystemStorage
from django.db import transaction
from django.db.models import Prefetch, Q
from django.http import FileResponse, Http404
from django.shortcuts import redirect
from django.urls import reverse
from django.utils import timezone
from django.views import View
from PIL import Image, ImageOps

from common.access import ProtectedViewMixin, get_scoped_object_or_404
from common.text import clean_description_text
from configuration.models import Period
from configuration.period_services import lock_open_period, lock_period_registry
from configuration.services import AuditoriaService

from .models import Activity, Evidence, EvidenceBatch, EvidenceValidation


VIEW_ACTIVITY = "activities.view_activity"
VIEW_EVIDENCE = "activities.view_evidence"
ADD_EVIDENCE = "activities.add_evidence"
REVIEW_EVIDENCE = "activities.add_evidencevalidation"
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


def evidence_context(user, activity):
    if not user.has_perm(VIEW_EVIDENCE) or not evidence_activities(user, VIEW_EVIDENCE).filter(pk=activity.pk).exists():
        return {}
    batches = activity.evidence_batches.filter(deleted_at__isnull=True).select_related("author").prefetch_related(
        Prefetch("images", queryset=Evidence.objects.filter(deleted_at__isnull=True).order_by("pk").prefetch_related(
            Prefetch("validations", queryset=EvidenceValidation.objects.filter(deleted_at__isnull=True)
                     .select_related("verifier").order_by("-created_at", "-pk"), to_attr="active_reviews"),
        ), to_attr="active_images"),
    )
    actor = getattr(user, "official", None)
    writable = actor is not None and actor.is_enabled and activity.deleted_at is None and Period.objects.filter(
        start_date__lte=activity.date, end_date__gte=activity.date, deleted_at__isnull=True, status=Period.Status.OPEN,
    ).exists()
    can_upload = writable and user.has_perm(ADD_EVIDENCE) and evidence_activities(user, ADD_EVIDENCE).filter(pk=activity.pk).exists()
    can_review = writable and user.has_perm(REVIEW_EVIDENCE) and evidence_activities(user, REVIEW_EVIDENCE).filter(pk=activity.pk).exists()
    visible_batches = []
    for batch in batches:
        if not batch.active_images:
            continue
        batch.review = next(iter(batch.active_images[0].active_reviews), None)
        if can_review and batch.author_id != actor.pk and not any(
            image.active_reviews for image in batch.active_images
        ):
            batch.review_form = EvidenceReviewForm(auto_id=f"review_{batch.pk}_%s")
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
                AuditoriaService.register_change(actor, "Evidencia adjuntada", batch,
                                                new_value=f"{activity.code} · {batch.get_stage_display()} · {len(saved)} imágenes")
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
                batch = get_scoped_object_or_404(request, activity.evidence_batches.select_for_update().filter(
                    deleted_at__isnull=True,
                ), pk=batch_id)
                if batch.author_id == actor.pk:
                    return self.handle_no_permission()
                if not form.is_valid():
                    raise ValidationError(form.errors.as_data())
                images = list(batch.images.filter(activity=activity, deleted_at__isnull=True))
                if not images or EvidenceValidation.objects.filter(evidence__in=images, deleted_at__isnull=True).exists():
                    raise ValidationError("Esta evidencia ya no está pendiente de revisión.")
                status = form.cleaned_data["status"]
                observation = form.cleaned_data["observation"]
                EvidenceValidation.objects.bulk_create([
                    EvidenceValidation(evidence=image, verifier=actor, status=status, observation=observation,
                                       validated_at=timezone.now())
                    for image in images
                ])
                AuditoriaService.register_change(actor, "Evidencia revisada", batch,
                    previous_value=EvidenceValidation.Status.PENDING, new_value=f"{status} · {observation}")
        except ValidationError as error:
            self.report_errors(request, error.messages)
        else:
            messages.success(request, "Revisión de evidencia guardada.")
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
