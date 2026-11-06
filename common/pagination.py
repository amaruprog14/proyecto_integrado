from django.core.paginator import Paginator
from common.list_state import (PAGE_SIZES, DEFAULT_SIZE, SORTS, module_for, prepare,
                               ordered, positive, query_params, sort_spec)


class ClampedPaginationMixin:
    """Paginación, orden y preferencias, después de autorizar la petición."""
    page_size_options = PAGE_SIZES
    paginate_by = DEFAULT_SIZE
    page_kwarg = 'page'

    def prepare_list_state(self):
        module = module_for(self.request)
        return prepare(self.request, module) if module else None

    def get(self, request, *args, **kwargs):
        self.prepare_list_state()
        response = super().get(request, *args, **kwargs)
        if hasattr(request, '_list_state'):
            response['X-List-URL'] = request.path + '?' + query_params(request._list_state).urlencode()
        return response

    def get_paginate_by(self, queryset):
        size = positive(self.request.GET.get('page_size'), DEFAULT_SIZE)
        return size if size in PAGE_SIZES else DEFAULT_SIZE

    def clamp_page(self, queryset):
        state = self.prepare_list_state()
        if state is not None:
            queryset = ordered(queryset, self.request._list_module, state)
        paginator = Paginator(queryset, self.get_paginate_by(queryset))
        page = paginator.page(min(positive(self.request.GET.get('page')), paginator.num_pages))
        if state is not None:
            state['page'] = page.number
            self.request.GET = query_params(state)
            if self.request.session.get(self.request._list_state_key) != state:
                self.request.session[self.request._list_state_key] = state.copy()
        return page

    def paginate_queryset(self, queryset, page_size):
        page = self.clamp_page(queryset)
        return page.paginator, page, page.object_list, page.has_other_pages()

    def list_pagination_context(self):
        state = self.prepare_list_state()
        context = dict(page_size_options=PAGE_SIZES, page_sizes=PAGE_SIZES,
                       selected_page_size=self.get_paginate_by(None), page_size=self.get_paginate_by(None))
        if state is not None:
            fields = sort_spec(self.request._list_module)[1]
            label = 'Incorporación al SGR' if self.request._list_module == 'group' else 'Fecha de creación'
            context.update(sort_choices=[('created', label)] + [(k, v[0]) for k, v in fields.items()],
                selected_sort=state['sort'], selected_direction=state['direction'],
                querystring=query_params(state, include_page=False).urlencode())
        return context

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(self.list_pagination_context())
        return context
