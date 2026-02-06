import base64
import os
from typing import Any, Dict, List, Optional, Tuple

import requests

from ..logging_utils import setup_logging


logger = setup_logging()


class NanoBananaUpstreamError(RuntimeError):
    """
    User-facing upstream error wrapper for NanoBanana(Google).

    - public_message: safe to show to end users
    - kind: machine-readable classification for ops/analytics
    - http_status/upstream_status/reason: best-effort upstream details
    """

    def __init__(
        self,
        public_message: str,
        *,
        kind: str,
        http_status: Optional[int] = None,
        upstream_status: Optional[str] = None,
        reason: Optional[str] = None,
        upstream_message: Optional[str] = None,
        retry_after: Optional[str] = None,
    ):
        super().__init__(public_message)
        self.public_message = public_message
        self.kind = str(kind or "nanobanana_unknown")
        self.http_status = int(http_status) if isinstance(http_status, int) else None
        self.upstream_status = upstream_status
        self.reason = reason
        self.upstream_message = upstream_message
        self.retry_after = retry_after


def _get_api_key() -> str:
    api_key = os.getenv("GOOGLE_AI_STUDIO_API_KEY") or os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError(
            "나노바나나(Google) 기능을 사용하려면 API 키가 필요합니다. "
            "서버 .env(또는 환경변수)에 GOOGLE_AI_STUDIO_API_KEY 또는 GEMINI_API_KEY를 설정한 뒤 서버를 재시작해 주세요."
        )
    return api_key


def _looks_like_key_issue(http_status: int, detail: Optional[str], err_status: Optional[str], err_reason: Optional[str]) -> bool:
    low = str(detail or "").lower()
    reason = str(err_reason or "").upper()
    status_txt = str(err_status or "").upper()
    if http_status in (401, 403):
        return True
    if "api key" in low or "apikey" in low or "api_key" in low:
        return True
    if "key not valid" in low or "invalid api key" in low or "invalid api-key" in low:
        return True
    if "permission" in low or "unauth" in low or "forbidden" in low:
        return True
    if "billing" in low:
        return True
    if reason in (
        "API_KEY_INVALID",
        "API_KEY_EXPIRED",
        "API_KEY_SERVICE_BLOCKED",
        "API_KEY_HTTP_REFERRER_BLOCKED",
        "API_KEY_IP_ADDRESS_BLOCKED",
    ):
        return True
    if status_txt in ("PERMISSION_DENIED", "UNAUTHENTICATED"):
        return True
    return False


def _looks_like_quota_issue(http_status: int, detail: Optional[str], err_status: Optional[str]) -> bool:
    low = str(detail or "").lower()
    status_txt = str(err_status or "").upper()
    if http_status == 429:
        return True
    if "quota" in low or "rate limit" in low or "resource exhausted" in low:
        return True
    if status_txt == "RESOURCE_EXHAUSTED":
        return True
    return False


def _parse_google_error(resp: requests.Response) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    """
    Returns (detail_message, err_status, err_reason) best-effort.
    """
    detail = None
    err_status = None
    err_reason = None
    try:
        data = resp.json()
        err = (data.get("error") or {}) if isinstance(data, dict) else {}
        if isinstance(err, dict):
            detail = err.get("message")
            err_status = err.get("status")
            try:
                details = err.get("details") or []
                if isinstance(details, list):
                    for d in details:
                        if not isinstance(d, dict):
                            continue
                        r = d.get("reason")
                        if isinstance(r, str) and r:
                            err_reason = r
                            break
                        r2 = d.get("reason") or (d.get("metadata") or {}).get("reason")
                        if isinstance(r2, str) and r2:
                            err_reason = r2
                            break
            except Exception:
                err_reason = None
    except Exception:
        detail = None
        err_status = None
        err_reason = None
    return detail, err_status, err_reason


