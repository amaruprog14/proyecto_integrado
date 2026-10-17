from django.views.generic import TemplateView


class MaintainerListView(TemplateView):
    template_name = ''


class RecoveryRequestView(TemplateView):
    template_name = 'accounts/recovery_request.html'


class RecoveryCodeView(TemplateView):
    template_name = 'accounts/recovery_code.html'


class RecoveryPasswordView(TemplateView):
    template_name = 'accounts/recovery_password.html'


class DelegationMaintainerView(MaintainerListView):
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
