import io
import os
import time
from datetime import timedelta
from unittest import mock

import pytest
from django.test import Client
from django.utils import timezone, translation
from PIL import Image

from app.contracts import (
    ALLOW_INTERNAL_IMAGE_ADDRESSES,
    EXTERNAL_IMAGE_MODE,
    IMAGE_MODE_COPY,
    IMAGE_MODE_EXTERNAL,
    ImageAddressInvalid,
    ImageRefused,
    MediaStorageProvider,
)
from app.domain import settings as domain_settings
from app.kernel import registry
from app.providers.media_local import remote
from app.providers.media_local.models import AddressCheck, MediaAsset
from app.providers.media_local.provider import LocalMediaStorage

pytestmark = pytest.mark.django_db
MB = 1024 * 1024
SVG = b'<svg xmlns="http://www.w3.org/2000/svg" width="1" height="1"></svg>'


@pytest.fixture(autouse=True)
def media_path(settings, tmp_path):
    settings.KVZ_MEDIA_PATH = str(tmp_path)
    return tmp_path


@pytest.fixture
def storage():
    return LocalMediaStorage()


def noise(width, height):
    return Image.frombytes("RGB", (width, height), os.urandom(width * height * 3))


def encoded(image, image_format, **options):
    buffer = io.BytesIO()
    image.save(buffer, image_format, **options)
    return buffer.getvalue()


def stored(storage, asset_id):
    return Image.open(storage.load(asset_id).path)


def test_satisfies_protocol_and_is_registered(storage):
    assert isinstance(storage, MediaStorageProvider)
    assert registry.keys("media_storage") == ["local"]


def test_png_becomes_webp_at_most_1600_px_and_700_kb(storage):
    asset_id = storage.store_image(encoded(noise(2000, 1800), "PNG"))
    image = stored(storage, asset_id)
    assert image.format == "WEBP"
    assert max(image.size) <= 1600
    asset = MediaAsset.objects.get(pk=asset_id)
    assert asset.size <= 700 * 1024
    assert asset.mime_type == "image/webp" and asset.kind == "image" and len(asset.sha256) == 64


def test_transparency_is_kept(storage):
    image = Image.new("RGBA", (10, 10), (255, 0, 0, 0))
    assert stored(storage, storage.store_image(encoded(image, "PNG"))).mode == "RGBA"


def test_exif_is_gone_from_a_stored_jpeg(storage):
    exif = Image.Exif()
    exif[0x010F] = "Secret camera"
    data = encoded(noise(50, 50), "JPEG", exif=exif)
    assert b"Secret camera" in data
    asset_id = storage.store_image(data)
    with open(storage.load(asset_id).path, "rb") as file:
        assert b"Secret camera" not in file.read()


def test_rotation_from_exif_is_applied(storage):
    exif = Image.Exif()
    exif[0x0112] = 6  # rotate 90 degrees
    data = encoded(noise(40, 20), "JPEG", exif=exif)
    assert stored(storage, storage.store_image(data)).size == (20, 40)


def test_svg_is_stored_unchanged_after_the_basic_check(storage):
    asset_id = storage.store_image(SVG)
    loaded = storage.load(asset_id)
    assert loaded.mime_type == "image/svg+xml"
    with open(loaded.path, "rb") as file:
        assert file.read() == SVG


def test_gif_is_stored_unchanged(storage):
    data = encoded(noise(5, 5), "GIF")
    loaded = storage.load(storage.store_image(data))
    assert loaded.mime_type == "image/gif"
    with open(loaded.path, "rb") as file:
        assert file.read() == data


def test_gif_above_5_mb_is_refused(storage):
    with pytest.raises(ImageRefused):
        storage.store_image(encoded(noise(5, 5), "GIF") + b"\0" * (5 * MB))


def test_svg_above_5_mb_is_refused(storage):
    with pytest.raises(ImageRefused):
        storage.store_image(SVG + b" " * (5 * MB))


