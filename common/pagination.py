class ClampedPaginationMixin:
    """
    Paginación que ajusta la página al rango disponible.

    Si un filtro reduce los resultados y la página solicitada deja de existir, o si llega un
    número inválido, se muestra la página válida más cercana en lugar de responder 404.
    """

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
