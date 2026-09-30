from datetime import timedelta

from django.contrib.auth.models import Group, User
from django.core.management.base import BaseCommand
from django.utils import timezone

from accounts.models import Area, Official, Position
from activities.models import Activity
from configuration.models import Item, Period


class Command(BaseCommand):
    help = "Carga 5 registros de prueba por modelo para probar Admin (versión sin area/user en Funcionario)."

    def handle(self, *args, **options):
        today = timezone.now().date()
        officials_group, _ = Group.objects.get_or_create(name="Funcionarios")

        # ---------- 5 Áreas (aún no conectadas a Official) ----------
        area_names = ["Área Norte", "Área Sur", "Área Centro", "Área Cordillera", "Área Costa"]
        areas = [Area.objects.get_or_create(area_name=n)[0] for n in area_names]

        # ---------- 5 Cargos ----------
        position_names = ["Analista", "Coordinador", "Administrativo", "Supervisor", "Encargado de Terreno"]
        positions = [Position.objects.get_or_create(position_name=n)[0] for n in position_names]

        # ---------- Superusuario técnico ----------
        if not User.objects.filter(username="admin_demo").exists():
            User.objects.create_superuser("admin_demo", "admin@demo.cl", "demo1234")

        # ---------- 5 Usuarios de Django (sin vincular a Official todavía) ----------
        for i in range(5):
            username = f"funcionario{i+1}"
            user, created = User.objects.get_or_create(username=username, defaults={"is_staff": True})
            if created:
                user.set_password("demo1234")
                user.save()
            user.groups.add(officials_group)

        # ---------- 5 Funcionarios (solo con cargo, como está tu modelo hoy) ----------
        officials = []
        for i in range(5):
            official, _ = Official.objects.get_or_create(
                national_id=f"{10000000 + i}-{i}",
                defaults=dict(
                    full_name=f"Funcionario Demo {i+1}",
                    email=f"funcionario{i+1}@demo.cl",
                    position=positions[i],
                ),
            )
            officials.append(official)

        # ---------- Evidencia de borrado lógico (deleted_at) ----------
        last_official = officials[4]
        if last_official.deleted_at is None:
            last_official.deleted_at = timezone.now()
            last_official.save(update_fields=["deleted_at", "updated_at"])

        # ---------- 5 Ítems ----------
        item_names = ["Atención ciudadana", "Terreno", "Reunión de coordinación",
                      "Levantamiento de datos", "Seguimiento de caso"]
        items = [Item.objects.get_or_create(item_name=n)[0] for n in item_names]

        # ---------- 5 Períodos ----------
        periods = []
        for i in range(5):
            start = today.replace(day=1) - timedelta(days=30 * i)
            end = start + timedelta(days=29)
            period, _ = Period.objects.get_or_create(
                start_date=start, end_date=end,
                defaults={"status": Period.Status.OPEN if i == 0 else Period.Status.CLOSED},
            )
            periods.append(period)

        # ---------- 5 Actividades ----------
        for i in range(5):
            Activity.objects.get_or_create(
                official=officials[i],
                item=items[i],
                date=today,
                record_type="Registro",
                defaults={"action_description": f"Actividad de prueba #{i+1} - {areas[i].area_name}"},
            )

        self.stdout.write(self.style.SUCCESS(
            "Seed cargado: 5 áreas, 5 cargos, 5 usuarios Django, 5 funcionarios, 5 ítems, 5 períodos, 5 actividades."
        ))