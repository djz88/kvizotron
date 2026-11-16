"""Admin images on the media volume (ADR-0028). The content decides, never the file name."""

import hashlib
import io
import logging
import os
import struct
import tempfile
import time
from collections.abc import Mapping, Sequence
from datetime import datetime, timedelta
from pathlib import Path
from uuid import UUID
from xml.parsers import expat

from django.conf import settings
from django.db.models import Sum
from django.utils import timezone
from django.utils.translation import gettext as _
from PIL import Image, ImageOps, UnidentifiedImageError

from app.contracts import AddressStatus, ImageAddressInvalid, ImageRefused, StoredImage

from . import remote
from .models import AddressCheck, MediaAsset

logger = logging.getLogger(__name__)
MB = 1024 * 1024
MAX_RASTER_BYTES = 15 * MB
MAX_SVG_GIF_BYTES = 5 * MB
MAX_STORED_BYTES = 700 * 1024
FETCH_SECONDS = 10.0
MAX_SIDE = 1600
MIN_SIDE = 200
# One worker serves everybody, so decoded size is bounded. JPEG decodes small through draft().
MAX_PIXELS = 40_000_000
MAX_JPEG_PIXELS = 100_000_000
MAX_GIF_FRAMES = 2000
QUALITY_STEPS = (80, 70, 60, 50, 40)
SHRINK_STEP = 0.8
RASTER_FORMATS = ("PNG", "JPEG", "WEBP", "GIF")
PARTICIPANT_FORMATS = ("PNG", "JPEG", "WEBP")
MAX_RUN_BYTES = 2 * 1024 * MB
HEIC_BRANDS = {b"heic", b"heix", b"hevc", b"hevx", b"heim", b"heis", b"mif1", b"msf1", b"avif"}
# Decoders of unusual files fail in many ways, and none of them may become a server error.
UNREADABLE = (
    OSError,
    ValueError,
    SyntaxError,
    EOFError,
    struct.error,
    Image.DecompressionBombError,
    MemoryError,
    KeyError,
    TypeError,
    IndexError,
)

Image.MAX_IMAGE_PIXELS = MAX_JPEG_PIXELS


def _not_an_image() -> ImageRefused:
    return ImageRefused(_("This file is not a usable image. Use PNG, JPEG, WebP, GIF or SVG."))


