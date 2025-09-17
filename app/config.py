"""
ComfyUI FastAPI 애플리케이션 설정 파일
프롬프트 관련 설정들을 중앙화하여 관리합니다.
"""

from typing import Dict, Any

# 워크플로우별 노드 ID 설정
# 각 워크플로우 JSON에서 프롬프트 타입별 노드 ID 매핑
WORKFLOW_CONFIGS = {
    "basic_workflow": {
        "prompt_a": "115",        # 긍정 프롬프트 A 노드 ID
        "prompt_b": "138",        # 긍정 프롬프트 B 노드 ID
        "negative_prompt": "116", # 부정 프롬프트 노드 ID
        "seed": "3"              # 시드 노드 ID
    },
    "advanced_workflow": {
        "prompt_a": "115",        # 동일한 구조라고 가정 (실제로는 확인 필요)
        "prompt_b": "138",
        "negative_prompt": "116",
        "seed": "3"
    }
}

# 통합된 기본 프롬프트 값들
# 각 용도(HTML, API, 워크플로우)에 맞게 사용할 수 있도록 구성
DEFAULT_VALUES = {
    "prompt_a": {
        "html": "1girl, cowboy shot, outdoors",
        "api": "1girl, cowboy shot, outdoors",
        "workflow": "1girl, cowboy shot, outdoors"
    },
    "prompt_b": {
        "html": "HDA_MasterpieceClassic_v1.2, traditional media, retro artstyle, 1980s style",
        "api": "HDA_MasterpieceClassic_v1.2, traditional media, retro artstyle, 1980s style",
        "workflow": "HDA_MasterpieceClassic_v1.2,\n(traditional media, retro artstyle, 1980s (style):1.15),\n"
    },
    "negative_prompt": {
        "html": "HDA_NegativeXLclassic",
        "api": "HDA_NegativeXLclassic",
        "workflow": "HDA_NegativeXLclassic"
    }
}

# 서버 설정
SERVER_CONFIG = {
    "workflow_json_path": "./workflows/basic_workflow.json",
    "output_dir": "./outputs/",
    "server_address": "127.0.0.1:8188"
}

def get_prompt_overrides(prompt_a: str, prompt_b: str, negative_prompt: str, workflow_name: str = "basic_workflow", seed: int = None) -> Dict[str, Any]:
    """
    프롬프트 오버라이드 데이터를 생성합니다.

    Args:
        prompt_a: 긍정 프롬프트 A
        prompt_b: 긍정 프롬프트 B
        negative_prompt: 부정 프롬프트
        workflow_name: 사용할 워크플로우 이름 (기본값: "basic_workflow")
        seed: 랜덤 시드 (None이면 현재 시간 사용)

    Returns:
        워크플로우 오버라이드 데이터

    Raises:
        ValueError: 지원하지 않는 워크플로우 이름인 경우
    """
    if workflow_name not in WORKFLOW_CONFIGS:
        available_workflows = list(WORKFLOW_CONFIGS.keys())
        raise ValueError(f"지원하지 않는 워크플로우입니다: {workflow_name}. 사용 가능한 워크플로우: {available_workflows}")

    workflow_config = WORKFLOW_CONFIGS[workflow_name]

    if seed is None:
        import time
        seed = int(time.time())

    return {
        workflow_config["prompt_a"]: {"inputs": {"text": prompt_a}},
        workflow_config["prompt_b"]: {"inputs": {"text": prompt_b}},
        workflow_config["negative_prompt"]: {"inputs": {"text": negative_prompt}},
        workflow_config["seed"]: {"inputs": {"seed": seed}}
    }

def get_api_examples() -> Dict[str, str]:
    """
    API 요청 모델에서 사용할 예제 값을 반환합니다.
    """
    return {
        key: DEFAULT_VALUES[key]["api"]
        for key in DEFAULT_VALUES.keys()
    }

def get_default_prompts_for_html() -> Dict[str, str]:
    """
    HTML 템플릿에서 사용할 기본 프롬프트 값을 반환합니다.
    """
    return {
        key: DEFAULT_VALUES[key]["html"]
        for key in DEFAULT_VALUES.keys()
    }

def get_workflow_defaults() -> Dict[str, str]:
    """
    워크플로우에서 사용할 긴 프롬프트 기본값을 반환합니다.
    """
    return {
        key: DEFAULT_VALUES[key]["workflow"]
        for key in DEFAULT_VALUES.keys()
    }
