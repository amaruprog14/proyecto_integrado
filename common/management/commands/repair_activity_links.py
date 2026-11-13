"""Reparación explícita de vínculos históricos, antes o después de migrar."""
from django.core.management.base import BaseCommand
from django.db import connection, transaction
from django.db.migrations.executor import MigrationExecutor
from django.db.models import Count
from configuration.services import AuditoriaService


class Command(BaseCommand):
    help = "Duplica actividades compartidas para conservar cada atención con un vínculo único."

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true", help="Aplicar la reparación; sin esta opción solo informa.")

    def handle(self, *args, **options):
        with connection.cursor() as cursor:
            columns = {column.name for column in connection.introspection.get_table_description(cursor, "activities_activity")}
        if "registration_position_id" in columns:
            from activities.models import Activity, SocialAttention
        else:
            loader = MigrationExecutor(connection).loader
            if "code" in columns:
                targets = [max(key for key in loader.applied_migrations if key[0] == "activities")]
            else:
                targets = [
                    ("accounts", "0007_shorten_delegation_fields"),
                    ("configuration", "0003_attentiontype_code_attentiontype_description_and_more"),
                    ("activities", "0004_socialattention_submission_token"),
                ]
            state = loader.project_state(targets)
            Activity = state.apps.get_model("activities", "Activity")
            SocialAttention = state.apps.get_model("activities", "SocialAttention")
        with transaction.atomic():
            duplicates = list(SocialAttention.objects.exclude(activity_id=None).values("activity_id")
                .annotate(total=Count("pk")).filter(total__gt=1))
            repaired = 0
            for duplicate in duplicates:
                activity = Activity.objects.select_for_update().get(pk=duplicate["activity_id"])
                attentions = list(SocialAttention.objects.select_for_update().filter(activity_id=activity.pk).order_by("pk"))
                for attention in attentions[1:]:
                    self.stdout.write(f"Atención {attention.pk}: separar de actividad {activity.pk}.")
                    if not options["apply"]:
                        continue
                    values = {field.attname: getattr(activity, field.attname) for field in Activity._meta.concrete_fields
                        if not field.primary_key and field.name not in ("code", "created_at", "updated_at")}
                    clone = Activity.objects.create(**values)
                    Activity.objects.filter(pk=clone.pk).update(created_at=activity.created_at, updated_at=activity.updated_at)
                    SocialAttention.objects.filter(pk=attention.pk).update(activity_id=clone.pk)
                    AuditoriaService.register_event(official=None, action="Reparación de vínculo histórico",
                        entity="activities_socialattention", record_id=attention.pk,
                        previous_value=f"Actividad: {activity.pk}", new_value=f"Actividad: {clone.pk}; copia conservando datos de {activity.pk}")
                    repaired += 1
            self.stdout.write(f"Duplicados detectados: {len(duplicates)}. Vínculos reparados: {repaired}.")
