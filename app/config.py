"""
ComfyUI FastAPI 애플리케이션 설정 파일 (리팩토링 v4.0 - 비율 기반 사이즈)
프롬프트 관련 설정들을 단순화하고 중앙에서 관리합니다.
"""
from typing import Dict, Any
import time

# --- 1. 워크플로우별 설정 ---
WORKFLOW_CONFIGS = {
    "BasicWorkFlow_PixelArt": {
        # 노드 ID
        "prompt_node": "6",
        "negative_prompt_node": "7",
        "seed_node": "3",
        "latent_image_node": "5",

        # 고정 프롬프트
        "style_prompt": "masterpiece, best quality, amazing quality, pixel_art",
        "negative_prompt": "bad quality, worst quality, worst detail, sketch, censor, blurry, ugly",

        # 추천 프롬프트
        "recommended_prompt": "1girl, solo, solid_oval_eyes, simple background",

        # ✨ [4차] 사전 정의된 사이즈 (v4.0)
        "sizes": {
            "square": {"width": 800, "height": 800},
            "landscape": {"width": 1024, "height": 576}, # 16:9 비율
            "portrait": {"width": 576, "height": 1024}  # 9:16 비율
        }
    }
}

# --- 2. 기본 값 ---
DEFAULT_VALUES = {
    "user_prompt": "a girl in a hanbok",
    "aspect_ratio": "square", # width, height 대신 aspect_ratio 사용
    # 기본 워크플로우의 고정/추천 프롬프트를 기본값으로 사용
    "style_prompt": WORKFLOW_CONFIGS["BasicWorkFlow_PixelArt"]["style_prompt"],
    "negative_prompt": WORKFLOW_CONFIGS["BasicWorkFlow_PixelArt"]["negative_prompt"],
    "recommended_prompt": WORKFLOW_CONFIGS["BasicWorkFlow_PixelArt"]["recommended_prompt"]
}

# --- 3. 서버 설정 ---
SERVER_CONFIG = {
    "output_dir": "./outputs/",
    "server_address": "127.0.0.1:8188"
}

# --- 4. 관련 함수 ---
def _clean_tags(tags_string: str) -> list[str]:
    """콤마로 구분된 문자열을 태그 리스트로 변환하고 정리합니다."""
    return [tag.strip() for tag in tags_string.split(',') if tag.strip()]

def get_prompt_overrides(
    user_prompt: str,
    aspect_ratio: str, # width, height 대신 aspect_ratio 사용
    workflow_name: str = "BasicWorkFlow_PixelArt",
    seed: int = None
) -> Dict[str, Any]:
    """
    사용자 프롬프트와 시스템 스타일 프롬프트를 결합하여 최종 오버라이드를 생성합니다.
    """
    if workflow_name not in WORKFLOW_CONFIGS:
        available = list(WORKFLOW_CONFIGS.keys())
        raise ValueError(f"지원하지 않는 워크플로우입니다: {workflow_name}. 사용 가능: {available}")

    config = WORKFLOW_CONFIGS[workflow_name]
    
    # --- [4차] 비율에 맞는 width, height 가져오기 ---
    if aspect_ratio not in config["sizes"]:
        raise ValueError(f"지원하지 않는 비율입니다: {aspect_ratio}. 사용 가능: {list(config['sizes'].keys())}")
    
    size = config["sizes"][aspect_ratio]
    width = size["width"]
    height = size["height"]
    
    # --- 프롬프트 결합 로직 ---
    user_tags = _clean_tags(user_prompt)
    style_tags = _clean_tags(config.get("style_prompt", ""))
    
    final_positive_tags = user_tags + [tag for tag in style_tags if tag not in user_tags]
    final_positive_prompt = ", ".join(final_positive_tags)
    
    if seed is None:
        seed = int(time.time() * 1000) % 1000000000000000

    overrides = {
        config["prompt_node"]: {"inputs": {"text": final_positive_prompt}},
        config["negative_prompt_node"]: {"inputs": {"text": config.get("negative_prompt", "")}},
        config["seed_node"]: {"inputs": {"seed": seed}}
    }
    
    if "latent_image_node" in config:
        overrides[config["latent_image_node"]] = {
            "inputs": {"width": width, "height": height}
        }
        
    return overrides

def get_default_values() -> Dict[str, Any]:
    """API와 HTML에서 공통으로 사용할 기본 값들을 반환합니다."""
    # width, height를 제거하고, sizes 딕셔너리를 추가합니다.
    defaults = DEFAULT_VALUES.copy()
    
    # 각 워크플로우의 사이즈 정보를 기본값에 포함시켜 프론트엔드로 전달
    defaults["workflows_sizes"] = {
        wf_id: wf_config.get("sizes", {})
        for wf_id, wf_config in WORKFLOW_CONFIGS.items()
    }
    
    # 더 이상 사용하지 않는 키 제거
    # defaults.pop("width", None) 
    # defaults.pop("height", None)
    
    return defaults