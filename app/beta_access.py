import hashlib
import os
from typing import Optional


DEFAULT_BETA_COOKIE_NAME = "beta_auth"


def beta_password() -> Optional[str]:
    pw = os.getenv("BETA_PASSWORD")
    if pw is None:
        return None
    pw = pw.strip()
    return pw or None


def beta_enabled() -> bool:
    return beta_password() is not None


def beta_cookie_name() -> str:
    name = os.getenv("BETA_COOKIE_NAME", DEFAULT_BETA_COOKIE_NAME)
    name = (name or "").strip()
    return name or DEFAULT_BETA_COOKIE_NAME


def _token_for_password(pw: str) -> str:
    # Bearer-like token derived from the shared password.
    # This is not meant to be "high security" auth—just a simple beta gate.
    data = f"beta_gate:v1:{pw}".encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def expected_cookie_value() -> Optional[str]:
    pw = beta_password()
    if not pw:
        return None
    return _token_for_password(pw)


def is_request_authed(cookies: dict) -> bool:
    if not beta_enabled():
        return True
    try:
        name = beta_cookie_name()
        expected = expected_cookie_value()
        got = cookies.get(name)
        return bool(expected) and isinstance(got, str) and got == expected
    except Exception:
        return False


