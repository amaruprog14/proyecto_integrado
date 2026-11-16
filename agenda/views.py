from django.core.paginator import Paginator
from django.db import transaction
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views import View

from common.access import ProtectedViewMixin, get_scoped_object_or_404
from configuration.services import AuditoriaService

from .alerts import inbox_alerts
from .models import Alert


class AlertInboxMixin(ProtectedViewMixin):
    permission_required = ()

    def has_permission(self):
        actor = getattr(self.request.user, "official", None)
        return actor is not None and actor.is_enabled and super().has_permission()

    def alerts(self):
        return inbox_alerts(self.request.user, self.request.user.official)


class AlertListView(AlertInboxMixin, View):
    def get(self, request):
        alerts = self.alerts().select_related("official")
        pending_only = request.GET.get("estado") != "todas"
        if pending_only:
            alerts = alerts.filter(status=Alert.Status.PENDING, resolved_at__isnull=True)
        page = Paginator(alerts, 20).get_page(request.GET.get("page"))
        return render(request, "agenda/alert_list.html", {"page_obj": page, "pending_only": pending_only})


class AlertSeenView(AlertInboxMixin, View):
    http_method_names = ["post"]

    def post(self, request, pk):
        with transaction.atomic():
            alert = get_scoped_object_or_404(request, self.alerts(), pk=pk)
            updated = Alert.objects.filter(pk=alert.pk, status=Alert.Status.PENDING, resolved_at__isnull=True).update(
                status=Alert.Status.SEEN, updated_at=timezone.now(),
            )
            if updated:
                AuditoriaService.register_change(
                    request.user.official, "Alerta revisada", alert, previous_value=Alert.Status.PENDING,
                    new_value=Alert.Status.SEEN, origin_ip=request.META.get("REMOTE_ADDR") or None,
                )
        return redirect("alert_list")
