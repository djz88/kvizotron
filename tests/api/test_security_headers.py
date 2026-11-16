import json
import re

import pytest

from app.domain import authoring, tokens
from tests.api.test_admin_auth import login
from tests.domain.helpers import ADMIN_ID, open_quiz_run, published_quiz
from tests.support.client import FormClient
from tests.support.photos import Player

pytestmark = pytest.mark.django_db


def test_csp_blocks_inline_and_foreign_sources(client):
    policy = client.get("/")["Content-Security-Policy"]
    for directive in (
        "default-src 'self'",
        "object-src 'none'",
        "base-uri 'self'",
        "frame-ancestors 'none'",
        "form-action 'self'",
    ):
        assert directive in policy
    assert "unsafe-inline" not in policy and "unsafe-eval" not in policy


def pages(client):
    run = open_quiz_run()
    return [client.get("/"), client.get("/q/kviz"), client.post(f"/r/{run.id}/start")]


def test_pages_have_no_inline_script_or_style(client):
    for response in pages(client):
        html = response.content.decode()
        assert " style=" not in html and "<style" not in html
        assert not re.search(r"<script(?![^>]*\bsrc=)", html)
        assert not re.search(r"\son\w+=", html)


def test_htmx_config_disables_eval_and_injected_styles(client):
    html = client.get("/").content.decode()
    raw = re.search(r'name="htmx-config" content="([^"]+)"', html).group(1).replace("&#34;", '"')
    config = json.loads(raw)
    assert config["allowEval"] is False
    assert config["includeIndicatorStyles"] is False
    assert config["historyCacheSize"] == 0
    assert {"code": "4..", "swap": True} in config["responseHandling"]


@pytest.mark.parametrize("name", ["htmx.min.js", "play.js"])
def test_assets_are_served_with_right_type(client, name):
    response = client.get(f"/assets/{name}")
    assert response.status_code == 200
    assert "javascript" in response["Content-Type"]
    assert "max-age" in response["Cache-Control"]
    assert f"/assets/{name}" in client.get("/").content.decode()


@pytest.mark.parametrize("name", ["unknown.js", "..%2Fhealth.py", "README"])
def test_other_asset_names_are_404(client, name):
    assert client.get(f"/assets/{name}").status_code == 404


# The response headers a browser relies on, checked on every kind of page the app serves.
#
# What Django already sends with the settings of this project, checked here and found fine:
# `X-Content-Type-Options: nosniff` (SecurityMiddleware, `SECURE_CONTENT_TYPE_NOSNIFF` is on by
# default), `Referrer-Policy: same-origin` (SecurityMiddleware default), the cross-origin opener
# policy `same-origin` (SecurityMiddleware default), a Content-Security-Policy with `frame-ancestors
# 'none'` (ContentSecurityPolicyMiddleware and `SECURE_CSP` in app/settings.py, which is the frame
# restriction), the `Secure` flag on the session and CSRF cookies and `HttpOnly` on the session
# cookie (`SESSION_COOKIE_SECURE`, `CSRF_COOKIE_SECURE`, `SESSION_COOKIE_HTTPONLY`), `SameSite=Lax`
# on both (app/settings.py). `Cache-Control: private, no-store` on the pages that hold a result link
# is set by the views themselves. Missing and added: the policy of `/media/<id>` replaces
# `SECURE_CSP` and had no `frame-ancestors`, which does not fall back to `default-src`;
# app/api/public.py names it. HSTS: Caddy sends it (tests/test_deploy_headers.py) and so does the
# application on HTTPS requests, for a single container without Caddy (ADR-0066, test below).

NO_STORE = "private, no-store"


def public_page(client):
    open_quiz_run()
    return client.get("/")


def admin_page(client):
    return client.get("/admin/quizzes")


def not_found(client):
    return client.get("/q/no-such-quiz")


def stored_image(client):
    from app.kernel import registry
    from tests.api.test_external_images import png

    asset = registry.get("media_storage", "local").store_image(png())
    return client.get(f"/media/{asset}")


def static_asset(client):
    return client.get("/assets/play.js")


def finished_attempt_token():
    """The private address of a submitted attempt of a run that still asks for a name."""
    player = Player(
        authoring.open_run(published_quiz(), admin_id=ADMIN_ID, rules={"ask_name": "required"})
    )
    assert player.plain({"auto_submit": "1"}).status_code == 200
    return tokens.issue_result(player.attempt.id)


def result_link(client):
    response = client.get("/v/" + finished_attempt_token())
    assert 'name="participant_name"' in response.content.decode()  # the real page, not "no link"
    return response


def identity(client):
    response = client.post(f"/v/{finished_attempt_token()}/identity", {"participant_name": "Jana"})
    assert response.status_code == 302  # filled in, not the "no link" page
    return response


# (route, the client is a logged-in admin, the page carries private data)
ROUTES = {
    "public page": (public_page, False, False),
    "admin page": (admin_page, True, False),
    "404": (not_found, False, False),
    "media": (stored_image, False, False),
    "asset": (static_asset, False, False),
    "result link": (result_link, False, True),
    "identity": (identity, False, True),
}


@pytest.fixture(autouse=True)
def media(tmp_path, settings):
    settings.KVZ_MEDIA_PATH = str(tmp_path)


@pytest.mark.parametrize("name", ROUTES)
def test_the_response_carries_the_headers_that_apply(name, admin_user):
    """AC-132: every kind of response carries the headers that apply to it."""
    route, as_admin, private = ROUTES[name]
    client = FormClient()
    if as_admin:
        client.force_login(admin_user)
    response = route(client)
    assert response.status_code in (200, 302, 404), response.status_code
    assert response["X-Content-Type-Options"] == "nosniff"
    assert response["Referrer-Policy"]
    assert response["Content-Security-Policy"]
    assert (
        response.get("X-Frame-Options") == "DENY"
        or "frame-ancestors 'none'" in response["Content-Security-Policy"]
    )
    if private:
        assert response["Cache-Control"] == NO_STORE
        assert response["Referrer-Policy"] == "no-referrer"


def test_cookies_are_secure_and_not_readable_by_scripts(admin_user):
    client = FormClient()
    client.get("/admin/login")
    assert login(client).status_code == 302
    csrf, session = client.cookies["csrftoken"], client.cookies["sessionid"]
    assert csrf["secure"] and csrf["samesite"] == "Lax"
    assert session["secure"] and session["httponly"] and session["samesite"] == "Lax"


def test_a_secure_response_carries_six_months_of_hsts(client):
    """ADR-0066: the application sends HSTS itself, so it holds without Caddy too (AC-132)."""
    response = client.get("/healthz", secure=True)
    assert response["Strict-Transport-Security"] == "max-age=15552000"
    assert "Strict-Transport-Security" not in client.get("/healthz")
