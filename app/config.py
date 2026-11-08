"""
LC Canvas 애플리케이션 설정 파일
프롬프트 관련 설정들을 단순화하고 중앙에서 관리합니다.
"""
from typing import Dict, Any
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
    "style_prompt": WORKFLOW_CONFIGS["NanoBanana"].get("style_prompt", ""),
    "negative_prompt": WORKFLOW_CONFIGS["NanoBanana"].get("negative_prompt", ""),
    "recommended_prompt": WORKFLOW_CONFIGS["NanoBanana"].get("recommended_prompt", "")
}

# --- 3. 서버 설정 ---
SERVER_CONFIG = {
    "output_dir": os.getenv("OUTPUT_DIR", "./outputs/"),
}

# --- 3.1 큐 환경 설정 ---
# OpenRouter 동시성/대기열/타임아웃은 OPENROUTER_* env로 main.py startup에서 적용합니다.
QUEUE_CONFIG = {
    "max_per_user_concurrent": int(os.getenv("MAX_PER_USER_CONCURRENT", "1")),
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
UPLOAD_CONFIG = {
    "inputs_max_bytes": int(os.getenv("INPUTS_MAX_BYTES", str(10 * 1024 * 1024))),
    "inputs_max_pixels": int(os.getenv("INPUTS_MAX_PIXELS", "40000000")),
}

# --- 4. 관련 함수 ---
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
    # 더 이상 사용하지 않는 키 제거
    # defaults.pop("width", None) 
    # defaults.pop("height", None)
    
    # 추천 프롬프트 템플릿(옵션) 주입
    try:
        defaults["workflow_prompt_templates"] = PROMPT_TEMPLATES
    except Exception:
        defaults["workflow_prompt_templates"] = {}
    return defaults
