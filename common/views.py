from django.shortcuts import render
from django.urls import Resolver404, resolve

LISTING_SUFFIXES = ("_maintainer", "_list")


def listing_url_for(path):
    """
    Listado del mantenedor al que pertenece `path`, p. ej. /configuration/items/1000/editar/ →
    /configuration/items/. Se recorren los prefijos de la ruta del más largo al más corto y se
    usa el primero que corresponde a una vista de listado; None si no hay ninguno.
    """
    segments = [segment for segment in path.split("/") if segment]
    for end in range(len(segments) - 1, 0, -1):
        candidate = "/" + "/".join(segments[:end]) + "/"
        try:
            match = resolve(candidate)
        except Resolver404:
            continue
        if (match.url_name or "").endswith(LISTING_SUFFIXES):
            return candidate
    return None


def page_not_found(request, exception):
    """
    Página 404 del SGR (handler404; solo se usa con DEBUG=False). Mantiene el 404 de los
    registros inexistentes o fuera del ámbito y ofrece volver al listado del mantenedor.
    """
    return render(request, "404.html", {"listing_url": listing_url_for(request.path)}, status=404)
