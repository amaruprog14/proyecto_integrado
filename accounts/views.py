import logging
import math
import time

from django.contrib import messages
from django.contrib.auth.forms import SetPasswordForm
from django.core.exceptions import ValidationError
from django.core.mail import send_mail
from django.db import transaction
from django.shortcuts import redirect
from django.urls import reverse_lazy
from django.utils.decorators import method_decorator
from django.views.decorators.cache import never_cache
from django.views.generic import FormView, TemplateView

from common.access import ProtectedViewMixin
from configuration.services import AuditoriaService

from .backends import SGRAuthBackend, find_user_by_email
from .forms import RecoveryCodeForm, RecoveryRequestForm
from .models import PasswordResetCode

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


class MaintainerListView(ProtectedViewMixin, TemplateView):
    template_name = ''


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

class DelegationMaintainerView(MaintainerListView):
    permission_required = 'accounts.view_delegation'
    template_name = 'accounts/delegation_list.html'
    extra_context = {
        'maintainer_title': 'Delegaciones municipales',
        'maintainer_kind': 'delegations',
        'columns': ['Código', 'Nombre', 'Comuna', 'Estado'],
        'statuses': ['Activa', 'Inactiva'],
        'records': [
            {'cells': ['DEL01', 'Centro', 'La Serena', 'Activa'], 'status': 'Activa', 'status_is_active': True},
            {'cells': ['DEL02', 'Norte', 'La Serena', 'Activa'], 'status': 'Activa', 'status_is_active': True},
            {'cells': ['DEL03', 'Sur', 'La Serena', 'Inactiva'], 'status': 'Inactiva', 'status_is_active': False},
            {'cells': ['DEL04', 'Las Compañías', 'La Serena', 'Activa'], 'status': 'Activa', 'status_is_active': True},
            {'cells': ['DEL05', 'La Pampa', 'La Serena', 'Activa'], 'status': 'Activa', 'status_is_active': True},
            {'cells': ['DEL06', 'Avenida del Mar', 'La Serena', 'Inactiva'], 'status': 'Inactiva', 'status_is_active': False},
            {'cells': ['DEL07', 'Alfalfares', 'La Serena', 'Activa'], 'status': 'Activa', 'status_is_active': True},
            {'cells': ['DEL08', 'Islón', 'La Serena', 'Activa'], 'status': 'Activa', 'status_is_active': True},
            {'cells': ['DEL09', 'Rural', 'La Serena', 'Activa'], 'status': 'Activa', 'status_is_active': True},
        ],
    }


class RoleMaintainerView(MaintainerListView):
    permission_required = 'accounts.view_role'
    template_name = 'accounts/role_list.html'
    extra_context = {
        'maintainer_title': 'Roles y permisos',
        'maintainer_kind': 'roles',
        'columns': ['Código', 'Rol', 'Alcance', 'Estado'],
        'statuses': ['Activo', 'Inactivo'],
        'records': [
            {'cells': ['ROL01', 'Administrador', 'Transversal', 'Activo'], 'status': 'Activo', 'status_is_active': True},
            {'cells': ['ROL02', 'Operador', 'Delegación', 'Activo'], 'status': 'Activo', 'status_is_active': True},
            {'cells': ['ROL03', 'Consultor', 'Solo lectura', 'Activo'], 'status': 'Activo', 'status_is_active': True},
            {'cells': ['ROL04', 'Supervisor', 'Delegaciones autorizadas', 'Activo'], 'status': 'Activo', 'status_is_active': True},
            {'cells': ['ROL05', 'Coordinador', 'Delegación', 'Activo'], 'status': 'Activo', 'status_is_active': True},
            {'cells': ['ROL06', 'Auditor', 'Solo lectura', 'Inactivo'], 'status': 'Inactivo', 'status_is_active': False},
            {'cells': ['ROL07', 'Atención', 'Solo registros propios', 'Activo'], 'status': 'Activo', 'status_is_active': True},
            {'cells': ['ROL08', 'Analista', 'Delegación', 'Activo'], 'status': 'Activo', 'status_is_active': True},
            {'cells': ['ROL09', 'Consulta general', 'Solo lectura', 'Inactivo'], 'status': 'Inactivo', 'status_is_active': False},
        ],
    }


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
        'columns': ['Nombre completo', 'RUT / identificador', 'Correo', 'Área', 'Cargo', 'Estado'],
        'statuses': ['Activo', 'Inactivo', 'Suspendido'],
        'records': [
            {'cells': ['Camila Rojas', '11.111.111-1', 'camila.rojas@example.test', 'Administración Municipal', 'Profesional', 'Activo'], 'status': 'Activo', 'status_is_active': True},
            {'cells': ['Diego Muñoz', '12.222.222-2', 'diego.munoz@example.test', 'Desarrollo Comunitario', 'Director', 'Activo'], 'status': 'Activo', 'status_is_active': True},
            {'cells': ['Sofía González', '13.333.333-3', 'sofia.gonzalez@example.test', 'Obras Municipales', 'Técnico', 'Suspendido'], 'status': 'Suspendido', 'status_is_active': False},
            {'cells': ['Matías Fuentes', '14.444.444-4', 'matias.fuentes@example.test', 'Tránsito y Transporte', 'Administrativo', 'Inactivo'], 'status': 'Inactivo', 'status_is_active': False},
            {'cells': ['Valentina Pérez', '15.555.555-5', 'valentina.perez@example.test', 'Secretaría Municipal', 'Jefe de departamento', 'Activo'], 'status': 'Activo', 'status_is_active': True},
            {'cells': ['Tomás Silva', '16.666.666-6', 'tomas.silva@example.test', 'Administración Municipal', 'Profesional', 'Activo'], 'status': 'Activo', 'status_is_active': True},
        ],
    }


class UserMaintainerView(MaintainerListView):
    permission_required = 'auth.view_user'
    template_name = 'accounts/user_list.html'
    extra_context = {
        'maintainer_title': 'Usuarios del sistema',
        'maintainer_kind': 'users',
        'columns': ['Nombre', 'Correo electrónico', 'Rol', 'Delegación', 'Estado'],
        'statuses': ['Activo', 'Inactivo'],
        'records': [
            {'cells': ['Ana Ejemplo', 'ana@example.test', 'Operador', 'Centro', 'Activo'], 'status': 'Activo', 'status_is_active': True},
            {'cells': ['Luis Ejemplo', 'luis@example.test', 'Consultor', 'Centro', 'Activo'], 'status': 'Activo', 'status_is_active': True},
            {'cells': ['Sara Ejemplo', 'sara@example.test', 'Operador', 'Norte', 'Activo'], 'status': 'Activo', 'status_is_active': True},
            {'cells': ['Camila Rojas', 'camila.rojas@example.test', 'Administrador', 'Centro', 'Activo'], 'status': 'Activo', 'status_is_active': True},
            {'cells': ['Diego Muñoz', 'diego.munoz@example.test', 'Operador', 'Sur', 'Activo'], 'status': 'Activo', 'status_is_active': True},
            {'cells': ['Matías Fuentes', 'matias.fuentes@example.test', 'Consultor', 'Centro', 'Inactivo'], 'status': 'Inactivo', 'status_is_active': False},
        ],
    }


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
