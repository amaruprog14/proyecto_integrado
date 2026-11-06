from django import template
from django.utils.html import format_html
from common.list_state import HEADER_KEYS, module_for, normalize, query_params

register = template.Library()


@register.simple_tag(takes_context=True)
def sort_header(context, label, index):
    request = context['request']
    module = module_for(request)
    keys = HEADER_KEYS.get(module, [])
    index = int(index)
    if index >= len(keys):
        return format_html('<th scope="col" class="{}">{}</th>', 'maintainer-actions' if str(label).lower() == 'acciones' else '', label)
    state = getattr(request, '_list_state', None) or normalize(request.GET, module)
    key = keys[index]
    active = state['sort'] == key
    direction = 'desc' if active and state['direction'] == 'asc' else 'asc'
    params = query_params({**state, 'sort': key, 'direction': direction, 'page': 1})
    aria = ('ascending' if state['direction'] == 'asc' else 'descending') if active else 'none'
    arrow = (' ↑' if state['direction'] == 'asc' else ' ↓') if active else ' ↕'
    return format_html('<th scope="col" aria-sort="{}"><a class="list-sort-link" href="?{}" aria-label="Ordenar por {}: {}">{}<span aria-hidden="true">{}</span></a></th>',
        aria, params.urlencode(), label, 'ascendente' if direction == 'asc' else 'descendente', label, arrow)
