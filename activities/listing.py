from datetime import date, datetime, time, timedelta

from django.urls import reverse
from django.utils import timezone
from django.utils.dateparse import parse_date

from common.list_state import sort_spec

from .client_portal import search_staff_requests, staff_requests
from .models import Activity, ClientRequest


REQUEST_RECORD_TYPE = "Solicitud ciudadana"
REQUEST_VIEW_PERMISSION = "activities.view_socialattention"


def filtered_requests(user, params):
    requests = staff_requests(user, REQUEST_VIEW_PERMISSION)
    if not user.has_perm(REQUEST_VIEW_PERMISSION) or params["record_source"] == "activity":
        return requests.none()
    status = params["status"]
    if status in (Activity.ListingStatus.ACTIVE, Activity.ListingStatus.INACTIVE) or any(
        params[key] for key in ("official", "item", "record_type")
    ):
        return requests.none()
    if status in ClientRequest.Status.values:
        requests = requests.filter(status=status)
    requests = search_staff_requests(requests, params["q"])
    zone = timezone.get_current_timezone()
    if start := parse_date(params["date_from"]):
        requests = requests.filter(created_at__gte=datetime.combine(start, time.min, tzinfo=zone))
    if (end := parse_date(params["date_to"])) and end < date.max:
        requests = requests.filter(created_at__lt=datetime.combine(end + timedelta(days=1), time.min, tzinfo=zone))
    return requests


def ordered_records(activities, requests, params):
    sort = params["sort"]
    created, activity_sort_fields = sort_spec("activity")
    activity_sort_field = created if sort == "created" else activity_sort_fields[sort][1]
    activity_keys = activities.order_by().values_list("pk", activity_sort_field)
    records = [(pk, "activity", value) for pk, value in activity_keys.iterator()]
    for pk, created_at in requests.order_by().values_list("pk", "created_at").iterator():
        if sort == "date":
            value = timezone.localdate(created_at)
        elif sort == "created":
            value = created_at
        elif sort == "code":
            value = f"SOL-{pk:06d}"
        else:
            value = REQUEST_RECORD_TYPE if sort == "record_type" else ""
        records.append((pk, "request", value))

    # Ordenar claves ligeras antes de paginar y cargar los modelos de la página.
    records.sort(key=lambda row: (row[1], -row[0]))
    records.sort(key=lambda row: row[2].casefold() if isinstance(row[2], str) else row[2],
                 reverse=params["direction"] == "desc")
    return records


def listing_objects(records, activities, requests):
    sources = {"activity": activities, "request": requests}
    objects = {
        source: queryset.in_bulk([pk for pk, kind, _ in records if kind == source])
        for source, queryset in sources.items()
    }
    return [objects[source][pk] for pk, source, _ in records if pk in objects[source]]


def export_objects(records, activities, requests):
    for start in range(0, len(records), 500):
        yield from listing_objects(records[start:start + 500], activities, requests)


def request_row(obj):
    date = timezone.localtime(obj.created_at).date()
    cells = [obj.identifier, "", "", date.isoformat(), REQUEST_RECORD_TYPE]
    return {
        "cells": cells + [obj.get_status_display()],
        "display_cells": [*cells[:3], date.strftime("%d-%m-%Y"), cells[4]],
        "status_code": obj.status,
        "status_label": obj.get_status_display(),
        "is_active": obj.status == ClientRequest.Status.RESOLVED,
        "detail": reverse("staff_client_request_detail", args=[obj.pk], query={"desde": "actividades"}),
        "view_label": f"Ver solicitud {obj.identifier}",
    }