def _classify_google_error(
    http_status: int,
    detail: Optional[str],
    err_status: Optional[str],
    err_reason: Optional[str],
) -> Tuple[str, str]:
    """
    Returns (kind, public_message).
    kind is used for ops/admin analytics and should be stable.
    """
    low = str(detail or "").lower()
    status_txt = str(err_status or "").upper()
    reason = str(err_reason or "").upper()

    # 1) Auth/billing/config issues (operator action)
    if _looks_like_key_issue(http_status, detail, err_status, err_reason):
        return (
            "nanobanana_auth",
            "나노바나나(구글) 연결 설정에 문제가 있어요. 운영자에게 문의해 주세요. "
            "(서버: GOOGLE_AI_STUDIO_API_KEY/GEMINI_API_KEY 및 권한/결제 상태 확인 필요)",
        )

    # 2) Quota / rate limit (user can retry later)
    # Google often uses RESOURCE_EXHAUSTED for both per-minute and daily quota.
    if _looks_like_quota_issue(http_status, detail, err_status) or status_txt == "RESOURCE_EXHAUSTED" or reason in (
        "RATE_LIMIT_EXCEEDED",
        "RESOURCE_EXHAUSTED",
    ):
        looks_rate = False
        looks_daily = False
        try:
            if "per minute" in low or "per-minute" in low or "requests per minute" in low or "rpm" in low:
                looks_rate = True
            if "per day" in low or "per-day" in low or "daily" in low or "24 hour" in low or "24h" in low:
                looks_daily = True
        except Exception:
            looks_rate = False
            looks_daily = False

        if looks_daily and not looks_rate:
            return ("nanobanana_quota_exhausted", "오늘 나노바나나 생성 한도에 도달했어요. 내일 다시 시도해 주세요.")
        if looks_rate and not looks_daily:
            return ("nanobanana_rate_limited", "요청이 몰려 잠시 대기해야 해요. 30~60초 후 다시 시도해 주세요.")

        return ("nanobanana_rate_limited", "요청이 너무 많거나 사용량 한도에 도달했어요. 잠시 후 다시 시도해 주세요.")

    # 3) Invalid request (user input/workflow config)
    if http_status == 400:
        return ("nanobanana_bad_request", "요청 내용이 올바르지 않아요. 프롬프트를 조금 더 구체적으로 작성해 주세요.")

    # 4) Upstream instability
    if 500 <= int(http_status) <= 599:
        return ("nanobanana_upstream_unavailable", "지금은 구글 서버가 잠시 불안정해요. 잠시 후 다시 시도해 주세요.")

    # 5) Fallback
    return ("nanobanana_unknown", "나노바나나 처리 중 오류가 발생했어요. 잠시 후 다시 시도해 주세요.")


def _raise_google_error(resp: requests.Response, *, context: str) -> None:
    detail, err_status, err_reason = _parse_google_error(resp)
    s = int(getattr(resp, "status_code", 0) or 0)
    retry_after = None
    try:
        retry_after = resp.headers.get("Retry-After")
    except Exception:
        retry_after = None

    kind, msg = _classify_google_error(s, detail, err_status, err_reason)
    logger.warning(
        {
            "event": "nanobanana_bad_status",
            "context": str(context or ""),
            "kind": kind,
            "status": s,
            "upstream_status": err_status,
            "reason": err_reason,
            "retry_after": retry_after,
            "upstream_message": detail,
            "message": msg,
        }
    )
    raise NanoBananaUpstreamError(
        msg,
        kind=kind,
        http_status=s,
        upstream_status=err_status,
        reason=err_reason,
        upstream_message=detail,
        retry_after=retry_after,
    )


def _extract_first_image_bytes(data: Any) -> bytes:
    """
    Gemini generateContent 응답에서 첫 번째 이미지(inline_data/inlineData)를 찾아 bytes로 반환합니다.
    """
    try:
        if not isinstance(data, dict):
            raise RuntimeError("나노바나나 응답 형식이 올바르지 않습니다.")
        candidates = data.get("candidates")
        if not isinstance(candidates, list) or not candidates:
            raise RuntimeError("나노바나나 응답에서 candidates를 찾지 못했습니다.")
        content = (candidates[0] or {}).get("content")
        if not isinstance(content, dict):
            raise RuntimeError("나노바나나 응답에서 content를 찾지 못했습니다.")
        parts = content.get("parts")
        if not isinstance(parts, list) or not parts:
            raise RuntimeError("나노바나나 응답에서 parts를 찾지 못했습니다.")

        for p in parts:
            if not isinstance(p, dict):
                continue
            inline = p.get("inline_data") or p.get("inlineData")
            if not isinstance(inline, dict):
                continue
            b64 = inline.get("data")
            if isinstance(b64, str) and b64:
                try:
                    return base64.b64decode(b64)
                except Exception:
                    raise RuntimeError("나노바나나 이미지 데이터(base64)를 해석하지 못했습니다.")
        raise RuntimeError("나노바나나 응답에 이미지가 포함되어 있지 않습니다.")
    except RuntimeError:
        raise
    except Exception:
        raise RuntimeError("나노바나나 응답을 해석하지 못했습니다.")


def build_google_prompt(req: Any, wf_cfg: Dict[str, Any]) -> str:
    user_prompt = str(getattr(req, "user_prompt", "") or "").strip()
    if not user_prompt:
        raise RuntimeError("프롬프트가 비어 있습니다. 내용을 입력해 주세요.")

    style_prompt = str((wf_cfg or {}).get("style_prompt") or "").strip()
    style_pos = str((wf_cfg or {}).get("style_prompt_position") or "").strip().lower()
    negative_prompt = str((wf_cfg or {}).get("negative_prompt") or "").strip()

    if style_prompt:
        if style_pos == "prepend":
            merged = f"{style_prompt}\n\n{user_prompt}"
        else:
            merged = f"{user_prompt}\n\n{style_prompt}"
    else:
        merged = user_prompt

    if negative_prompt:
        # Prefer a non-negative phrasing for NanoBanana prompts.
        merged = f"{merged}\n\nKeep absent: {negative_prompt}"

    return merged.strip()


