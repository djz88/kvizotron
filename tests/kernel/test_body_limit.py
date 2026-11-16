"""ADR-0066: the request body ceiling Caddy keeps, held by the application as well."""

import pytest
from django.http import HttpResponse
from django.test import RequestFactory

from app.kernel.middleware import BodyLimitMiddleware

MB = 1024 * 1024


def answer(request):
    return HttpResponse("ok")


def post(path, length, **extra):
    request = RequestFactory().post(path, data=b"", content_type="application/octet-stream")
    request.META["CONTENT_LENGTH"] = str(length)
    request.META.update(extra)
    return BodyLimitMiddleware(answer)(request)


@pytest.mark.parametrize(
    ("path", "length", "status"),
    [
        ("/admin/quizzes", 16 * MB, 200),
        ("/admin/quizzes", 16 * MB + 1, 413),
        ("/admin/import/new", 101 * MB, 200),
        ("/admin/import/new", 101 * MB + 1, 413),
        ("/a/0f1e2d3c/submit", 101 * MB, 200),
        ("/a/0f1e2d3c/submit/more", 16 * MB + 1, 413),
    ],
)
def test_a_body_over_its_ceiling_is_refused_before_anything_reads_it(path, length, status):
    """AC-181: the declared length decides, before anything reads the body."""
    assert post(path, length).status_code == status


def test_a_body_without_a_length_is_refused():
    """Chunked bodies have no length to check up front; browsers always send one."""
    response = post("/admin/quizzes", 0, HTTP_TRANSFER_ENCODING="chunked")
    assert response.status_code == 411


def test_a_malformed_length_is_refused():
    assert post("/admin/quizzes", "lots").status_code == 400


def test_a_refused_body_still_carries_the_security_headers(client):
    """It runs after SecurityMiddleware and the CSP middleware, which do not read the body."""
    response = client.post(
        "/admin/quizzes",
        data=b"",
        content_type="text/plain",
        CONTENT_LENGTH=str(17 * MB),
        secure=True,
    )
    assert response.status_code == 413
    assert response["X-Content-Type-Options"] == "nosniff"
    assert response["Strict-Transport-Security"] == "max-age=15552000"
    assert "Content-Security-Policy" in response


def test_caddy_and_the_application_hold_the_same_ceilings():
    """Caddy's MB is 10^6 bytes; both sides count in MiB (ADR-0066)."""
    import re
    from pathlib import Path

    from app.kernel import middleware

    caddyfile = (Path(__file__).resolve().parents[2] / "deploy" / "Caddyfile").read_text()
    sizes = re.findall(r"max_size (\d+)MiB", caddyfile)
    assert sorted(int(size) * MB for size in sizes) == [middleware.BODY, middleware.LARGE_BODY]


@pytest.mark.parametrize(
    "path",
    ["/admin/import/new", "/admin/import/abc/check", "/a/0f1e2d3c/submit"],
)
def test_the_paths_caddy_lets_through_large_get_the_large_ceiling_here_too(path):
    """Caddy's `@large` matcher and LARGE_BODY_ROUTE name the same addresses (ADR-0066)."""
    import re
    from pathlib import Path

    from app.kernel import middleware

    caddyfile = (Path(__file__).resolve().parents[2] / "deploy" / "Caddyfile").read_text()
    globs = re.search(r"@large path (.+)", caddyfile).group(1).split()
    by_caddy = any(re.fullmatch(glob.replace("*", ".*"), path) for glob in globs)
    assert by_caddy and middleware.LARGE_BODY_ROUTE.fullmatch(path)


def test_caddy_names_no_large_path_the_application_does_not():
    import re
    from pathlib import Path

    caddyfile = (Path(__file__).resolve().parents[2] / "deploy" / "Caddyfile").read_text()
    globs = re.search(r"@large path (.+)", caddyfile).group(1).split()
    assert globs == ["/admin/import/*", "/a/*/submit"]  # change both places together
