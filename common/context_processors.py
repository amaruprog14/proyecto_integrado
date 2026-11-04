def maintainer_realtime(request):
    from common.realtime import ROUTES
    name = getattr(request.resolver_match, 'url_name', None)
    module = next((key for key, route in ROUTES.items() if route == name), None)
    return {'maintainer_ws_url': f'/ws/maintainers/{module}/' if module else ''}
