import logging
import math
import time

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import SetPasswordForm
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import ValidationError
from django.core.mail import send_mail
from django.db import transaction
from django.db.models import Q
from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect
from django.urls import reverse_lazy
from django.utils.decorators import method_decorator
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.cache import never_cache
from django.views.generic import (
    CreateView,
    DetailView,
    FormView,
    ListView,
    TemplateView,
    UpdateView,
    View,
)

from common.access import (
    ProtectedViewMixin,
    ScopedObjectMixin,
    get_scoped_object_or_404,
    register_denied_access,
)
from common.exports import xlsx_response
from common.modal_forms import ModalFormOnlyMixin
from common.pagination import ClampedPaginationMixin  # noqa: F401 (también se importaba desde aquí)
from common.text import describe_changes, format_snapshot
from configuration.services import AuditoriaService

from .backends import SGRAuthBackend, find_user_by_email
from .delegation_context import (
    ACTIVE_DELEGATION_SESSION_KEY,
    authorized_active_delegations,
    get_active_delegation,
)
from .forms import (
    DelegationForm,
    OfficialForm,
    OwnOfficialProfileForm,
    OfficialUserForm,
    RecoveryCodeForm,
    RecoveryRequestForm,
)
from .models import Delegation, Official, PasswordResetCode, Role
from .role_forms import (
    active_officials,
    last_global_administrator,
    sole_global_administrator_message,
    sole_global_administrator_role,
)

logger = logging.getLogger(__name__)

RECOVERY_SESSION_KEY = 'password_recovery'
CODE_SENT_MESSAGE = 'Si el correo corresponde a una cuenta activa, te enviamos un código de verificación.'
INVALID_CODE_MESSAGE = 'El código es incorrecto o ya no es válido.'
EXPIRED_CODE_MESSAGE = 'El código venció. Solicita un nuevo código.'
BLOCKED_CODE_MESSAGE = 'Superaste el máximo de intentos. Solicita un nuevo código.'
RESEND_ERROR_MESSAGES = {
    'resend_too_soon': 'Debes esperar antes de solicitar un nuevo código.',
    'resend_limit': 'Alcanzaste el máximo de reenvíos. Podrás pedir otro código cuando venza el actual.',
}
# Columnas visibles del listado de funcionarios; la exportación usa las mismas.
OFFICIAL_COLUMNS = ['Nombre completo', 'RUT o RUN chileno', 'Correo', 'Área', 'Cargo', 'Estado']


class MaintainerListView(ProtectedViewMixin, TemplateView):
    template_name = ''


class ActiveDelegationSelectView(ProtectedViewMixin, View):
    permission_required = ()
    http_method_names = ["post"]

    def post(self, request):
        selected_id = request.POST.get("delegation_id", "")
        delegation = None
        if selected_id.isdecimal():
            delegation = authorized_active_delegations(request.user).filter(
                pk=int(selected_id)
            ).first()
        return_to = request.POST.get("next")
        if not url_has_allowed_host_and_scheme(
            return_to, allowed_hosts={request.get_host()}, require_https=request.is_secure()
        ):
            return_to = reverse_lazy("home")
        if delegation is None:
            messages.error(request, "No tienes autorización para seleccionar esa delegación.")
            return redirect(return_to)
        request.session[ACTIVE_DELEGATION_SESSION_KEY] = delegation.pk
        messages.success(
            request,
            f"Delegación activa: {delegation.code} · {delegation.delegation_name}.",
        )
        return redirect(return_to)


# --- Recuperación de contraseña (SCRUM-31) ---
#
# El estado del flujo vive en la sesión y nunca guarda el código en claro. Si el correo no
# corresponde a una cuenta activa no se emite código, pero se simulan vigencia, intentos y
# reenvíos para que las respuestas no revelen si la cuenta existe.

def mask_email(email):
    name, _, domain = email.partition('@')
    return f'{name[:1]}***@{domain}'


