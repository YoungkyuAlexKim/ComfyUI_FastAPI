"""
사용자 인증 및 익명 사용자 관리 모듈
"""
import uuid
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fastapi import Request
    from fastapi.responses import HTMLResponse
    from fastapi import WebSocket

# --- Anonymous user ID helpers ---
ANON_COOKIE_NAME = "anon_id"
ANON_COOKIE_PREFIX = "anon-"

def _ensure_anon_id_cookie(req: "Request", resp: "HTMLResponse") -> str:
    """익명 사용자 ID 쿠키를 보장하고 반환합니다."""
    existing = req.cookies.get(ANON_COOKIE_NAME)
    if existing and isinstance(existing, str) and existing.startswith(ANON_COOKIE_PREFIX):
        return existing
    new_id = ANON_COOKIE_PREFIX + uuid.uuid4().hex
    # ~180 days
    max_age = 60 * 60 * 24 * 180
    resp.set_cookie(
        key=ANON_COOKIE_NAME,
        value=new_id,
        httponly=True,
        samesite="lax",
        secure=False,
        max_age=max_age,
    )
    return new_id

def _get_anon_id_from_request(req: "Request") -> str:
    """HTTP 요청에서 익명 사용자 ID를 추출합니다."""
    value = req.cookies.get(ANON_COOKIE_NAME)
    if value and isinstance(value, str) and value.startswith(ANON_COOKIE_PREFIX):
        return value
    # Fallback anonymous namespace when no cookie is present (should be rare for API calls)
    return ANON_COOKIE_PREFIX + "guest"

def _get_anon_id_from_ws(websocket: "WebSocket") -> str:
    """WebSocket에서 익명 사용자 ID를 추출합니다."""
    value = websocket.cookies.get(ANON_COOKIE_NAME)
    if value and isinstance(value, str) and value.startswith(ANON_COOKIE_PREFIX):
        return value
    return ANON_COOKIE_PREFIX + "guest"
