"""The proxy tells browsers to use HTTPS, without extending it to subdomains or the preload list."""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def test_caddy_sets_one_hsts_header_without_subdomains_or_preload():
    """AC-132: Caddy sends one HSTS header of six months, without subdomains or preload."""
    caddyfile = (ROOT / "deploy" / "Caddyfile").read_text()
    lines = [line for line in caddyfile.splitlines() if "Strict-Transport-Security" in line]
    assert len(lines) == 1
    assert "max-age=15552000" in lines[0]
    assert not re.search(r"includeSubDomains|preload", lines[0], re.IGNORECASE)


def test_caddy_closes_an_idle_upstream_connection_before_gunicorn_does():
    """AC-133: gunicorn closes an idle keep-alive connection after 2 s. A POST that Caddy sends on
    a connection closed at that moment is reset and answered 502 (found by `make load`), so Caddy
    must give up its idle connections sooner."""
    caddyfile = (ROOT / "deploy" / "Caddyfile").read_text()
    found = re.search(
        r"reverse_proxy app:8000 \{[^}]*transport http \{\s*keepalive (\d+)s", caddyfile
    )
    assert found is not None, "reverse_proxy needs `transport http { keepalive 1s }`"
    assert int(found[1]) < 2


def test_caddy_replaces_the_hsts_header_of_the_application():
    """ADR-0066: the application sends HSTS too; Caddy must replace it (`>` defers the set until
    the upstream answered), or a response would carry two headers."""
    caddyfile = (ROOT / "deploy" / "Caddyfile").read_text()
    assert re.search(r"^\s*header >Strict-Transport-Security ", caddyfile, re.M)
