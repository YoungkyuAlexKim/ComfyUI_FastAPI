"""
ComfyUI FastAPI 애플리케이션 설정 파일 (리팩토링 v3.1 - 추천 프롬프트 추가)
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
        
        # 고정 프롬프트 (v3.0)
        "style_prompt": "masterpiece, best quality, amazing quality, pixel_art",
        "negative_prompt": "bad quality, worst quality, worst detail, sketch, censor, blurry, ugly",
        
        # 추천 프롬프트 (v3.1)
        "recommended_prompt": "1girl, solo, solid_oval_eyes, simple background"
    }
}

# --- 2. 기본 값 ---
DEFAULT_VALUES = {
    "user_prompt": "a girl in a hanbok",
    "width": 800,
    "height": 800,
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
    width: int,
    height: int,
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
    
    # --- 프롬프트 결합 로직 ---
    user_tags = _clean_tags(user_prompt)
    style_tags = _clean_tags(config.get("style_prompt", ""))
    
    # 중복 제거: 사용자 태그에 이미 스타일 태그가 있으면 스타일 태그를 추가하지 않음
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
    return DEFAULT_VALUES.copy()
