from django.db.models import Q

from configuration.models import ActivityType, AttentionType, ServiceType, SubattentionType


CLASSIFICATION = (
    ("activity_type", ActivityType, "area_id"),
    ("service_type", ServiceType, "activity_type_id"),
    ("attention_type", AttentionType, "service_type_id"),
    ("subattention_type", SubattentionType, "attention_type_id"),
)


def classification_choices(official, activity):
    """Opciones por área con la cadena vigente y los valores históricos del mismo funcionario."""
    area_id = official.area_id if official else None
    types = ActivityType.objects.none()
    if area_id:
        types = ActivityType.objects.filter(area_id=area_id, area__is_active=True, area__deleted_at__isnull=True,
                                            is_active=True, deleted_at__isnull=True)
    services = ServiceType.objects.filter(activity_type__in=types, is_active=True, deleted_at__isnull=True)
    attention = AttentionType.objects.filter(service_type__in=services, is_active=True, deleted_at__isnull=True)
    subattention = SubattentionType.objects.filter(attention_type__in=attention, is_active=True, deleted_at__isnull=True)
    choices = dict(zip((key for key, _, _ in CLASSIFICATION), (types, services, attention, subattention)))
    if official and official.pk == activity.official_id:
        for key, model, _ in CLASSIFICATION:
            saved_id = getattr(activity, f"{key}_id")
            if saved_id:
                choices[key] = model.objects.filter(Q(pk__in=choices[key].order_by().values("pk")) | Q(pk=saved_id))
    return choices