def _too_large(limit: int) -> ImageRefused:
    return ImageRefused(_("This file is too large. The limit is %(mb)s MB.") % {"mb": limit // MB})


def _refuse_entity(*_args: object) -> None:
    raise ValueError("an SVG may not declare entities")


def _refuse_internal_subset(
    _name: str, _system: str | None, _public: str | None, internal: bool
) -> None:
    """Drawing programs write a plain DOCTYPE, and the parser does not fetch what it names."""
    if internal:
        raise ValueError("an SVG may not declare its own document type rules")


def _check_svg(data: bytes) -> None:
    """Handlers inside the parser, so another text encoding cannot hide a declaration."""
    names: list[str] = []
    parser = expat.ParserCreate()
    parser.StartDoctypeDeclHandler = _refuse_internal_subset
    parser.EntityDeclHandler = _refuse_entity
    parser.StartElementHandler = lambda name, _attributes: names.append(name)
    try:
        parser.Parse(data, True)
    except (expat.ExpatError, ValueError, LookupError) as exc:
        raise _not_an_image() from exc
    if not names or names[0].rsplit(":", 1)[-1] != "svg":
        raise _not_an_image()


def _looks_like_heic(data: bytes) -> bool:
    return data[4:8] == b"ftyp" and data[8:12] in HEIC_BRANDS


def _looks_like_markup(data: bytes) -> bool:
    start = data[:256].lstrip(b"\xef\xbb\xbf\xff\xfe\x00 \t\r\n")
    return start.startswith((b"<", b"<\x00"))


def _open(data: bytes) -> Image.Image:
    try:
        image = Image.open(io.BytesIO(data), formats=RASTER_FORMATS)
    except (UnidentifiedImageError, *UNREADABLE, Image.DecompressionBombWarning) as exc:
        raise _not_an_image() from exc
    limit = MAX_JPEG_PIXELS if image.format == "JPEG" else MAX_PIXELS
    if image.width * image.height > limit:
        raise _not_an_image()
    return image


def _compressed(image: Image.Image) -> bytes:
    """Quality falls step by step, then the dimensions."""
    while True:
        for quality in QUALITY_STEPS:
            buffer = io.BytesIO()
            image.save(buffer, "WEBP", quality=quality, method=4)
            if buffer.tell() <= MAX_STORED_BYTES:
                return buffer.getvalue()
        if max(image.size) <= MIN_SIDE:
            raise _not_an_image()
        width, height = image.size
        image = image.resize((max(1, int(width * SHRINK_STEP)), max(1, int(height * SHRINK_STEP))))


def _to_webp(image: Image.Image) -> bytes:
    """Saving from pixels drops EXIF and any other metadata. Shrinking first saves memory."""
    try:
        image.draft("RGB", (MAX_SIDE, MAX_SIDE))
        has_alpha = image.mode in ("RGBA", "LA", "PA") or "transparency" in image.info
        target = "RGBA" if has_alpha else "RGB"
        converted = image if image.mode == target else image.convert(target)
        converted.thumbnail((MAX_SIDE, MAX_SIDE))
        converted.info["exif"] = image.info.get("exif", b"")
        upright = ImageOps.exif_transpose(converted)
        upright.info.pop("exif", None)
        return _compressed(upright)
    except UNREADABLE as exc:
        raise _not_an_image() from exc


def _verified_gif(image: Image.Image, data: bytes) -> bytes:
    """Stored unchanged, so every frame is decoded here to find a damaged file."""
    if len(data) > MAX_SVG_GIF_BYTES:
        raise _too_large(MAX_SVG_GIF_BYTES)
    try:
        if getattr(image, "n_frames", 1) > MAX_GIF_FRAMES:
            raise _not_an_image()
        for frame in range(getattr(image, "n_frames", 1)):
            image.seek(frame)
            image.load()
    except UNREADABLE as exc:
        raise _not_an_image() from exc
    return data


def _heic_refused() -> ImageRefused:
    return ImageRefused(
        _("HEIC photos cannot be used. Save the photo as JPEG on the phone and upload it again.")
    )


def _participant_photo(data: bytes) -> bytes:
    """From the public, so never a kind of file that can carry a script or stay unchanged."""
    if len(data) > MAX_RASTER_BYTES:
        raise _too_large(MAX_RASTER_BYTES)
    if _looks_like_heic(data):
        raise _heic_refused()
    try:
        if _looks_like_markup(data):
            raise _not_an_image()
        image = _open(data)
        if image.format not in PARTICIPANT_FORMATS:
            raise _not_an_image()
        return _to_webp(image)
    except ImageRefused as exc:
        raise ImageRefused(_("This file is not a usable photo. Use PNG, JPEG or WebP.")) from exc


def _prepared(data: bytes) -> tuple[bytes, str, str]:
    """The bytes to store, their type and file extension."""
    if len(data) > MAX_RASTER_BYTES:
        raise _too_large(MAX_RASTER_BYTES)
    if _looks_like_heic(data):
        raise _heic_refused()
    if _looks_like_markup(data):
        if len(data) > MAX_SVG_GIF_BYTES:
            raise _too_large(MAX_SVG_GIF_BYTES)
        _check_svg(data)
        return data, "image/svg+xml", "svg"
    image = _open(data)
    if image.format == "GIF":
        return _verified_gif(image, data), "image/gif", "gif"
    return _to_webp(image), "image/webp", "webp"


def _usable(data: bytes) -> bool:
    """Opens the file as an upload would, without the work of storing it."""
    try:
        if _looks_like_markup(data):
            _check_svg(data)
        else:
            _open(data)
    except ImageRefused:
        return False
    return True


def _remove_unsaved(path: Path) -> None:
    """A file nothing points to is removed; the error that caused it stays."""
    try:
        path.unlink(missing_ok=True)
    except OSError as error:
        logger.warning("An unsaved media file could not be removed: %s", type(error).__name__)


class LocalMediaStorage:
    id = "local"

    def store_image(self, data: bytes) -> str:
        content, mime_type, extension = _prepared(data)
        return self._saved(content, mime_type, extension, private=False)

    def store_participant_image(self, data: bytes, *, run_assets: Sequence[str]) -> str:
        content = _participant_photo(data)
        used = MediaAsset.objects.filter(pk__in=run_assets).aggregate(total=Sum("size"))["total"]
        if (used or 0) + len(content) > MAX_RUN_BYTES:
            raise ImageRefused(_("This run cannot take any more photos."))
        return self._saved(content, "image/webp", "webp", private=True)

    def check_participant_image(self, data: bytes) -> None:
        _participant_photo(data)

    def delete_image(self, asset_id: str) -> None:
        asset = self._asset(asset_id)
        if asset is None:
            return
        (Path(settings.KVZ_MEDIA_PATH) / asset.storage_key).unlink(missing_ok=True)
        asset.delete()

    def private_assets_older_than(self, cutoff: datetime) -> Sequence[str]:
        ids = MediaAsset.objects.filter(private=True, created_at__lt=cutoff).values_list(
            "pk", flat=True
        )
        return [str(asset_id) for asset_id in ids]

    def _saved(self, content: bytes, mime_type: str, extension: str, *, private: bool) -> str:
        asset = MediaAsset(
            mime_type=mime_type,
            size=len(content),
            sha256=hashlib.sha256(content).hexdigest(),
            private=private,
        )
        asset.storage_key = f"{asset.id}.{extension}"
        directory = Path(settings.KVZ_MEDIA_PATH)
        directory.mkdir(parents=True, exist_ok=True)
        target = directory / asset.storage_key
        temporary = tempfile.NamedTemporaryFile(dir=directory, delete=False)
        try:
            with temporary:
                temporary.write(content)
            os.chmod(temporary.name, 0o640)
            os.replace(temporary.name, target)
        except BaseException:
            _remove_unsaved(Path(temporary.name))
            raise
        try:
            asset.save()
        except BaseException:
            _remove_unsaved(target)
            raise
        return str(asset.id)

    def check_image_address(self, url: str) -> None:
        try:
            remote.check_address(url)
        except remote.RemoteRefused as exc:
            raise ImageAddressInvalid(
                _("Enter a whole address starting with https://, with no login in it.")
            ) from exc

    def fetch_image(self, url: str, *, allow_internal: bool, deadline: float) -> str:
        """A fetched image goes through everything an uploaded one does."""
        self.check_image_address(url)
        try:
            data = remote.fetch(
                url,
                allow_internal=allow_internal,
                timeout=min(FETCH_SECONDS, deadline - time.monotonic()),
                max_bytes=MAX_RASTER_BYTES,
            )
        except remote.RemoteInternal as exc:
            raise ImageRefused(
                _("This address is in an internal network, which the settings do not allow.")
            ) from exc
        except remote.RemoteRefused as exc:
            raise ImageRefused(_("The image could not be fetched from this address.")) from exc
        return self.store_image(data)

    def _reachable(self, url: str, allow_internal: bool, timeout: float) -> bool:
        try:
            data = remote.fetch(
                url, allow_internal=allow_internal, timeout=timeout, max_bytes=MAX_RASTER_BYTES
            )
        except remote.RemoteRefused:
            return False
        return _usable(data)

    def check_addresses(
        self,
        urls: Sequence[str],
        *,
        allow_internal: bool,
        per_address: float = 3.0,
        total: float = 10.0,
        max_age: timedelta = timedelta(hours=1),
    ) -> None:
        deadline = time.monotonic() + total
        fresh = set(
            AddressCheck.objects.filter(
                address__in=urls, checked_at__gt=timezone.now() - max_age
            ).values_list("address", flat=True)
        )
        for url in urls:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            if url not in fresh:
                ok = self._reachable(url, allow_internal, min(per_address, remaining))
                AddressCheck.objects.update_or_create(
                    address=url, defaults={"ok": ok, "checked_at": timezone.now()}
                )

    def address_status(self, urls: Sequence[str]) -> Mapping[str, AddressStatus]:
        return {
            check.address: AddressStatus(check.ok, check.checked_at)
            for check in AddressCheck.objects.filter(address__in=urls)
        }

    def _asset(self, asset_id: str) -> MediaAsset | None:
        try:
            return MediaAsset.objects.filter(pk=UUID(str(asset_id))).first()
        except ValueError:
            return None

    def exists(self, asset_id: str) -> bool:
        return self._asset(asset_id) is not None

    def load(self, asset_id: str) -> StoredImage | None:
        asset = self._asset(asset_id)
        if asset is None:
            return None
        path = Path(settings.KVZ_MEDIA_PATH) / asset.storage_key
        return StoredImage(str(path), asset.mime_type, asset.private) if path.is_file() else None
