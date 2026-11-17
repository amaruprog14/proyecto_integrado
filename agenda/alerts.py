from collections import defaultdict

from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.db.models import Q
from django.urls import reverse
from django.utils import timezone

from accounts.models import Official, Role
from activities.models import Activity
from common.scopes import permission_scope, scope_officials
from configuration.models import Period

from .commitments import ASSIGN, VIEW, deadline_labels, scoped_commitments
from .models import Alert, Commitment


PERFORMANCE_TYPES = (Alert.AlertType.NO_RECORDS, Alert.AlertType.LOW_PROGRESS)


def eligible_officials(permission):
    app, codename = permission.split(".")
    return Official.objects.filter(
        status=Official.Status.ACTIVE, deleted_at__isnull=True, user__is_active=True,
    ).filter(
        Q(user__is_superuser=True)
        | Q(roles__permissions__codename=codename, roles__permissions__content_type__app_label=app,
            roles__is_active=True, roles__deleted_at__isnull=True)
        | Q(user__groups__permissions__codename=codename, user__groups__permissions__content_type__app_label=app,
            user__groups__sgr_profile__is_active=True, user__groups__sgr_profile__deleted_at__isnull=True)
        | Q(user__user_permissions__codename=codename, user__user_permissions__content_type__app_label=app)
    ).select_related("user", "position").distinct()


def evidence_review_scope(user):
    from activities.evidence import REVIEW_EVIDENCE, VIEW_ACTIVITY, VIEW_EVIDENCE, evidence_activities

    if not user.has_perms((VIEW_ACTIVITY, VIEW_EVIDENCE, REVIEW_EVIDENCE)):
        return Activity.objects.none()
    return evidence_activities(user, REVIEW_EVIDENCE).filter(
        pk__in=evidence_activities(user, VIEW_EVIDENCE).values("pk"),
    )


def notify_evidence_reviewers(batch):
    from activities.evidence import REVIEW_EVIDENCE

    for candidate in eligible_officials(REVIEW_EVIDENCE).exclude(pk=batch.author_id):
        if evidence_review_scope(candidate.user).filter(pk=batch.activity_id).exists():
            Alert.objects.get_or_create(
                official=candidate, evidence_batch=batch,
                defaults={
                    "alert_type": Alert.AlertType.PENDING_EVIDENCE,
                    "reason": f"La actividad {batch.activity.code} tiene evidencia pendiente de revisión.",
                    "reference_link": reverse("activity_detail", args=[batch.activity_id], fragment=f"evidence-batch-{batch.pk}"),
                },
            )


def resolve_evidence_alerts(batch):
    now = timezone.now()
    Alert.objects.filter(evidence_batch=batch, deleted_at__isnull=True, resolved_at__isnull=True).update(
        resolved_at=now, updated_at=now,
    )


def update_commitment_alerts(record, today=None, supervisors=None):
    today = today or timezone.localdate()
    now = timezone.now()
    alerts = Alert.objects.filter(commitment=record, deleted_at__isnull=True)
    recipients = set()
    if (record.deleted_at is None and record.current_status not in Commitment.CLOSED_STATUSES
            and record.committed_date <= today + timedelta(days=settings.COMMITMENT_DUE_WARNING_DAYS)):
        if supervisors is None:
            supervisors = list(eligible_officials(ASSIGN))
        responsible = record.responsible
        candidates = {official.pk: official for official in supervisors}
        candidates[responsible.pk] = responsible
        label = deadline_labels(record, today)
        reason = f"{record.identifier} · {label} · Fecha comprometida: {record.committed_date:%d-%m-%Y}."
        for pk, candidate in candidates.items():
            user = candidate.user
            if not candidate.is_enabled or not user or not user.has_perm(VIEW):
                continue
            if not scoped_commitments(user).filter(pk=record.pk).exists():
                continue
            if pk != responsible.pk and not scoped_commitments(user, ASSIGN).filter(pk=record.pk).exists():
                continue
            recipients.add(pk)
            alert, created = Alert.objects.get_or_create(official_id=pk, commitment=record, defaults={
                "alert_type": Alert.AlertType.DUE_DATE, "reason": reason,
                "reference_link": reverse("commitment_detail", args=[record.pk]),
            })
            if not created and alert.deleted_at is None and (alert.reason != reason or alert.resolved_at):
                Alert.objects.filter(pk=alert.pk).update(
                    reason=reason, resolved_at=None, status=Alert.Status.PENDING, updated_at=now,
                )
    alerts.filter(resolved_at__isnull=True).exclude(official_id__in=recipients).update(resolved_at=now, updated_at=now)


def refresh_commitment_alerts():
    today = timezone.localdate()
    supervisors = list(eligible_officials(ASSIGN))
    records = Commitment.objects.filter(
        Q(committed_date__lte=today + timedelta(days=settings.COMMITMENT_DUE_WARNING_DAYS),
          deleted_at__isnull=True) & ~Q(current_status__in=Commitment.CLOSED_STATUSES)
        | Q(alerts__resolved_at__isnull=True, alerts__isnull=False),
    ).order_by().values_list("pk", flat=True).distinct()
    for pk in records.iterator():
        with transaction.atomic():
            record = Commitment.objects.select_for_update().get(pk=pk)
            update_commitment_alerts(record, today, supervisors)