def test_raster_above_15_mb_is_refused(storage):
    with pytest.raises(ImageRefused):
        storage.store_image(encoded(noise(5, 5), "PNG") + b"\0" * (15 * MB))


def test_text_named_png_is_refused(storage):
    with pytest.raises(ImageRefused):
        storage.store_image(b"this is not an image")


def test_corrupt_png_is_refused(storage):
    data = encoded(noise(50, 50), "PNG")
    with pytest.raises(ImageRefused):
        storage.store_image(data[: len(data) // 2])
    assert not MediaAsset.objects.exists()


def test_decompression_bomb_is_refused(storage):
    bomb = Image.new("1", (20000, 20000))
    with pytest.raises(ImageRefused):
        storage.store_image(encoded(bomb, "PNG"))


def test_heic_is_refused_with_a_helpful_message(storage):
    data = b"\0\0\0\x18ftypheic\0\0\0\0mif1heic" + b"\0" * 100
    with pytest.raises(ImageRefused, match="HEIC"):
        storage.store_image(data)


@pytest.mark.parametrize(
    "svg",
    [
        b'<!DOCTYPE svg [<!ENTITY a "b">]><svg xmlns="http://www.w3.org/2000/svg"/>',
        '<!DOCTYPE svg [<!ENTITY a "b">]><svg xmlns="http://www.w3.org/2000/svg"/>'.encode(
            "utf-16"
        ),
        b"<html></html>",
        b"<svg",
    ],
    ids=["entity", "entity-utf16", "other-root", "broken"],
)
def test_bad_svg_is_refused(storage, svg):
    with pytest.raises(ImageRefused):
        storage.store_image(svg)


def test_exists(storage):
    asset_id = storage.store_image(SVG)
    assert storage.exists(asset_id)
    assert not storage.exists("00000000-0000-7000-8000-000000000000")
    assert not storage.exists("not-a-uuid")


def test_load_of_unknown_asset_is_none(storage):
    assert storage.load("00000000-0000-7000-8000-000000000000") is None


def test_served_with_type_nosniff_and_svg_sandbox(storage):
    response = Client().get(f"/media/{storage.store_image(SVG)}")
    assert response.status_code == 200
    assert response["Content-Type"] == "image/svg+xml"
    assert response["X-Content-Type-Options"] == "nosniff"
    assert "sandbox" in response["Content-Security-Policy"]
    assert "immutable" in response["Cache-Control"]


def test_served_webp_has_its_type(storage):
    response = Client().get(f"/media/{storage.store_image(encoded(noise(5, 5), 'PNG'))}")
    assert response["Content-Type"] == "image/webp"


def test_unknown_asset_is_404():
    assert Client().get("/media/00000000-0000-7000-8000-000000000000").status_code == 404


def test_a_lost_file_is_404(storage, media_path):
    asset_id = storage.store_image(SVG)
    for file in media_path.iterdir():
        file.unlink()
    assert Client().get(f"/media/{asset_id}").status_code == 404


def test_svg_with_a_plain_doctype_from_a_drawing_program_is_accepted(storage):
    svg = (
        b'<?xml version="1.0"?><!DOCTYPE svg PUBLIC "-//W3C//DTD SVG 1.1//EN" '
        b'"http://www.w3.org/Graphics/SVG/1.1/DTD/svg11.dtd">'
        b'<svg xmlns="http://www.w3.org/2000/svg"/>'
    )
    assert storage.load(storage.store_image(svg)).mime_type == "image/svg+xml"


def test_corrupt_gif_is_refused(storage):
    data = encoded(noise(100, 100), "GIF")
    with pytest.raises(ImageRefused):
        storage.store_image(data[: len(data) // 2])
    assert not MediaAsset.objects.exists()


def test_animated_gif_is_accepted(storage):
    frames = [noise(10, 10), noise(10, 10)]
    data = encoded(frames[0], "GIF", save_all=True, append_images=frames[1:])
    assert storage.load(storage.store_image(data)).mime_type == "image/gif"


def test_png_above_the_pixel_limit_is_refused(storage):
    with pytest.raises(ImageRefused):
        storage.store_image(encoded(Image.new("1", (7000, 6000)), "PNG"))


def test_running_out_of_memory_is_a_refusal_not_a_server_error(storage, monkeypatch):
    def no_memory(image):
        raise MemoryError

    monkeypatch.setattr("app.providers.media_local.provider._compressed", no_memory)
    with pytest.raises(ImageRefused):
        storage.store_image(encoded(noise(5, 5), "PNG"))


@pytest.mark.parametrize("error", [KeyError, TypeError, IndexError])
def test_an_exotic_failure_in_the_image_library_is_a_refusal(storage, monkeypatch, error):
    def fails(image):
        raise error("exotic")

    monkeypatch.setattr("app.providers.media_local.provider._compressed", fails)
    with pytest.raises(ImageRefused):
        storage.store_image(encoded(noise(5, 5), "PNG"))


FUTURE = 10**12  # a deadline that has not passed


def png(side=3000):
    buffer = io.BytesIO()
    Image.new("RGB", (side, side), "red").save(buffer, "PNG")
    return buffer.getvalue()


def test_a_fetched_image_goes_through_the_upload_processing(monkeypatch):
    monkeypatch.setattr(remote, "fetch", lambda *a, **k: png())
    asset_id = LocalMediaStorage().fetch_image(
        "https://a.cz/x.png", allow_internal=False, deadline=FUTURE
    )
    stored = MediaAsset.objects.get(pk=asset_id)
    assert stored.mime_type == "image/webp"


def test_a_fetched_file_that_is_not_an_image_is_refused(monkeypatch):
    monkeypatch.setattr(remote, "fetch", lambda *a, **k: b"<html>nope</html>")
    with pytest.raises(ImageRefused):
        LocalMediaStorage().fetch_image("https://a.cz/x", allow_internal=False, deadline=FUTURE)
    assert not MediaAsset.objects.exists()


def test_a_bad_address_says_so():
    with pytest.raises(ImageAddressInvalid):
        LocalMediaStorage().fetch_image("http://a.cz/x", allow_internal=False, deadline=FUTURE)


def test_a_failed_fetch_is_a_refusal_but_not_a_bad_address(monkeypatch):
    def fail(*_args, **_kwargs):
        raise remote.RemoteRefused("down")

    monkeypatch.setattr(remote, "fetch", fail)
    with pytest.raises(ImageRefused) as refused:
        LocalMediaStorage().fetch_image("https://a.cz/x", allow_internal=False, deadline=FUTURE)
    assert not isinstance(refused.value, ImageAddressInvalid)


def test_the_time_left_limits_the_fetch(monkeypatch):
    fetch = mock.Mock(return_value=png(10))
    monkeypatch.setattr(remote, "fetch", fetch)
    storage = LocalMediaStorage()
    storage.fetch_image("https://a.cz/x", allow_internal=True, deadline=time.monotonic() + 2)
    assert fetch.call_args.kwargs["timeout"] <= 2
    assert fetch.call_args.kwargs["allow_internal"] is True
    storage.fetch_image("https://a.cz/x", allow_internal=False, deadline=FUTURE)
    assert fetch.call_args.kwargs["timeout"] == 10
    assert fetch.call_args.kwargs["max_bytes"] == 15 * MB


def test_the_provider_declares_its_two_settings():
    mode = domain_settings.CATALOGUE[EXTERNAL_IMAGE_MODE]
    assert mode.default == IMAGE_MODE_COPY
    assert mode.choices == (IMAGE_MODE_COPY, IMAGE_MODE_EXTERNAL)
    assert set(mode.scopes) == set(domain_settings.ALL_SCOPES)
    switch = domain_settings.CATALOGUE[ALLOW_INTERNAL_IMAGE_ADDRESSES]
    assert switch.default == "off"
    assert switch.scopes == ("global",)
    assert switch.scope_reason


def test_the_internal_switch_warns_on_its_page():
    with translation.override("en"):
        assert "stolen" in str(domain_settings.CATALOGUE[ALLOW_INTERNAL_IMAGE_ADDRESSES].help)


A = "https://a.example/1.png"
B = "https://a.example/2.png"


def checked(urls, **kwargs):
    storage = LocalMediaStorage()
    storage.check_addresses(urls, allow_internal=kwargs.pop("allow_internal", False), **kwargs)
    return storage.address_status(urls)


def test_a_check_records_the_result(monkeypatch):
    monkeypatch.setattr(remote, "fetch", lambda *a, **k: png(10))
    status = checked([A])
    assert status[A].ok
    assert status[A].checked_at


def test_a_recent_check_is_not_repeated(monkeypatch):
    fetch = mock.Mock(return_value=png(10))
    monkeypatch.setattr(remote, "fetch", fetch)
    checked([A])
    checked([A])
    assert fetch.call_count == 1


def test_an_old_check_is_repeated(monkeypatch):
    fetch = mock.Mock(return_value=png(10))
    monkeypatch.setattr(remote, "fetch", fetch)
    checked([A])
    old = timezone.now() - timedelta(minutes=61)
    AddressCheck.objects.filter(address=A).update(checked_at=old)
    checked([A])
    assert fetch.call_count == 2


def test_a_check_within_the_hour_is_not_repeated_at_59_minutes(monkeypatch):
    fetch = mock.Mock(return_value=png(10))
    monkeypatch.setattr(remote, "fetch", fetch)
    checked([A])
    recent = timezone.now() - timedelta(minutes=59)
    AddressCheck.objects.filter(address=A).update(checked_at=recent)
    checked([A])
    assert fetch.call_count == 1


def test_the_budget_leaves_the_rest_unchecked(monkeypatch):
    def slow(*_args, **_kwargs):
        time.sleep(0.02)
        return png(10)

    monkeypatch.setattr(remote, "fetch", slow)
    status = checked([A, B], total=0.01)
    assert A in status
    assert B not in status


def test_each_address_has_its_own_time_limit(monkeypatch):
    fetch = mock.Mock(return_value=png(10))
    monkeypatch.setattr(remote, "fetch", fetch)
    checked([A], per_address=3.0, total=10.0)
    assert fetch.call_args.kwargs["timeout"] <= 3.0


def test_a_failed_fetch_counts_as_failed(monkeypatch):
    monkeypatch.setattr(remote, "fetch", mock.Mock(side_effect=remote.RemoteRefused("down")))
    assert not checked([A])[A].ok


def test_what_is_not_an_image_counts_as_failed(monkeypatch):
    monkeypatch.setattr(remote, "fetch", lambda *a, **k: b"<html>nope</html>")
    assert not checked([A])[A].ok
    assert not MediaAsset.objects.exists()


def test_a_check_stores_no_image(monkeypatch):
    monkeypatch.setattr(remote, "fetch", lambda *a, **k: png(10))
    checked([A])
    assert not MediaAsset.objects.exists()


def test_an_internal_address_with_the_switch_off_counts_as_failed(monkeypatch):
    fetch = mock.Mock(side_effect=remote.RemoteInternal("a.example"))
    monkeypatch.setattr(remote, "fetch", fetch)
    assert not checked([A])[A].ok
    assert fetch.call_args.kwargs["allow_internal"] is False


def test_a_later_check_replaces_the_result(monkeypatch):
    monkeypatch.setattr(remote, "fetch", mock.Mock(side_effect=remote.RemoteRefused("down")))
    assert not checked([A])[A].ok
    AddressCheck.objects.filter(address=A).update(checked_at=timezone.now() - timedelta(hours=2))
    monkeypatch.setattr(remote, "fetch", lambda *a, **k: png(10))
    assert checked([A])[A].ok
