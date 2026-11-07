from django.http import HttpResponseBadRequest
from django.shortcuts import render
from django.template import loader
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


def bad_request(request, exception):
    """
    Página 400 del SGR (handler400; solo se usa con DEBUG=False). Como la 500, se renderiza sin el
    contexto de la petición: con un Host no permitido request.get_host() vuelve a fallar, y la
    página no debe depender de la sesión ni de la base de datos. Nunca muestra la excepción.
    """
    return HttpResponseBadRequest(loader.render_to_string("400.html"))
