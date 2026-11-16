"""ADR-0066: KVZ_TRUSTED_PROXIES decides which address the request limits count."""

import pytest
from django.core.exceptions import ImproperlyConfigured

from app import settings as app_settings


@pytest.mark.parametrize(("raw", "value"), [("", 1), ("0", 0), ("1", 1), ("2", 2)])
def test_a_whole_number_is_read_and_empty_is_the_default(monkeypatch, raw, value):
    monkeypatch.setenv("KVZ_TRUSTED_PROXIES", raw)
    assert app_settings._count("KVZ_TRUSTED_PROXIES", 1) == value


@pytest.mark.parametrize("raw", ["-1", "abc", "1.5", " 1"])
def test_anything_else_stops_the_start(monkeypatch, raw):
    monkeypatch.setenv("KVZ_TRUSTED_PROXIES", raw)
    with pytest.raises(ImproperlyConfigured):
        app_settings._count("KVZ_TRUSTED_PROXIES", 1)
