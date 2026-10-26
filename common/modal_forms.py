from django.http import Http404, HttpResponse


class ModalFormOnlyMixin:
    """Require maintainer create/edit forms to be opened by the modal client."""

    modal_header = "X-Modal-Request"
    modal_header_value = "true"

    def dispatch(self, request, *args, **kwargs):
        if (
            request.method == "GET"
            and request.headers.get(self.modal_header) != self.modal_header_value
        ):
            raise Http404
        response = super().dispatch(request, *args, **kwargs)
        if (
            request.method == "POST"
            and request.headers.get(self.modal_header) == self.modal_header_value
            and response.status_code in (301, 302, 303, 307, 308)
        ):
            return HttpResponse(status=204)
        return response
