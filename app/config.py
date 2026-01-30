"""
ComfyUI FastAPI 애플리케이션 설정 파일 (리팩토링 v4.0 - 비율 기반 사이즈)
프롬프트 관련 설정들을 단순화하고 중앙에서 관리합니다.
"""
from typing import Dict, Any
import time
import os
try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

from .workflow_configs import WORKFLOW_CONFIGS
try:
    # 선택: 워크플로우별 추천 프롬프트 템플릿(title/text)
    from .prompt_templates import PROMPT_TEMPLATES  # type: ignore
except Exception:
    PROMPT_TEMPLATES = {}

# --- 2. 기본 값 ---
DEFAULT_VALUES = {
    # user_prompt는 워크플로우별로 개별 설정됨 (제거)
    "aspect_ratio": "square", # width, height 대신 aspect_ratio 사용
    # 기본 워크플로우의 고정/추천 프롬프트를 기본값으로 사용
    "style_prompt": WORKFLOW_CONFIGS["BasicWorkFlow_PixelArt"]["style_prompt"],
    "negative_prompt": WORKFLOW_CONFIGS["BasicWorkFlow_PixelArt"]["negative_prompt"],
    "recommended_prompt": WORKFLOW_CONFIGS["BasicWorkFlow_PixelArt"]["recommended_prompt"]
}

# --- 3. 서버 설정 ---
SERVER_CONFIG = {
    "output_dir": os.getenv("OUTPUT_DIR", "./outputs/"),
    "server_address": os.getenv("COMFYUI_SERVER", "127.0.0.1:8188"),
}

# --- 3.0 ComfyUI local paths (optional) ---
# Used for housekeeping, e.g., deleting uploaded control images after job completion
COMFY_INPUT_DIR = os.getenv("COMFY_INPUT_DIR", None)

# --- 3.1 큐/타임아웃 환경 설정 ---
QUEUE_CONFIG = {
    "max_per_user_queue": int(os.getenv("MAX_PER_USER_QUEUE", "5")),
    "max_per_user_concurrent": int(os.getenv("MAX_PER_USER_CONCURRENT", "1")),
    "job_timeout_seconds": float(os.getenv("JOB_TIMEOUT_SECONDS", "180")),
}

# --- 3.2 작업 DB 경로 ---
JOB_DB_PATH = os.getenv("JOB_DB_PATH", "db/app_data.db")

# --- 3.3 Logging settings (via .env) ---
# LOG_LEVEL: DEBUG|INFO|WARNING|ERROR (default INFO)
# LOG_FORMAT: json|text (default json)
# LOG_TO_FILE: true|false (default false)
# LOG_FILE_PATH: logs/app.log (used when LOG_TO_FILE=true)
# LOG_MAX_BYTES: integer bytes for rotation (default 1048576)
# LOG_BACKUP_COUNT: integer number of rotated files (default 3)

# --- 3.4 Health/Timeouts (.env) ---
# 건강검진에 사용되는 임계치 및 네트워크 타임아웃 설정
HEALTHZ_CONFIG = {
    "disk_min_free_mb": int(os.getenv("HEALTHZ_DISK_MIN_FREE_MB", "512")),
}

HTTP_TIMEOUTS = {
    # requests 타임아웃 (초): (connect, read)
    "comfy_http_connect": float(os.getenv("COMFY_HTTP_CONNECT_TIMEOUT", "3")),
    "comfy_http_read": float(os.getenv("COMFY_HTTP_READ_TIMEOUT", "10")),
}

# WebSocket 타임아웃 (초)
WS_TIMEOUTS = {
    "comfy_ws_connect": float(os.getenv("COMFY_WS_CONNECT_TIMEOUT", "5")),
    "comfy_ws_idle": float(os.getenv("COMFY_WS_IDLE_TIMEOUT", "120")),
}

# Progress logging controls
PROGRESS_LOG_CONFIG = {
    # Log every N percent (e.g., 10 => 0,10,20,...). Set to 0 to disable step gating.
    "step_percent": int(os.getenv("PROGRESS_LOG_STEP", "10")),
    # Minimum interval between logs per job in milliseconds
    "min_interval_ms": int(os.getenv("PROGRESS_LOG_MIN_MS", "500")),
    # Log level for progress messages: debug|info
    "level": os.getenv("PROGRESS_LOG_LEVEL", "info").lower(),
}

# --- 3.5 Upload limits (.env) ---
# Control image upload: maximum allowed size in bytes (default: 10MB)
UPLOAD_CONFIG = {
    "controls_max_bytes": int(os.getenv("CONTROLS_MAX_BYTES", str(10 * 1024 * 1024))),
    "inputs_max_bytes": int(os.getenv("INPUTS_MAX_BYTES", str(10 * 1024 * 1024))),
}

# --- 4. 관련 함수 ---
def _clean_tags(tags_string: str) -> list[str]:
    """콤마로 구분된 문자열을 태그 리스트로 변환하고 정리합니다."""
    return [tag.strip() for tag in tags_string.split(',') if tag.strip()]

