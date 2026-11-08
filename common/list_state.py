"""Preferencias de listados. Los querysets autorizados se construyen en las vistas."""
from django.http import QueryDict
from django.utils.dateparse import parse_date
from django.db.models import F
from common.text import normalize_spaces

PAGE_SIZES = (5, 15, 30)
DEFAULT_SIZE = 15
SORTS = {
    'official': ('created_at', {'name': ('Nombre', 'full_name'), 'email': ('Correo', 'email')}),
    'delegation': ('created_at', {'name': ('Nombre', 'delegation_name'), 'code': ('Código', 'code')}),
    'user': ('date_joined', {'name': ('Usuario', 'username'), 'email': ('Correo', 'email')}),
    'role': ('created_at', {'name': ('Nombre', 'role_name'), 'scope': ('Alcance', 'scope')}),
    'item': ('created_at', {'name': ('Nombre', 'item_name'), 'code': ('Código', 'code')}),
    'attention_type': ('created_at', {'name': ('Nombre', 'name'), 'code': ('Código', 'code')}),
    'subattention_type': ('created_at', {'name': ('Nombre', 'name'), 'code': ('Código', 'code')}),
    'position': ('created_at', {'name': ('Nombre', 'position_name'), 'description': ('Descripción', 'description')}),
    'area': ('created_at', {'name': ('Nombre', 'area_name'), 'status': ('Estado', 'is_active')}),
    'group': ('sgr_profile__created_at', {'name': ('Nombre', 'name'), 'scope': ('Alcance', 'sgr_profile__scope')}),
    'period': ('created_at', {'start': ('Inicio', 'start_date'), 'end': ('Término', 'end_date')}),
    'activity': ('created_at', {'code': ('Código', 'code'), 'date': ('Fecha de actividad', 'date')}),
}
SORTS['territory'] = ('created_at', {'code': ('Código', 'code'), 'name': ('Nombre', 'territory_name'), 'delegation': ('Delegación', 'delegation__delegation_name'), 'description': ('Descripción', 'description')})
SORTS['official'][1].update(rut=('RUT o RUN chileno', 'national_id'), area=('Área', 'area__area_name'), position=('Cargo', 'position__position_name'))
SORTS['delegation'][1].update(address=('Dirección', 'address'), commune=('Comuna', 'commune'))
SORTS['user'][1].update(name=('Nombre', '_sort_name'), email=('Correo electrónico', '_sort_email'), role=('Rol', '_sort_roles'), delegation=('Delegación', '_sort_delegation'))
SORTS['role'][1].update(description=('Descripción', 'description'), permissions=('Permisos', '_sort_permission_count'), officials=('Funcionarios activos', 'active_official_count'))
SORTS['item'][1]['description'] = ('Descripción', 'description')
SORTS['attention_type'][1]['description'] = ('Descripción', 'description')
SORTS['subattention_type'][1]['parent'] = ('Tipo de Atención asociado', 'attention_type__name')
SORTS['area'][1].pop('status', None)
SORTS['group'][1].update(members=('Miembros', '_sort_members'), permissions=('Permisos', '_sort_permission_count'))
SORTS['activity'][1].update(official=('Funcionario', 'official__full_name'), item=('Ítem', 'item__item_name'), record_type=('Tipo de registro', 'record_type'))
# Los índices siguen las celdas visibles; Estado y Acciones nunca figuran aquí.
HEADER_KEYS = {
    'official': ['name', 'rut', 'email', 'area', 'position'],
    'delegation': ['code', 'name', 'address', 'commune'],
    'user': ['name', 'email', 'role', 'delegation'],
    'role': ['name', 'description', 'scope', 'permissions', 'officials'],
    'item': ['code', 'name', 'description'],
    'attention_type': ['code', 'name', 'description'],
    'subattention_type': ['code', 'name', 'parent'],
    'position': ['name', 'description'], 'area': ['name'],
    'group': ['name', 'scope', 'members', 'permissions'],
    'period': ['start', 'end'],
    'activity': ['code', 'official', 'item', 'date', 'record_type'],
    'territory': ['code', 'name', 'delegation', 'description'],
    'client_request': ['code', 'subject', 'created'],
    'staff_request': ['code', 'recipient', 'subject', 'delegation'],
}
REQUEST_SORTS = {
    key: ('created_at', {'code': ('Folio', 'pk'), 'subject': ('Solicitud', 'subject'),
        'recipient': ('Solicitante', 'recipient__full_name'), 'delegation': ('Delegación', 'delegation__delegation_name')})
    for key in ('client_request', 'staff_request')
}


def sort_spec(module):
    return (SORTS if module in SORTS else REQUEST_SORTS)[module]
ROUTES = {'official_maintainer': 'official', 'delegation_list': 'delegation', 'user_maintainer': 'user',
    'role_list': 'role', 'item_maintainer': 'item', 'attention_type_maintainer': 'attention_type',
    'subattention_type_maintainer': 'subattention_type',
    **{k + '_maintainer': k for k in ('position', 'area', 'group', 'period', 'activity', 'territory')},
    'client_requests': 'client_request', 'staff_client_requests': 'staff_request',
    **{k + '_export': k for k in SORTS}}


