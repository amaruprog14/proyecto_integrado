def revision_from_form(client, url):
    return client.get(url, HTTP_X_MODAL_REQUEST="true").context["edit_revision"]


def post_with_revision(client, url, data=None, **kwargs):
    """POST de edición con la revisión vigente del formulario (control de edición simultánea)."""
    data = dict(data or {})
    data.setdefault("edit_revision", revision_from_form(client, url))
    return client.post(url, data, **kwargs)
