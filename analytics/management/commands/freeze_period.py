"""Congela los resultados de un período que se cerró antes de existir el congelamiento."""
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from analytics.services import CalculadorDesempenoService
from configuration.models import Period
from configuration.period_services import lock_period_registry
from configuration.services import AuditoriaService


class Command(BaseCommand):
    help = ("Congela los indicadores de un período cerrado. Idempotente: si el período ya está congelado "
            "(frozen_at), no repite ni reemplaza el congelamiento. Excluye funcionarios archivados.")

    def add_arguments(self, parser):
        parser.add_argument("period_id", type=int, help="Identificador del período cerrado.")

    def handle(self, *args, period_id, **options):
        with transaction.atomic():
            lock_period_registry()
            period = Period.objects.select_for_update().filter(pk=period_id, deleted_at__isnull=True).first()
            if period is None:
                raise CommandError(f"No existe el período {period_id}.")
            if period.status != Period.Status.CLOSED:
                raise CommandError("El período está abierto: sus resultados se congelan al cerrarlo.")
            if period.frozen_at is not None:
                self.stdout.write(f"Período {period}: ya estaba congelado el {period.frozen_at:%d-%m-%Y %H:%M}; sin cambios.")
                return
            created = CalculadorDesempenoService.freeze_period(period)
            AuditoriaService.register_change(
                official=None, action="Congelamiento de indicadores", instance=period,
                new_value=f"{created} indicadores congelados del período {period}",
            )
        self.stdout.write(self.style.SUCCESS(f"Período {period}: {created} indicadores congelados."))