def _normalize_image_size(v: Optional[str]) -> Optional[str]:
    """
    Gemini REST docs: imageSize must use uppercase 'K' (e.g., "1K", "2K", "4K").
    """
    if v is None:
        return None
    s = str(v or "").strip()
    if not s:
        return None
    s = s.upper()
    # Accept "1k" => "1K" and reject unexpected values (best-effort safety)
    if s in ("1K", "2K", "4K"):
        return s
    return None


def generate_text_to_image(
    *,
    model: str,
    prompt: str,
    aspect_ratio: Optional[str] = None,
    image_size: Optional[str] = None,
    timeout: Tuple[float, float] = (5.0, 60.0),
) -> bytes:
    api_key = _get_api_key()
    model = str(model or "").strip()
    if not model:
        raise RuntimeError("나노바나나 모델 설정이 비어 있습니다. 서버 워크플로우 설정을 확인해 주세요.")

    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    # Build generation config (REST format)
    gen_cfg: Dict[str, Any] = {"responseModalities": ["TEXT", "IMAGE"]}
    try:
        img_cfg: Dict[str, Any] = {}
        if isinstance(aspect_ratio, str) and aspect_ratio.strip():
            img_cfg["aspectRatio"] = aspect_ratio.strip()
        size_norm = _normalize_image_size(image_size)
        if size_norm:
            img_cfg["imageSize"] = size_norm
        if img_cfg:
            gen_cfg["imageConfig"] = img_cfg
    except Exception:
        gen_cfg = {"responseModalities": ["TEXT", "IMAGE"]}
    try:
        resp = requests.post(
            url,
            params={"key": api_key},
            json={
                "contents": [{"role": "user", "parts": [{"text": prompt}]}],
                "generationConfig": gen_cfg,
            },
            timeout=timeout,
        )
    except Exception as e:
        logger.warning({"event": "nanobanana_upstream_error", "context": "txt2img", "error": str(e)})
        raise NanoBananaUpstreamError(
            "나노바나나(Google) 연결이 잠시 불안정해요. 잠시 후 다시 시도해 주세요.",
            kind="nanobanana_network",
            upstream_message=str(e),
        )

    if not resp.ok:
        _raise_google_error(resp, context="txt2img")

    try:
        data = resp.json()
    except Exception:
        raise RuntimeError("나노바나나 API 응답을 해석하지 못했습니다.")

    return _extract_first_image_bytes(data)


def generate_image_edit(
    *,
    model: str,
    prompt: str,
    images: List[bytes],
    aspect_ratio: Optional[str] = None,
    image_size: Optional[str] = None,
    timeout: Tuple[float, float] = (5.0, 90.0),
) -> bytes:
    """
    NanoBanana(Gemini) image-edit(img2img) 호출.

    - parts 구성: [ {text}, {inline_data(image/png)}, ... ]
    - images는 순서가 의미가 있으므로, 전달된 순서를 그대로 유지합니다.
    """
    api_key = _get_api_key()
    model = str(model or "").strip()
    if not model:
        raise RuntimeError("나노바나나 모델 설정이 비어 있습니다. 서버 워크플로우 설정을 확인해 주세요.")

    if not isinstance(images, list) or not images:
        raise RuntimeError("입력 이미지가 없습니다. 이미지를 1장 이상 선택해 주세요.")

    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"

    gen_cfg: Dict[str, Any] = {"responseModalities": ["TEXT", "IMAGE"]}
    try:
        img_cfg: Dict[str, Any] = {}
        if isinstance(aspect_ratio, str) and aspect_ratio.strip():
            img_cfg["aspectRatio"] = aspect_ratio.strip()
        size_norm = _normalize_image_size(image_size)
        if size_norm:
            img_cfg["imageSize"] = size_norm
        if img_cfg:
            gen_cfg["imageConfig"] = img_cfg
    except Exception:
        gen_cfg = {"responseModalities": ["TEXT", "IMAGE"]}

    parts: List[Dict[str, Any]] = [{"text": str(prompt or "")}]
    for b in images:
        if not isinstance(b, (bytes, bytearray)) or not b:
            continue
        parts.append(
            {
                "inline_data": {
                    "mime_type": "image/png",
                    "data": base64.b64encode(bytes(b)).decode("utf-8"),
                }
            }
        )

    if len(parts) <= 1:
        raise RuntimeError("입력 이미지 데이터가 비어 있습니다. 다른 이미지를 다시 선택해 주세요.")

    try:
        resp = requests.post(
            url,
            params={"key": api_key},
            json={
                "contents": [{"role": "user", "parts": parts}],
                "generationConfig": gen_cfg,
            },
            timeout=timeout,
        )
    except Exception as e:
        logger.warning({"event": "nanobanana_upstream_error", "context": "imgedit", "error": str(e)})
        raise NanoBananaUpstreamError(
            "나노바나나(Google) 연결이 잠시 불안정해요. 잠시 후 다시 시도해 주세요.",
            kind="nanobanana_network",
            upstream_message=str(e),
        )

    if not resp.ok:
        _raise_google_error(resp, context="imgedit")

    try:
        data = resp.json()
    except Exception:
        raise RuntimeError("나노바나나 API 응답을 해석하지 못했습니다.")

    return _extract_first_image_bytes(data)

