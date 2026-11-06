from pathlib import Path

from django.http import FileResponse, Http404, HttpRequest

ASSETS = Path(__file__).parent / "assets"
SERVED = frozenset({"pico.min.css", "theme.css"})


def asset(request: HttpRequest, name: str) -> FileResponse:
    if name not in SERVED:
        raise Http404
    response = FileResponse((ASSETS / name).open("rb"), content_type="text/css")
    response["Cache-Control"] = "public, max-age=3600"
    return response
