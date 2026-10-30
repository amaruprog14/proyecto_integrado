from datetime import timedelta

from django.contrib.auth.models import Group, Permission, User
from django.core.management.base import BaseCommand, CommandError
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.utils import timezone

from accounts.models import Area, Delegation, Official, Position, Role, ServiceRecipient
from activities.models import Activity, SocialAttention
from configuration.models import Item, Period, ActivityType, ServiceType, AttentionType, SubattentionType

from common.demo_data import (
    DELEGATIONS, ROLES,
    DEMO_OFFICIAL_NAMES, DEMO_PASSWORD, AREA_NAMES, POSITION_NAMES,
    ITEM_NAMES, CATALOG_CHAINS, DEMO_GROUPS, demo_accounts, demo_rut,
    batch_letters,
)

def get_permissions(names):
    """Permisos a partir de "app_label.codename"; falla si alguno no existe."""
    query = Q()
    for name in names:
        app_label, codename = name.split(".")
        query |= Q(content_type__app_label=app_label, codename=codename)
    permissions = Permission.objects.filter(query).select_related("content_type")
    missing = set(names) - {f"{p.content_type.app_label}.{p.codename}" for p in permissions}
    if missing:
        raise CommandError(f"Permisos inexistentes: {', '.join(sorted(missing))}")
    return permissions


def get_administrator_permissions():
    """Ver, crear y modificar todo el dominio y las cuentas; la auditoría solo se consulta."""
    return (
        Permission.objects.filter(
            Q(content_type__app_label__in=["accounts", "activities", "configuration"])
            | Q(content_type__app_label="auth", content_type__model__in=["user", "group"])
        )
        .exclude(codename__startswith="delete_")
        .exclude(codename__in=["add_auditlog", "change_auditlog"])
    )


