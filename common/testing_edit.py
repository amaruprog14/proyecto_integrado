def revision_from_form(client, url):
    return client.get(url, HTTP_X_MODAL_REQUEST="true").context["edit_revision"]
