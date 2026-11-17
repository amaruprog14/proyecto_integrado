from django.http import JsonResponse
from django.utils.dateparse import parse_date
from django.views import View

from accounts.models import Official
from activities.classification import CLASSIFICATION, classification_choices
from activities.models import Activity
from activities.territorial import registration_delegations
from common.access import ProtectedViewMixin, get_scoped_object_or_404
from common.list_state import positive
from common.maintainer_forms import activity_item_choices
from common.maintainers import activity_queryset
from common.scopes import scope_officials


class ActivityEligibleItemsView(ProtectedViewMixin, View):
    def get_permission_required(self):
        action = "change" if self.request.GET.get("activity") else "add"
        return (f"activities.{action}_activity",)

    def get(self, request):
        permission = self.get_permission_required()[0]
        officials = scope_officials(Official.objects.filter(
            status=Official.Status.ACTIVE, deleted_at__isnull=True,
        ), request.user, permission)
        official = get_scoped_object_or_404(request, officials, pk=positive(request.GET.get("official"), 0))
        raw_date = request.GET.get("date", "")
        try:
            date = parse_date(raw_date)
        except ValueError:
            date = None
        if raw_date and date is None:
            return JsonResponse({"error": "Selecciona una fecha válida."}, status=400)
        activity_id = request.GET.get("activity")
        activity = Activity()
        if activity_id:
            activity = get_scoped_object_or_404(
                request, activity_queryset(request.user, permission).filter(social_attentions__isnull=True),
                pk=positive(activity_id, 0),
            )
        items = list(activity_item_choices(official, date, activity).values("id", "item_name")) if date else []
        choices = classification_choices(official, activity)
        classification = {
            key: list(choices[key].values("id", "name", parent)) for key, _, parent in CLASSIFICATION
        }
        return JsonResponse({
            "items": items, "classification": classification,
            "delegations": list(registration_delegations(official, request.user, permission).values("id", "delegation_name")),
        })
