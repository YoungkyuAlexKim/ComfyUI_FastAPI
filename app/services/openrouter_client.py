import base64
import os
from typing import Any, Dict, List, Optional, Tuple

import requests

from ..logging_utils import setup_logging


logger = setup_logging()

DEFAULT_BASE_URL = "https://openrouter.ai/api/v1"
DEFAULT_TEXT_MODEL = "google/gemini-3.1-flash-lite"

# Server-side allowlist for user-selectable hosted image models. Keep this
# authoritative: the browser receives a public copy but cannot add model IDs.
IMAGE_MODEL_OPTIONS: Dict[str, Dict[str, Any]] = {
    "google/gemini-3-pro-image": {
        "label": "Nano Banana Pro",
        "description": "고품질 · 1K와 2K 출력 비용 동일",
        "resolutions": ["1K", "2K"],
        "default_resolution": "2K",
        "zdr": True,
        "max_input_references": 14,
    },
    "google/gemini-3.1-flash-image": {
        "label": "Nano Banana 2",
        "description": "균형형 · 빠른 생성과 해상도별 과금",
        "resolutions": ["1K", "2K"],
        "default_resolution": "1K",
        "zdr": True,
        "max_input_references": 14,
    },
    "google/gemini-3.1-flash-lite-image": {
        "label": "Nano Banana 2 Lite",
        "description": "경제형 · 빠른 초안 및 반복 작업",
        "resolutions": ["1K"],
        "default_resolution": "1K",
        "zdr": True,
        "max_input_references": 14,
    },
    "openai/gpt-image-2": {
        "label": "GPT Image 2",
        "description": "OpenAI · 정교한 지시 이행과 이미지 편집",
        "resolutions": ["1K", "2K"],
        "default_resolution": "1K",
        "qualities": [
            {"value": "low", "label": "Low · 빠른 초안"},
            {"value": "medium", "label": "Medium · 일반 작업"},
            {"value": "high", "label": "High · 최종 품질"},
        ],
        "default_quality": "medium",
        "zdr": False,
        "max_input_references": 16,
        "privacy_notice": "ZDR 미지원 · 데이터 수집 거부 설정은 유지됩니다.",
    },
}


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


def gpt_image_timeout_seconds() -> float:
    try:
        value = float(os.getenv("GPT_IMAGE_2_TIMEOUT_SECONDS", "300") or "300")
    except Exception:
        value = 300.0
    return max(60.0, min(600.0, value))


def public_image_model_options() -> List[Dict[str, Any]]:
    return [
        {
            "id": model_id,
            "label": cfg["label"],
            "description": cfg["description"],
            "resolutions": list(cfg["resolutions"]),
            "default_resolution": cfg["default_resolution"],
            "qualities": list(cfg.get("qualities") or []),
            "default_quality": cfg.get("default_quality"),
            "zdr": bool(cfg.get("zdr", True)),
            "privacy_notice": str(cfg.get("privacy_notice") or ""),
            "max_input_references": int(cfg.get("max_input_references") or 0),
        }
        for model_id, cfg in IMAGE_MODEL_OPTIONS.items()
    ]


def resolve_image_model_options(
    *,
    requested_model: Optional[str],
    requested_resolution: Optional[str],
    requested_quality: Optional[str],
    default_model: str,
) -> Tuple[str, str, Optional[str]]:
    model = str(requested_model or default_model or "").strip()
    cfg = IMAGE_MODEL_OPTIONS.get(model)
    if not cfg:
        raise RuntimeError("선택한 이미지 모델은 현재 사용할 수 없습니다. 모델을 다시 선택해 주세요.")

    resolution = str(requested_resolution or cfg["default_resolution"] or "").strip().upper()
    allowed = cfg.get("resolutions") or []
    if resolution not in allowed:
        allowed_text = ", ".join(str(v) for v in allowed)
        raise RuntimeError(f"선택한 모델은 {resolution} 출력을 지원하지 않습니다. 지원 해상도: {allowed_text}")
    quality_options = cfg.get("qualities") or []
    allowed_qualities = [str(item.get("value") or "") for item in quality_options if isinstance(item, dict)]
    if allowed_qualities:
        quality = str(requested_quality or cfg.get("default_quality") or "").strip().lower()
        if quality not in allowed_qualities:
            allowed_text = ", ".join(allowed_qualities)
            raise RuntimeError(f"선택한 모델은 {quality or '빈'} 품질 옵션을 지원하지 않습니다. 지원 품질: {allowed_text}")
    else:
        quality = None
    return model, resolution, quality


