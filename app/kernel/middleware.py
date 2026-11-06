from django.http import Http404

from app.kernel.registry import is_enabled


class ModuleGateMiddleware:
    """Routes of a disabled module answer 404; other routes are not touched."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        return self.get_response(request)

    def process_view(self, request, view_func, view_args, view_kwargs):
        namespaces = request.resolver_match.namespaces
        if namespaces and not is_enabled(namespaces[0]):
            raise Http404
