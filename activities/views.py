from django.views.generic import TemplateView

from common.access import ProtectedViewMixin


class ActivityMaintainerView(ProtectedViewMixin, TemplateView):
    permission_required = 'activities.view_activity'
    template_name = 'activities/activity_list.html'
    extra_context = {
        'maintainer_title': 'Actividades',
        'maintainer_kind': 'activities',
        'columns': ['Código', 'Funcionario', 'Ítem', 'Fecha', 'Tipo de registro', 'Estado'],
        'statuses': ['Vigente', 'Archivada'],
        'records': [
            {
                'cells': ['ACT001', 'Camila Rojas', 'Atenciones realizadas', '16-10-2026', 'Registro mensual', 'Vigente'],
                'status': 'Vigente',
                'status_is_active': True,
            },
            {
                'cells': ['ACT002', 'Diego Muñoz', 'Fiscalizaciones', '15-10-2026', 'Terreno', 'Vigente'],
                'status': 'Vigente',
                'status_is_active': True,
            },
            {
                'cells': ['ACT003', 'Sofía González', 'Informes emitidos', '14-10-2026', 'Registro mensual', 'Archivada'],
                'status': 'Archivada',
                'status_is_active': False,
            },
            {
                'cells': ['ACT004', 'Matías Fuentes', 'Atenciones realizadas', '13-10-2026', 'Terreno', 'Vigente'],
                'status': 'Vigente',
                'status_is_active': True,
            },
            {
                'cells': ['ACT005', 'Valentina Pérez', 'Inspecciones', '12-10-2026', 'Registro mensual', 'Vigente'],
                'status': 'Vigente',
                'status_is_active': True,
            },
            {
                'cells': ['ACT006', 'Tomás Silva', 'Informes emitidos', '11-10-2026', 'Terreno', 'Vigente'],
                'status': 'Vigente',
                'status_is_active': True,
            },
        ],
    }


class AttentionEntryView(ProtectedViewMixin, TemplateView):
    permission_required = 'activities.add_socialattention'
    template_name = 'activities/attention_entry.html'
