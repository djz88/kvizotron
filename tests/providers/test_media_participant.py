"""A participant's photo: only ordinary pictures, rebuilt, private (ADR-0028, AC-57)."""

import io
from pathlib import Path

import pytest
from django.conf import settings as django_settings
from PIL import Image

from app.contracts import ImageRefused
from app.providers.media_local import provider as module
from app.providers.media_local.models import MediaAsset
from app.providers.media_local.provider import LocalMediaStorage

pytestmark = pytest.mark.django_db


@pytest.fixture
def storage(tmp_path, settings):
    settings.KVZ_MEDIA_PATH = str(tmp_path)
    return LocalMediaStorage()


def encoded(image, fmt="PNG", **options):
    buffer = io.BytesIO()
    image.save(buffer, fmt, **options)
    return buffer.getvalue()


def picture(fmt="PNG", size=(40, 20), **options):
    return encoded(Image.new("RGB", size, "red"), fmt, **options)


def opened(storage, asset_id):
    return Image.open(storage.load(asset_id).path)


def test_portrait_exif_is_stored_upright_and_exif_is_gone(storage):
    exif = Image.Exif()
    exif[0x0112] = 6  # rotate 90 degrees to show
    exif[0x010F] = "A phone"
    stored = opened(
        storage,
        storage.store_participant_image(picture("JPEG", (40, 20), exif=exif), run_assets=[]),
    )
    assert stored.size == (20, 40)
    assert not stored.getexif()
    assert stored.format == "WEBP"


def test_stored_private_as_webp(storage):
    asset_id = storage.store_participant_image(picture("JPEG"), run_assets=[])
    loaded = storage.load(asset_id)
    assert loaded.private is True and loaded.mime_type == "image/webp"
    assert MediaAsset.objects.get(pk=asset_id).private is True


def test_admin_images_stay_public(storage):
    assert storage.load(storage.store_image(picture())).private is False


@pytest.mark.parametrize("fmt", ["PNG", "JPEG", "WEBP"])
def test_ordinary_pictures_are_taken(storage, fmt):
    storage.check_participant_image(picture(fmt))
    assert storage.store_participant_image(picture(fmt), run_assets=[])


def test_disguised_file_refused(storage):
    with pytest.raises(ImageRefused):
        storage.store_participant_image(b"#!/bin/sh\nrm -rf /\n", run_assets=[])
    assert MediaAsset.objects.count() == 0


@pytest.mark.parametrize(
    "data",
    [
        encoded(Image.new("P", (10, 10)), "GIF"),
        b'<svg xmlns="http://www.w3.org/2000/svg"><rect width="1" height="1"/></svg>',
        b"<html><script>alert(1)</script></html>",
    ],
    ids=["gif", "svg", "html"],
)
def test_only_png_jpeg_webp(storage, data):
    with pytest.raises(ImageRefused):
        storage.check_participant_image(data)
    with pytest.raises(ImageRefused):
        storage.store_participant_image(data, run_assets=[])


def test_15_mb_limit(storage):
    with pytest.raises(ImageRefused):
        storage.store_participant_image(b"x" * (15 * 1024 * 1024 + 1), run_assets=[])


def test_stored_at_most_700_kb(storage):
    noise = Image.effect_noise((3000, 2000), 100).convert("RGB")
    asset_id = storage.store_participant_image(encoded(noise, "JPEG", quality=95), run_assets=[])
    assert storage.load(asset_id) and MediaAsset.objects.get(pk=asset_id).size <= 700 * 1024
    assert max(opened(storage, asset_id).size) <= 1600


def test_pixel_limit(storage):
    with pytest.raises(ImageRefused):
        storage.store_participant_image(encoded(Image.new("1", (7000, 6000)), "PNG"), run_assets=[])


def test_run_limit_refuses_the_next(storage, monkeypatch):
    first = storage.store_participant_image(picture(), run_assets=[])
    monkeypatch.setattr(module, "MAX_RUN_BYTES", MediaAsset.objects.get(pk=first).size)
    with pytest.raises(ImageRefused):
        storage.store_participant_image(picture(), run_assets=[first])
    assert MediaAsset.objects.count() == 1
    assert storage.store_participant_image(picture(), run_assets=[])


def test_delete_removes_row_and_file(storage):
    asset_id = storage.store_participant_image(picture(), run_assets=[])
    path = Path(storage.load(asset_id).path)
    storage.delete_image(asset_id)
    assert not path.exists() and storage.load(asset_id) is None
    assert MediaAsset.objects.count() == 0


def test_delete_of_a_missing_image_is_harmless(storage):
    storage.delete_image("00000000-0000-7000-8000-000000000001")
    storage.delete_image("nonsense")
    assert Path(django_settings.KVZ_MEDIA_PATH).is_dir()


def test_the_refusal_names_only_what_a_participant_may_send(storage):
    with pytest.raises(ImageRefused) as error:
        storage.store_participant_image(b"not a picture", run_assets=[])
    assert "PNG" in str(error.value)
    assert "GIF" not in str(error.value) and "SVG" not in str(error.value)
    with pytest.raises(ImageRefused) as error:
        storage.check_participant_image(encoded(Image.new("P", (10, 10)), "GIF"))
    assert "GIF" not in str(error.value)
