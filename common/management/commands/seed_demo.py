"""Semilla idempotente del caso SGR, con personas y operaciones ficticias."""
from collections import Counter
from datetime import date, timedelta
from decimal import Decimal
from uuid import NAMESPACE_URL, uuid5

from django.contrib.auth.models import Group, Permission, User
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.db import IntegrityError, transaction
from django.db.models import Q

from accounts.models import (
    Area, Delegation, Function, GroupProfile, Official, Position, Role,
    ServiceRecipient, Territory,
)
from activities.models import Activity, AttentionCase, ClientRequest, ClientRequestEvent, SocialAttention
from analytics.measurement import ADD_PLAN, CHANGE_PLAN, PUBLISH_PLAN, VIEW_PLAN, create_revision, publish_version
from analytics.models import MeasurementAdjustment, MeasurementItem, MeasurementPlan
from configuration.models import AttentionType, Item, Period, PeriodMutex, SubattentionType
from configuration.services import AuditoriaService
from common.demo_data import CONSULTA_PERMISSIONS, OPERATOR_PERMISSIONS, demo_rut, require_seed_password
from common.sgr_seed_data import (
    ATTENTION_CATALOG, GEOGRAPHY, POSITIONS, POSITION_ITEMS, fictional_name,
)

MARKER = "[SGR seed v1]"
CONSULTATION_GROUP = "Consulta SGR"
MEASUREMENT_PLAN_PERMISSIONS = (VIEW_PLAN, ADD_PLAN, CHANGE_PLAN, PUBLISH_PLAN)
DEMO_PERIODS = ((date(2026, 7, 1), date(2026, 9, 30)), (date(2026, 10, 1), date(2026, 12, 31)))
DEMO_REVISION_DATE = date(2026, 10, 15)
DEMO_ADJUSTED_OFFICIAL_INDEX = 8


def get_permissions(names):
    query = Q(pk__in=[])
    for name in names:
        app_label, codename = name.split(".")
        query |= Q(content_type__app_label=app_label, codename=codename)
    permissions = Permission.objects.filter(query).select_related("content_type")
    missing = set(names) - {f"{p.content_type.app_label}.{p.codename}" for p in permissions}
    if missing:
        raise CommandError(f"Permisos inexistentes: {', '.join(sorted(missing))}. Ejecuta migrate antes de la semilla.")
    return permissions


def get_administrator_permissions():
    return Permission.objects.filter(
        Q(content_type__app_label__in=["accounts", "activities", "configuration"])
        | Q(content_type__app_label="auth", content_type__model__in=["user", "group"])
        | Q(pk__in=get_permissions(MEASUREMENT_PLAN_PERMISSIONS))
    ).exclude(codename__startswith="delete_").exclude(
        codename__in=["add_auditlog", "change_auditlog"]
    )


