import base64
import os
from typing import Any, Dict, List, Optional, Tuple

import requests

from ..logging_utils import setup_logging


logger = setup_logging()

DEFAULT_BASE_URL = "https://openrouter.ai/api/v1"
DEFAULT_TEXT_MODEL = "google/gemini-3.1-flash-lite"


class OpenRouterUpstreamError(RuntimeError):
    """Safe, classified OpenRouter error for UI and operations logging."""

    def __init__(
        self,
        public_message: str,
        *,
        kind: str,
        http_status: Optional[int] = None,
        upstream_code: Optional[str] = None,
        upstream_message: Optional[str] = None,
        retry_after: Optional[str] = None,
    ):
        super().__init__(public_message)
        self.public_message = public_message
        self.kind = str(kind or "openrouter_unknown")
        self.http_status = int(http_status) if isinstance(http_status, int) else None
        self.upstream_code = upstream_code
        self.upstream_message = upstream_message
        self.retry_after = retry_after


def is_configured() -> bool:
    return bool(str(os.getenv("OPENROUTER_API_KEY") or "").strip())


def _get_api_key() -> str:
    api_key = str(os.getenv("OPENROUTER_API_KEY") or "").strip()
    if not api_key:
        raise RuntimeError(
            "OpenRouter 기능을 사용하려면 API 키가 필요합니다. "
            "서버 .env에 OPENROUTER_API_KEY를 설정한 뒤 서버를 재시작해 주세요."
        )
    return api_key


def _base_url() -> str:
    return str(os.getenv("OPENROUTER_BASE_URL") or DEFAULT_BASE_URL).strip().rstrip("/")


def _headers() -> Dict[str, str]:
    headers = {
        "Authorization": f"Bearer {_get_api_key()}",
        "Content-Type": "application/json",
    }
    site_url = str(os.getenv("OPENROUTER_SITE_URL") or "").strip()
    app_name = str(os.getenv("OPENROUTER_APP_NAME") or "LC AI Canvas").strip()
    if site_url:
        headers["HTTP-Referer"] = site_url
    if app_name:
        headers["X-Title"] = app_name
    return headers


def _provider_preferences(*, require_parameters: bool) -> Dict[str, Any]:
    prefs: Dict[str, Any] = {
        "data_collection": "deny",
        "require_parameters": bool(require_parameters),
    }
    # Nano Banana Pro currently has a ZDR-capable route. This can be disabled
    # later for a model that has no ZDR route (for example via OPENROUTER_ZDR=false).
    zdr = str(os.getenv("OPENROUTER_ZDR", "true") or "true").strip().lower()
    prefs["zdr"] = zdr not in ("0", "false", "no", "off")
    return prefs


def _parse_error(resp: requests.Response) -> Tuple[Optional[str], Optional[str]]:
    try:
        data = resp.json()
    except Exception:
        return None, None
    err = data.get("error") if isinstance(data, dict) else None
    if not isinstance(err, dict):
        return None, None
    code = err.get("code")
    message = err.get("message")
    return (str(code) if code is not None else None, str(message) if message else None)


def _raise_for_response(resp: requests.Response, *, context: str) -> None:
    status = int(getattr(resp, "status_code", 0) or 0)
    code, detail = _parse_error(resp)
    low = str(detail or "").lower()
    retry_after = None
    try:
        retry_after = resp.headers.get("Retry-After")
    except Exception:
        pass

    if status in (401, 403):
        kind = "openrouter_auth"
        message = "OpenRouter 연결 설정에 문제가 있어요. 운영자에게 문의해 주세요."
    elif status == 402 or "credit" in low or "balance" in low:
        kind = "openrouter_credits_exhausted"
        message = "OpenRouter 사용 크레딧이 부족해요. 운영자에게 문의해 주세요."
    elif status == 429:
        kind = "openrouter_rate_limited"
        message = "요청이 몰려 잠시 대기해야 해요. 잠시 후 다시 시도해 주세요."
    elif status == 400:
        kind = "openrouter_bad_request"
        message = "요청 내용이 올바르지 않아요. 입력 내용이나 워크플로우 설정을 확인해 주세요."
    elif 500 <= status <= 599:
        kind = "openrouter_upstream_unavailable"
        message = "외부 AI 서비스가 잠시 불안정해요. 잠시 후 다시 시도해 주세요."
    else:
        kind = "openrouter_unknown"
        message = "외부 AI 서비스 처리 중 오류가 발생했어요. 잠시 후 다시 시도해 주세요."

    logger.warning({
        "event": "openrouter_bad_status",
        "context": context,
        "kind": kind,
        "status": status,
        "upstream_code": code,
        "retry_after": retry_after,
        "upstream_message": detail,
    })
    raise OpenRouterUpstreamError(
        message,
        kind=kind,
        http_status=status,
        upstream_code=code,
        upstream_message=detail,
        retry_after=retry_after,
    )