def get_prompt_overrides(
    user_prompt: str,
    aspect_ratio: str,  # width, height 대신 aspect_ratio 사용
    workflow_name: str = "BasicWorkFlow_PixelArt",
    seed: int | None = None,
    control: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    """
    사용자 프롬프트와 시스템 스타일 프롬프트를 결합하여 최종 오버라이드를 생성합니다.
    """
    if workflow_name not in WORKFLOW_CONFIGS:
        available = list(WORKFLOW_CONFIGS.keys())
        raise ValueError(f"지원하지 않는 워크플로우입니다: {workflow_name}. 사용 가능: {available}")

    config = WORKFLOW_CONFIGS[workflow_name]

    # --- [선택] 비율 기반 사이즈 계산 (sizes 정의가 있는 워크플로우에서만) ---
    width = None
    height = None
    try:
        if isinstance(config.get("sizes"), dict):
            if aspect_ratio not in config["sizes"]:
                raise ValueError(
                    f"지원하지 않는 비율입니다: {aspect_ratio}. 사용 가능: {list(config['sizes'].keys())}"
                )
            size = config["sizes"][aspect_ratio]
            width = size.get("width")
            height = size.get("height")
    except Exception:
        # sizes가 없거나 잘못돼도 이미지 변환형 워크플로우에선 무시 가능
        width = None
        height = None

    # --- 프롬프트 결합 로직 (prompt_node가 있는 워크플로우에서만 적용) ---
    final_positive_prompt = None
    try:
        user_tags = _clean_tags(user_prompt)
        style_tags = _clean_tags(config.get("style_prompt", ""))
        final_positive_tags = user_tags + [tag for tag in style_tags if tag not in user_tags]
        final_positive_prompt = ", ".join(final_positive_tags)
    except Exception:
        final_positive_prompt = user_prompt or ""

    if seed is None:
        seed = int(time.time() * 1000) % 1000000000000000

    overrides: Dict[str, Any] = {}

    # prompt / negative / seed 노드는 존재할 때만 반영
    try:
        pn = config.get("prompt_node")
        prompt_key = (config.get("prompt_input_key") or "text") if isinstance(config, dict) else "text"
        if pn:
            overrides[pn] = {"inputs": {str(prompt_key): final_positive_prompt or ""}}
    except Exception:
        pass
    try:
        nn = config.get("negative_prompt_node")
        negative_key = (config.get("negative_prompt_input_key") or "text") if isinstance(config, dict) else "text"
        if nn:
            overrides[nn] = {"inputs": {str(negative_key): config.get("negative_prompt", "")}}
    except Exception:
        pass
    try:
        sn = config.get("seed_node")
        if sn is not None:
            seed_key = (config.get("seed_input_key") or "seed") if isinstance(config, dict) else "seed"
            overrides[sn] = {"inputs": {str(seed_key): seed}}
    except Exception:
        pass

    # latent 이미지 사이즈 지정은 노드와 width/height 모두 있을 때만
    try:
        ln = config.get("latent_image_node")
        if ln and width is not None and height is not None:
            overrides[ln] = {"inputs": {"width": width, "height": height}}
    except Exception:
        pass
    
    # --- Optional ControlNet overrides ---
    try:
        cn_cfg = config.get("controlnet") if isinstance(config, dict) else None
        if control and cn_cfg and cn_cfg.get("enabled"):
            apply_node = cn_cfg.get("apply_node")
            image_node = cn_cfg.get("image_node")
            defaults = cn_cfg.get("defaults", {})
            # Strength: if provided, otherwise keep workflow default
            strength = control.get("strength") if isinstance(control, dict) else None
            if apply_node and (strength is not None):
                # Merge with default start/end percent
                start_pct = defaults.get("start_percent", 0.0)
                end_pct = defaults.get("end_percent", 0.33)
                overrides[apply_node] = {
                    "inputs": {
                        "strength": float(strength),
                        "start_percent": float(start_pct),
                        "end_percent": float(end_pct),
                    }
                }
            # Image filename override when available (must exist in ComfyUI input storage)
            image_filename = control.get("image_filename") if isinstance(control, dict) else None
            if image_node and image_filename:
                overrides[image_node] = {"inputs": {"image": image_filename}}
    except Exception:
        # Fail-safe: ignore controlnet override errors
        pass

    return overrides

def get_workflow_default_prompt(workflow_id: str) -> str:
    """특정 워크플로우의 기본 사용자 프롬프트를 반환합니다."""
    if workflow_id in WORKFLOW_CONFIGS:
        return WORKFLOW_CONFIGS[workflow_id].get("default_user_prompt", "")
    return ""

def get_default_values() -> Dict[str, Any]:
    """API와 HTML에서 공통으로 사용할 기본 값들을 반환합니다."""
    # width, height를 제거하고, sizes 딕셔너리를 추가합니다.
    defaults = DEFAULT_VALUES.copy()
    
    # 각 워크플로우의 사이즈 정보를 기본값에 포함시켜 프론트엔드로 전달
    defaults["workflows_sizes"] = {
        wf_id: wf_config.get("sizes", {})
        for wf_id, wf_config in WORKFLOW_CONFIGS.items()
    }
    
    # 워크플로우별 기본 프롬프트 정보 추가
    defaults["workflow_default_prompts"] = {
        wf_id: wf_config.get("default_user_prompt", "")
        for wf_id, wf_config in WORKFLOW_CONFIGS.items()
    }
    # 워크플로우별 사용 가능한 ControlNet 슬롯 이름 배열(없으면 ["default"]) 추가
    defaults["workflow_control_slots"] = {
        wf_id: (list(wf_config.get("control_slots", {}).keys()) if isinstance(wf_config.get("control_slots", {}), dict) and wf_config.get("control_slots") else ["default"])
        for wf_id, wf_config in WORKFLOW_CONFIGS.items()
    }
    
    # 더 이상 사용하지 않는 키 제거
    # defaults.pop("width", None) 
    # defaults.pop("height", None)
    
    # 추천 프롬프트 템플릿(옵션) 주입
    try:
        defaults["workflow_prompt_templates"] = PROMPT_TEMPLATES
    except Exception:
        defaults["workflow_prompt_templates"] = {}
    return defaults