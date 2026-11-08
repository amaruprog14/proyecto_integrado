from django.core.management.base import BaseCommand
from django.db import transaction

from accounts.evaluation_admin import USERNAME, provision_evaluation_admin
from configuration.models import PeriodMutex


class Command(BaseCommand):
    help = "Prepara solo el administrador de evaluación A; conserva el administrador global y los datos de negocio."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true", help="Valida la creación y revierte los cambios.")

    @transaction.atomic
    def handle(self, *args, **options):
        mutex, _ = PeriodMutex.objects.get_or_create(pk=1)
        PeriodMutex.objects.select_for_update().get(pk=mutex.pk)
        user, created, _ = provision_evaluation_admin()
        self.stdout.write(f"{USERNAME}: {'creada' if created else 'ya preparada'}; ámbito Las Compañías; sin staff ni superusuario.")
        self.stdout.write("Administrador global conservado. No se cargaron ni archivaron registros de negocio.")
        if options["dry_run"]:
            transaction.set_rollback(True)
            self.stdout.write("SIMULACIÓN: todos los cambios revertidos.")
