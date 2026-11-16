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
    """AC-16: the stored photo carries no EXIF."""
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
    """AC-16: a script posing as a picture is refused and nothing is stored."""
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


def test_a_15_mb_phone_photo_is_accepted_and_stored_small(storage):
    """AC-16: a photo just under 15 MB is taken and kept as at most 700 KB."""
    noise = Image.effect_noise((4000, 3000), 128).convert("RGB")
    photo = encoded(noise, "JPEG", quality=97, subsampling=0)
    assert 13 * 1024 * 1024 < len(photo) < 15 * 1024 * 1024
    asset_id = storage.store_participant_image(photo, run_assets=[])
    assert MediaAsset.objects.get(pk=asset_id).size <= 700 * 1024


def test_stored_at_most_700_kb(storage):
    noise = Image.effect_noise((3000, 2000), 100).convert("RGB")
    asset_id = storage.store_participant_image(encoded(noise, "JPEG", quality=95), run_assets=[])
    assert storage.load(asset_id) and MediaAsset.objects.get(pk=asset_id).size <= 700 * 1024
    assert max(opened(storage, asset_id).size) <= 1600


def test_pixel_limit(storage):
    with pytest.raises(ImageRefused):
        storage.store_participant_image(encoded(Image.new("1", (7000, 6000)), "PNG"), run_assets=[])


def test_run_limit_refuses_the_next(storage, monkeypatch):
    """AC-16: once the run's photo limit is used up, the next image is refused."""
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


def test_a_row_that_cannot_be_saved_leaves_no_file(storage, tmp_path, monkeypatch):
    """AC-147: the file is written before its row, so a failed save removes it again."""

    def broken(self, *args, **kwargs):
        raise RuntimeError("database is locked")

    monkeypatch.setattr(MediaAsset, "save", broken)
    with pytest.raises(RuntimeError, match="database is locked"):
        storage.store_participant_image(picture(), run_assets=[])
    assert not list(tmp_path.iterdir())
    assert MediaAsset.objects.count() == 0


def test_a_failed_removal_does_not_hide_the_save_error(storage, monkeypatch, caplog):
    def broken(self, *args, **kwargs):
        raise RuntimeError("database is locked")

    def stuck(self, *args, **kwargs):
        raise PermissionError("/secret/path")

    monkeypatch.setattr(MediaAsset, "save", broken)
    monkeypatch.setattr(Path, "unlink", stuck)
    with pytest.raises(RuntimeError, match="database is locked"):
        storage.store_participant_image(picture(), run_assets=[])
    assert "PermissionError" in caplog.text and "/secret/path" not in caplog.text


@pytest.mark.parametrize("step", ["replace", "chmod", "write"])
def test_a_failure_while_writing_leaves_no_temporary_file(storage, tmp_path, monkeypatch, step):
    """AC-147: a full disk or a failed rename leaves neither the temporary file nor a row."""

    def broken(*args, **kwargs):
        raise OSError("no space left on device")

    if step == "replace":
        monkeypatch.setattr(module.os, "replace", broken)
    elif step == "chmod":
        monkeypatch.setattr(module.os, "chmod", broken)
    else:
        real = module.tempfile.NamedTemporaryFile

        def failing_write(*args, **kwargs):
            handle = real(*args, **kwargs)
            monkeypatch.setattr(handle.file, "write", broken, raising=False)
            return handle

        monkeypatch.setattr(module.tempfile, "NamedTemporaryFile", failing_write)
    with pytest.raises(OSError, match="no space"):
        storage.store_participant_image(picture(), run_assets=[])
    assert not list(tmp_path.iterdir())
    assert MediaAsset.objects.count() == 0