class Command(BaseCommand):
    help = "Completa los datos de demostración una vez y crea nuevos usuarios y funcionarios en cada ejecución."

    def batch_is_used(self, batch):
        accounts = demo_accounts(batch)
        checks = (
            (User, Q(username__in=[a["username"] for a in accounts]) | Q(email__in=[a["email"] for a in accounts])),
            (Official, Q(national_id__in=[a["national_id"] for a in accounts]) | Q(email__in=[a["email"] for a in accounts])),
        )
        return any(model.objects.filter(query).exists() for model, query in checks)

    @staticmethod
    def catalog_code(prefix, batch, index):
        return f"{prefix}-DEMO-{batch_letters(batch)}-{index + 1}"

    def handle(self, *args, **options):
        batch = 0
        # Si dos procesos eligen el mismo lote, la restricción única revierte todo
        # el intento perdedor y se busca otro lote; no quedan registros parciales.
        for attempt in range(5):
            while self.batch_is_used(batch):
                batch += 1
            try:
                with transaction.atomic():
                    self.create_batch(batch)
            except IntegrityError as error:
                duplicate = error.args and error.args[0] == 1062
                if not duplicate and "UNIQUE constraint failed" not in str(error):
                    raise
                batch += 1
                continue
            break
        else:
            raise CommandError("No se pudo reservar un lote libre. Vuelve a ejecutar seed_demo.")

        self.stdout.write(self.style.SUCCESS(
            f"Lote {batch_letters(batch)} creado: 7 usuarios y 7 funcionarios nuevos. "
            "Los demás datos de demostración se reutilizan y solo se completan si faltan."
        ))
        self.stdout.write(f"Contraseña inicial de las cuentas nuevas: {DEMO_PASSWORD}")
        for account in demo_accounts(batch):
            note = " (sin contexto: funcionario archivado)" if account["username"].startswith("funcionario5") else ""
            self.stdout.write(f"  {account['username']} | {account['email']} | {account['delegation']}{note}")

    def create_batch(self, batch):
        today = timezone.localdate()
        areas = {n: Area.objects.get_or_create(area_name=n)[0] for n in AREA_NAMES}
        positions = {n: Position.objects.get_or_create(
            position_name=n, defaults={"description": f"Funciones de {n.lower()} en la gestión municipal."}
        )[0] for n in POSITION_NAMES}
        delegations = {}
        for code, n, address, _, status in DELEGATIONS:
            delegation = Delegation.objects.filter(delegation_name=n).first()
            if delegation is None:
                available_code = self.available_code(Delegation, code)
                delegation = Delegation.objects.create(code=available_code, delegation_name=n,
                    address=address, commune="La Serena", status=status)
            delegations[n] = delegation
        roles = {}
        for role_name, (scope, description, permissions) in ROLES.items():
            role, created = Role.objects.get_or_create(role_name=role_name,
                defaults={"scope": scope, "description": description})
            if created:
                role.permissions.set(get_administrator_permissions() if permissions is None else get_permissions(permissions))
            roles[role_name] = role

        officials = []
        for i, account in enumerate(demo_accounts(batch)):
            first, _, last = account["full_name"].partition(" ")
            user = User.objects.create_user(
                username=account["username"], email=account["email"], password=DEMO_PASSWORD,
                first_name=first, last_name=last, is_staff=True, is_superuser=(i == 0),
            )
            area = areas[account["area"]]
            position = positions[account["position"]]
            delegation = delegations[account["delegation"]]
            official = Official.objects.create(
                full_name=account["full_name"], national_id=account["national_id"],
                email=account["email"], phone=account["phone"], area=area, position=position,
                delegation=delegation, user=None if i == 5 else user,
                deleted_at=timezone.now() if i == 5 else None,
            )
            official.roles.set([role for key, role in roles.items() if key in account["roles"]])
            official.authorized_delegations.set([
                delegation for key, delegation in delegations.items() if key in account.get("authorized", [])
            ])
            if 1 <= i <= 5:
                officials.append(official)
        for group_name in DEMO_GROUPS:
            Group.objects.get_or_create(name=group_name)
        items = []
        for i, n in enumerate(ITEM_NAMES):
            item = Item.objects.filter(item_name=n).first()
            if item is None:
                item = Item.objects.create(code=self.available_code(Item, self.catalog_code("ITM", 0, i)),
                    item_name=n, description=f"Registro municipal de {n.lower()}.")
            items.append(item)

        # Completar hasta cinco períodos; nunca agregar otros cinco por ejecución.
        end = today.replace(day=1) + timedelta(days=29)
        earliest = Period.objects.order_by("start_date").values_list("start_date", flat=True).first()
        if earliest is not None:
            end = min(end, earliest - timedelta(days=1))
        for i in range(max(0, 5 - Period.objects.count())):
            start = end - timedelta(days=29)
            Period.objects.create(start_date=start, end_date=end,
                                  status=Period.Status.OPEN if i == 0 else Period.Status.CLOSED)
            end = start - timedelta(days=1)

        activities = []
        base_accounts = demo_accounts()
        for i, official in enumerate(officials):
            for j in range(2):
                # Clave estable independiente del lote de usuarios actual.
                description = f"Actividad de prueba - {base_accounts[i+1]['full_name']} - {base_accounts[i+1]['area']}"
                activity = Activity.objects.filter(item=items[(i+j) % 5], action_description=description).order_by("pk").first()
                if activity is None:
                    activity = Activity.objects.create(official=official, item=items[(i+j) % 5],
                        date=today, record_type="Registro", action_description=description)
                if j == 0:
                    activities.append(activity)
        for i, (activity_name, service_name, attention_name, sub_name) in enumerate(CATALOG_CHAINS):
            activity_type, _ = ActivityType.objects.get_or_create(area=areas[AREA_NAMES[i]], name=activity_name)
            service, _ = ServiceType.objects.get_or_create(activity_type=activity_type, name=service_name)
            attention = AttentionType.objects.filter(service_type=service, name=attention_name).first()
            if attention is None:
                attention = AttentionType.objects.create(
                    code=self.available_code(AttentionType, self.catalog_code("TAT", 0, i)), service_type=service,
                    name=attention_name, description=f"Atención municipal de {attention_name.lower()}.")
            subattention = SubattentionType.objects.filter(attention_type=attention, name=sub_name).first()
            if subattention is None:
                subattention = SubattentionType.objects.create(
                    code=self.available_code(SubattentionType, self.catalog_code("SAT", 0, i)), attention_type=attention,
                    name=sub_name, description=f"Gestión municipal de {sub_name.lower()}.")
            recipient, _ = ServiceRecipient.objects.get_or_create(national_id=demo_rut(20000000+i),
                defaults={"full_name": f"Solicitante Demo {DEMO_OFFICIAL_NAMES[i]}"})
            token = f"seed-A-attention-{i+1}"
            # Compatibilidad con los tokens de la versión original.
            if SocialAttention.objects.filter(submission_token__in=[token, f"seed-demo-attention-{i+1}"]).exists():
                continue
            responsible = activities[i % 4].official
            if not SocialAttention.validate_attention_limit(recipient.pk):
                continue
            SocialAttention.objects.create(
                submission_token=token, recipient=recipient, attention_type=attention, subattention_type=subattention,
                delegation=responsible.delegation, responsible=responsible, date=today,
                activity=activities[i % 4], description=f"Solicitud de demostración de {attention_name.lower()}.")

    @staticmethod
    def available_code(model, base):
        code = base
        index = 0
        while model.objects.filter(code=code).exists():
            code = f"{base}-{batch_letters(index)}"
            index += 1
        return code