def _post(path: str, payload: Dict[str, Any], *, timeout: Tuple[float, float], context: str) -> Dict[str, Any]:
    try:
        resp = requests.post(
            f"{_base_url()}/{path.lstrip('/')}",
            headers=_headers(),
            json=payload,
            timeout=timeout,
        )
    except Exception as exc:
        logger.warning({"event": "openrouter_network_error", "context": context, "error": str(exc)})
        raise OpenRouterUpstreamError(
            "외부 AI 서비스 연결이 잠시 불안정해요. 잠시 후 다시 시도해 주세요.",
            kind="openrouter_network",
            upstream_message=str(exc),
        ) from exc
    if not resp.ok:
        _raise_for_response(resp, context=context)
    try:
        data = resp.json()
    except Exception as exc:
        raise OpenRouterUpstreamError(
            "외부 AI 서비스 응답을 해석하지 못했습니다.",
            kind="openrouter_invalid_response",
            http_status=int(getattr(resp, "status_code", 0) or 0),
        ) from exc
    if not isinstance(data, dict):
        raise OpenRouterUpstreamError(
            "외부 AI 서비스 응답 형식이 올바르지 않습니다.",
            kind="openrouter_invalid_response",
        )
    return data


def build_image_prompt(req: Any, wf_cfg: Dict[str, Any]) -> str:
    user_prompt = str(getattr(req, "user_prompt", "") or "").strip()
    if not user_prompt:
        raise RuntimeError("프롬프트가 비어 있습니다. 내용을 입력해 주세요.")
    style_prompt = str((wf_cfg or {}).get("style_prompt") or "").strip()
    style_pos = str((wf_cfg or {}).get("style_prompt_position") or "").strip().lower()
    negative_prompt = str((wf_cfg or {}).get("negative_prompt") or "").strip()
    if style_prompt:
        merged = f"{style_prompt}\n\n{user_prompt}" if style_pos == "prepend" else f"{user_prompt}\n\n{style_prompt}"
    else:
        merged = user_prompt
    if negative_prompt:
        merged = f"{merged}\n\nKeep absent: {negative_prompt}"
    return merged.strip()


def _extract_image(data: Dict[str, Any]) -> bytes:
    items = data.get("data")
    first = items[0] if isinstance(items, list) and items else None
    encoded = first.get("b64_json") if isinstance(first, dict) else None
    if not isinstance(encoded, str) or not encoded:
        raise OpenRouterUpstreamError(
            "이미지 생성 응답에 이미지가 포함되어 있지 않습니다.",
            kind="openrouter_invalid_response",
        )
    if encoded.startswith("data:") and "," in encoded:
        encoded = encoded.split(",", 1)[1]
    try:
        return base64.b64decode(encoded, validate=True)
    except Exception as exc:
        raise OpenRouterUpstreamError(
            "이미지 생성 응답을 해석하지 못했습니다.",
            kind="openrouter_invalid_response",
        ) from exc


def generate_image(
    *,
    model: str,
    prompt: str,
    images: Optional[List[bytes]] = None,
    aspect_ratio: Optional[str] = None,
    resolution: Optional[str] = None,
    timeout: Tuple[float, float] = (5.0, 90.0),
) -> bytes:
    model = str(model or "").strip()
    if not model:
        raise RuntimeError("이미지 모델 설정이 비어 있습니다. 서버 워크플로우 설정을 확인해 주세요.")
    payload: Dict[str, Any] = {
        "model": model,
        "prompt": str(prompt or ""),
        "n": 1,
        "provider": _provider_preferences(require_parameters=True),
    }
    if aspect_ratio:
        payload["aspect_ratio"] = str(aspect_ratio).strip()
    if resolution:
        payload["resolution"] = str(resolution).strip().upper()
    refs: List[Dict[str, Any]] = []
    for raw in images or []:
        if isinstance(raw, (bytes, bytearray)) and raw:
            refs.append({
                "type": "image_url",
                "image_url": {
                    "url": f"data:image/png;base64,{base64.b64encode(bytes(raw)).decode('ascii')}"
                },
            })
    if refs:
        payload["input_references"] = refs
    return _extract_image(_post("images", payload, timeout=timeout, context="image"))


def generate_text(
    *,
    prompt: str,
    model: Optional[str] = None,
    temperature: float = 0.2,
    top_p: float = 0.95,
    max_tokens: int = 256,
    timeout: Tuple[float, float] = (5.0, 30.0),
) -> str:
    chosen_model = str(model or os.getenv("OPENROUTER_TEXT_MODEL") or DEFAULT_TEXT_MODEL).strip()
    payload: Dict[str, Any] = {
        "model": chosen_model,
        "messages": [{"role": "user", "content": str(prompt or "")}],
        "temperature": float(temperature),
        "top_p": float(top_p),
        "max_tokens": int(max_tokens),
        "provider": _provider_preferences(require_parameters=False),
    }
    data = _post("chat/completions", payload, timeout=timeout, context="text")
    choices = data.get("choices")
    message = (choices[0] or {}).get("message") if isinstance(choices, list) and choices else None
    content = message.get("content") if isinstance(message, dict) else None
    if isinstance(content, str):
        result = content.strip()
    elif isinstance(content, list):
        result = "".join(
            str(part.get("text") or "") for part in content if isinstance(part, dict) and part.get("type") in (None, "text")
        ).strip()
    else:
        result = ""
    if not result:
        raise OpenRouterUpstreamError(
            "텍스트 생성 결과가 비어 있습니다. 잠시 후 다시 시도해 주세요.",
            kind="openrouter_invalid_response",
        )
    return result