def send_recovery_code(email, code):
    minutes = int(PasswordResetCode.ttl().total_seconds() // 60)
    try:
        send_mail(
            'Código de recuperación de contraseña · SGR',
            f'Tu código de verificación es {code}.\n\n'
            f'Vence en {minutes} minutos y solo puede usarse una vez. '
            'Si no solicitaste recuperar tu contraseña, ignora este mensaje.',
            None,
            [email],
        )
    except Exception:
        # La respuesta al usuario no cambia: informar el fallo revelaría que la cuenta existe.
        logger.exception('No se pudo enviar el código de recuperación de contraseña.')


def new_recovery_state(email, record):
    return {
        'code_id': record.pk if record else None,
        'email': email,
        'sent_at': record.last_sent_at.timestamp() if record else time.time(),
        'attempts': 0,
        'resends': 0,
        'verified': False,
    }


class RecoveryFlowMixin:
    def get_state(self):
        return self.request.session.get(RECOVERY_SESSION_KEY)

    def save_state(self, state):
        self.request.session[RECOVERY_SESSION_KEY] = state

    def clear_state(self):
        self.request.session.pop(RECOVERY_SESSION_KEY, None)

    @staticmethod
    def get_record(state):
        if not state or state.get('code_id') is None:
            return None
        return PasswordResetCode.objects.select_related('user').filter(pk=state['code_id']).first()

    @staticmethod
    def is_expired(state, record):
        if record is not None:
            return record.is_expired
        return time.time() >= state['sent_at'] + PasswordResetCode.ttl().total_seconds()

    @staticmethod
    def resend_wait_remaining(state):
        remaining = state['sent_at'] + PasswordResetCode.resend_wait().total_seconds() - time.time()
        return max(0, math.ceil(remaining))


@method_decorator(never_cache, name='dispatch')
class RecoveryRequestView(RecoveryFlowMixin, FormView):
    template_name = 'accounts/recovery_request.html'
    form_class = RecoveryRequestForm
    success_url = reverse_lazy('recovery_code')

    def form_valid(self, form):
        email = form.cleaned_data['email']
        record = None
        user = find_user_by_email(email)
        if user is not None and SGRAuthBackend().user_can_authenticate(user):
            try:
                record, code = PasswordResetCode.issue(user)
            except ValidationError:
                # Espera mínima o máximo de reenvíos: sigue vigente el último código enviado.
                record = PasswordResetCode.objects.filter(user=user, used_at__isnull=True).first()
            else:
                send_recovery_code(email, code)
        self.save_state(new_recovery_state(email, record))
        messages.info(self.request, CODE_SENT_MESSAGE)
        return super().form_valid(form)


@method_decorator(never_cache, name='dispatch')
class RecoveryCodeView(RecoveryFlowMixin, FormView):
    template_name = 'accounts/recovery_code.html'
    form_class = RecoveryCodeForm
    success_url = reverse_lazy('recovery_password')

    def dispatch(self, request, *args, **kwargs):
        self.state = self.get_state()
        if self.state is None:
            messages.info(request, 'Solicita un código de verificación para continuar.')
            return redirect('recovery_request')
        self.record = self.get_record(self.state)
        return super().dispatch(request, *args, **kwargs)

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        if self.request.method == 'POST':
            # Cada casilla del código se envía con name="code".
            kwargs['data'] = {'code': ''.join(self.request.POST.getlist('code'))}
        return kwargs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        wait = self.resend_wait_remaining(self.state)
        context.update(
            masked_email=mask_email(self.state['email']),
            resend_wait=wait,
            resend_wait_display=f'{wait // 60:02d}:{wait % 60:02d}',
            ttl_minutes=int(PasswordResetCode.ttl().total_seconds() // 60),
        )
        return context

    def post(self, request, *args, **kwargs):
        if request.POST.get('action') == 'resend':
            return self.resend()
        return super().post(request, *args, **kwargs)

    def form_valid(self, form):
        state, record = self.state, self.record
        max_attempts = PasswordResetCode.max_attempts()
        if state['attempts'] >= max_attempts or (record and record.failed_attempts >= max_attempts):
            form.add_error(None, BLOCKED_CODE_MESSAGE)
        elif self.is_expired(state, record):
            form.add_error(None, EXPIRED_CODE_MESSAGE)
        elif record is not None and record.verify(form.cleaned_data['code']):
            state['verified'] = True
            self.save_state(state)
            return super().form_valid(form)
        else:
            state['attempts'] += 1
            self.save_state(state)
            remaining = max_attempts - state['attempts']
            if remaining > 0:
                form.add_error(None, f'{INVALID_CODE_MESSAGE} Intentos restantes: {remaining}.')
            else:
                form.add_error(None, BLOCKED_CODE_MESSAGE)
        return self.form_invalid(form)

    def resend(self):
        state, record = self.state, self.record
        wait = self.resend_wait_remaining(state)
        if wait:
            messages.error(self.request, f'Debes esperar {wait} segundos para solicitar un nuevo código.')
            return redirect('recovery_code')

        if record is not None:
            try:
                record, code = PasswordResetCode.issue(record.user)
            except ValidationError as error:
                messages.error(self.request, RESEND_ERROR_MESSAGES[error.code])
                return redirect('recovery_code')
            send_recovery_code(state['email'], code)
        else:
            resends = 0 if self.is_expired(state, None) else state['resends'] + 1
            if resends > PasswordResetCode.max_resends():
                messages.error(self.request, RESEND_ERROR_MESSAGES['resend_limit'])
                return redirect('recovery_code')
            state['resends'] = resends

        state.update(
            code_id=record.pk if record else None,
            sent_at=record.last_sent_at.timestamp() if record else time.time(),
            attempts=0,
            verified=False,
        )
        self.save_state(state)
        messages.info(self.request, CODE_SENT_MESSAGE)
        return redirect('recovery_code')


@method_decorator(never_cache, name='dispatch')
class RecoveryPasswordView(RecoveryFlowMixin, FormView):
    template_name = 'accounts/recovery_password.html'
    form_class = SetPasswordForm
    success_url = reverse_lazy('login')

    def dispatch(self, request, *args, **kwargs):
        state = self.get_state()
        self.record = self.get_record(state) if state and state.get('verified') else None
        if self.record is None or not self.record.can_set_password():
            return self.reject()
        return super().dispatch(request, *args, **kwargs)

    def reject(self):
        messages.error(self.request, 'Verifica un código vigente antes de crear una nueva contraseña.')
        return redirect('recovery_request')

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['user'] = self.record.user
        return kwargs

    def form_valid(self, form):
        with transaction.atomic():
            # Se bloquea el código para que un doble envío no lo use dos veces.
            record = PasswordResetCode.objects.select_for_update().get(pk=self.record.pk)
            if not record.can_set_password():
                return self.reject()
            user = form.save()
            record.consume()
            AuditoriaService.register_change(
                official=getattr(user, 'official', None),
                action='Cambio de contraseña por recuperación',
                instance=user,
                origin_ip=self.request.META.get('REMOTE_ADDR') or None,
            )
        self.clear_state()
        messages.success(
            self.request,
            'Tu contraseña fue actualizada. Ya puedes ingresar con tu nueva contraseña.',
        )
        return super().form_valid(form)


# --- Mantenedores (SCRUM-30: acceso validado en el servidor) ---

class PositionMaintainerView(MaintainerListView):
    permission_required = 'accounts.view_position'
    template_name = 'accounts/position_list.html'
    extra_context = {
        'maintainer_title': 'Cargos',
        'maintainer_kind': 'positions',
        'columns': ['Cargo', 'Descripción', 'Vigencia'],
        'statuses': ['Vigente', 'No vigente'],
        'records': [
            {'cells': ['Alcalde', 'Autoridad comunal', 'Vigente'], 'status': 'Vigente', 'status_is_active': True},
            {'cells': ['Director', 'Dirección municipal', 'Vigente'], 'status': 'Vigente', 'status_is_active': True},
            {'cells': ['Jefe de departamento', 'Jefatura de unidad', 'Vigente'], 'status': 'Vigente', 'status_is_active': True},
            {'cells': ['Profesional', 'Gestión profesional', 'Vigente'], 'status': 'Vigente', 'status_is_active': True},
            {'cells': ['Administrativo', 'Apoyo administrativo', 'No vigente'], 'status': 'No vigente', 'status_is_active': False},
            {'cells': ['Técnico', 'Gestión técnica', 'Vigente'], 'status': 'Vigente', 'status_is_active': True},
        ],
    }


class AreaMaintainerView(MaintainerListView):
    permission_required = 'accounts.view_area'
    template_name = 'accounts/area_list.html'
    extra_context = {
        'maintainer_title': 'Áreas',
        'maintainer_kind': 'areas',
        'columns': ['Área', 'Vigencia'],
        'statuses': ['Vigente', 'No vigente'],
        'records': [
            {'cells': ['Administración Municipal', 'Vigente'], 'status': 'Vigente', 'status_is_active': True},
            {'cells': ['Desarrollo Comunitario', 'Vigente'], 'status': 'Vigente', 'status_is_active': True},
            {'cells': ['Obras Municipales', 'Vigente'], 'status': 'Vigente', 'status_is_active': True},
            {'cells': ['Tránsito y Transporte', 'Vigente'], 'status': 'Vigente', 'status_is_active': True},
            {'cells': ['Medio Ambiente', 'No vigente'], 'status': 'No vigente', 'status_is_active': False},
            {'cells': ['Secretaría Municipal', 'Vigente'], 'status': 'Vigente', 'status_is_active': True},
        ],
    }


class OfficialMaintainerView(MaintainerListView):
    permission_required = 'accounts.view_official'
    template_name = 'accounts/official_list.html'
    extra_context = {
        'maintainer_title': 'Funcionarios',
        'maintainer_kind': 'officials',
        'columns': OFFICIAL_COLUMNS,
        'statuses': Official.Status.choices,
    }

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        records = []
        for official in listed_officials(self.request):
            records.append(
                {
                    "cells": official_cells(official),
                    "pk": official.pk,
                    "is_self": is_same_identity(
                        self.request.user, target_official=official
                    ),
                    "status": official.status,
                    "status_is_active": official.status == Official.Status.ACTIVE,
                }
            )
        context["records"] = records
        context["total"] = len(records)
        context["can_add"] = self.request.user.has_perm("accounts.add_official")
        context["can_change"] = self.request.user.has_perm("accounts.change_official")
        return context


class GroupMaintainerView(MaintainerListView):
    permission_required = 'auth.view_group'
    template_name = 'accounts/group_list.html'
    extra_context = {
        'maintainer_title': 'Grupos de usuarios',
        'maintainer_kind': 'groups',
        'columns': ['Grupo', 'Permisos asignados'],
        'statuses': [],
        'records': [
            {'cells': ['Administradores', 'Permisos administrativos']},
            {'cells': ['Funcionarios', 'Consulta y gestión de actividades']},
            {'cells': ['Consulta', 'Solo lectura']},
            {'cells': ['Supervisores', 'Consulta de delegaciones autorizadas']},
            {'cells': ['Operadores', 'Registro de actividades']},
            {'cells': ['Auditoría', 'Consulta de registros']},
        ],
    }


# --- CRUD de Delegaciones y Usuarios (persistencia real, ámbito por delegación) ---
#
# El alcance del actor se calcula con la misma regla de Official.get_authorized_delegations()
# (rol vigente de alcance ALL => todas las delegaciones; en otro caso, la delegación principal
# más las autorizadas). A diferencia del modelo, aquí también se incluyen las delegaciones
# inactivas del ámbito, porque el mantenedor debe poder consultarlas y reactivarlas. El
# superusuario conserva el alcance total. Los formularios limitan sus opciones a este ámbito,
# de modo que un identificador enviado desde el navegador fuera del alcance no valida.


def _authorized_delegation_ids(user):
    """IDs de delegaciones dentro del ámbito, o None cuando el alcance es total."""
    if user.is_superuser:
        return None
    official = getattr(user, "official", None)
    if official is None:
        return set()
    if official.roles.filter(is_active=True, scope=Role.Scope.ALL).exists():
        return None
    ids = set(official.get_authorized_delegations().values_list("pk", flat=True))
    ids |= set(official.authorized_delegations.values_list("pk", flat=True))
    if official.delegation_id:
        ids.add(official.delegation_id)
    return ids


def scoped_delegations(user):
    """Delegaciones que el actor puede consultar y administrar."""
    ids = _authorized_delegation_ids(user)
    if ids is None:
        return Delegation.objects.all()
    return Delegation.objects.filter(pk__in=ids)


def scoped_users(user):
    """Cuentas cuyo funcionario pertenece al ámbito de delegaciones del actor."""
    ids = _authorized_delegation_ids(user)
    users = get_user_model().objects.all()
    if ids is None:
        return users
    return users.filter(
        Q(official__delegation_id__in=ids) | Q(official__authorized_delegations__in=ids)
    ).distinct()


def scoped_officials(user):
    queryset = Official.objects.filter(deleted_at__isnull=True)
    ids = _authorized_delegation_ids(user)
    if ids is not None:
        queryset = queryset.filter(
            Q(delegation_id__in=ids) | Q(authorized_delegations__in=ids)
        ).distinct()
    return queryset


def is_same_identity(actor, target_user=None, target_official=None):
    """Comprueba la identidad User/Official sin confiar en un identificador enviado."""
    if target_user is not None and actor.pk == target_user.pk:
        return True
    official = getattr(actor, "official", None)
    if target_official is not None and official is not None and official.pk == target_official.pk:
        return True
    if (
        target_user is not None
        and official is not None
        and official.user_id == target_user.pk
    ):
        return True
    if (
        target_official is not None
        and getattr(target_official, "user_id", None) == actor.pk
    ):
        return True
    return False


def filter_delegations(queryset, params):
    """Búsqueda parcial (código, nombre, dirección, comuna) y filtro por estado."""
    query = (params.get("q") or "").strip()
    status = (params.get("status") or "").strip()
    if query:
        queryset = queryset.filter(
            Q(code__icontains=query)
            | Q(delegation_name__icontains=query)
            | Q(address__icontains=query)
            | Q(commune__icontains=query)
        )
    if status in Delegation.Status.values:
        queryset = queryset.filter(status=status)
    return queryset


def filter_users(queryset, params):
    """Búsqueda parcial en varios campos y filtro por estado (usuario y funcionario)."""
    query = (params.get("q") or "").strip()
    status = (params.get("status") or "").strip()
    if query:
        queryset = queryset.filter(
            Q(username__icontains=query)
            | Q(first_name__icontains=query)
            | Q(last_name__icontains=query)
            | Q(email__icontains=query)
            | Q(official__full_name__icontains=query)
            | Q(official__national_id__icontains=query)
            | Q(official__email__icontains=query)
            | Q(official__delegation__delegation_name__icontains=query)
            | Q(official__delegation__code__icontains=query)
            | Q(official__roles__role_name__icontains=query)
        ).distinct()
    if status == Official.Status.ACTIVE:
        queryset = queryset.filter(is_active=True).filter(
            Q(official__isnull=True) | Q(official__status=Official.Status.ACTIVE)
        )
    elif status == Official.Status.INACTIVE:
        queryset = queryset.filter(
            Q(official__isnull=True, is_active=False)
            | Q(official__status=Official.Status.INACTIVE)
        )
    elif status == Official.Status.SUSPENDED:
        queryset = queryset.filter(official__status=Official.Status.SUSPENDED)
    return queryset


def filter_officials(queryset, params):
    """
    Búsqueda parcial en las columnas visibles (nombre, RUT, correo, área, cargo o estado) y
    filtro por estado: la misma coincidencia que aplica la tabla en el navegador.
    """
    query = (params.get("q") or "").strip()
    status = (params.get("status") or "").strip()
    if query:
        statuses = [value for value, label in Official.Status.choices if query.lower() in label.lower()]
        queryset = queryset.filter(
            Q(full_name__icontains=query)
            | Q(national_id__icontains=query)
            | Q(email__icontains=query)
            | Q(area__area_name__icontains=query)
            | Q(position__position_name__icontains=query)
            | Q(status__in=statuses)
        )
    if status in Official.Status.values:
        queryset = queryset.filter(status=status)
    return queryset


def listed_officials(request):
    """Funcionarios del ámbito y de la delegación activa, con la búsqueda y el estado pedidos."""
    officials = (
        scoped_officials(request.user)
        .select_related("area", "position", "delegation", "user")
        .order_by("full_name")
    )
    active_delegation = get_active_delegation(request)
    if active_delegation is not None:
        officials = officials.filter(
            Q(delegation=active_delegation)
            | Q(authorized_delegations=active_delegation)
        ).distinct()
    return filter_officials(officials, request.GET)


def official_cells(official):
    """Valores de las columnas OFFICIAL_COLUMNS para la tabla y la exportación."""
    return [
        official.full_name,
        official.national_id,
        official.email,
        official.area.area_name if official.area else "—",
        official.position.position_name if official.position else "—",
        official.get_status_display(),
    ]


def display_status(user):
    """Estado mostrado de la cuenta: combina User.is_active con Official.status."""
    official = getattr(user, "official", None)
    if official is not None and official.status == Official.Status.SUSPENDED:
        return Official.Status.SUSPENDED
    if not user.is_active or (official is not None and official.status != Official.Status.ACTIVE):
        return Official.Status.INACTIVE
    return Official.Status.ACTIVE


def decorate_user(user):
    """Valores de presentación (nombre, correo, rol, delegación y estado) para las tablas."""
    official = getattr(user, "official", None)
    user.display_name = (
        official.full_name
        if official is not None and official.full_name
        else (user.get_full_name().strip() or user.username)
    )
    user.display_email = (official.email if official is not None and official.email else user.email) or "—"
    user.display_delegation = official.delegation if official is not None else None
    if official is not None and official.roles.exists():
        user.display_roles = ", ".join(role.role_name for role in official.roles.all())
    elif user.is_superuser:
        user.display_roles = "Administrador del sistema"
    else:
        user.display_roles = "Sin rol"
    code = display_status(user)
    user.status_code = code
    user.status_label = Official.Status(code).label
    user.status_is_active = code == Official.Status.ACTIVE
    return user


def sole_global_administrator_user_pk():
    """Cuenta del único titular activo del último rol Administrador global, si la hay."""
    role = last_global_administrator()
    if role is None:
        return None
    holders = list(active_officials(role).values_list("user_id", flat=True)[:2])
    return holders[0] if len(holders) == 1 else None


def deny_privileged_role_assignment(request, form):
    """
    Responde 403 con auditoría si el formulario pidió roles privilegiados sin accounts.change_role,
    igual que el mantenedor de Roles con los permisos privilegiados. Las casillas ya se muestran
    bloqueadas, de modo que solo una petición manipulada llega aquí.
    """
    denied = getattr(form, "denied_privileged_roles", None)
    if denied:
        register_denied_access(request, ["accounts.change_role"])
        names = ", ".join(role.role_name for role in denied)
        raise PermissionDenied(f"Asignar roles privilegiados ({names}) requiere accounts.change_role.")


def delegation_label(delegation):
    return f"{delegation.code} · {delegation.delegation_name}" if delegation else "—"


def delegation_snapshot(delegation):
    """Valores auditables de la delegación."""
    return {
        "Código": delegation.code,
        "Nombre": delegation.delegation_name,
        "Dirección": delegation.address,
        "Comuna": delegation.commune,
        "Estado": delegation.get_status_display(),
    }


def official_snapshot(official):
    """Valores auditables del perfil de funcionario, leídos de la base (roles y delegaciones al día)."""
    return {
        "Nombre completo": official.full_name,
        "RUT o RUN chileno": official.national_id,
        "Correo de contacto": official.email,
        "Teléfono": official.phone or "—",
        "Área": official.area.area_name if official.area else "—",
        "Cargo": official.position.position_name if official.position else "—",
        "Delegación principal": delegation_label(official.delegation),
        "Delegaciones autorizadas": ", ".join(
            sorted(delegation_label(item) for item in official.authorized_delegations.all())
        ) or "—",
        "Roles": ", ".join(sorted(role.role_name for role in official.roles.all())) or "Sin rol",
        "Estado": official.get_status_display(),
    }


def user_snapshot(user):
    """Valores auditables de la cuenta y de su perfil de funcionario; nunca la contraseña ni su hash."""
    snapshot = {
        "Usuario": user.username,
        "Nombres": user.first_name or "—",
        "Apellidos": user.last_name or "—",
        "Correo": user.email or "—",
        "Acceso al Admin": "Sí" if user.is_staff else "No",
        "Cuenta activa": "Sí" if user.is_active else "No",
    }
    official = Official.objects.filter(user=user).first()
    if official is not None:
        snapshot.update(official_snapshot(official))
    return snapshot


def password_change_note(snapshot, form):
    """Si se cambió la contraseña, lo deja en el valor nuevo sin registrar la clave."""
    if form.cleaned_data.get("password1"):
        snapshot["Contraseña"] = "Actualizada (no se registra su valor)"
    return snapshot


def _actor_official(request):
    return getattr(request.user, "official", None)


def _registrar_auditoria(request, action, instance, previous="", new=""):
    AuditoriaService.register_change(
        official=_actor_official(request),
        action=action,
        instance=instance,
        previous_value=previous,
        new_value=new,
        origin_ip=request.META.get("REMOTE_ADDR") or None,
    )


class DelegationListView(ClampedPaginationMixin, ProtectedViewMixin, ListView):
    permission_required = "accounts.view_delegation"
    template_name = "accounts/delegation_list.html"
    context_object_name = "delegations"
    paginate_by = 10

    def get_queryset(self):
        queryset = scoped_delegations(self.request.user).order_by("delegation_name", "pk")
        return filter_delegations(queryset, self.request.GET)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        params = self.request.GET.copy()
        params.pop(self.page_kwarg, None)
        context.update(
            maintainer_title="Delegaciones municipales",
            maintainer_kind="delegations",
            query=(self.request.GET.get("q") or "").strip(),
            selected_status=(self.request.GET.get("status") or "").strip(),
            status_choices=Delegation.Status.choices,
            querystring=params.urlencode(),
            total=context["paginator"].count,
            can_add=self.request.user.has_perm("accounts.add_delegation"),
            can_change=self.request.user.has_perm("accounts.change_delegation"),
        )
        return context


class DelegationExportView(ProtectedViewMixin, View):
    permission_required = "accounts.view_delegation"

    def get(self, request):
        queryset = filter_delegations(
            scoped_delegations(request.user).order_by("delegation_name", "pk"), request.GET
        )
        rows = (
            (
                delegation.code,
                delegation.delegation_name,
                delegation.address,
                delegation.commune,
                delegation.get_status_display(),
            )
            for delegation in queryset
        )
        return xlsx_response(
            "delegaciones",
            ("Código", "Nombre", "Dirección", "Comuna", "Estado"),
            rows,
            sheet_title="Delegaciones",
        )


class DelegationCreateView(ProtectedViewMixin, ModalFormOnlyMixin, CreateView):
    permission_required = "accounts.add_delegation"
    model = Delegation
    form_class = DelegationForm
    template_name = "accounts/delegation_form.html"
    success_url = reverse_lazy("delegation_list")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(maintainer_title="Nueva delegación", form_mode="create")
        return context

    def form_valid(self, form):
        response = super().form_valid(form)
        _registrar_auditoria(
            self.request,
            "Creación de delegación",
            self.object,
            new=format_snapshot(delegation_snapshot(self.object)),
        )
        messages.success(
            self.request,
            f"La delegación {self.object.delegation_name} fue creada correctamente.",
        )
        return response

    def form_invalid(self, form):
        messages.error(self.request, "No se pudo guardar la delegación. Revisa los datos ingresados.")
        return super().form_invalid(form)


class DelegationUpdateView(ScopedObjectMixin, ProtectedViewMixin, ModalFormOnlyMixin, UpdateView):
    permission_required = "accounts.change_delegation"
    model = Delegation
    form_class = DelegationForm
    template_name = "accounts/delegation_form.html"
    success_url = reverse_lazy("delegation_list")

    def get_queryset(self):
        return scoped_delegations(self.request.user)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(maintainer_title=f"Editar delegación {self.object.code}", form_mode="edit")
        return context

    def form_valid(self, form):
        # self.object ya trae los valores del formulario: el anterior se lee de la base.
        previous_snapshot = delegation_snapshot(type(self.object).objects.get(pk=self.object.pk))
        response = super().form_valid(form)
        previous, new = describe_changes(previous_snapshot, delegation_snapshot(self.object))
        _registrar_auditoria(
            self.request, "Actualización de delegación", self.object, previous=previous, new=new
        )
        messages.success(
            self.request,
            f"La delegación {self.object.delegation_name} fue actualizada correctamente.",
        )
        return response

    def form_invalid(self, form):
        messages.error(self.request, "No se pudo guardar la delegación. Revisa los datos ingresados.")
        return super().form_invalid(form)


class DelegationDetailView(ScopedObjectMixin, ProtectedViewMixin, DetailView):
    permission_required = "accounts.view_delegation"
    model = Delegation
    template_name = "accounts/delegation_detail.html"
    context_object_name = "delegation"

    def get_queryset(self):
        return scoped_delegations(self.request.user)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        delegation = self.object
        context.update(
            maintainer_title="Detalle de delegación",
            officials_count=delegation.officials.count(),
            authorized_count=delegation.authorized_officials.count(),
            attentions_count=delegation.social_attentions.count(),
            can_change=self.request.user.has_perm("accounts.change_delegation"),
        )
        return context


class DelegationDeactivateView(ProtectedViewMixin, View):
    permission_required = "accounts.change_delegation"

    def post(self, request, pk):
        delegation = get_scoped_object_or_404(request, scoped_delegations(request.user), pk=pk)
        if delegation.status == Delegation.Status.INACTIVE:
            messages.info(request, "La delegación ya estaba inactiva.")
            return redirect("delegation_list")
        delegation.deactivate()
        _registrar_auditoria(
            request, "Desactivación de delegación", delegation, previous="Estado: Activa", new="Estado: Inactiva"
        )
        messages.success(
            request, f"La delegación {delegation.delegation_name} fue desactivada correctamente."
        )
        return redirect("delegation_list")


class DelegationActivateView(ProtectedViewMixin, View):
    permission_required = "accounts.change_delegation"

    def post(self, request, pk):
        delegation = get_scoped_object_or_404(request, scoped_delegations(request.user), pk=pk)
        if delegation.status == Delegation.Status.ACTIVE:
            messages.info(request, "La delegación ya estaba activa.")
            return redirect("delegation_list")
        delegation.activate()
        _registrar_auditoria(
            request, "Activación de delegación", delegation, previous="Estado: Inactiva", new="Estado: Activa"
        )
        messages.success(
            request, f"La delegación {delegation.delegation_name} fue activada correctamente."
        )
        return redirect("delegation_list")


class OfficialExportView(ProtectedViewMixin, View):
    """Exporta a Excel los funcionarios del ámbito con los mismos filtros y columnas de la tabla."""

    permission_required = "accounts.view_official"

    def get(self, request):
        return xlsx_response(
            "funcionarios",
            OFFICIAL_COLUMNS,
            (official_cells(official) for official in listed_officials(request)),
            sheet_title="Funcionarios",
        )


class OfficialCreateView(ProtectedViewMixin, ModalFormOnlyMixin, FormView):
    permission_required = "accounts.add_official"
    template_name = "accounts/official_form.html"
    form_class = OfficialForm
    success_url = reverse_lazy("official_maintainer")

    def get_form_kwargs(self):
            kwargs = super().get_form_kwargs()
            kwargs.update(
                actor=self.request.user,
                delegation_queryset=scoped_delegations(self.request.user),
                active_delegation=get_active_delegation(self.request),
                existing_usernames=get_user_model().objects.values_list("username", flat=True),
            )
            return kwargs

    def get_context_data(self, **kwargs):
            context = super().get_context_data(**kwargs)
            context.update(
                maintainer_title="Nuevo funcionario",
                form_mode="create",
                existing_usernames=list(
                    get_user_model().objects.values_list("username", flat=True)
                ),
            )
            return context

    def form_valid(self, form):
            deny_privileged_role_assignment(self.request, form)
            official = form.save()
            _registrar_auditoria(
                self.request,
                "Creación de funcionario",
                official,
                new=format_snapshot(official_snapshot(official)),
            )
            messages.success(
                self.request,
                f"El funcionario {official.full_name} fue creado correctamente.",
            )
            return super().form_valid(form)

    def form_invalid(self, form):
            deny_privileged_role_assignment(self.request, form)
            messages.error(
                self.request,
                "No se pudo guardar el funcionario. Revisa los datos ingresados.",
            )
            return super().form_invalid(form)


class OfficialUpdateView(ProtectedViewMixin, ModalFormOnlyMixin, FormView):
    permission_required = "accounts.change_official"
    template_name = "accounts/official_form.html"
    form_class = OfficialForm
    success_url = reverse_lazy("official_maintainer")

    def get_official(self):
            if not hasattr(self, "_official"):
                self._official = get_scoped_object_or_404(
                    self.request,
                    scoped_officials(self.request.user)
                    .select_related("user", "area", "position", "delegation"),
                    pk=self.kwargs["pk"],
                )
            return self._official

    def dispatch(self, request, *args, **kwargs):
            if request.user.is_authenticated and request.user.has_perm(self.permission_required):
                official = self.get_official()
                if is_same_identity(request.user, target_official=official):
                    return redirect("my_profile")
            return super().dispatch(request, *args, **kwargs)

    def get_form_kwargs(self):
            kwargs = super().get_form_kwargs()
            kwargs.update(
                actor=self.request.user,
                instance=self.get_official(),
                delegation_queryset=scoped_delegations(self.request.user),
                active_delegation=get_active_delegation(self.request),
            )
            return kwargs

    def get_context_data(self, **kwargs):
            context = super().get_context_data(**kwargs)
            official = self.get_official()
            context.update(
                maintainer_title=f"Editar funcionario {official.full_name}",
                form_mode="edit",
                edited_official=official,
            )
            return context

    def form_valid(self, form):
            deny_privileged_role_assignment(self.request, form)
            previous_snapshot = official_snapshot(self.get_official())
            official = form.save()
            previous, new = describe_changes(previous_snapshot, official_snapshot(official))
            _registrar_auditoria(
                self.request,
                "Actualización de funcionario",
                official,
                previous=previous,
                new=new,
            )
            messages.success(
                self.request,
                f"El funcionario {official.full_name} fue actualizado correctamente.",
            )
            return super().form_valid(form)

    def form_invalid(self, form):
            deny_privileged_role_assignment(self.request, form)
            messages.error(
                self.request,
                "No se pudo actualizar el funcionario. Revisa los datos ingresados.",
            )
            return super().form_invalid(form)


class UserListView(ClampedPaginationMixin, ProtectedViewMixin, ListView):
    permission_required = "auth.view_user"
    template_name = "accounts/user_list.html"
    context_object_name = "users"
    paginate_by = 10

    def get_queryset(self):
        queryset = (
            scoped_users(self.request.user)
            .select_related("official", "official__delegation")
            .prefetch_related("official__roles")
            .order_by("username")
        )
        active_delegation = get_active_delegation(self.request)
        if active_delegation is not None:
            queryset = queryset.filter(
                Q(official__isnull=True)
                | Q(official__delegation=active_delegation)
                | Q(official__authorized_delegations=active_delegation)
            ).distinct()
        return filter_users(queryset, self.request.GET)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        for user in context["users"]:
            decorate_user(user)
        params = self.request.GET.copy()
        params.pop(self.page_kwarg, None)
        can_change = self.request.user.has_perm("auth.change_user")
        context.update(
            maintainer_title="Usuarios del sistema",
            maintainer_kind="users",
            query=(self.request.GET.get("q") or "").strip(),
            selected_status=(self.request.GET.get("status") or "").strip(),
            status_choices=Official.Status.choices,
            querystring=params.urlencode(),
            total=context["paginator"].count,
            can_add=self.request.user.has_perm("auth.add_user"),
            can_change=can_change,
            protected_user_pk=sole_global_administrator_user_pk() if can_change else None,
        )
        return context


class UserDetailView(ScopedObjectMixin, ProtectedViewMixin, DetailView):
    permission_required = "auth.view_user"
    template_name = "accounts/user_detail.html"
    context_object_name = "account"

    def get_queryset(self):
        return (
            scoped_users(self.request.user)
            .select_related("official", "official__delegation", "official__area", "official__position")
            .prefetch_related("official__roles", "official__authorized_delegations")
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        decorate_user(self.object)
        context.update(
            maintainer_title="Detalle de usuario",
            can_change=(
                self.request.user.has_perm("auth.change_user")
                and not is_same_identity(self.request.user, target_user=self.object)
            ),
            authorized_delegations=self.object.official.authorized_delegations.all()
            if getattr(self.object, "official", None) is not None
            else [],
        )
        return context


class UserExportView(ProtectedViewMixin, View):
    permission_required = "auth.view_user"

    def get(self, request):
        queryset = (
            scoped_users(request.user)
            .select_related("official", "official__delegation")
            .prefetch_related("official__roles")
            .order_by("username")
        )
        active_delegation = get_active_delegation(request)
        if active_delegation is not None:
            queryset = queryset.filter(
                Q(official__isnull=True)
                | Q(official__delegation=active_delegation)
                | Q(official__authorized_delegations=active_delegation)
            ).distinct()
        queryset = filter_users(queryset, request.GET)
        rows = []
        for user in queryset:
            decorate_user(user)
            official = getattr(user, "official", None)
            rows.append(
                (
                    user.username,
                    user.display_name,
                    user.display_email,
                    (official.national_id if official is not None else "") or "",
                    user.display_roles,
                    str(user.display_delegation) if user.display_delegation else "",
                    user.status_label,
                )
            )
        return xlsx_response(
            "usuarios",
            (
                "Nombre de usuario",
                "Nombre",
                "Correo electrónico",
                "RUT o RUN chileno",
                "Rol",
                "Delegación",
                "Estado",
            ),
            rows,
            sheet_title="Usuarios",
        )


class UserCreateView(ProtectedViewMixin, ModalFormOnlyMixin, FormView):
    permission_required = "auth.add_user"
    template_name = "accounts/user_form.html"
    form_class = OfficialUserForm
    success_url = reverse_lazy("user_maintainer")

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["actor"] = self.request.user
        kwargs["delegation_queryset"] = scoped_delegations(self.request.user)
        kwargs["active_delegation"] = get_active_delegation(self.request)
        return kwargs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(
            maintainer_title="Nuevo usuario",
            form_mode="create",
            edited_user=None,
            existing_usernames=list(
                get_user_model().objects.values_list("username", flat=True)
            ),
        )
        return context

    def form_valid(self, form):
        deny_privileged_role_assignment(self.request, form)
        user = form.save()
        _registrar_auditoria(
            self.request, "Creación de usuario", user, new=format_snapshot(user_snapshot(user))
        )
        messages.success(self.request, f"El usuario {user.username} fue creado correctamente.")
        return super().form_valid(form)

    def form_invalid(self, form):
        deny_privileged_role_assignment(self.request, form)
        messages.error(self.request, "No se pudo guardar el usuario. Revisa los datos ingresados.")
        return super().form_invalid(form)


class OwnOfficialProfileView(LoginRequiredMixin, FormView):
    """Edición personal aislada de la administración de cuentas y funcionarios."""

    template_name = "accounts/my_profile.html"
    form_class = OwnOfficialProfileForm
    success_url = reverse_lazy("my_profile")

    def dispatch(self, request, *args, **kwargs):
        official = getattr(request.user, "official", None)
        if official is None or not official.is_enabled:
            raise PermissionDenied("Tu cuenta no tiene un perfil de funcionario habilitado.")
        self.official = official
        return super().dispatch(request, *args, **kwargs)

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["instance"] = self.official
        return kwargs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(
            maintainer_title="Mi perfil",
            profile_official=self.official,
        )
        return context

    def form_valid(self, form):
        official = form.save()
        _registrar_auditoria(
            self.request,
            "Actualización del perfil propio",
            official,
            new=official.email,
        )
        messages.success(self.request, "Tus datos personales fueron actualizados correctamente.")
        return super().form_valid(form)

    def form_invalid(self, form):
        messages.error(self.request, "No se pudo actualizar tu perfil. Revisa los datos ingresados.")
        return super().form_invalid(form)


class UserUpdateView(ProtectedViewMixin, ModalFormOnlyMixin, FormView):
    permission_required = "auth.change_user"
    template_name = "accounts/user_form.html"
    form_class = OfficialUserForm
    success_url = reverse_lazy("user_maintainer")

    def get_edited_user(self):
        if not hasattr(self, "_edited_user"):
            self._edited_user = get_scoped_object_or_404(
                self.request, scoped_users(self.request.user), pk=self.kwargs["pk"]
            )
        return self._edited_user

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["actor"] = self.request.user
        kwargs["instance"] = self.get_edited_user()
        kwargs["delegation_queryset"] = scoped_delegations(self.request.user)
        kwargs["active_delegation"] = get_active_delegation(self.request)
        return kwargs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        edited_user = self.get_edited_user()
        context.update(
            maintainer_title=f"Editar usuario {edited_user.username}",
            form_mode="edit",
            edited_user=edited_user,
            existing_usernames=list(
                get_user_model()
                .objects.exclude(pk=edited_user.pk)
                .values_list("username", flat=True)
            ),
        )
        return context

    def form_valid(self, form):
        deny_privileged_role_assignment(self.request, form)
        previous_snapshot = user_snapshot(self.get_edited_user())
        user = form.save()
        previous, new = describe_changes(
            previous_snapshot, password_change_note(user_snapshot(user), form)
        )
        _registrar_auditoria(self.request, "Actualización de usuario", user, previous=previous, new=new)
        messages.success(self.request, f"El usuario {user.username} fue actualizado correctamente.")
        return super().form_valid(form)

    def form_invalid(self, form):
        deny_privileged_role_assignment(self.request, form)
        messages.error(self.request, "No se pudo guardar el usuario. Revisa los datos ingresados.")
        return super().form_invalid(form)


class UserDeactivateView(ProtectedViewMixin, View):
    permission_required = "auth.change_user"

    def post(self, request, pk):
        target = get_scoped_object_or_404(request, scoped_users(request.user), pk=pk)
        if is_same_identity(request.user, target_user=target):
            messages.error(request, "No puedes desactivar tu propia cuenta.")
            return redirect("user_maintainer")
        if not target.is_active and display_status(target) != Official.Status.ACTIVE:
            messages.info(request, f"El usuario {target.username} ya estaba inactivo.")
            return redirect("user_maintainer")
        protected_role = sole_global_administrator_role(getattr(target, "official", None))
        if protected_role is not None:
            messages.error(
                request, sole_global_administrator_message(target.official, protected_role, "desactivar a")
            )
            return redirect("user_maintainer")
        previous_status = Official.Status(display_status(target)).label
        target.is_active = False
        target.save(update_fields=["is_active"])
        official = getattr(target, "official", None)
        if official is not None and official.status == Official.Status.ACTIVE:
            official.status = Official.Status.INACTIVE
            official.save(update_fields=["status", "updated_at"])
        _registrar_auditoria(
            request,
            "Desactivación de usuario",
            target,
            previous=f"Usuario: {target.username}\nEstado: {previous_status}",
            new=f"Usuario: {target.username}\nEstado: {Official.Status.INACTIVE.label}",
        )
        messages.success(request, f"El usuario {target.username} fue desactivado correctamente.")
        return redirect("user_maintainer")


class UserActivateView(ProtectedViewMixin, View):
    permission_required = "auth.change_user"

    def post(self, request, pk):
        target = get_scoped_object_or_404(request, scoped_users(request.user), pk=pk)
        if is_same_identity(request.user, target_user=target):
            messages.error(request, "No puedes cambiar el estado de tu propia cuenta desde la administración.")
            return redirect("user_maintainer")
        if target.is_active and display_status(target) == Official.Status.ACTIVE:
            messages.info(request, f"El usuario {target.username} ya estaba activo.")
            return redirect("user_maintainer")
        previous_status = Official.Status(display_status(target)).label
        target.is_active = True
        target.save(update_fields=["is_active"])
        official = getattr(target, "official", None)
        if official is not None and official.status != Official.Status.ACTIVE:
            official.status = Official.Status.ACTIVE
            official.save(update_fields=["status", "updated_at"])
        _registrar_auditoria(
            request,
            "Activación de usuario",
            target,
            previous=f"Usuario: {target.username}\nEstado: {previous_status}",
            new=f"Usuario: {target.username}\nEstado: {Official.Status.ACTIVE.label}",
        )
        messages.success(request, f"El usuario {target.username} fue activado correctamente.")
        return redirect("user_maintainer")
