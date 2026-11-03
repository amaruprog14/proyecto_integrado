from django.core.management.base import BaseCommand, CommandError
from django.db.models import Q
from django.utils import timezone
from configuration.models import Period, AttentionType


class Command(BaseCommand):
    help = "Comprueba período abierto e ítems configurados para registrar atenciones."

    def handle(self, *args, **options):
        today = timezone.localdate()
        missing = AttentionType.objects.filter(is_active=True, deleted_at__isnull=True).filter(
            Q(activity_item__isnull=True) | Q(activity_item__is_active=False) | Q(activity_item__deleted_at__isnull=False))
        errors = []
        if not Period.objects.filter(start_date__lte=today, end_date__gte=today, status=Period.Status.OPEN, deleted_at__isnull=True).exists():
            errors.append(f"No hay período abierto para {today}.")
        if missing.exists():
            errors.append("Configurar ítems vigentes en: " + ", ".join(missing.values_list("name", flat=True)))
        if errors:
            raise CommandError("; ".join(errors))
        self.stdout.write(self.style.SUCCESS("Configuración lista para registrar atenciones."))
