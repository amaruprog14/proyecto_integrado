from itertools import islice

from django.db.models import F, Q

from accounts.models import Role
from activities.models import Activity
from activities.territorial import activities_in_delegations
from analytics.models import DelegationActivityFreeze, DelegationActivitySnapshot
from common.scopes import delegation_ids, permission_scope


VIEW_ACTIVITY = "activities.view_activity"


def computable_territory(queryset, period, until):
    from analytics.services import computable_activities

    return computable_activities(queryset.filter(
        deleted_at__isnull=True, date__range=(period.start_date, min(period.end_date, until)),
    ))


def freeze_territorial_activities(period, now):
    freeze = DelegationActivityFreeze.objects.create(period=period, captured_at=now)
    rows = computable_territory(Activity.objects.all(), period, period.end_date).filter(
        Q(social_attentions__delegation__isnull=False) | Q(registration_delegation__isnull=False),
    ).order_by("pk").values(
        "pk", "code", "date", "official_id", "official__full_name", "item__item_name", "delegation_estimated",
        "registration_delegation_id", "social_attentions__delegation_id",
    ).iterator(chunk_size=500)
    snapshots = (
        DelegationActivitySnapshot(
            freeze=freeze, activity_id=row["pk"], code=row["code"], date=row["date"],
            official_id=row["official_id"], official_name=row["official__full_name"], item_name=row["item__item_name"],
            delegation_id=row["social_attentions__delegation_id"] or row["registration_delegation_id"],
            estimated=row["social_attentions__delegation_id"] is None and row["delegation_estimated"],
        ) for row in rows
    )
    while batch := list(islice(snapshots, 500)):
        DelegationActivitySnapshot.objects.bulk_create(batch)


def territorial_records(user, delegation, period, today):
    """Fuente compartida entre el total del tablero y la página de respaldo."""
    if not user.has_perm(VIEW_ACTIVITY):
        return None
    scope = permission_scope(user, VIEW_ACTIVITY)
    if scope is None or (scope == Role.Scope.DELEGATION and delegation.pk not in delegation_ids(user)):
        return None
    if period.status == period.Status.CLOSED:
        freeze = DelegationActivityFreeze.objects.filter(period=period, captured_at=period.frozen_at).first()
        if freeze is None:
            return None
        rows = freeze.activities.filter(delegation=delegation)
        if scope == Role.Scope.OWN:
            rows = rows.filter(official__user=user)
        return rows

    rows = activities_in_delegations(Activity.objects.all(), [delegation.pk])
    if scope == Role.Scope.OWN:
        rows = rows.filter(official__user=user)
    return computable_territory(rows, period, today).annotate(
        official_name=F("official__full_name"), item_name=F("item__item_name"), activity_id=F("pk"),
        estimated=F("delegation_estimated"),
    )
