"""Scripts and stylesheets are addressed by their content, so a new version is loaded at once."""

import hashlib
import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.django_db
ROOT = Path(__file__).resolve().parents[2]


def test_every_script_and_stylesheet_of_a_page_carries_its_content_version(client):
    html = client.get("/").content.decode()
    addresses = re.findall(r'<script src="([^"]+)"', html) + re.findall(
        r'<link rel="stylesheet" href="([^"]+)"', html
    )
    assert addresses
    for address in addresses:
        path, _, version = address.partition("?v=")
        name = path.rsplit("/", 1)[1]
        folder = "app/plugins/theme_default/assets" if path.startswith("/m/") else "app/api/assets"
        content = (ROOT / folder / name).read_bytes()
        assert version == hashlib.sha256(content).hexdigest()[:12], address
        assert client.get(address).status_code == 200