class Command(BaseCommand):
    help = "Carga ≥2.000 registros de negocio ficticios del caso SGR sin duplicar ni reemplazar datos existentes."

    def add_arguments(self, parser):
        parser.add_argument("--no-input", action="store_true", help="Compatibilidad con automatización; no solicita datos interactivos.")
        parser.add_argument("--dry-run", action="store_true", help="Valida y muestra conteos; revierte toda la carga.")

    def handle(self, *args, **options):
        password = require_seed_password()
        self.created = Counter()
        self.used = {}
        self.new_objects = set()
        try:
            with transaction.atomic():
                # Serializa ejecuciones de la semilla y no cambia períodos previamente creados.
                mutex, _ = PeriodMutex.objects.get_or_create(pk=1)
                PeriodMutex.objects.select_for_update().get(pk=mutex.pk)
                self.load(password)
                self.report(options["dry_run"])
                if options["dry_run"]:
                    transaction.set_rollback(True)
        except (ValidationError, IntegrityError) as error:
            raise CommandError(f"Carga revertida por datos incompatibles: {error}") from error

    def ensure(self, model, defaults=None, **lookup):
        obj = model.objects.filter(**lookup).first()
        if obj is None:
            obj = model(**lookup, **(defaults or {}))
            obj.full_clean()
            obj.save()
            self.created[model.__name__] += 1
            self.new_objects.add((model, obj.pk))
        elif getattr(obj, "deleted_at", None) or getattr(obj, "is_active", True) is False:
            raise CommandError(f"{model.__name__} {obj.pk} está archivado o desactivado. No se reactiva automáticamente.")
        self.used.setdefault(model, set()).add(obj.pk)
        return obj

    def user(self, username, password):
        email = f"{username.lower()}@sgr.example.invalid"
        user = User.objects.filter(username=username).first()
        if user:
            allowed_groups = {self.consultation_group.pk} if username in ("readerA", "readerB") else set()
            if (user.email != email or user.is_superuser or user.is_staff or not user.is_active
                    or set(user.groups.values_list("pk", flat=True)) - allowed_groups
                    or user.user_permissions.exists()):
                raise CommandError(f"La cuenta {username} ya existe con otra configuración. No se modifica ni se reutiliza sin revisión.")
            if not user.check_password(password):
                user.set_password(password)
                user.save(update_fields=["password"])
                self.created["PasswordsReset"] += 1
        else:
            if User.objects.filter(email=email).exists():
                raise CommandError(f"Correo de demostración ocupado para {username}.")
            user = User(username=username, email=email, first_name=username)
            user.set_password(password)
            user.full_clean()
            user.save()
            self.created["User"] += 1
        return user

    def role(self, name, scope, permissions):
        expected = set(permissions.values_list("pk", flat=True))
        role = self.ensure(Role, role_name=name, defaults={"scope": scope, "description": f"{MARKER} Perfil de acceso del caso SGR."})
        if role.scope != scope:
            raise CommandError(f"El rol {name} tiene un alcance distinto. No se alteran sus permisos.")
        if (Role, role.pk) in self.new_objects:
            role.permissions.set(expected)
        elif set(role.permissions.values_list("pk", flat=True)) != expected:
            upgrade_permissions = set(get_permissions([
                "accounts.archive_official", "activities.archive_activity",
                *MEASUREMENT_PLAN_PERMISSIONS,
            ]).values_list("pk", flat=True))
            current = set(role.permissions.values_list("pk", flat=True))
            if (name == "Administrador" and scope == Role.Scope.ALL
                    and current < expected and expected - current <= upgrade_permissions):
                role.permissions.add(*(expected - current))
            else:
                raise CommandError(f"El rol {name} tiene permisos distintos. Revisa su configuración antes de cargar.")
        return role

    @staticmethod
    def complete_seed_user_name(profile):
        user = profile.user
        # Solo reemplaza los valores originales de la semilla antigua. Los
        # nombres editados desde el perfil o el mantenedor se conservan.
        if user and user.first_name == user.username and not user.last_name:
            first_name, separator, last_name = profile.full_name.strip().partition(" ")
            if separator and last_name:
                user.first_name, user.last_name = first_name, last_name
                user.save(update_fields=["first_name", "last_name"])

    def publish_demo_version(self, version):
        publish_version(version)
        AuditoriaService.register_change(
            official=None, action="Publicación de plan de medición", instance=version,
            new_value=f"{MARKER} {version.plan.position} · Versión {version.number} · Vigente desde {version.effective_from:%d-%m-%Y}",
        )
        self.created["PublishedMeasurementVersion"] += 1

    def load_measurement_plans(self, period, positions, functions, items, demo_official):
        configured_positions = set(period.measurement_plans.values_list("position_id", flat=True))
        for name, position in positions.items():
            if position.pk in configured_positions:
                self.created["PreservedMeasurementPlan"] += 1
                continue

            plan = MeasurementPlan.objects.create(period=period, position=position)
            version = plan.versions.create(number=1, effective_from=period.start_date)
            item_names = POSITION_ITEMS[name]
            basis_points, remainder = divmod(10000, len(item_names))
            lines = {}
            for index, item_name in enumerate(item_names):
                percentage = item_name == "Soluciones de ingresos al tubo"
                weight = Decimal(basis_points + (1 if index < remainder else 0)) / 100
                lines[item_name] = MeasurementItem.objects.create(
                    version=version, function=functions[name], item=items[item_name],
                    goal_type=MeasurementItem.GoalType.PERCENTAGE if percentage else MeasurementItem.GoalType.QUANTITY,
                    goal=80 if percentage else 12,
                    weight=weight,
                )

            if name == "Gestor social" and demo_official.position_id == position.pk:
                attention = lines["Atención social a usuario presencial"]
                visit = lines["Visita terreno"]
                MeasurementAdjustment.objects.create(
                    line=attention, official=demo_official, goal=24, weight=attention.weight + 5,
                )
                MeasurementAdjustment.objects.create(
                    line=visit, official=demo_official, weight=visit.weight - 5,
                )

            self.publish_demo_version(version)
            if name == "Gestor social" and period.start_date == DEMO_PERIODS[1][0]:
                revision = create_revision(plan, DEMO_REVISION_DATE)
                revision.items.filter(item=items["Visita terreno"]).update(goal=18)
                self.publish_demo_version(revision)
            self.created["MeasurementPlan"] += 1

    def load(self, password):
        delegations, territories = [], []
        for name, names in GEOGRAPHY.items():
            delegation = self.ensure(Delegation, delegation_name=name, defaults={
                "address": "Dirección ficticia de demostración", "commune": "La Serena",
            })
            if delegation.status != Delegation.Status.ACTIVE:
                raise CommandError(f"La delegación {name} no está activa.")
            delegations.append(delegation)
            for territory_name in names:
                territories.append(self.ensure(Territory, delegation=delegation,
                    name_key=territory_name.casefold(), defaults={"territory_name": territory_name,
                    "description": f"{MARKER} Catálogo territorial del Excel, sin datos personales."}))

        positions, areas, functions = {}, {}, {}
        for name, (area_name, description) in POSITIONS.items():
            positions[name] = self.ensure(Position, position_name=name, defaults={"description": description})
            areas[name] = self.ensure(Area, area_name=area_name)
            functions[name] = self.ensure(Function, function_name=f"Funciones de {name.lower()}", defaults={"description": description})
            # No sobrescribir asociaciones de una función existente.
            if (Function, functions[name].pk) in self.new_objects:
                functions[name].positions.add(positions[name])
            elif not functions[name].positions.filter(pk=positions[name].pk).exists():
                raise CommandError(f"La función de {name} está vinculada a otro cargo.")
        items = {}
        for names in POSITION_ITEMS.values():
            for name in names:
                items[name] = self.ensure(Item, item_name=name, defaults={"description": f"{MARKER} Indicador de la matriz trimestral SGR."})

        roles = {
            "adminA": self.role("Administrador", "ALL", get_administrator_permissions()),
            "editorA": self.role("Funcionario", "DELEGATION", get_permissions(OPERATOR_PERMISSIONS + ["accounts.add_official", "accounts.change_official"])),
            "readerA": self.role("Usuario consulta", "DELEGATION", get_permissions(CONSULTA_PERMISSIONS)),
        }
        self.role("Coordinador del sistema", "ALL", get_permissions(CONSULTA_PERMISSIONS + ["accounts.view_delegation", "configuration.view_period"]))
        self.role("Delegado", "DELEGATION", get_permissions(CONSULTA_PERMISSIONS + ["accounts.view_delegation", "configuration.view_period"]))
        self.role("Verificador", "DELEGATION", get_permissions(CONSULTA_PERMISSIONS + ["activities.view_evidence", "activities.view_evidencevalidation", "activities.add_evidencevalidation", "activities.change_evidencevalidation"]))
        # Grupo funcional pequeño: replica la lectura que ya otorga el rol de consulta.
        # El alcance sigue siendo la delegación principal de cada miembro.
        group = self.ensure(Group, name=CONSULTATION_GROUP)
        expected_group_permissions = set(get_permissions(CONSULTA_PERMISSIONS).values_list("pk", flat=True))
        if (Group, group.pk) in self.new_objects:
            group.permissions.set(expected_group_permissions)
        elif set(group.permissions.values_list("pk", flat=True)) != expected_group_permissions:
            raise CommandError("El grupo Consulta SGR tiene otros permisos. No se modifica.")
        profile = self.ensure(GroupProfile, group=group, defaults={
            "description": f"{MARKER} Lectores de gestión de su propia delegación.",
            "scope": Role.Scope.DELEGATION,
        })
        if profile.scope != Role.Scope.DELEGATION:
            raise CommandError("El grupo Consulta SGR tiene otro alcance. No se modifica.")
        self.consultation_group = group
        users = {name: self.user(name, password) for name in ("adminA", "editorA", "readerA", "readerB", "clientA", "clientB")}
        # Seis cuentas originales y una adicional de evaluación en el funcionario 006.
        officials = []
        account_indices = {0: "adminA", 2: "editorA", 4: "readerA", 1: "readerB"}
        position_names = list(POSITIONS)
        for i in range(100):
            position_name = position_names[i % len(position_names)]
            username = account_indices.get(i)
            user = users.get(username)
            official = self.ensure(Official, national_id=demo_rut(70000000 + i), defaults={
                "full_name": fictional_name(i), "email": f"official{i:03d}@sgr.example.invalid",
                "area": areas[position_name], "position": positions[position_name],
                "delegation": delegations[i % 2], "user": user,
            })
            if i == 6:
                from accounts.evaluation_admin import USERNAME, provision_evaluation_admin
                previous_user = User.objects.filter(username=USERNAME).first()
                reset = previous_user is not None and not previous_user.check_password(password)
                _, user_created, role_created = provision_evaluation_admin(reset_password=True)
                self.created["User"] += int(user_created)
                self.created["Role"] += int(role_created)
                self.created["PasswordsReset"] += int(reset)
                officials.append(official)
                continue
            if official.user_id != (user.pk if user else None) or official.email != f"official{i:03d}@sgr.example.invalid" or official.delegation_id != delegations[i % 2].pk or not official.is_enabled:
                raise CommandError(f"Colisión o cambio de contexto del funcionario simulado {i}; no se reemplaza.")
            role = roles.get(username, roles["readerA"] if username == "readerB" else roles["editorA"])
            if (Official, official.pk) in self.new_objects:
                official.roles.add(role)
            elif set(official.roles.values_list("pk", flat=True)) != {role.pk} or official.authorized_delegations.exists():
                raise CommandError(f"El funcionario simulado {i} tiene roles o delegaciones adicionales. Revisión necesaria.")
            self.complete_seed_user_name(official)
            officials.append(official)

        for username in ("readerA", "readerB"):
            group.user_set.add(users[username])

        for start, end in DEMO_PERIODS:
            period = self.ensure(Period, start_date=start, end_date=end)
            if period.status != Period.Status.OPEN:
                raise CommandError("Un período de la semilla está cerrado. No se insertan registros en él.")
            self.load_measurement_plans(period, positions, functions, items, officials[DEMO_ADJUSTED_OFFICIAL_INDEX])
        pairs = []
        for name, subnames in ATTENTION_CATALOG.items():
            attention = self.ensure(AttentionType, name=name, service_type=None, defaults={
                "description": f"{MARKER} LISTA del Excel.", "activity_item": items["Atención social a usuario presencial"],
            })
            if attention.activity_item_id != items["Atención social a usuario presencial"].pk:
                raise CommandError(f"El tipo {name} tiene otro ítem automático. No se cambia.")
            for subname in subnames:
                pairs.append((attention, self.ensure(SubattentionType, attention_type=attention, name=subname,
                    defaults={"description": f"{MARKER} LISTA del Excel."})))
        recipients = []
        for i in range(300):
            user = users["clientA"] if i == 0 else users["clientB"] if i == 4 else None
            recipient = self.ensure(ServiceRecipient, national_id=demo_rut(71000000 + i), defaults={
                "full_name": fictional_name(100+i), "email": f"recipient{i:03d}@sgr.example.invalid",
                "territory": territories[i % 8], "address": f"Calle ficticia de demostración {i+1}", "user": user,
            })
            if recipient.user_id != (user.pk if user else None) or recipient.territory_id != territories[i % 8].pk or not recipient.is_enabled or recipient.email != f"recipient{i:03d}@sgr.example.invalid":
                raise CommandError(f"Colisión o cambio de contexto de la persona simulada {i}; no se reemplaza.")
            self.complete_seed_user_name(recipient)
            recipients.append(recipient)
        for i in range(1200):
            is_attention = i >= 900
            recipient_index = i - 900
            official = officials[i % 100]
            # Territorios 0–3 pertenecen a Compañías, 4–7 a Antena.
            if is_attention:
                recipient = recipients[recipient_index]
                delegation_index = recipient_index % 8 // 4
                social_officials = [person for person in officials if person.position.position_name == "Gestor social"
                                    and person.delegation_id == delegations[delegation_index].pk and not person.user_id]
                official = social_officials[(recipient_index // 8) % len(social_officials)]
                item = items["Atención social a usuario presencial"]
            else:
                position_items = POSITION_ITEMS[official.position.position_name]
                item = items[position_items[(i // 100) % len(position_items)]]
            activity_date = date(2026, 7, 1) + timedelta(days=(i * 7) % 123)
            record_type = Activity.RecordType.ATTENTION if is_attention else Activity.RecordType.FIELD if i % 3 == 0 else Activity.RecordType.MONTHLY
            activity = self.ensure(Activity, code=f"SGR26-ACT-{i+1:04d}", defaults={
                "official": official, "item": item, "date": activity_date, "record_type": record_type,
                "action_description": f"{MARKER} Caso ficticio {i+1}: {item.item_name.lower()} en {official.delegation.delegation_name}. Jornada {1 + i // 123}.",
            })
            if activity.official_id != official.pk or activity.item_id != item.pk or activity.record_type != record_type:
                raise CommandError(f"El código {activity.code} tiene otro contexto. No se reemplaza la actividad existente.")
            if is_attention:
                attention, subattention = pairs[recipient_index % len(pairs)]
                token = f"sgr26-att-{recipient_index+1:04d}"
                existing = SocialAttention.objects.filter(submission_token=token).first()
                if existing:
                    case = existing.case
                else:
                    case = AttentionCase.objects.create(recipient=recipient, delegation=official.delegation,
                        responsible=official, subject=attention.name[:100])
                entry = self.ensure(SocialAttention, submission_token=token, defaults={
                    "case": case, "activity": activity, "recipient": recipient, "attention_type": attention,
                    "subattention_type": subattention, "delegation": official.delegation,
                    "responsible": official, "date": activity.date, "description": activity.action_description,
                    "result": "Gestión de demostración realizada.",
                })
                if entry.activity_id != activity.pk or entry.recipient_id != recipient.pk:
                    raise CommandError(f"Token de atención ocupado: {token}.")
        for i in range(100):
            recipient = recipients[0 if i % 2 == 0 else 4]
            attention, subattention = pairs[i % len(pairs)]
            status = ClientRequest.Status.values[i % 3]
            request = self.ensure(ClientRequest, submission_token=uuid5(NAMESPACE_URL, f"sgr-seed-v1/request/{i}"), defaults={
                "recipient": recipient, "territory": recipient.territory, "address_snapshot": recipient.address,
                "delegation": recipient.delegation, "attention_type": attention, "subattention_type": subattention,
                "subject": f"Solicitud ficticia {i+1}: {subattention.name}",
                "description": f"{MARKER} Solicitud de demostración para {subattention.name.lower()}.",
                "status": status, "response": "Gestión simulada atendida por la delegación." if status == ClientRequest.Status.RESOLVED else "",
            })
            if request.recipient_id != recipient.pk or request.delegation_id != recipient.delegation_id:
                raise CommandError("Token de solicitud ocupado o contexto cambiado.")
            # Se crea el historial completo únicamente al crear una solicitud, nunca al repetir.
            if not request.events.exists():
                for step in ClientRequest.Status.values[:ClientRequest.Status.values.index(request.status)+1]:
                    self.ensure(ClientRequestEvent, request=request, status=step, defaults={"response": request.response if step == ClientRequest.Status.RESOLVED else ""})

    def report(self, dry_run):
        business = (Official, Activity, ServiceRecipient, SocialAttention, ClientRequest)
        total = sum(len(self.used.get(model, ())) for model in business)
        if total != 2000:
            raise CommandError(f"Conteo de negocio inesperado: {total}; se revierte la carga.")
        self.stdout.write("SIMULACIÓN: carga revertida." if dry_run else self.style.SUCCESS("Semilla SGR completada; datos existentes conservados."))
        for model, ids in self.used.items():
            self.stdout.write(f"{model.__name__}: {len(ids)} de semilla; {self.created[model.__name__]} nuevos; {model.objects.count()} totales en BD")
        self.stdout.write(f"Negocio: {total} (sin auth, catálogos, historial ni sesiones). Usuarios nuevos: {self.created['User']}.")
        self.stdout.write(
            f"Planes de medición nuevos: {self.created['MeasurementPlan']}. "
            f"Versiones publicadas: {self.created['PublishedMeasurementVersion']}. "
            f"Planes existentes conservados: {self.created['PreservedMeasurementPlan']}."
        )
        self.stdout.write(f"Contraseñas de cuentas de semilla restablecidas: {self.created['PasswordsReset']}.")
        self.stdout.write("Cuentas: adminEvalA, editorA, readerA, readerB, clientA, clientB; adicional global: adminA.")
