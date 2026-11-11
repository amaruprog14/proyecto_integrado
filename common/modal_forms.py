from django.contrib import messages
from django.http import Http404, HttpResponse


def is_modal_request(request):
    return request.headers.get("X-Modal-Request") == "true"


def add_form_success(request, message):
    if not (is_modal_request(request) and request.headers.get("X-Modal-Feedback") == "inline"):
        messages.success(request, message)


def add_form_error(request, message):
    if not is_modal_request(request):
        messages.error(request, message)


class ModalFormOnlyMixin:
    """Require maintainer create/edit forms to be opened by the modal client."""

    def dispatch(self, request, *args, **kwargs):
        if request.method == "GET" and not is_modal_request(request):
            raise Http404
        response = super().dispatch(request, *args, **kwargs)
        if (
            request.method == "POST"
            and is_modal_request(request)
            and response.status_code in (301, 302, 303, 307, 308)
        ):
            return HttpResponse(status=204)
        return response