def image_model_max_references(model: str) -> int:
    cfg = IMAGE_MODEL_OPTIONS.get(str(model or "").strip()) or {}
    return max(1, min(16, int(cfg.get("max_input_references") or 14)))


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


def _provider_preferences(*, require_parameters: bool, model: Optional[str] = None) -> Dict[str, Any]:
    prefs: Dict[str, Any] = {
        "data_collection": "deny",
        "require_parameters": bool(require_parameters),
    }
    # Respect the global privacy default, except for explicitly allowlisted
    # models that currently have no ZDR-capable route (GPT Image 2).
    zdr = str(os.getenv("OPENROUTER_ZDR", "true") or "true").strip().lower()
    global_zdr = zdr not in ("0", "false", "no", "off")
    model_cfg = IMAGE_MODEL_OPTIONS.get(str(model or "").strip())
    # A model may force ZDR off when no compatible route exists. Otherwise the
    # operator's global OPENROUTER_ZDR setting remains authoritative.
    prefs["zdr"] = False if model_cfg and model_cfg.get("zdr") is False else global_zdr
    return prefs


def _gpt_image_size(resolution: str, aspect_ratio: Optional[str]) -> str:
    resolution = str(resolution or "1K").strip().upper()
    aspect = str(aspect_ratio or "1:1").strip()
    sizes = {
        "1K": {
            "1:1": "1024x1024",
            "16:9": "1536x1024",
            "9:16": "1024x1536",
        },
        "2K": {
            "1:1": "2048x2048",
            "16:9": "2048x1152",
            "9:16": "1152x2048",
        },
    }
    by_aspect = sizes.get(resolution)
    if not by_aspect:
        raise RuntimeError(f"GPT Image 2가 지원하지 않는 해상도입니다: {resolution}")
    return by_aspect.get(aspect, by_aspect["1:1"])


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

    if str(code or "").lower() == "moderation_blocked" or "moderation_blocked" in low:
        kind = "openrouter_moderation_blocked"
        message = "안전 정책으로 인해 이미지를 만들 수 없어요. 표현을 조금 바꿔 다시 시도해 주세요."
    elif status in (401, 403):
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
    except requests.exceptions.ReadTimeout as exc:
        logger.warning({
            "event": "openrouter_read_timeout",
            "context": context,
            "read_timeout_seconds": timeout[1] if isinstance(timeout, tuple) and len(timeout) > 1 else None,
            "error": str(exc),
        })
        timeout_message = (
            "이미지 생성 시간이 길어 응답 제한시간을 초과했어요. 잠시 후 다시 시도해 주세요."
            if context == "image"
            else "외부 AI 응답 시간이 길어 제한시간을 초과했어요. 잠시 후 다시 시도해 주세요."
        )
        raise OpenRouterUpstreamError(
            timeout_message,
            kind="openrouter_timeout",
            upstream_message=str(exc),
        ) from exc
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
    quality: Optional[str] = None,
    timeout: Tuple[float, float] = (5.0, 90.0),
) -> bytes:
    model = str(model or "").strip()
    if not model:
        raise RuntimeError("이미지 모델 설정이 비어 있습니다. 서버 워크플로우 설정을 확인해 주세요.")
    payload: Dict[str, Any] = {
        "model": model,
        "prompt": str(prompt or ""),
        "n": 1,
        "provider": _provider_preferences(require_parameters=True, model=model),
    }
    if model == "openai/gpt-image-2":
        payload["size"] = _gpt_image_size(str(resolution or "1K"), aspect_ratio)
        payload["quality"] = str(quality or "medium").strip().lower()
        payload["background"] = "opaque"
    else:
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
        max_refs = image_model_max_references(model)
        if len(refs) > max_refs:
            raise RuntimeError(f"선택한 모델은 참조 이미지를 최대 {max_refs}장까지 지원합니다.")
        payload["input_references"] = refs
    data = _post("images", payload, timeout=timeout, context="image")
    usage = data.get("usage") if isinstance(data, dict) else None
    if isinstance(usage, dict):
        logger.info({"event": "openrouter_image_usage", "model": model, "usage": usage})
    return _extract_image(data)


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
        "provider": _provider_preferences(require_parameters=False, model=chosen_model),
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
