class ClampedPaginationMixin:
    """
    Paginación que ajusta la página al rango disponible.

    Si un filtro reduce los resultados y la página solicitada deja de existir, o si llega un
    número inválido, se muestra la página válida más cercana en lugar de responder 404.
    """

    page_size_options = (5, 10, 25, 50, 100)

    def get_paginate_by(self, queryset):
        try:
            size = int(self.request.GET.get("page_size", self.paginate_by))
        except (TypeError, ValueError):
            size = self.paginate_by
        return size if size in self.page_size_options else self.paginate_by

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(page_size_options=self.page_size_options,
                       selected_page_size=self.get_paginate_by(None))
        return context

    def paginate_queryset(self, queryset, page_size):
        paginator = self.get_paginator(
            queryset,
            page_size,
            orphans=self.get_paginate_orphans(),
            allow_empty_first_page=self.get_allow_empty(),
        )
        page = self.kwargs.get(self.page_kwarg) or self.request.GET.get(self.page_kwarg) or 1
        try:
            page_number = int(page)
        except (TypeError, ValueError):
            page_number = 1
        page_number = max(1, min(page_number, paginator.num_pages))
        page = paginator.page(page_number)
        return paginator, page, page.object_list, page.has_other_pages()
