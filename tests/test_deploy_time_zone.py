"""The container runs in a real time zone, not UTC by accident, and the deployment can change it."""

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def test_the_image_sets_a_time_zone():
    assert "TZ=Europe/Prague" in (ROOT / "Dockerfile").read_text()


def test_compose_lets_the_deployment_choose_the_server_zone():
    assert "TZ: ${KVZ_SERVER_TZ:-Europe/Prague}" in (ROOT / "deploy" / "compose.yaml").read_text()
