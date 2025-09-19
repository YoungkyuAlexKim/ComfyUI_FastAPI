from typing import Dict, Any

# Centralized workflow-specific configurations
# Move/add new workflows here without touching the global config module

WORKFLOW_CONFIGS: Dict[str, Dict[str, Any]] = {
    "BasicWorkFlow_PixelArt": {
        "display_name": "픽셀 아트",
        "description": "레트로 감성의 픽셀 아트 스타일 이미지를 생성합니다",

        # 기본 사용자 프롬프트 (워크플로우별 고유)
        "default_user_prompt": "a girl in a hanbok",

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

        # [v4.0] 비율 기반 사이즈
        "sizes": {
            "square": {"width": 800, "height": 800},
            "landscape": {"width": 1024, "height": 576},
            "portrait": {"width": 576, "height": 1024},
        },

        # ControlNet mapping for current single-control workflow
        "controlnet": {
            "enabled": True,
            "apply_node": "23",  # ControlNetApplyAdvanced
            "image_node": "28",  # LoadImage
            "defaults": {
                "strength": 0,
                "start_percent": 0.0,
                "end_percent": 0.33,
            },
        },
    },

    # 멀티 ControlNet 매핑 샘플 (참고용 주석)
    # 실제 노드 ID는 워크플로우 JSON에서 확인해 입력하세요.
    # "PhotoWithMultiControls": {
    #     "display_name": "멀티 컨트롤 데모",
    #     "description": "scribble + depth + normal 예시",
    #     "default_user_prompt": "a scenic landscape",
    #     "prompt_node": "6",
    #     "negative_prompt_node": "7",
    #     "seed_node": "3",
    #     "latent_image_node": "5",
    #     "style_prompt": "high quality, detailed",
    #     "negative_prompt": "low quality, blurry",
    #     "sizes": {
    #         "square": {"width": 1024, "height": 1024},
    #         "landscape": {"width": 1344, "height": 768},
    #         "portrait": {"width": 768, "height": 1344}
    #     },
    #     "control_slots": {
    #         "scribble": {"apply_node": "23", "image_node": "28"},
    #         "depth":    {"apply_node": "45", "image_node": "46"},
    #         "normal":   {"apply_node": "60", "image_node": "61"}
    #     }
    # }
}


