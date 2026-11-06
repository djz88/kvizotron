import json
import re

import pytest

from tests.domain.helpers import open_quiz_run

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
