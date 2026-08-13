"""Shared validation and registration for browser and MCP image attachments."""

from __future__ import annotations

import base64
from dataclasses import dataclass
from io import BytesIO
import os
import re
from threading import RLock
from typing import Any

from ..config import UPLOAD_CONFIG
from .asset_service import AssetService

try:
    from PIL import Image, ImageOps
except Exception:
    Image = None
    ImageOps = None


_ALLOWED_FORMATS = {"PNG", "JPEG", "WEBP"}
_ALLOWED_MIME_TYPES = {"image/png", "image/jpeg", "image/webp"}
_EXTENSION_BY_FORMAT = {"PNG": ".png", "JPEG": ".jpg", "WEBP": ".webp"}
_DATA_URL_PATTERN = re.compile(r"^data:(image/(?:png|jpeg|webp));base64,(.*)$", re.IGNORECASE | re.DOTALL)
_DEDUPLICATED_REGISTRATION_LOCK = RLock()


class InputAssetError(ValueError):
    def __init__(self, code: str, message: str, *, status_code: int = 400):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


@dataclass(frozen=True)
class NormalizedInputImage:
    png_bytes: bytes
    original_filename: str
    source_mime_type: str
    width: int
    height: int
    sha256: str


def input_max_bytes() -> int:
    return max(1, int(UPLOAD_CONFIG.get("inputs_max_bytes", 10 * 1024 * 1024)))


def input_max_pixels() -> int:
    return max(1, int(UPLOAD_CONFIG.get("inputs_max_pixels", 40_000_000)))


def input_base64_max_characters() -> int:
    return ((input_max_bytes() + 2) // 3) * 4 + 128


def _safe_filename(filename: str | None, fallback_extension: str) -> str:
    name = str(filename or "").replace("\\", "/").rsplit("/", 1)[-1].strip()
    if not name or name in {".", ".."}:
        return f"upload{fallback_extension}"
    name = "".join(ch for ch in name if ch >= " " and ch not in {"/", "\\"}).strip()
    if not name:
        return f"upload{fallback_extension}"
    stem, extension = os.path.splitext(name)
    if not stem:
        stem = "upload"
    if extension.lower() not in {".png", ".jpg", ".jpeg", ".webp"}:
        extension = fallback_extension
    return f"{stem[:180]}{extension.lower()}"


def decode_base64_image(value: str) -> tuple[bytes, str | None]:
    encoded = str(value or "").strip()
    data_url_mime: str | None = None
    match = _DATA_URL_PATTERN.fullmatch(encoded)
    if match:
        data_url_mime = match.group(1).lower()
        encoded = match.group(2)
    encoded = "".join(encoded.split())
    if not encoded:
        raise InputAssetError("empty_image", "Image attachment is empty")
    if len(encoded) > input_base64_max_characters():
        raise InputAssetError(
            "image_too_large",
            f"Image attachment exceeds the {input_max_bytes()} byte input limit",
            status_code=413,
        )
    try:
        raw = base64.b64decode(encoded, validate=True)
    except Exception as exc:
        raise InputAssetError("invalid_base64", "Image attachment is not valid base64") from exc
    return raw, data_url_mime


def normalize_input_image(
    raw_bytes: bytes,
    *,
    filename: str | None,
    content_type: str | None,
) -> NormalizedInputImage:
    if not isinstance(raw_bytes, bytes) or not raw_bytes:
        raise InputAssetError("empty_image", "Image attachment is empty")
    max_bytes = input_max_bytes()
    if len(raw_bytes) > max_bytes:
        raise InputAssetError(
            "image_too_large",
            f"Image attachment exceeds the {max_bytes} byte input limit",
            status_code=413,
        )
    declared_mime = str(content_type or "").split(";", 1)[0].strip().lower()
    if declared_mime and declared_mime not in _ALLOWED_MIME_TYPES:
        raise InputAssetError("unsupported_image_type", "Only PNG, JPEG, and WEBP images are supported")
    if Image is None:
        raise InputAssetError("image_decoder_unavailable", "Server image decoding is unavailable", status_code=503)

    try:
        with Image.open(BytesIO(raw_bytes)) as source:
            source_format = str(source.format or "").upper()
            if source_format not in _ALLOWED_FORMATS:
                raise InputAssetError("unsupported_image_type", "Only PNG, JPEG, and WEBP images are supported")
            actual_mime = f"image/{'jpeg' if source_format == 'JPEG' else source_format.lower()}"
            if declared_mime and declared_mime != actual_mime:
                raise InputAssetError("mime_type_mismatch", "Declared mime type does not match image content")
            width, height = source.size
            if width < 1 or height < 1 or width * height > input_max_pixels():
                raise InputAssetError(
                    "image_dimensions_too_large",
                    f"Image dimensions exceed the {input_max_pixels()} pixel limit",
                    status_code=413,
                )
            source.load()
            if ImageOps is not None:
                source = ImageOps.exif_transpose(source)
            has_alpha = source.mode in ("RGBA", "LA") or (
                source.mode == "P" and "transparency" in (source.info or {})
            )
            normalized = source.convert("RGBA" if has_alpha else "RGB")
            width, height = normalized.size
            out = BytesIO()
            normalized.save(out, format="PNG")
            png_bytes = out.getvalue()
    except InputAssetError:
        raise
    except Exception as exc:
        raise InputAssetError("invalid_image", "Image attachment is corrupt or unreadable") from exc

    if len(png_bytes) > max_bytes:
        raise InputAssetError(
            "normalized_image_too_large",
            f"Normalized PNG exceeds the {max_bytes} byte input limit",
            status_code=413,
        )
    import hashlib

    return NormalizedInputImage(
        png_bytes=png_bytes,
        original_filename=_safe_filename(filename, _EXTENSION_BY_FORMAT[source_format]),
        source_mime_type=declared_mime or actual_mime,
        width=width,
        height=height,
        sha256=hashlib.sha256(png_bytes).hexdigest(),
    )


def register_input_image(
    asset_service: AssetService,
    owner_id: str,
    raw_bytes: bytes,
    *,
    filename: str | None,
    content_type: str | None,
    deduplicate: bool = False,
) -> tuple[dict[str, Any], bool]:
    normalized = normalize_input_image(raw_bytes, filename=filename, content_type=content_type)
    if not deduplicate:
        row = asset_service.create_input_image(
            owner_id,
            normalized.png_bytes,
            normalized.original_filename,
        )
        return row, False

    # MCP retries can arrive concurrently. Keep the lookup-and-create pair in
    # one process-local critical section so a single server process does not
    # create duplicate active inputs for the same normalized content.
    with _DEDUPLICATED_REGISTRATION_LOCK:
        existing = asset_service.find_active_by_sha256(
            owner_id,
            normalized.sha256,
            kinds=("input",),
        )
        if existing is not None:
            path = asset_service.resolve_storage_path(existing.get("storage_path"))
            if path and os.path.isfile(path):
                return existing, True
        row = asset_service.create_input_image(
            owner_id,
            normalized.png_bytes,
            normalized.original_filename,
        )
        return row, False
