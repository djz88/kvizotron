from pathlib import Path

from django.http import FileResponse, Http404, HttpRequest

ASSETS = Path(__file__).parent / "assets"
TYPES = {
    "pico.min.css": "text/css",
    "theme.css": "text/css",
    "badge-python.svg": "image/svg+xml",
    "badge-django.svg": "image/svg+xml",
    "badge-htmx.svg": "image/svg+xml",
}
SERVED = frozenset(TYPES)


def asset(request: HttpRequest, name: str) -> FileResponse:
    if name not in SERVED:
        raise Http404
    response = FileResponse((ASSETS / name).open("rb"), content_type=TYPES[name])
    response["Cache-Control"] = "public, max-age=3600"
    return response
