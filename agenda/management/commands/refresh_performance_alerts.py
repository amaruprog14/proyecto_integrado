from django.core.management.base import BaseCommand

from agenda.alerts import refresh_commitment_alerts, refresh_performance_alerts


class Command(BaseCommand):
    help = "Actualiza las alertas de desempeño y vencimiento de compromisos."

    def handle(self, *args, **options):
        created, resolved = refresh_performance_alerts()
        self.stdout.write(f"Alertas creadas: {created}. Alertas resueltas: {resolved}.")
        refresh_commitment_alerts()
        self.stdout.write("Alertas de compromisos actualizadas.")