def module_for(request):
    return ROUTES.get(getattr(request.resolver_match, 'url_name', None))


def positive(value, default=1):
    try:
        value = int(value)
        return value if 0 < value <= 9223372036854775807 else default
    except (ValueError, TypeError, OverflowError):
        return default


def normalize(params, module):
    statuses = ('RECEIVED', 'REVIEW', 'RESOLVED') if module in REQUEST_SORTS else ('ACTIVE', 'INACTIVE', 'SUSPENDED') if module == 'official' else ('1', '0') if module in ('attention_type', 'subattention_type') else ('OPEN', 'CLOSED') if module == 'period' else ('ACTIVE', 'INACTIVE')
    state = dict(q=normalize_spaces(params.get('q'))[:200], status=params.get('status', ''),
        page=positive(params.get('page')), page_size=positive(params.get('page_size'), DEFAULT_SIZE),
        sort=params.get('sort', 'created'), direction=params.get('direction', 'desc'))
    if state['status'] not in statuses:
        state['status'] = ''
    if state['page_size'] not in PAGE_SIZES:
        state['page_size'] = DEFAULT_SIZE
    if state['sort'] not in ('created', *sort_spec(module)[1]):
        state['sort'], state['direction'] = 'created', 'desc'
    if state['direction'] not in ('asc', 'desc'):
        state['direction'] = 'desc'
    if module == 'activity':
        from activities.models import Activity
        for key in ('official', 'item'):
            state[key] = str(positive(params.get(key), 0) or '')
        value = params.get('record_type', '')
        state['record_type'] = value if value in Activity.RecordType.values else ''
        for key in ('date_from', 'date_to'):
            try:
                value = parse_date(params.get(key, ''))
            except (ValueError, TypeError):
                value = None
            state[key] = value.isoformat() if value else ''
    return state


def query_params(state, include_page=True):
    params = QueryDict('', mutable=True)
    for key, value in state.items():
        if include_page or key != 'page':
            params[key] = str(value)
    return params


def prepare(request, module):
    if hasattr(request, '_list_state'):
        return request._list_state
    from accounts.delegation_context import get_active_delegation
    delegation = get_active_delegation(request)
    key = f'list_state:v1:{request.user.pk}:{module}:{delegation.pk if delegation else "all"}'
    saved = request.session.get(key)
    previous = normalize(saved if isinstance(saved, dict) else {}, module)
    if (module == 'activity' and previous['status'] == 'INACTIVE' and 'status' not in request.GET
            and not request.user.has_perm('activities.archive_activity')):
        # Si se retiró el permiso de historial, regresar a vigentes en lugar de
        # mantener una preferencia que ya no puede consultarse.
        previous['status'] = ''
        previous['page'] = 1
    combined = {**previous, **{k: request.GET[k] for k in previous if k in request.GET}}
    state = normalize(combined, module)
    if saved and any(state[k] != previous[k] for k in state if k != 'page'):
        state['page'] = 1
    request._list_state, request._list_state_key, request._list_module = state, key, module
    request.GET = query_params(state)
    return state


def ordered(queryset, module, params):
    state = normalize(params, module)
    created, fields = sort_spec(module)
    field = created if state['sort'] == 'created' else fields[state['sort']][1]
    from django.db.models import Count, Min, Value, CharField, Case, When
    from django.db.models.functions import Coalesce, NullIf, Concat, Trim
    if module == 'user':
        queryset = queryset.annotate(
            _sort_name=Coalesce(NullIf('official__full_name', Value('')),
                NullIf('service_recipient__full_name', Value('')),
                NullIf(Trim(Concat('first_name', Value(' '), 'last_name')), Value('')), 'username'),
            _sort_email=Coalesce(NullIf('official__email', Value('')), NullIf('service_recipient__email', Value('')), 'email'),
            _sort_roles=Coalesce(Min('official__roles__role_name'), Case(
                When(is_superuser=True, then=Value('Administrador del sistema')),
                When(service_recipient__isnull=False, then=Value('Cliente')), default=Value('Sin rol'), output_field=CharField())),
            _sort_delegation=Coalesce('official__delegation__delegation_name', 'service_recipient__territory__delegation__delegation_name'))
    if module in ('role', 'group'):
        queryset = queryset.annotate(_sort_permission_count=Count('permissions', distinct=True))
        if module == 'group':
            queryset = queryset.annotate(_sort_members=Count('user', distinct=True))
        if state['sort'] == 'scope':
            from accounts.models import Role
            scope_field = 'scope' if module == 'role' else 'sgr_profile__scope'
            queryset = queryset.annotate(_sort_scope=Case(*[When(**{scope_field: value}, then=Value(label))
                for value, label in Role.Scope.choices], default=Value('Sin configurar'), output_field=CharField()))
            field = '_sort_scope'
    order = F(field).desc(nulls_last=True) if state['direction'] == 'desc' else F(field).asc(nulls_last=True)
    return queryset.order_by(order, '-pk')
