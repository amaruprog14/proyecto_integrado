from django.views.generic import TemplateView

from common.access import ProtectedViewMixin


class AttentionTypeMaintainerView(ProtectedViewMixin, TemplateView):
    permission_required = 'configuration.view_attentiontype'
    template_name = 'configuration/attention_type_list.html'
    extra_context = {
        'maintainer_title': 'Tipos de Atención',
        'maintainer_kind': 'attention-types',
        'columns': ['Código', 'Nombre', 'Descripción', 'Estado'],
        'statuses': ['Activo', 'Inactivo'],
        'records': [
            {
                'cells': ['TA001', 'Social', 'Apoyo social', 'Activo'],
                'status': 'Activo',
                'status_is_active': True,
            },
            {
                'cells': ['TA002', 'Salud', 'Orientación', 'Activo'],
                'status': 'Activo',
                'status_is_active': True,
            },
            {
                'cells': ['TA003', 'Educación', 'Apoyo escolar', 'Activo'],
                'status': 'Activo',
                'status_is_active': True,
            },
            {
                'cells': ['TA004', 'Vivienda', 'Orientación habitacional', 'Activo'],
                'status': 'Activo',
                'status_is_active': True,
            },
            {
                'cells': ['TA005', 'Adulto mayor', 'Apoyo y orientación', 'Activo'],
                'status': 'Activo',
                'status_is_active': True,
            },
            {
                'cells': ['TA006', 'Deportes', 'Actividades recreativas', 'Inactivo'],
                'status': 'Inactivo',
                'status_is_active': False,
            },
        ],
    }


class SubattentionTypeMaintainerView(ProtectedViewMixin, TemplateView):
    permission_required = 'configuration.view_subattentiontype'
    template_name = 'configuration/subattention_type_list.html'
    extra_context = {
        'maintainer_title': 'Sub Atención',
        'maintainer_kind': 'subattention-types',
        'columns': ['Código', 'Nombre', 'Tipo asociado', 'Estado'],
        'statuses': ['Activo', 'Inactivo'],
        'records': [
            {
                'cells': ['SA001', 'Ayuda social', 'Social', 'Activo'],
                'status': 'Activo',
                'status_is_active': True,
            },
            {
                'cells': ['SA002', 'Consulta médica', 'Salud', 'Activo'],
                'status': 'Activo',
                'status_is_active': True,
            },
            {
                'cells': ['SA003', 'Beca municipal', 'Educación', 'Activo'],
                'status': 'Activo',
                'status_is_active': True,
            },
            {
                'cells': ['SA004', 'Orientación familiar', 'Social', 'Activo'],
                'status': 'Activo',
                'status_is_active': True,
            },
            {
                'cells': ['SA005', 'Entrega de medicamentos', 'Salud', 'Activo'],
                'status': 'Activo',
                'status_is_active': True,
            },
            {
                'cells': ['SA006', 'Taller de apoyo escolar', 'Educación', 'Inactivo'],
                'status': 'Inactivo',
                'status_is_active': False,
            },
        ],
    }


class PeriodMaintainerView(ProtectedViewMixin, TemplateView):
    permission_required = 'configuration.view_period'
    template_name = 'configuration/period_list.html'
    extra_context = {
        'maintainer_title': 'Períodos',
        'maintainer_kind': 'periods',
        'columns': ['Fecha de inicio', 'Fecha de término', 'Estado'],
        'statuses': ['Abierto', 'Cerrado'],
        'records': [
            {
                'cells': ['01-01-2026', '31-03-2026', 'Cerrado'],
                'status': 'Cerrado',
                'status_is_active': False,
            },
            {
                'cells': ['01-04-2026', '30-06-2026', 'Cerrado'],
                'status': 'Cerrado',
                'status_is_active': False,
            },
            {
                'cells': ['01-07-2026', '30-09-2026', 'Cerrado'],
                'status': 'Cerrado',
                'status_is_active': False,
            },
            {
                'cells': ['01-10-2026', '31-12-2026', 'Abierto'],
                'status': 'Abierto',
                'status_is_active': True,
            },
            {
                'cells': ['01-01-2025', '31-03-2025', 'Cerrado'],
                'status': 'Cerrado',
                'status_is_active': False,
            },
            {
                'cells': ['01-04-2025', '30-06-2025', 'Cerrado'],
                'status': 'Cerrado',
                'status_is_active': False,
            },
        ],
    }
