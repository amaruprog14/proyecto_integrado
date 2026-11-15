from django import forms
from django.contrib import messages
from django.db import transaction
from django.shortcuts import redirect
from django.urls import reverse
from django.views import View

from activities.cases import CHANGE_CASE, VIEW_CASE, scoped_cases
from common.access import ProtectedViewMixin, get_scoped_object_or_404
from common.text import clean_description_text
from configuration.services import AuditoriaService

from .commitments import CHANGE, VIEW, scoped_commitments
from .models import Comment


class InternalCommentForm(forms.Form):
    text = forms.CharField(
        label="Comentario interno", max_length=500,
        widget=forms.Textarea(attrs={"class": "form-control", "rows": 3}),
    )

    def clean_text(self):
        return clean_description_text(self.cleaned_data["text"])


def activity_comments_queryset(user, permission):
    from common.maintainers import activity_queryset

    return activity_queryset(user, permission)


COMMENT_TARGETS = {
    "activity": (
        activity_comments_queryset, "activities.view_activity", "activities.change_activity",
        "activity_detail", "activity_internal_comment",
    ),
    "case": (scoped_cases, VIEW_CASE, CHANGE_CASE, "attention_case_detail", "case_internal_comment"),
    "commitment": (scoped_commitments, VIEW, CHANGE, "commitment_detail", "commitment_internal_comment"),
}


def comment_open(record, target):
    if record.deleted_at is not None:
        return False
    if target == "case":
        return not record.is_closed
    if target == "commitment":
        return bool(record.next_statuses)
    return True


def comments_context(user, record, target):
    queryset, _, change_permission, _, post_route = COMMENT_TARGETS[target]
    actor = getattr(user, "official", None)
    can_comment = (
        actor is not None and actor.is_enabled and comment_open(record, target)
        and user.has_perm(change_permission) and queryset(user, change_permission).filter(pk=record.pk).exists()
    )
    return {
        "show_internal_comments": True,
        "internal_comments": record.comments.filter(deleted_at__isnull=True).select_related("author").order_by("date", "pk"),
        "internal_comment_form": InternalCommentForm() if can_comment else None,
        "internal_comment_url": reverse(post_route, args=[record.pk]) if can_comment else None,
    }


class InternalCommentView(ProtectedViewMixin, View):
    target = None
    http_method_names = ["post"]

    def get_permission_required(self):
        return COMMENT_TARGETS[self.target][1:3]

    def post(self, request, pk):
        queryset, view_permission, change_permission, detail_route, _ = COMMENT_TARGETS[self.target]
        actor = getattr(request.user, "official", None)
        if actor is None or not actor.is_enabled:
            return self.handle_no_permission()
        readable = queryset(request.user, view_permission).values("pk")
        writable = queryset(request.user, change_permission).filter(pk__in=readable)
        success_url = reverse(detail_route, args=[pk], fragment="internal-comments")
        with transaction.atomic():
            records = writable.model.objects.select_for_update().filter(pk__in=writable.values("pk"))
            record = get_scoped_object_or_404(request, records, pk=pk)
            if not comment_open(record, self.target):
                return self.handle_no_permission()
            form = InternalCommentForm(request.POST)
            if form.is_valid():
                comment = Comment.objects.create(author=actor, text=form.cleaned_data["text"], **{self.target: record})
                AuditoriaService.register_change(
                    actor, "Comentario interno agregado", comment,
                    new_value=f"{record._meta.label_lower} {record.pk}", origin_ip=request.META.get("REMOTE_ADDR") or None,
                )
                messages.success(request, "Comentario interno guardado.")
            else:
                messages.error(request, "Escribe un comentario de hasta 500 caracteres.")
        return redirect(success_url)
