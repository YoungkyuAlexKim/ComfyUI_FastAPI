"""Browser principal management.

The application historically used a caller-controlled ``anon_id`` cookie as
both the browser identity and the storage directory name.  This module keeps
those stable IDs for backwards compatibility, but adds strict validation and a
server-signed session cookie.  ``PRINCIPAL_IDENTITY_MODE=enforced`` disables
the legacy unsigned-cookie bridge after the migration window.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
from pathlib import Path
import re
import secrets
import uuid
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from fastapi import Request, WebSocket
    from starlette.responses import Response


ANON_COOKIE_NAME = "anon_id"
ANON_COOKIE_PREFIX = "anon-"
PRINCIPAL_COOKIE_NAME = "lc_principal"
_PRINCIPAL_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$")
_COOKIE_VERSION = "v1"


def _parse_bool(val: str | None, default: bool = False) -> bool:
    if val is None:
        return default
    return val.strip().lower() in ("1", "true", "yes", "on")


def validate_principal_id(value: object) -> Optional[str]:
    """Return a storage-safe principal ID, or ``None`` when invalid.

    The same validator is used at every filesystem and authorization boundary.
    In particular, path separators, dots, whitespace and control characters
    are never accepted.
    """

    if not isinstance(value, str):
        return None
    candidate = value.strip()
    if not candidate or not _PRINCIPAL_PATTERN.fullmatch(candidate):
        return None
    return candidate


def require_principal_id(value: object) -> str:
    principal_id = validate_principal_id(value)
    if principal_id is None:
        raise ValueError("Invalid principal ID")
    return principal_id


def _identity_mode() -> str:
    mode = str(os.getenv("PRINCIPAL_IDENTITY_MODE", "compat") or "compat").strip().lower()
    return mode if mode in {"compat", "enforced"} else "compat"


def _secret_file_path() -> Path:
    configured = str(os.getenv("PRINCIPAL_COOKIE_SECRET_FILE", "") or "").strip()
    return Path(configured or "db/principal_cookie.secret")


def _load_cookie_secret() -> bytes:
    configured = str(os.getenv("PRINCIPAL_COOKIE_SECRET", "") or "").strip()
    if configured:
        return configured.encode("utf-8")

    path = _secret_file_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        raw = path.read_bytes().strip()
        if len(raw) >= 32:
            return raw
    except FileNotFoundError:
        pass

    raw = secrets.token_bytes(48)
    tmp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        tmp.write_bytes(raw)
        try:
            os.chmod(tmp, 0o600)
        except OSError:
            pass
        os.replace(tmp, path)
    finally:
        try:
            if tmp.exists():
                tmp.unlink()
        except OSError:
            pass
    return raw


def _b64encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _b64decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + ("=" * (-len(value) % 4)))


def _signed_cookie_value(principal_id: str) -> str:
    safe_id = require_principal_id(principal_id)
    payload = _b64encode(safe_id.encode("utf-8"))
    signed = f"{_COOKIE_VERSION}.{payload}"
    signature = hmac.new(_load_cookie_secret(), signed.encode("ascii"), hashlib.sha256).digest()
    return f"{signed}.{_b64encode(signature)}"


def _principal_from_signed_cookie(value: object) -> Optional[str]:
    if not isinstance(value, str):
        return None
    try:
        version, payload, encoded_signature = value.split(".", 2)
        if version != _COOKIE_VERSION:
            return None
        signed = f"{version}.{payload}"
        expected = hmac.new(_load_cookie_secret(), signed.encode("ascii"), hashlib.sha256).digest()
        supplied = _b64decode(encoded_signature)
        if not hmac.compare_digest(expected, supplied):
            return None
        principal_id = _b64decode(payload).decode("utf-8")
    except (ValueError, UnicodeError):
        return None
    return validate_principal_id(principal_id)


def _legacy_principal_from_cookies(cookies: object) -> Optional[str]:
    if _identity_mode() != "compat":
        return None
    try:
        value = cookies.get(ANON_COOKIE_NAME)
    except Exception:
        return None
    principal_id = validate_principal_id(value)
    if principal_id and principal_id.startswith(ANON_COOKIE_PREFIX):
        return principal_id
    return None


def _principal_from_cookie_jar(cookies: object) -> Optional[str]:
    try:
        signed = cookies.get(PRINCIPAL_COOKIE_NAME)
    except Exception:
        signed = None
    return _principal_from_signed_cookie(signed) or _legacy_principal_from_cookies(cookies)


def _new_browser_principal() -> str:
    return ANON_COOKIE_PREFIX + uuid.uuid4().hex


def _get_anon_id_from_request(req: "Request") -> str:
    """Resolve the browser principal prepared by middleware or cookies."""

    try:
        state_value = validate_principal_id(getattr(req.state, "principal_id", None))
        if state_value:
            return state_value
    except Exception:
        pass

    principal_id = _principal_from_cookie_jar(req.cookies)
    if principal_id:
        return principal_id

    # The old X-Anon-Id escape hatch is disabled by default because it lets a
    # caller impersonate any known owner.  It exists only for a short, explicit
    # compatibility window if a deployment truly needs it.
    if _parse_bool(os.getenv("ALLOW_LEGACY_ANON_HEADER"), False) and _identity_mode() == "compat":
        try:
            header_id = validate_principal_id(req.headers.get("x-anon-id"))
        except Exception:
            header_id = None
        if header_id and header_id.startswith(ANON_COOKIE_PREFIX):
            return header_id

    return _new_browser_principal()


def _get_anon_id_from_ws(websocket: "WebSocket") -> str:
    return _principal_from_cookie_jar(websocket.cookies) or _new_browser_principal()


def _cookie_is_secure(req: "Request") -> bool:
    secure_cookie_env = _parse_bool(os.getenv("COOKIE_SECURE"), False)
    try:
        xf_proto = (req.headers.get("x-forwarded-proto") or "").split(",")[0].strip().lower()
    except Exception:
        xf_proto = ""
    is_https = (getattr(getattr(req, "url", None), "scheme", "") == "https") or xf_proto == "https"
    return bool(secure_cookie_env and is_https)


def _set_principal_cookies(req: "Request", resp: "Response", principal_id: str) -> None:
    safe_id = require_principal_id(principal_id)
    common = {
        "httponly": True,
        "samesite": "lax",
        "secure": _cookie_is_secure(req),
        "max_age": 60 * 60 * 24 * 180,
    }
    # Keep anon_id temporarily because the current frontend embeds it for the
    # WebSocket UI.  Authorization uses the signed cookie first.
    resp.set_cookie(key=ANON_COOKIE_NAME, value=safe_id, **common)
    resp.set_cookie(key=PRINCIPAL_COOKIE_NAME, value=_signed_cookie_value(safe_id), **common)


def _ensure_anon_id_cookie(req: "Request", resp: "Response", preferred_id: str | None = None) -> str:
    existing = _principal_from_cookie_jar(req.cookies)
    principal_id = existing or validate_principal_id(preferred_id) or _new_browser_principal()
    _set_principal_cookies(req, resp, principal_id)
    return principal_id


def prepare_request_principal(req: "Request") -> tuple[str, bool]:
    """Resolve/create a principal before routing.

    Returns ``(principal_id, needs_cookie_upgrade)``.  The caller should set
    both cookies on the response when the second value is true.
    """

    signed_id = None
    signed_cookie_present = False
    try:
        signed_cookie = req.cookies.get(PRINCIPAL_COOKIE_NAME)
        signed_cookie_present = bool(signed_cookie)
        signed_id = _principal_from_signed_cookie(signed_cookie)
    except Exception:
        pass
    raw_legacy_id = None
    try:
        candidate = validate_principal_id(req.cookies.get(ANON_COOKIE_NAME))
        if candidate and candidate.startswith(ANON_COOKIE_PREFIX):
            raw_legacy_id = candidate
    except Exception:
        pass
    legacy_id = _legacy_principal_from_cookies(req.cookies) if signed_id is None else None
    principal_id = signed_id or legacy_id or _new_browser_principal()
    req.state.principal_id = principal_id
    if signed_id:
        identity_source = "signed_cookie"
    elif legacy_id:
        identity_source = "legacy_cookie"
    elif signed_cookie_present:
        identity_source = "invalid_signed_cookie"
    elif raw_legacy_id and _identity_mode() == "enforced":
        identity_source = "legacy_cookie_rejected"
    else:
        identity_source = "new_principal"
    req.state.principal_identity_source = identity_source
    return principal_id, signed_id != principal_id
