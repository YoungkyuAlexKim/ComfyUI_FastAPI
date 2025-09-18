"""
ComfyUI FastAPI 애플리케이션 설정 파일 (리팩토링 v2.2 - 이미지 사이즈 추가)
프롬프트 관련 설정들을 단순화하고 중앙에서 관리합니다.
"""
from typing import Dict, Any
import time

# --- 1. 워크플로우별 노드 ID 설정 (이미지 사이즈 노드 추가) ---
WORKFLOW_CONFIGS = {
    "BasicWorkFlow_PixelArt": {
        "prompt": "6",           # 긍정 프롬프트 노드 ID
        "negative_prompt": "7",  # 부정 프롬프트 노드 ID
        "seed": "3",             # 시드 노드 ID
        "latent_image": "5"      # 이미지 크기(EmptyLatentImage) 노드 ID 추가
    }
}

# --- 2. 기본 값 (프롬프트, 이미지 크기 등) ---
DEFAULT_VALUES = {
    "prompt": "1girl, solo, standing, full_body, solid_oval_eyes, chibi, simple background, masterpiece, best quality, amazing quality, pixel_art",
    "negative_prompt": "bad quality, worst quality, worst detail, sketch, censor",
    "width": 800,
    "height": 800
}

# --- 3. 서버 설정 ---
SERVER_CONFIG = {
    "output_dir": "./outputs/",
    "server_address": "127.0.0.1:8188"
}

# --- 4. 관련 함수 (이미지 사이즈 처리 로직 추가) ---

def get_prompt_overrides(
    prompt: str,
    negative_prompt: str,
    width: int,
    height: int,
    workflow_name: str = "BasicWorkFlow_PixelArt",
    seed: int = None
) -> Dict[str, Any]:
    """
    단일 프롬프트 구조에 맞춰 워크플로우 오버라이드 데이터를 생성합니다.
    (width, height 인자 추가)
    """
    if workflow_name not in WORKFLOW_CONFIGS:
        available = list(WORKFLOW_CONFIGS.keys())
        raise ValueError(f"지원하지 않는 워크플로우입니다: {workflow_name}. 사용 가능: {available}")

    config = WORKFLOW_CONFIGS[workflow_name]

    if seed is None:
        seed = int(time.time() * 1000) % 1000000000000000

    overrides = {
        config["prompt"]: {"inputs": {"text": prompt}},
        config["negative_prompt"]: {"inputs": {"text": negative_prompt}},
        config["seed"]: {"inputs": {"seed": seed}}
    }
    
    # 설정에 latent_image 노드 ID가 있으면 width와 height 값을 추가합니다.
    if "latent_image" in config:
        overrides[config["latent_image"]] = {
            "inputs": {
                "width": width,
                "height": height
            }
        }
        
    return overrides

def get_default_values() -> Dict[str, Any]:
    """
    API와 HTML에서 공통으로 사용할 기본 값들 (프롬프트, 사이즈)을 반환합니다.
    """
    return DEFAULT_VALUES.copy()

