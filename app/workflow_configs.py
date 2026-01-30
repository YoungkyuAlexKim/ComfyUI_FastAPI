from typing import Dict, Any

# Centralized workflow-specific configurations
# Move/add new workflows here without touching the global config module

WORKFLOW_CONFIGS: Dict[str, Dict[str, Any]] = {
    "RMBG2": {
        "display_name": "배경 제거 (RMBG 2.0)",
        "description": "입력 이미지의 배경을 자동으로 제거하여 투명 배경(PNG)으로 출력합니다.",

        # 프롬프트/네거티브/시드 노드가 없는 단순 워크플로우이므로 매핑은 생략
        "default_user_prompt": "",
        "style_prompt": "",
        "negative_prompt": "",

        # Img2Img: 입력 이미지를 받아야 함
        # RMBG2.json 기준: 노드 1(AILab_LoadImage)의 inputs.image 에 Comfy input 파일명을 주입
        "image_input": {"image_node": "1", "input_field": "image"},

        # UI 힌트: 프롬프트 입력은 숨기고(누끼 전용), 비율/번역/컨트롤/LoRA 등은 비노출
        "ui": {
            "showControlNet": False,
            "showLora": False,
            "showPromptTranslate": False,
            # 분류용: 태그 기반/자연어가 아닌 "도구" 워크플로우
            "templateMode": "utility",
            "disableAspect": True,
            "hideUserPrompt": True,
            # RMBG2는 seed가 결과에 큰 의미가 없으므로 UI에서 숨김(서버는 내부적으로 seed를 생성/기록할 수 있음)
            "hideSeed": True,
            "generateLabel": "배경 제거하기",
            # RMBG2 전용 파라미터(UI에 노출할 값의 기본값/범위)
            "rmbgParams": {
                "mask_blur": {"min": 0, "max": 64, "step": 1, "default": 0},
                "mask_offset": {"min": -64, "max": 64, "step": 1, "default": 0},
            },
        },
        # RMBG 워크플로우 파라미터가 적용되는 노드 정보 (RMBG2.json 기준)
        "rmbg": {"node": "11"},
    },

    "BasicWorkFlow_PixelArt": {
        "display_name": "픽셀 아트",
        "description": "레트로 감성의 픽셀 아트 스타일 이미지를 생성합니다",
        # 테스트 동안 워크플로우 목록에서 숨김 처리
        "hidden": True,

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
        # 테스트 동안 워크플로우 목록에서 숨김 처리
        "hidden": True,

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

    "CJKStyle_Klein_Character": {
        "display_name": "CJK 아트생성",
        "description": "CJK 아트 생성 워크플로우입니다. 상단 탭에서 캐릭터/펫을 전환할 수 있습니다.",

        # 기본 사용자 프롬프트: 자연어(영문) 예시.
        # (한국어로 작성했다면 '프롬프트 변환' 버튼으로 영어로 바꾼 뒤 생성하는 것을 권장합니다.)
        "default_user_prompt": (
            "school girl with serahuku. blue sailor collar,\n\n"
            "light_green hair with blunt_bang. side-twintail hair. star-shaped golden hair ornament. pinky cheek.\n\n"
            "a single brown school bag is positioned next to her.\n\n"
            "featured in simple gray background."
        ),

        # 프롬프트: CLIPTextEncode(107).inputs.text
        "prompt_node": "107",
        "prompt_input_key": "text",

        # 스타일 토큰/룰(숨김 마스터 프롬프트): 항상 프롬프트 앞에 붙습니다.
        # - 트리거 워드 + 캐릭터 핵심 규칙(필수)
        "style_prompt": "CJKUnit., An armless character with simple dot eyes, featuring tiny black legs.",
        "style_prompt_position": "prepend",
        "negative_prompt": "",

        # Seed: RandomNoise(104).inputs.noise_seed
        "seed_node": "104",
        "seed_input_key": "noise_seed",

        # 비율 기반 사이즈 (프론트는 square/landscape/portrait 선택)
        "sizes": {
            "square": {"width": 1024, "height": 1024},
            "landscape": {"width": 1344, "height": 768},
            "portrait": {"width": 768, "height": 1344},
        },

        # 이 워크플로우는 width/height가 PrimitiveInt 노드(122/123)에서 결정됩니다.
        # 서버는 이 노드들의 inputs.value만 업데이트하면, 연결된 모든 노드가 동일한 크기를 참조하게 됩니다.
        "size_nodes": {"width_node": "122", "height_node": "123", "value_key": "value"},

        # LoRA: LoraLoaderModelOnly(117).inputs.strength_model
        "loras": {
            "style": {
                "node": "117",
                "name_input": "lora_name",
                "unet_input": "strength_model",
                # LoraLoaderModelOnly는 clip strength가 없으므로 동일 키로 매핑
                "clip_input": "strength_model",
                "defaults": {"unet": 1.0, "clip": 1.0},
                "min": 0.0,
                "max": 1.5,
                "step": 0.05,
            }
        },
        "lora_hint": {
            "style": "강도를 높일수록 CJK 스타일 성향이 강해집니다.",
            "character": "",
        },

        # 사용자 입력 이미지 없이, ComfyUI input 폴더에 미리 존재하는 레퍼런스 이미지를 사용합니다.
        # (없으면 서버가 친절한 에러로 안내합니다.)
        "required_comfy_inputs": ["CJKCharacterBase.png"],

        # UI 힌트
        "ui": {
            "showControlNet": False,
            "showLora": True,
            "showStyleLora": True,
            "showCharacterLora": False,
            "showPromptTranslate": True,
            "templateMode": "natural",
            # 내부 뎁스(탭) 분기:
            # - 기본(Txt2Img) 탭: 캐릭터 생성
            # - 보조(Img2Img) 탭: 펫 생성 (입력 이미지를 요구하지 않는 Txt2Img 워크플로우지만, UI 탭 구조를 재사용합니다)
            "related": {"img2img": "CJKStyle_Klein_Pet", "items": "CJKStyle_Klein_Items"},
            "modeTabLabels": {"txt2img": "캐릭터생성", "img2img": "펫생성", "items": "아이템생성"},
            "modeTabIcons": {"txt2img": "🧑", "img2img": "🐾", "items": "🪚"},
        },
    },

    "CJKStyle_Klein_Pet": {
        # 좌측 목록에서는 숨기고, CJK 아트생성 내부 탭에서만 사용합니다.
        "hidden": True,
        "display_name": "CJK 아트생성 (펫)",
        "description": "Klein(Flux2) 기반 CJK 펫 아트 생성 워크플로우입니다. 메인(펫) LoRA + 서브(톤 맞춤) LoRA를 함께 사용합니다.",

        # 기본 사용자 프롬프트(간단 예시)
        "default_user_prompt": "a small dog pet with single horn. two-tone fur.\n\nsimple gray background",

        # 프롬프트: CLIPTextEncode(94).inputs.text
        "prompt_node": "94",
        "prompt_input_key": "text",

        # 트리거: CJKPet.
        "style_prompt": "CJKPet.",
        "style_prompt_position": "prepend",
        "negative_prompt": "",

        # Seed: RandomNoise(92).inputs.noise_seed
        "seed_node": "92",
        "seed_input_key": "noise_seed",

        # Size: PrimitiveInt(90/91).inputs.value
        "sizes": {
            "square": {"width": 768, "height": 768},
            "landscape": {"width": 1024, "height": 576},
            "portrait": {"width": 576, "height": 1024},
        },
        "size_nodes": {"width_node": "90", "height_node": "91", "value_key": "value"},

        # LoRA 매핑:
        # - 메인(펫) LoRA: node 100 (CJKStyle_pet.safetensors)
        # - 서브(톤 맞춤) LoRA: node 102 (CJKStyle_ver3.safetensors, 기본 0.3 유지 권장)
        #
        # UI에서 슬롯 이름은 기존 구조를 재사용합니다:
        # - style => 메인(펫)
        # - character => 서브(톤 맞춤)
        "loras": {
            "style": {
                "node": "100",
                "name_input": "lora_name",
                "unet_input": "strength_model",
                "clip_input": "strength_model",
                "defaults": {"unet": 1.0, "clip": 1.0},
                "min": 0.0,
                "max": 1.5,
                "step": 0.05,
            },
            "character": {
                "node": "102",
                "name_input": "lora_name",
                "unet_input": "strength_model",
                "clip_input": "strength_model",
                "defaults": {"unet": 0.3, "clip": 0.3},
                "min": 0.0,
                "max": 1.5,
                "step": 0.05,
            },
        },
        "lora_hint": {
            "style": "메인(펫) LoRA 강도입니다. 기본값 1.0을 기준으로 조절하세요.",
            "character": "서브(톤 맞춤) LoRA입니다. 기본값 0.3을 유지하는 것을 권장합니다.",
        },

        "ui": {
            "showControlNet": False,
            "showLora": True,
            "showStyleLora": True,
            "showCharacterLora": True,
            "showPromptTranslate": True,
            "templateMode": "natural",
            # LoRA 라벨 커스텀(기존 CSS/DOM 구조 유지)
            "loraLabels": {
                "style": "Pet LoRA (main)",
                "character": "Style LoRA (sub)",
            },
            # 기본값(0.3)을 보존하기 위해, 서브 LoRA는 "고급 토글"로 잠금(기본: 숨김)
            "loraAdvanced": {
                "enableCharacterToggle": True,
                "defaultUnlocked": False,
                "label": "서브 LoRA 조절(고급 · 기본 0.3 유지 권장)",
            },
        },
    },

    "CJKStyle_Klein_Items": {
        # 좌측 목록에서는 숨기고, CJK 아트생성 내부 탭에서만 사용합니다.
        "hidden": True,
        "display_name": "CJK 아트생성 (아이템)",
        "description": "Klein(Flux2) 기반 CJK 아이템/오브젝트 어셋 생성 워크플로우입니다. 메인(아이템) LoRA + 서브(톤 맞춤) LoRA를 함께 사용합니다.",

        # 기본 사용자 프롬프트(간단 예시)
        "default_user_prompt": "a single game item asset, featured in simple gray background.",

        # 프롬프트: CLIPTextEncode(94).inputs.text
        "prompt_node": "94",
        "prompt_input_key": "text",

        # 트리거: 워크플로우 JSON에선 CJKUnit. 로 구성되어 있어 그대로 사용합니다.
        "style_prompt": "CJKUnit.",
        "style_prompt_position": "prepend",
        "negative_prompt": "",

        # Seed: RandomNoise(92).inputs.noise_seed
        "seed_node": "92",
        "seed_input_key": "noise_seed",

        # Size: PrimitiveInt(90/91).inputs.value
        "sizes": {
            "square": {"width": 768, "height": 768},
            "landscape": {"width": 1024, "height": 576},
            "portrait": {"width": 576, "height": 1024},
        },
        "size_nodes": {"width_node": "90", "height_node": "91", "value_key": "value"},

        # LoRA 매핑:
        # - 메인(아이템) LoRA: node 100 (CJKItems_001.safetensors)
        # - 서브(톤 맞춤) LoRA: node 102 (CJKStyle_ver3.safetensors, 기본 0.3 유지 권장)
        "loras": {
            "style": {
                "node": "100",
                "name_input": "lora_name",
                "unet_input": "strength_model",
                "clip_input": "strength_model",
                "defaults": {"unet": 1.0, "clip": 1.0},
                "min": 0.0,
                "max": 1.5,
                "step": 0.05,
            },
            "character": {
                "node": "102",
                "name_input": "lora_name",
                "unet_input": "strength_model",
                "clip_input": "strength_model",
                "defaults": {"unet": 0.3, "clip": 0.3},
                "min": 0.0,
                "max": 1.5,
                "step": 0.05,
            },
        },
        "lora_hint": {
            "style": "메인(아이템) LoRA 강도입니다. 기본값 1.0을 기준으로 조절하세요.",
            "character": "서브(톤 맞춤) LoRA입니다. 기본값 0.3을 유지하는 것을 권장합니다.",
        },

        "ui": {
            "showControlNet": False,
            "showLora": True,
            "showStyleLora": True,
            "showCharacterLora": True,
            "showPromptTranslate": True,
            "templateMode": "natural",
            # 라벨 커스텀(기존 CSS/DOM 구조 유지)
            "loraLabels": {
                "style": "Item LoRA (main)",
                "character": "Style LoRA (sub)",
            },
            # 기본값(0.3)을 보존하기 위해, 서브 LoRA는 "고급 토글"로 잠금(기본: 숨김)
            "loraAdvanced": {
                "enableCharacterToggle": True,
                "defaultUnlocked": False,
                "label": "서브 LoRA 조절(고급 · 기본 0.3 유지 권장)",
            },
        },
    },


    "LOSstyle_Qwen": {
        "display_name": "LOS 스타일",
        "description": "Qwen 이미지 베이스 + Lightning LoRA 고정, 스타일 LoRA 조절형(컨트롤넷 없음)",

        # 사용자 프롬프트: 자연어(한국어) 기본값
        "default_user_prompt": "짧은 갈색 머리에 노란 코트를 입은 귀엽고 스타일화된 소녀가 어두운 아늑한 도서관에서 커다랗고 미소 짓는 파란 슬라임을 안고 있는 장면. 오래된 책들로 가득한 높은 나무 책장과 타일 바닥이 보이는 실내 일러스트로, 캐릭터와 마스코트의 친밀한 분위기를 강조해 주세요. 카메라는 위쪽에서 내려다보는 시점입니다.",

        # 노드 ID 매핑
        "prompt_node": "6",
        "negative_prompt_node": "7",
        "seed_node": "3",
        "latent_image_node": "58",

        # 시스템 스타일 프롬프트: LOSart를 시스템 프롬프트로 이동
        "style_prompt": "LOSart",
        # 네거티브 프롬프트는 공란 유지(고급형 베이스 모델 가정)
        "negative_prompt": "",

        # 권장 해상도: 정사각 1280x1280, 16:9 가로/세로는 이를 기준으로 산정
        "sizes": {
            "square": {"width": 1280, "height": 1280},
            "landscape": {"width": 1280, "height": 720},
            "portrait": {"width": 720, "height": 1280},
        },

        # ControlNet 미사용
        # "controlnet": 없음
        # "control_slots": 없음

        # UI 힌트: 컨트롤넷 비노출, 스타일 LoRA만 노출(캐릭터 LoRA는 숨김)
        "ui": {
            "showControlNet": False,
            "showLora": True,
            "showStyleLora": True,
            "showCharacterLora": False,
            # LOS 스타일: 한국어 자연어 → 이미지 생성용 영어 프롬프트 변환 버튼 사용
            "showPromptTranslate": True,
            # 자연어 템플릿 모드 표시(프론트의 중복 병합 로직에 사용)
            "templateMode": "natural",
            # 편집(img2img) 관련 워크플로우 링크(목록 비노출 전용)
            "related": {"img2img": "LOSStyle_Klein_Img2Img"}
        },

        # LoRA 매핑: Lightning(고정), 스타일(조절), 캐릭터(0.0, 비노출)
        # Qwen 워크플로우는 LoraLoaderModelOnly를 사용하므로 strength_clip이 없습니다.
        # 프론트가 단일 슬라이더로 값을 보낼 때도 안전하게 적용되도록 clip_input을 strength_model로 동일 지정합니다.
        "loras": {
            "style": {
                "node": "75",
                "name_input": "lora_name",
                "unet_input": "strength_model",
                "clip_input": "strength_model",
                "defaults": {"unet": 1.0, "clip": 1.0},
                "min": 0.0,
                "max": 1.5,
                "step": 0.05
            },
            "character": {
                "node": "76",
                "name_input": "lora_name",
                "unet_input": "strength_model",
                "clip_input": "strength_model",
                "defaults": {"unet": 0.0, "clip": 0.0},
                "min": 0.0,
                "max": 1.5,
                "step": 0.05
            }
        },

        # 사용자 안내 문구
        "lora_hint": {
            "style": "강도를 높일수록 LOS 스타일 성향이 강해집니다.",
            "character": "캐릭터 LoRA는 현재 숨김 상태입니다. 필요 시만 사용하세요."
        }
    },

    "LOSStyle_Klein_Img2Img": {
        "hidden": True,
        "display_name": "LOS 스타일 — 편집 (Klein)",
        "description": "Klein 기반 Flux2 Img2Img 편집 워크플로우입니다. (LOS 스타일 편집 대체)",

        # 프롬프트: 단일 positive conditioning만 사용 (negative는 ConditioningZeroOut 기반)
        # - CLIPTextEncode(107) inputs.text
        "prompt_node": "107",
        "prompt_input_key": "text",
        # Negative prompt node 없음(워크플로우 구조상 별도 네거티브 텍스트 인코딩을 쓰지 않음)
        # "negative_prompt_node": 없음

        # Img2Img 기본 사용자 프롬프트
        "default_user_prompt": "이미지에서 파란 슬라임을 제거하고, 강아지로 교체해 주세요.",

        # 워크플로우 기본 스타일 토큰 (유저 프롬프트와 함께 positive 텍스트로 들어감)
        # (학습 캡션 형태와 맞추기 위해 콤마 형태 사용)
        "style_prompt": "LOSart",
        "negative_prompt": "",

        # Seed: RandomNoise(104) inputs.noise_seed
        "seed_node": "104",
        "seed_input_key": "noise_seed",

        # 입력 이미지 매핑(필수): LoadImage(81) inputs.image
        "image_input": {"image_node": "81", "input_field": "image"},

        # LoRA: 스타일 LoRA 강도 조절(노드 117)
        "loras": {
            "style": {
                "node": "117",
                "name_input": "lora_name",
                "unet_input": "strength_model",
                # LoraLoaderModelOnly는 clip strength가 없으므로 동일 키로 매핑
                "clip_input": "strength_model",
                "defaults": {"unet": 1.0, "clip": 1.0},
                "min": 0.0,
                "max": 1.5,
                "step": 0.05,
            }
        },
        "lora_hint": {
            "style": "강도를 높일수록 LOS 스타일 성향이 강해집니다.",
            "character": "",
        },

        # UI 힌트: Img2Img에서는 입력 비율을 따르므로 비율 UI 비활성
        "ui": {
            "showControlNet": False,
            "showLora": True,
            "showStyleLora": True,
            "showCharacterLora": False,
            "showPromptTranslate": True,
            "templateMode": "natural",
            "disableAspect": True,
        },
    },

    "OHDstyle_Qwen": {
        "display_name": "OHD 스타일",
        "description": "Qwen 이미지 베이스 + Lightning LoRA 고정, 스타일 LoRA 조절형(컨트롤넷 없음)",

        # 사용자 프롬프트: 자연어(한국어) 기본값
        "default_user_prompt": "짧은 갈색 머리에 노란 코트를 입은 귀엽고 스타일화된 소녀가 어두운 아늑한 도서관에서 커다랗고 미소 짓는 파란 슬라임을 안고 있는 장면. 오래된 책들로 가득한 높은 나무 책장과 타일 바닥이 보이는 실내 일러스트로, 캐릭터와 마스코트의 친밀한 분위기를 강조해 주세요. 카메라는 위쪽에서 내려다보는 시점입니다.",

        # 노드 ID 매핑 (OHDstyle_Qwen.json 기준)
        "prompt_node": "6",
        "negative_prompt_node": "7",
        "seed_node": "3",
        "latent_image_node": "58",

        # 시스템 스타일 프롬프트
        "style_prompt": "OHDart, Cute cozy cartoon style with thick clean outlines and soft pastel coloring",
        "negative_prompt": "",

        # 권장 해상도: 정사각 1280x1280
        "sizes": {
            "square": {"width": 1280, "height": 1280},
            "landscape": {"width": 1280, "height": 720},
            "portrait": {"width": 720, "height": 1280},
        },

        # UI 힌트: 컨트롤넷 비노출, 스타일 LoRA만 노출(캐릭터 LoRA는 숨김)
        "ui": {
            "showControlNet": False,
            "showLora": True,
            "showStyleLora": True,
            "showCharacterLora": False,
            # OHD 스타일: 한국어 자연어 → 이미지 생성용 영어 프롬프트 변환 버튼 사용
            "showPromptTranslate": True,
            "templateMode": "natural",
            # Img2Img는 Klein 워크플로우로 연결
            "related": {"img2img": "OHDStyle_Klein_Img2Img"},
        },

        # LoRA 매핑: Lightning(고정), 스타일(조절), 캐릭터(0.0, 비노출)
        # Qwen 워크플로우는 LoraLoaderModelOnly를 사용하므로 strength_clip이 없습니다.
        "loras": {
            "style": {
                "node": "75",
                "name_input": "lora_name",
                "unet_input": "strength_model",
                "clip_input": "strength_model",
                "defaults": {"unet": 1.0, "clip": 1.0},
                "min": 0.0,
                "max": 1.5,
                "step": 0.05,
            },
            "character": {
                "node": "76",
                "name_input": "lora_name",
                "unet_input": "strength_model",
                "clip_input": "strength_model",
                "defaults": {"unet": 0.0, "clip": 0.0},
                "min": 0.0,
                "max": 1.5,
                "step": 0.05,
            },
        },

        # 사용자 안내 문구
        "lora_hint": {
            "style": "강도를 높일수록 OHD 스타일 성향이 강해집니다.",
            "character": "캐릭터 LoRA는 현재 숨김 상태입니다. 필요 시만 사용하세요.",
        },
    },

    "OHDStyle_Klein_Img2Img": {
        "hidden": True,
        "display_name": "OHD 스타일 — 편집 (Klein)",
        "description": "Klein 기반 Flux2 Img2Img 편집 워크플로우입니다. (OHD 스타일 편집 대체)",

        # 프롬프트: 단일 positive conditioning만 사용 (negative는 ConditioningZeroOut 기반)
        # - CLIPTextEncode(107) inputs.text
        "prompt_node": "107",
        "prompt_input_key": "text",
        # Negative prompt node 없음(워크플로우 구조상 별도 네거티브 텍스트 인코딩을 쓰지 않음)
        # "negative_prompt_node": 없음

        # Img2Img 기본 사용자 프롬프트
        "default_user_prompt": "이미지에서 파란 슬라임을 제거하고, 강아지로 교체해 주세요.",

        # 워크플로우 기본 스타일 토큰 (유저 프롬프트와 함께 positive 텍스트로 들어감)
        "style_prompt": "OHDart.",
        "negative_prompt": "",

        # Seed: RandomNoise(104) inputs.noise_seed
        "seed_node": "104",
        "seed_input_key": "noise_seed",

        # 입력 이미지 매핑(필수): LoadImage(81) inputs.image
        "image_input": {"image_node": "81", "input_field": "image"},

        # LoRA: 스타일 LoRA 강도 조절(노드 117). (name은 고정이지만 슬라이더로 strength_model 조절)
        "loras": {
            "style": {
                "node": "117",
                "name_input": "lora_name",
                "unet_input": "strength_model",
                # LoraLoaderModelOnly는 clip strength가 없으므로 동일 키로 매핑
                "clip_input": "strength_model",
                "defaults": {"unet": 1.0, "clip": 1.0},
                "min": 0.0,
                "max": 1.5,
                "step": 0.05,
            }
        },
        "lora_hint": {
            "style": "강도를 높일수록 Klein 스타일 성향이 강해집니다.",
            "character": "",
        },

        # UI 힌트: Img2Img에서는 입력 비율을 따르므로 비율 UI 비활성
        "ui": {
            "showControlNet": False,
            "showLora": True,
            "showStyleLora": True,
            "showCharacterLora": False,
            "showPromptTranslate": True,
            "templateMode": "natural",
            "disableAspect": True,
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