def inbox_alerts(user, official):
    from analytics.views import TEAM_PERFORMANCE, VIEW_PERFORMANCE

    evidence = Q(
        alert_type=Alert.AlertType.PENDING_EVIDENCE, evidence_batch__deleted_at__isnull=True,
        evidence_batch__activity_id__in=evidence_review_scope(user).values("pk"),
    )
    allowed = evidence
    if user.has_perm(VIEW):
        allowed |= Q(alert_type=Alert.AlertType.DUE_DATE, commitment_id__in=scoped_commitments(user).values("pk"))
    if user.has_perm(VIEW_PERFORMANCE):
        subjects = Q(performance_subject=official)
        if user.has_perm(TEAM_PERFORMANCE):
            permitted = scope_officials(Official.objects.all(), user, TEAM_PERFORMANCE)
            subjects |= Q(performance_subject_id__in=permitted.values("pk"))
        allowed |= (
            Q(alert_type__in=PERFORMANCE_TYPES, performance_period__isnull=False,
              performance_period__deleted_at__isnull=True, performance_subject__deleted_at__isnull=True)
            & subjects
        )
    return Alert.objects.filter(official=official, deleted_at__isnull=True).filter(allowed)


def refresh_performance_alerts(today=None):
    """Reconcilia los avisos del período vigente. Se puede ejecutar repetidamente."""
    from analytics.services import CalculadorDesempenoService, TrafficLight
    from analytics.views import TEAM_PERFORMANCE, VIEW_PERFORMANCE, recent_activity
    from common.maintainers import activity_queryset

    today = today or timezone.localdate()
    tracked = Alert.objects.filter(
        alert_type__in=PERFORMANCE_TYPES, performance_period__isnull=False, deleted_at__isnull=True,
    )
    period = Period.objects.filter(
        deleted_at__isnull=True, status=Period.Status.OPEN, start_date__lte=today, end_date__gte=today,
    ).order_by("-start_date", "-pk").first()
    now = timezone.now()
    active = {}
    if period is not None:
        staff = Official.objects.filter(status=Official.Status.ACTIVE, deleted_at__isnull=True).select_related("position")
        results = {
            result.official.pk: result for result in CalculadorDesempenoService.calculate_many(staff, period, today)
            if result.items
        }
        own_stats = recent_activity(list(results), period, today, Activity.objects.all())
        supervisors = defaultdict(list)
        for reviewer in eligible_officials(TEAM_PERFORMANCE):
            if not reviewer.user.has_perms((VIEW_PERFORMANCE, TEAM_PERFORMANCE)):
                continue
            if permission_scope(reviewer.user, TEAM_PERFORMANCE) not in (Role.Scope.ALL, Role.Scope.DELEGATION):
                continue
            subjects = list(scope_officials(staff.filter(pk__in=results), reviewer.user, TEAM_PERFORMANCE).exclude(pk=reviewer.pk)
                            .values_list("pk", flat=True))
            stats = recent_activity(subjects, period, today, activity_queryset(reviewer.user, TEAM_PERFORMANCE))
            for subject_id in subjects:
                supervisors[subject_id].append((reviewer.pk, stats[subject_id]["attention"]))
        own_recipients = set(eligible_officials(VIEW_PERFORMANCE).values_list("pk", flat=True))
        for subject_id, result in results.items():
            recipients = supervisors[subject_id]
            if subject_id in own_recipients:
                recipients.append((subject_id, own_stats[subject_id]["attention"]))
            for recipient_id, inactive in recipients:
                if inactive:
                    active[recipient_id, subject_id, Alert.AlertType.NO_RECORDS] = (
                        f"{result.official.full_name} alcanzó el umbral de días sin registros válidos."
                    )
                if result.total_traffic_light == TrafficLight.RED:
                    active[recipient_id, subject_id, Alert.AlertType.LOW_PROGRESS] = (
                        f"{result.official.full_name} tiene un resultado de desempeño bajo el umbral."
                    )
    existing = {
        (alert.official_id, alert.performance_subject_id, alert.alert_type): alert
        for alert in tracked.filter(performance_period=period)
    } if period is not None else {}
    active_ids = []
    created = 0
    for (recipient_id, subject_id, kind), reason in active.items():
        alert = existing.get((recipient_id, subject_id, kind))
        if alert is None:
            alert, is_new = Alert.objects.get_or_create(
                official_id=recipient_id, performance_subject_id=subject_id, performance_period=period, alert_type=kind,
                defaults={
                    "reason": reason[:255],
                    "reference_link": reverse("my_performance", query={"period": period.pk, "official": subject_id},
                                              fragment="recent-activity-title" if kind == Alert.AlertType.NO_RECORDS else "resumen-title"),
                },
            )
            created += is_new
        if alert.deleted_at is not None:
            continue
        if alert.resolved_at is not None:
            Alert.objects.filter(pk=alert.pk, resolved_at__isnull=False).update(
                resolved_at=None, status=Alert.Status.PENDING, updated_at=now,
            )
        active_ids.append(alert.pk)
    resolved = tracked.filter(resolved_at__isnull=True).exclude(pk__in=active_ids).update(resolved_at=now, updated_at=now)
    return created, resolved
