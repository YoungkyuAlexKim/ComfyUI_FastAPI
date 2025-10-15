from typing import Dict, Any

# Centralized workflow-specific configurations
# Move/add new workflows here without touching the global config module

WORKFLOW_CONFIGS: Dict[str, Dict[str, Any]] = {
    "BasicWorkFlow_PixelArt": {
        "display_name": "픽셀 아트",
        "description": "레트로 감성의 픽셀 아트 스타일 이미지를 생성합니다",

        # 기본 사용자 프롬프트 (워크플로우별 고유)
        "default_user_prompt": "1girl, solo, hanbok",

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
        # 카드 UI 슬롯 메타(단일 슬롯)
        "control_slots": {
            "default": {
                "apply_node": "23",
                "image_node": "28",
                "label": "Scribble",
                "type": "scribble",
                "ui": {
                    "strength": {"min": 0.0, "max": 1.5, "step": 0.05, "default": 0.0},
                    "start_percent": {"min": 0.0, "max": 1.0, "step": 0.01, "default": 0.0},
                    "end_percent": {"min": 0.0, "max": 1.0, "step": 0.01, "default": 0.33}
                }
            }
        },
        # UI schema
        "ui": {
            "showControlNet": True,
            # 추천 프롬프트 템플릿(초보자용 클릭 추가)
            # 프론트에서 chips 형태로 노출되며 클릭 시 사용자 프롬프트에 병합됩니다.
            "promptTemplates": [
                "1girl, solo, solid_oval_eyes, simple background",
                "chibi, full_body, simple background",
                "close-up, portrait, detailed eyes",
                "dynamic pose, action, motion lines",
                "fantasy armor, sword, standing",
                "cute, small animal companion"
            ]
        },
    },

    "BasicWorkFlow_MKStyle": {
        "display_name": "MK 스타일",
        "description": "MK 스타일 템플릿 + 업스케일/리파인 + 얼굴 디테일러 적용",

        # 사용자 프롬프트는 시스템 프롬프트에 병합되는 형태(선택 입력)
        "default_user_prompt": "",

        # 노드 ID 매핑 (JSON 기준)
        # - 포지티브/네거티브 프롬프트 인코딩: 6 / 7
        # - 시드: 초기 KSampler(3)
        # - 빈 잠재 이미지: 5 (1024x1024)
        "prompt_node": "6",
        "negative_prompt_node": "7",
        "seed_node": "3",
        "latent_image_node": "5",

        # 고정 프롬프트(시스템 스타일)
        "style_prompt": "CQArt, masterpiece, best quality, amazing quality",
        "negative_prompt": "bad quality, worst quality, worst detail, signature",

        # 비율 기반 사이즈(기본 정사각 1024x1024)
        # 16:9 계열은 GPU 친화적으로 64 배수에 가깝게 조정
        "sizes": {
            "square": {"width": 1024, "height": 1024},
            "landscape": {"width": 1344, "height": 768},
            "portrait": {"width": 768, "height": 1344},
        },

        # ControlNet 매핑(단일) + 슬롯 메타(UI 범위/기본값)
        "controlnet": {
            "enabled": True,
            "apply_node": "23",
            "image_node": "28",
            "defaults": {
                "strength": 0,
                "start_percent": 0.0,
                "end_percent": 0.33,
            },
        },
        # 슬롯 단위 제어(멀티/단일 모두 지원). 기본 슬롯명: "default"
        "control_slots": {
            "default": {
                "apply_node": "23",
                "image_node": "28",
                "label": "Scribble",
                "type": "scribble",
                "ui": {
                    "strength": {"min": 0.0, "max": 1.5, "step": 0.05, "default": 0.0},
                    "start_percent": {"min": 0.0, "max": 1.0, "step": 0.01, "default": 0.0},
                    "end_percent": {"min": 0.0, "max": 1.0, "step": 0.01, "default": 0.33}
                }
            }
        },

        # UI 힌트
        "ui": {
        "showControlNet": True,
        # LoRA 강도 조절 UI 노출 (슬라이더)
        "showLora": True,
        # 당분간 캐릭터 LoRA 슬라이더는 숨김, 스타일만 노출
        "showStyleLora": True,
        "showCharacterLora": False
        },
        # LoRA 매핑(노드/입력 키)
        # - 캐릭터 로라: 워크플로우 노드 14
        # - 스타일 로라: 워크플로우 노드 42
        # - 입력 필드명은 pysssss LoraLoader 기준
        "loras": {
            "character": {
                "node": "14",
                "name_input": "lora_name",
                "unet_input": "strength_model",
                "clip_input": "strength_clip",
                # 기본값 및 UI 범위 (프론트 참고용)
                "defaults": {"unet": 0.0, "clip": 0.0},
                "min": 0.0,
                "max": 1.5,
                "step": 0.05
            },
            "style": {
                "node": "42",
                "name_input": "lora_name",
                "unet_input": "strength_model",
                "clip_input": "strength_clip",
                # 워크플로우 JSON 기본값 반영(0.8)
                "defaults": {"unet": 0.8, "clip": 0.8},
                "min": 0.0,
                "max": 1.5,
                "step": 0.05
            }
        }
        ,
        # LoRA 슬라이더 사용자 힌트(워크플로우별 커스텀 문구)
        "lora_hint": {
            "style": "강도가 높아질 수록 민국님 그림체에 점점 더 가까워집니다. 강도가 낮아질수록 모델 잠재력이 높아집니다",
            "character": ""
        }
    },

    "BasicWorkFlow_LOSStyle": {
        "display_name": "레오슬 스타일",
        "description": "새로 학습한 LOS 스타일 LoRA를 사용하는 기본 워크플로우(페이스 디테일러 없음)",

        # 사용자 프롬프트는 시스템 프롬프트에 병합되는 형태(선택 입력)
        "default_user_prompt": "no_humans, blue_slime",

        # 노드 ID 매핑 (JSON 기준)
        # - 포지티브/네거티브 프롬프트 인코딩: 6 / 7
        # - 시드: 초기 KSampler(3)
        # - 빈 잠재 이미지: 5
        "prompt_node": "6",
        "negative_prompt_node": "7",
        "seed_node": "3",
        "latent_image_node": "5",

        # 고정 프롬프트(시스템 스타일)
        # JSON 내 텍스트를 기반으로 핵심 스타일 키워드와 품질 태그를 유지
        "style_prompt": "LOSart, masterpiece, best quality, amazing quality",
        "negative_prompt": "bad quality,worst quality,worst detail",

        # 비율 기반 사이즈(기본 정사각 1024x1024; 가로/세로는 GPU 친화 해상도)
        "sizes": {
            "square": {"width": 1024, "height": 1024},
            "landscape": {"width": 1024, "height": 576},
            "portrait": {"width": 576, "height": 1024}
        },

        # ControlNet 매핑(단일)
        "controlnet": {
            "enabled": True,
            "apply_node": "23",
            "image_node": "28",
            "defaults": {
                "strength": 0,
                "start_percent": 0.0,
                "end_percent": 0.33
            }
        },
        # 슬롯 단위 제어(멀티/단일 모두 지원). 기본 슬롯명: "default"
        "control_slots": {
            "default": {
                "apply_node": "23",
                "image_node": "28",
                "label": "Scribble",
                "type": "scribble",
                "ui": {
                    "strength": {"min": 0.0, "max": 1.5, "step": 0.05, "default": 0.0},
                    "start_percent": {"min": 0.0, "max": 1.0, "step": 0.01, "default": 0.0},
                    "end_percent": {"min": 0.0, "max": 1.0, "step": 0.01, "default": 0.33}
                }
            }
        },

        # UI 힌트
        "ui": {
            "showControlNet": True,
            # LoRA 강도 조절 UI 노출 (스타일만 노출)
            "showLora": True,
            "showStyleLora": True,
            "showCharacterLora": False
        },

        # LoRA 매핑(노드/입력 키)
        # - 스타일 LoRA: 노드 42 (기본 1.0)
        # - 캐릭터 LoRA: 노드 14 (기본 0.0)
        "loras": {
            "style": {
                "node": "42",
                "name_input": "lora_name",
                "unet_input": "strength_model",
                "clip_input": "strength_clip",
                "defaults": {"unet": 1, "clip": 1},
                "min": 0.0,
                "max": 1.5,
                "step": 0.05
            },
            "character": {
                "node": "14",
                "name_input": "lora_name",
                "unet_input": "strength_model",
                "clip_input": "strength_clip",
                "defaults": {"unet": 0.0, "clip": 0.0},
                "min": 0.0,
                "max": 1.5,
                "step": 0.05
            }
        },

        # LoRA 슬라이더 사용자 힌트
        "lora_hint": {
            "style": "강도가 높을수록 LOS 스타일 성향이 강해집니다. 낮추면 베이스 모델 특성이 반영됩니다.",
            "character": "캐릭터 LoRA는 선택 사용입니다. 필요 시만 값을 올려주세요."
        },

        # 추천 프롬프트(초보자용 클릭 추가용 문구)
        "recommended_prompt": "no_humans, blue_slime, blue_sky, clouds, simple_background, castle"
    },

    "ILXL_Pixelator": {
        "display_name": "픽셀레이터(입력 이미지 변환)",
        "description": "입력 이미지를 픽셀 아트 스타일로 변환합니다(자동 태깅 고정).",

        # 사용자 프롬프트는 '추가 프롬프트'로만 사용(선택)
        "default_user_prompt": "",

        # 이미지 입력 노드 매핑: LoadImage(32).inputs.image ← Comfy input 파일명
        "image_input": {"image_node": "32", "input_field": "image"},

        # 시드 노드: 메인 KSampler(3)
        "seed_node": "3",

        # 정사각형 고정(800x800)
        "sizes": {"square": {"width": 800, "height": 800}},

        # ILXL 기본 시스템(추가) 프롬프트는 63번 노드 텍스트에 해당
        "style_prompt": "masterpiece, best quality, amazing quality, 4k, very aesthetic, ultra-detailed, (pixel art, dithering, pixelated, sprite art, 8-bit:1.2)",

        # UI 스키마(프런트 조건부 렌더링용)
        "ui": {
            "showAutoTagsReadOnly": True,
            "showSystemPromptReadOnly": True,
            "showNegative": False,
            "aspectOptions": ["square"],
            "additionalPromptTargetNode": "63",
            "showControlNet": False
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


