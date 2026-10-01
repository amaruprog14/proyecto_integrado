from datetime import timedelta

from django.contrib.auth.models import Group, Permission, User
from django.core.management.base import BaseCommand
from django.utils import timezone

from accounts.models import Area, Official, Position
from activities.models import Activity
from configuration.models import Item, Period


class Command(BaseCommand):
    help = "Carga datos de prueba: 5 registros por modelo, con funcionarios repartidos en áreas para demostrar el scoping."

    def handle(self, *args, **options):
        today = timezone.now().date()
        officials_group, _ = Group.objects.get_or_create(name="Funcionarios")
        # Permisos del usuario limitado: sin eliminar. El scoping (área) se aplica en el Admin.
        officials_group.permissions.set(Permission.objects.filter(codename__in=[
            "view_activity", "add_activity", "change_activity", "view_official", "view_item",
        ]))

        # Grupo de solo lectura (usuario de consulta): ve su ámbito pero no modifica
        consulta_group, _ = Group.objects.get_or_create(name="Consulta")
        consulta_group.permissions.set(Permission.objects.filter(codename__in=[
            "view_activity", "view_official", "view_item",
        ]))

        # ---------- 5 Áreas ----------
        area_names = ["Área Norte", "Área Sur", "Área Centro", "Área Cordillera", "Área Costa"]
        areas = [Area.objects.get_or_create(area_name=n)[0] for n in area_names]

        # ---------- 5 Cargos ----------
        position_names = ["Analista", "Coordinador", "Administrativo", "Supervisor", "Encargado de Terreno"]
        positions = [Position.objects.get_or_create(position_name=n)[0] for n in position_names]

        # ---------- Superusuario técnico ----------
        if not User.objects.filter(username="admin_demo").exists():
            User.objects.create_superuser("admin_demo", "admin@demo.cl", "demo1234")

        # ---------- 5 Usuarios de Django (funcionario1-4 se vinculan a un Official; funcionario5 queda SIN contexto) ----------
        users = []
        for i in range(5):
            username = f"funcionario{i+1}"
            user, created = User.objects.get_or_create(username=username, defaults={"is_staff": True})
            if created:
                user.set_password("demo1234")
                user.save()
            user.groups.add(officials_group)
            users.append(user)

        # ---------- 5 Funcionarios: 1-2 en Norte, 3-4 en Sur, 5 en Centro (archivado) ----------
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
            # Vincular área y usuario (solo guarda si cambió, para no alterar updated_at en cada seed)
            wanted_area = areas[[0, 0, 1, 1, 2][i]]
            wanted_user = users[i] if i < 4 else None
            if official.area_id != wanted_area.id or official.user_id != (wanted_user.id if wanted_user else None):
                official.area = wanted_area
                official.user = wanted_user
                official.save(update_fields=["area", "user", "updated_at"])
            officials.append(official)

        # ---------- Usuario de consulta (solo lectura) en Área Norte ----------
        consulta_user, created = User.objects.get_or_create(username="consulta_norte", defaults={"is_staff": True})
        if created:
            consulta_user.set_password("demo1234")
            consulta_user.save()
        consulta_user.groups.add(consulta_group)
        consulta_official, _ = Official.objects.get_or_create(
            national_id="10000099-9",
            defaults=dict(full_name="Consulta Demo Norte", email="consulta_norte@demo.cl",
                          position=positions[0], area=areas[0], user=consulta_user),
        )

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

        # ---------- 10 Actividades (2 por funcionario, para ver datos en ambas áreas) ----------
        for i, official in enumerate(officials):
            for j in range(2):
                Activity.objects.get_or_create(
                    official=official,
                    item=items[(i + j) % 5],
                    date=today,
                    record_type="Registro",
                    defaults={"action_description": f"Actividad de prueba - {official.full_name} - {official.area.area_name}"},
                )

        self.stdout.write(self.style.SUCCESS(
            "Seed cargado: 5 áreas, 5 cargos, 7 usuarios Django, 6 funcionarios (Norte, Sur y Centro), 5 ítems, 5 períodos y 10 actividades."
        ))