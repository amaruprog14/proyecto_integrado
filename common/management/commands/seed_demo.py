# common/management/commands/seed_demo.py
from django.contrib.auth.models import User, Group
from django.core.management.base import BaseCommand
from django.utils import timezone
from datetime import timedelta

from accounts.models import Area, Cargo, Funcionario
from configuration.models import Item, Periodo
from activities.models import Actividad


class Command(BaseCommand):
    help = "Carga 5 registros de prueba por modelo para probar Admin (versión sin area/user en Funcionario)."

    def handle(self, *args, **options):
        hoy = timezone.now().date()
        grupo_funcionarios, _ = Group.objects.get_or_create(name="Funcionarios")

        # ---------- 5 Áreas (aún no conectadas a Funcionario) ----------
        nombres_areas = ["Área Norte", "Área Sur", "Área Centro", "Área Cordillera", "Área Costa"]
        areas = [Area.objects.get_or_create(nombre_area=n)[0] for n in nombres_areas]

        # ---------- 5 Cargos ----------
        nombres_cargos = ["Analista", "Coordinador", "Administrativo", "Supervisor", "Encargado de Terreno"]
        cargos = [Cargo.objects.get_or_create(nombre_cargo=n)[0] for n in nombres_cargos]

        # ---------- Superusuario técnico ----------
        if not User.objects.filter(username="admin_demo").exists():
            User.objects.create_superuser("admin_demo", "admin@demo.cl", "demo1234")

        # ---------- 5 Usuarios de Django (sin vincular a Funcionario todavía) ----------
        for i in range(5):
            username = f"funcionario{i+1}"
            user, created = User.objects.get_or_create(username=username, defaults={"is_staff": True})
            if created:
                user.set_password("demo1234")
                user.save()
            user.groups.add(grupo_funcionarios)

        # ---------- 5 Funcionarios (solo con cargo, como está tu modelo hoy) ----------
        funcionarios = []
        for i in range(5):
            func, _ = Funcionario.objects.get_or_create(
                rut_identificador=f"{10000000 + i}-{i}",
                defaults=dict(
                    nombre_completo=f"Funcionario Demo {i+1}",
                    email=f"funcionario{i+1}@demo.cl",
                    cargo=cargos[i],
                ),
            )
            funcionarios.append(func)

        # ---------- 5 Ítems ----------
        nombres_items = ["Atención ciudadana", "Terreno", "Reunión de coordinación",
                          "Levantamiento de datos", "Seguimiento de caso"]
        items = [Item.objects.get_or_create(nombre_item=n)[0] for n in nombres_items]

        # ---------- 5 Períodos ----------
        periodos = []
        for i in range(5):
            inicio = hoy.replace(day=1) - timedelta(days=30 * i)
            termino = inicio + timedelta(days=29)
            periodo, _ = Periodo.objects.get_or_create(
                fecha_inicio=inicio, fecha_termino=termino,
                defaults={"estado": Periodo.Estado.ABIERTO if i == 0 else Periodo.Estado.CERRADO},
            )
            periodos.append(periodo)

        # ---------- 5 Actividades ----------
        for i in range(5):
            Actividad.objects.get_or_create(
                funcionario=funcionarios[i],
                item=items[i],
                fecha=hoy,
                tipo_registro="Registro",
                defaults={"descripcion_accion": f"Actividad de prueba #{i+1} - {areas[i].nombre_area}"},
            )

        self.stdout.write(self.style.SUCCESS(
            "Seed cargado: 5 áreas, 5 cargos, 5 usuarios Django, 5 funcionarios, 5 ítems, 5 períodos, 5 actividades."
        ))