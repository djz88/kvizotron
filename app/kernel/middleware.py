import codecs
import re
from collections.abc import Callable
from typing import Any

from django.http import Http404, HttpResponse

from app.kernel.registry import is_enabled

UPLOAD_ROUTE = re.compile(
    r"/admin/(?:quizzes|banks)/[0-9a-fA-F-]{36}/questions/(?:new|[^/]+/edit)"
    r"|/admin/quizzes/[0-9a-fA-F-]{36}/preview/submit"
    r"|/admin/import/new"
    r"|/admin/settings/branding"
    r"|/admin/quizzes/[0-9a-fA-F-]{36}/branding"
)
# Set by the API: whether a public request may carry a file. Must not read the body.
public_upload_check: Callable[[Any], bool] | None = None


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


def _may_upload(request) -> bool:
    by_admin = UPLOAD_ROUTE.fullmatch(request.path) and request.user.is_authenticated
    if not by_admin and not (public_upload_check and public_upload_check(request)):
        return False
    try:
        codecs.lookup(request.content_params.get("charset", "utf-8"))
    except LookupError:
        return False
    return True


class RefuseMultipartMiddleware:
    """Multipart parses uploads before any view runs, so only a logged-in admin's editor gets it,
    and on a public address only an attempt that asks for a photo (ADR-0047).

    An invalid charset in such a request would also end in a server error.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if (
            request.method == "POST"
            and request.content_type.startswith("multipart/")
            and not _may_upload(request)
        ):
            return HttpResponse(status=415)
        return self.get_response(request)
