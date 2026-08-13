from typing import Dict, Any

# Centralized workflow-specific configurations
# Move/add new workflows here without touching the global config module

WORKFLOW_CONFIGS: Dict[str, Dict[str, Any]] = {
    "RMBG2": {
        "display_name": "배경 제거 (RMBG 2.0)",
        "description": "입력 이미지의 배경을 자동으로 제거하여 투명 배경(PNG)으로 출력합니다.",
        "category": "image_tools",
        "capability": "remove_background",
        "mcp_public": True,

        # 프롬프트/네거티브/시드 노드가 없는 단순 워크플로우이므로 매핑은 생략
        "default_user_prompt": "",
        "style_prompt": "",
        "negative_prompt": "",

        # Img2Img: 입력 이미지를 받아야 함
        # RMBG2.json 기준: 노드 1(AILab_LoadImage)의 inputs.image 에 Comfy input 파일명을 주입
        "image_input": {"image_node": "1", "input_field": "image"},

        # UI 힌트: 프롬프트 입력은 숨기고(누끼 전용), 비율/번역/컨트롤/LoRA 등은 비노출
        "ui": {
            # FontAwesome icon name (frontend): <i class="fas fa-...">
            "icon": "cut",
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

    "NanoBanana": {
        "display_name": "기본 워크플로우",
        "description": "Nano Banana 계열 모델을 선택해 자연어 프롬프트 이미지를 생성합니다.",
        "hidden": False,
        "category": "image_generation",
        "capability": "create_image",
        "mcp_public": True,

        # 기본 프롬프트는 비워두고, placeholder로만 안내합니다.
        "default_user_prompt": "",
        "style_prompt_position": "prepend",
        "style_prompt": (
            "TASK: Create one finished image that follows the USER REQUEST.\n"
            "PRIORITY: Follow the user's explicit subject, action, composition, style, and output requirements.\n"
            "REFERENCE IMAGES: When references are attached, use them only for the identities, designs, or visual details requested by the user; do not reproduce a reference-sheet layout unless requested.\n"
            "OUTPUT: Return one clean final image. Do not add unrequested text, captions, logos, borders, or watermarks."
        ),
        "negative_prompt": "",

        # Provider routing (handled in app/services/generation.py)
        "provider": "openrouter",
        # UI 기본값은 Nano Banana Pro 2K이며, 요청 시 허용된 모델/해상도로 변경할 수 있습니다.
        "openrouter": {"model": "google/gemini-3-pro-image", "mode": "text-to-image"},

        "ui": {
            "icon": "magic",
            # Separate category for NanoBanana family
            "templateMode": "nanobanana",
            # Enable @Name character mentions UI/logic ONLY for this base txt2img workflow.
            "characterMentions": True,
            "showLora": False,
            "showPromptTranslate": True,
            "userPromptPlaceholder": "무엇을 만들고 싶으신가요? 간단히 적어주세요.. (예: 한복을 입은 소녀, 비 오는 밤의 네온 거리)",
            "related": {"img2img": "NanoBanana_Img2Img"},
            "modeTabLabels": {"txt2img": "생성", "img2img": "편집"},
        },
    },

    "GameUI_Elements": {
        "display_name": "게임 UI 엘리먼트 메이커",
        "description": "원하는 게임 UI 엘리먼트를 설명하면 후보 4개를 만들고 개별 PNG로 자동 분리합니다.",
        "hidden": False,
        "category": "image_generation",
        "capability": "create_game_ui_assets",
        "mcp_public": True,
        "default_user_prompt": "",
        "style_prompt": "",
        "negative_prompt": "",
        "provider": "openrouter",
        "openrouter": {
            "model": "openai/gpt-image-2",
            "mode": "text-to-image",
            "allowed_models": ["openai/gpt-image-2"],
            "default_resolution": "2K",
            "default_quality": "medium",
            "workflow_scoped_preferences": True,
        },
        "ui": {
            "icon": "icons",
            "templateMode": "gameui",
            "badges": ["MVP"],
            "showLora": False,
            "showPromptTranslate": True,
            "hideSeed": True,
            "disableAspect": True,
            "hideHostedImageOptions": True,
            "generateLabel": "후보 4개 만들기",
            "userPromptLabel": "무엇을 만들까요?",
            "userPromptPlaceholder": "용도, 형태, 재질, 색감과 스타일을 자유롭게 설명해 주세요.",
            "userPromptHelp": "아래 예시에서 시작하거나 직접 적어보세요. 형태와 용도는 문장 안에서 자유롭게 요청할 수 있습니다.",
            "imageInputMulti": {"enabled": True, "max": 3},
            "gameUiTool": {
                "enabled": True,
                "allowReferences": True,
                "grid": "2x2",
                "variantCount": 4,
                "promptPresetInitialCount": 6,
                "defaults": {
                    "backgroundMode": "transparent",
                },
            },
            "promptTemplates": [
                {
                    "title": "얼음 마법 아이콘",
                    "category": "아이콘과 심벌",
                    "text": "모바일 다크 판타지 RPG용 얼음 마법 스킬 아이콘. 중앙에 푸른 수정과 날카롭게 퍼지는 눈꽃, 차가운 청백색 광원, 강한 실루엣과 굵은 명암. 작은 화면에서도 한눈에 읽히게 만들고 글자와 배경 장면은 넣지 마세요."
                },
                {
                    "title": "독 상태이상",
                    "category": "아이콘과 심벌",
                    "text": "전략 RPG의 독 상태이상 아이콘. 금이 간 녹색 유리병에서 보랏빛 독기가 피어오르는 모습, 위험을 알리는 날카로운 형태, 어두운 테두리와 높은 색 대비. 32픽셀에서도 식별되도록 세부 묘사는 절제하고 글자는 넣지 마세요."
                },
                {
                    "title": "전설 등급 검",
                    "category": "아이콘과 심벌",
                    "text": "핵앤슬래시 게임의 전설 등급 검 아이템. 비스듬히 놓인 검은 강철 대검, 금빛 룬과 붉은 보석, 오래된 전투 흔적, 고급 판타지 아이템 렌더링. 검 전체가 잘리지 않게 보이고 배경 장면과 글자는 넣지 마세요."
                },
                {
                    "title": "골드 재화 토큰",
                    "category": "아이콘과 심벌",
                    "text": "캐주얼 판타지 게임의 골드 재화 토큰. 왕관 문양이 양각된 두꺼운 원형 금화, 따뜻한 금빛, 부드러운 하이라이트와 또렷한 외곽선, 친근하고 고급스러운 3D 스타일. 숫자와 글자 없이 독립된 토큰 하나로 만드세요."
                },
                {
                    "title": "원형 공격 버튼",
                    "category": "버튼과 컨트롤",
                    "text": "모바일 액션 RPG용 원형 기본 공격 버튼. 중앙에 은빛 검 심벌, 두꺼운 청동 테두리, 어두운 가죽 질감, 눌러도 형태가 잘 읽히는 단단한 입체감. 작은 화면에서 터치 버튼으로 보이게 만들고 글자와 배경 장면은 넣지 마세요."
                },
                {
                    "title": "가로 확인 버튼",
                    "category": "버튼과 컨트롤",
                    "text": "근미래 우주선 인터페이스용 가로형 확인 버튼 스킨. 짙은 건메탈 표면, 얇은 청록색 에너지 라인, 잘린 모서리와 절제된 광택. 중앙은 나중에 라벨을 넣을 수 있도록 깨끗하고 넓게 비우며 글자는 생성하지 마세요."
                },
                {
                    "title": "목재 탭 버튼",
                    "category": "버튼과 컨트롤",
                    "text": "아늑한 농장 시뮬레이션 게임용 가로 탭 버튼. 밝은 참나무 판자, 둥근 모서리, 작은 잎사귀 장식과 부드러운 그림자, 손으로 만든 듯한 친근한 스타일. 중앙 라벨 영역은 비우고 배경 장면과 글자는 넣지 마세요."
                },
                {
                    "title": "초상화 프레임",
                    "category": "프레임과 표식",
                    "text": "전설 등급 보스 캐릭터 초상화용 세로 프레임. 검게 그을린 금속과 붉은 보석, 위협적인 고딕 가시 장식, 상단에 작은 왕관 형태. 중앙 초상화 영역은 넓고 완전히 열린 상태로 두며 인물과 글자는 넣지 마세요."
                },
                {
                    "title": "인벤토리 슬롯",
                    "category": "프레임과 표식",
                    "text": "중세 판타지 인벤토리용 정사각형 아이템 슬롯. 낡은 철제 테두리와 짙은 가죽 안쪽 면, 모서리의 작은 리벳, 선택되지 않은 기본 상태. 아이템을 올릴 중앙 공간은 단순하게 유지하고 아이템과 숫자는 넣지 마세요."
                },
                {
                    "title": "길드 엠블럼",
                    "category": "프레임과 표식",
                    "text": "북부 용병 길드를 상징하는 방패형 엠블럼. 은빛 늑대 머리와 산맥 문양, 남색 에나멜과 마모된 은 테두리, 절제되고 권위 있는 중세 판타지 스타일. 독립된 완성형 문장으로 만들고 글자는 넣지 마세요."
                },
                {
                    "title": "랭크 업적 배지",
                    "category": "프레임과 표식",
                    "text": "경쟁 게임의 최상위 랭크 업적 배지. 날개가 펼쳐진 육각형 실루엣, 백금과 보라색 수정, 중심의 추상적인 별 문양, 선명한 대칭 구조와 고급스러운 광택. 숫자와 글자 없이 작게 축소해도 등급이 느껴지게 만드세요."
                },
                {
                    "title": "체력 오브",
                    "category": "독립 HUD 요소",
                    "text": "고딕 액션 RPG의 체력 표시용 붉은 유리 오브. 검은 철제 받침과 가느다란 악마 날개 장식, 내부에 천천히 소용돌이치는 붉은 액체, 정면에서 본 독립 HUD 요소. 다른 패널이나 숫자, 글자는 붙이지 마세요."
                },
            ],
        },
    },

    "NanoBanana_Img2Img": {
        "hidden": True,
        "display_name": "기본 워크플로우 — 편집",
        "description": "이미지를 입력으로 받아 자연어로 편집합니다. (단일 입력)",
        "category": "image_generation",
        "capability": "create_image",
        "mcp_public": True,

        "default_user_prompt": "Edit the provided image according to the requested changes.",
        "style_prompt_position": "prepend",
        "style_prompt": (
            "TASK: Edit the provided image or images according to the USER REQUEST.\n"
            "INPUT ROLES: Treat Image 1 as the base image unless the user explicitly assigns different roles. Treat additional images as references or source elements in their provided order.\n"
            "EDIT BOUNDARY: Change only what the user requests. Keep everything else the same unless a requested change logically requires a local adjustment.\n"
            "PRESERVE: Maintain unrequested subject identity, facial features, body proportions, composition, camera angle, geometry, background, palette, lighting, rendering style, and existing text or design elements.\n"
            "OUTPUT: Return one clean edited image. Do not add unrequested text, captions, logos, borders, or watermarks."
        ),
        "negative_prompt": "",

        "provider": "openrouter",
        "openrouter": {"model": "google/gemini-3-pro-image", "mode": "image-edit"},

        # 존재만으로 UI가 '입력 이미지 필요'로 인지하도록 둡니다.
        # (ComfyUI workflow JSON에는 주입하지 않으며, OpenRouter provider 경로에서만 사용)
        "image_input": {"image_node": "_openrouter", "input_field": "image"},

        "ui": {
            "icon": "edit",
            "templateMode": "nanobanana",
            "showLora": False,
            "showPromptTranslate": True,
            # 나노바나나 편집은 "입력 비율 유지(자동)" 또는 "출력 비율 지정"을 선택할 수 있습니다.
            # - auto: 입력 이미지 비율을 그대로 따름(권장)
            # - square/landscape/portrait: 출력 비율을 지정(모델이 확장/크롭을 수행할 수 있음)
            "disableAspect": False,
            "aspectOptions": ["auto", "square", "landscape", "portrait"],
            "promptTemplates": [
                {
                    "title": "골든아워 조명",
                    "category": "조명 변경",
                    "text": "원본의 인물, 의상, 배경과 구도는 그대로 유지하고 따뜻한 골든아워 조명과 자연스러운 그림자만 적용해 주세요."
                },
                {
                    "title": "강한 역광",
                    "category": "조명 변경",
                    "text": "원본의 모든 요소와 카메라 구도는 그대로 유지하고, 피사체 뒤에서 들어오는 강한 영화적 역광만 추가해 주세요."
                },
                {
                    "title": "부드러운 스튜디오 조명",
                    "category": "조명 변경",
                    "text": "얼굴과 형태를 바꾸지 말고 부드러운 스튜디오 조명과 완만한 그림자를 적용해 주세요. 기존 색감과 배경은 그대로 유지해 주세요."
                },
                {
                    "title": "네온 조명",
                    "category": "조명 변경",
                    "text": "장면의 내용과 구도는 그대로 두고 핑크와 블루 계열의 네온 조명, 반사광과 일관된 그림자만 적용해 주세요."
                },
            ],
            # Phase C: multi-image img2img 지원 (최대 14장)
            # UI에서 선택 순서가 곧 모델에 전달되는 순서입니다.
            "imageInputMulti": {"enabled": True, "max": 14},
        },
    },

    "NanoBanana_TurnaroundSheet": {
        "display_name": "턴어라운드 시트 (캐릭터)",
        "description": "캐릭터 1장을 넣으면 정면/측면/후면 등 턴어라운드 시트로 만들어줍니다.",
        "hidden": False,
        "category": "image_generation",
        "capability": "create_character_sheet",
        "mcp_public": True,

        # 사용자가 아무 설명을 안 해도 일단 결과가 나오도록 기본 프롬프트 제공
        # (툴 워크플로우에서는 프롬프트 입력창을 숨기므로, 내부 프롬프트는 영어로 고정하는 것이 안정적입니다.)
        "default_user_prompt": "Create a character turnaround sheet from the provided character reference.",
        "style_prompt_position": "prepend",
        "style_prompt": (
            "GOAL: Create a production-ready character turnaround sheet for a game-art pipeline.\n"
            "REFERENCE: Image 1 is the sole source of character identity and design.\n"
            "VIEW SPECIFICATION: Follow the exact view count and ordered view list stated in the user requirements. Create each requested view exactly once; do not add, omit, or duplicate views.\n"
            "CONSISTENCY: Preserve the same face, hairstyle, body proportions, outfit construction, colors, materials, accessories, and art style in every view. Preserve asymmetrical details on the correct side of the character.\n"
            "POSE AND CAMERA: Neutral standing pose, arms relaxed where the design allows, full body visible with head and feet included, consistent scale, eye-level camera, and minimal perspective distortion.\n"
            "LAYOUT: Place views in one horizontal sheet in the specified order, evenly spaced and clearly separated, on a simple neutral background with uniform neutral lighting.\n"
            "BOUNDARY: Do not redesign, beautify, simplify, add, or remove character details.\n"
            "OUTPUT: One clean sheet image. Do not add labels, captions, borders, logos, or watermarks."
        ),
        "negative_prompt": "",

        "provider": "openrouter",
        "openrouter": {"model": "google/gemini-3-pro-image", "mode": "image-edit"},

        # 입력 이미지가 필수인 도구
        "image_input": {"image_node": "_openrouter", "input_field": "image"},

        "ui": {
            "templateMode": "nanobanana",
            "showLora": False,
            "showPromptTranslate": True,
            "generateLabel": "턴어라운드 시트 만들기",
            # 툴 UI로만 조작하도록 프롬프트 입력은 숨김(혼동 방지)
            "hideUserPrompt": True,
            # 시트는 가로가 유리하므로 기본은 Landscape만 노출
            "disableAspect": False,
            "aspectOptions": ["landscape"],
            # Tool UI options (frontend hint)
            "turnaroundTool": {
                "enabled": True,
                "viewPresets": [
                    {"value": "5", "label": "5뷰 (정면/3-4/측면/후면/3-4후면)"},
                    {"value": "3", "label": "3뷰 (정면/측면/후면)"},
                    {"value": "8", "label": "8뷰 (좌/우 포함)"},
                ],
                "defaultViews": "5",
            },
        },
    },

    "NanoBanana_ExpressionPortraitSheet": {
        "display_name": "표정 포트레이트 시트 (캐릭터)",
        "description": "캐릭터 1장을 넣으면 같은 그림체/같은 인상으로 표정 포트레이트들을 한 장의 시트로 만들어줍니다.",
        "hidden": False,
        "category": "image_generation",
        "capability": "create_character_sheet",
        "mcp_public": True,

        # 툴 워크플로우:
        # - 기본 동작은 "프롬프트 없이도" 결과가 나오도록 영어 기본 프롬프트를 둡니다.
        # - 사용자가 원하면 "화풍(스타일) 힌트"를 선택 입력으로 추가할 수 있도록 UI에서 프롬프트 입력을 엽니다.
        "default_user_prompt": "Create a portrait expression sheet from the provided character reference.",
        "style_prompt_position": "prepend",
        "style_prompt": (
            "GOAL: Create a production-ready character expression portrait sheet for a game-art pipeline.\n"
            "REFERENCE: Image 1 is the source of character identity and design. Match its art style unless a STYLE OVERRIDE is explicitly provided.\n"
            "EXPRESSION SPECIFICATION: Follow the exact portrait count, grid, and ordered expression list stated in the user requirements. Show each requested expression exactly once; do not add, omit, or duplicate portraits.\n"
            "IDENTITY: Preserve facial structure, eye shape and color, hairstyle, age, body proportions, outfit, colors, materials, and accessories across every portrait. Change only expression-related facial muscles and subtle expression-appropriate head movement.\n"
            "FRAMING: Head-and-shoulders portraits, near-front view, eyes visible where appropriate, consistent crop, head size, camera, background, and lighting in every cell.\n"
            "LAYOUT: One evenly divided grid on a simple neutral background, with one centered portrait per cell.\n"
            "OUTPUT: One clean sheet image. Do not add labels, captions, borders, logos, or watermarks."
        ),
        "negative_prompt": "",

        "provider": "openrouter",
        "openrouter": {"model": "google/gemini-3-pro-image", "mode": "image-edit"},

        # 입력 이미지가 필수인 도구
        "image_input": {"image_node": "_openrouter", "input_field": "image"},

        "ui": {
            "templateMode": "nanobanana",
            "showLora": False,
            "showPromptTranslate": True,
            "generateLabel": "표정 포트레이트 만들기",
            # 스타일 힌트(선택 입력)로 프롬프트 입력을 사용
            "hideUserPrompt": False,
            # 프롬프트가 비어 있으면 default_user_prompt로 동작(기존과 동일)
            "userPromptOptional": True,
            "userPromptLabel": "스타일(선택)",
            "userPromptHelp": (
                "여기에는 '화풍/렌더링'만 적어주세요. (예: 수채화, 지브리풍, 애니 셀채색, 필름 그레인)\n"
                "비워두면 입력 이미지의 기존 스타일을 그대로 따릅니다."
            ),
            "userPromptPlaceholder": "원하는 화풍을 적어주세요(선택). 비워두면 기존처럼 입력 이미지 스타일을 유지합니다.",
            # 2x2 / 3x3 시트는 정사각형이 가장 안정적입니다.
            "disableAspect": False,
            "aspectOptions": ["square"],
            "expressionTool": {
                "enabled": True,
                "countPresets": [
                    {"value": "9", "label": "9개 (3×3 그리드 · 기본)"},
                    {"value": "4", "label": "4개 (2×2 그리드)"},
                ],
                "defaultCount": "9",
            },
        },
    },

    "NanoBanana_StoryboardCutboard": {
        "display_name": "스토리보드 컷보드 (6컷/9컷)",
        "description": "입력 이미지 1장을 기준으로, 6컷(2×3) 또는 9컷(3×3) 스토리보드 컷보드를 한 장의 그리드 이미지로 만들어줍니다.",
        "hidden": False,
        "category": "image_generation",
        "capability": "create_storyboard",
        "mcp_public": True,

        # 사용자가 아무 설명을 안 해도 최소 동작은 하도록 기본값을 둡니다.
        "default_user_prompt": "",
        "style_prompt_position": "prepend",
        "style_prompt": (
            "GOAL: Create a storyboard cutboard in one image for a coherent 10–15 second cinematic sequence.\n"
            "REFERENCE: Image 1 establishes the characters, designs, location, visual style, time of day, and starting situation.\n"
            "\n"
            "CONTINUITY:\n"
            "- Preserve character identity, face, hair, body proportions, outfit, colors, object design, location, art style, and cinematic color grade across all panels.\n"
            "- Maintain screen direction, spatial relationships, prop continuity, and believable action progression between adjacent panels.\n"
            "- Introduce new characters, objects, or location details only when the STORY explicitly requires them.\n"
            "\n"
            "ALLOWED CHANGES:\n"
            "- Character action, expression, and staging required by the STORY.\n"
            "- Framing, camera angle, camera distance, lens feel, depth of field, and implied camera motion.\n"
            "\n"
            "SEQUENCE:\n"
            "- Read chronologically from left to right, then top to bottom.\n"
            "- Create exactly the requested number of panels, each showing one distinct consecutive moment; do not duplicate or omit panels.\n"
            "- Build a clear setup → escalation → turning point → resolution arc that follows the STORY rather than inventing a different plot.\n"
            "\n"
            "FORMAT:\n"
            "- One image containing the exact requested grid.\n"
            "- Panels edge-to-edge with no outer padding, captions, labels, logos, or watermarks.\n"
            "- Keep panel boundaries visually clear without decorative frames.\n"
        ),
        "negative_prompt": "",

        "provider": "openrouter",
        "openrouter": {"model": "google/gemini-3-pro-image", "mode": "image-edit"},

        # 입력 이미지가 필수인 도구 (OpenRouter provider 경로에서만 사용)
        "image_input": {"image_node": "_openrouter", "input_field": "image"},

        "ui": {
            "templateMode": "nanobanana",
            "showLora": False,
            "showPromptTranslate": True,
            "generateLabel": "컷보드 만들기",
            "userPromptPlaceholder": "이 장면은 어떤 장면인가요? 한 줄로 짧게 적어주세요..",
            # 컷보드는 6/9에 따라 그리드 비율이 달라질 수 있어, 비율 선택 UI는 숨깁니다.
            # (프론트에서 컷 수에 맞춰 aspect_ratio를 자동 지정합니다.)
            "disableAspect": True,
            "storyboardTool": {
                "enabled": True,
                "cutPresets": [
                    {"value": "9", "label": "9컷 (3×3 그리드 · 기본)"},
                    {"value": "6", "label": "6컷 (2×3 그리드)"},
                ],
                "defaultCuts": "9",
            },
            "hostedModelRecommendation": {
                "title": "GPT Image 2 권장",
                "message": "컷 간 연속성과 구도 정확도를 안정적으로 확보하려면 GPT Image 2 사용을 권장합니다.",
            },
        },
    },

    "NanoBanana_ChainsawJuiceKingCharacter": {
        "display_name": "체인소주스킹 캐릭터생성",
        "description": "컨셉 한 줄을 입력하면, 숨겨진 레퍼런스 이미지를 바탕으로 64가지 의상 버전을 8×8 그리드 한 장으로 만들어줍니다.",
        "hidden": False,
        "category": "image_generation",
        "capability": "internal_image_preset",
        "mcp_public": False,

        # 사용자는 '컨셉'만 짧게 입력하도록 유도합니다.
        "default_user_prompt": "",
        "style_prompt_position": "prepend",
        "style_prompt": (
            "작업목표 : 참고 이미지의 빈 공간에 팔이 없고 다리가 짧은 둥근 공 모양의 캐릭터를 배치하고, 그 위에 다양한 의상을 입히세요.\n"
            "중요 : 모든 의상은 팔 부분이 없어야 합니다. (팔/소매 금지)\n"
            "\n"
            "추가 규칙 :\n"
            "- 참고 이미지(레퍼런스)의 구도/배경은 유지하고, 캐릭터와 의상만 추가하세요.\n"
            "- 같은 캐릭터(정체성 유지)로 의상만 다양하게 바꿔주세요.\n"
            "- 텍스트/로고/워터마크는 넣지 마세요.\n"
        ),
        "negative_prompt": "",

        "provider": "openrouter",
        # Internally we will attach a hidden reference image and call image-edit.
        # Keep this workflow as txt2img from the UI perspective.
        # 2026-07 내부 비교 테스트 기준:
        # 이 워크플로우의 팔 없는 캐릭터 구조와 8×8 의상 배치를 안정적으로 준수한 모델은
        # GPT Image 2 High뿐이었으므로 모델 선택을 제한합니다.
        # 다른 모델을 다시 허용하려면 동일 조건의 결과 품질을 먼저 재검증하세요.
        "openrouter": {
            "model": "openai/gpt-image-2",
            "mode": "text-to-image",
            "allowed_models": ["openai/gpt-image-2"],
            "default_quality": "high",
            "workflow_scoped_preferences": True,
        },

        # Hidden reference image(s) that are automatically attached server-side.
        # Path is relative to repo root unless absolute.
        # NOTE: 이 파일은 브라우저에서 직접 접근되지 않는 "서버 전용" 경로에 둡니다.
        "openrouter_hidden_reference_images": ["app/resources/refs/chainsaw_juice_king_reference.png"],

        "ui": {
            "icon": "crown",
            "templateMode": "nanobanana",
            "showLora": False,
            # 이 워크플로우는 한글 컨셉 입력이 더 잘 먹히는 경우가 있어 기본은 번역 버튼을 숨깁니다.
            "showPromptTranslate": False,
            "generateLabel": "캐릭터 시트 만들기",
            "userPromptPlaceholder": "어떤 컨셉인가요? (예: 일본애니 판타지 컨셉, 인어공주 동화 스타일) — 비워두면 기본: 일상 캐주얼 스타일",
            # Aspect ratio will be forced to square in frontend for this tool.
            "disableAspect": True,
            "hostedModelRecommendation": {
                "title": "GPT Image 2 전용 · High 권장",
                "message": "정확한 캐릭터 구조와 8×8 의상 시트를 위해 High 품질 사용을 권장합니다.",
            },
        },
    },

    "AceStep15XL": {
        "display_name": "🎵 음악 생성 (ACE-Step)",
        "description": "텍스트 설명과 가사를 입력하여 AI 음악(MP3)을 생성합니다.",
        "category": "music_generation",
        "capability": "generate_music",
        "mcp_public": True,

        # 프롬프트 노드: TextEncodeAceStepAudio1.5 (node 94) — tags 필드에 주입
        "prompt_node": "94",
        "prompt_input_key": "tags",

        "default_user_prompt": "pop, piano, emotional, warm, acoustic, 100 BPM",
        "style_prompt": "",
        "negative_prompt": "",

        # 시드: TextEncodeAceStepAudio1.5 (node 94)의 seed 필드
        "seed_node": "94",
        "seed_input_key": "seed",

        # KSampler(node 3)에도 시드 주입
        "extra_seed_nodes": [{"node": "3", "key": "seed"}],

        # 이미지 사이즈/비율은 사용하지 않음
        "sizes": {},

        # 오디오 전용 설정
        "audio_workflow": True,
        "audio_params": {
            # TextEncodeAceStepAudio1.5 (node 94) 의 각 파라미터 → 프론트에서 오버라이드 가능
            "lyrics_node": "94",
            "lyrics_key": "lyrics",
            "bpm_node": "94",
            "bpm_key": "bpm",
            "duration_node_encode": "94",    # TextEncode의 duration
            "duration_node_latent": "98",    # EmptyAceStep1.5LatentAudio의 seconds
            "duration_key_encode": "duration",
            "duration_key_latent": "seconds",
            "timesignature_node": "94",
            "timesignature_key": "timesignature",
            "language_node": "94",
            "language_key": "language",
            "keyscale_node": "94",
            "keyscale_key": "keyscale",
        },
        # 고정 파라미터 (사용자에게 노출하지 않음)
        "audio_fixed_params": {
            "94": {
                "cfg_scale": 2,
                "temperature": 0.85,
                "top_p": 0.9,
                "top_k": 0,
                "min_p": 0,
                "generate_audio_codes": True,
            }
        },

        "ui": {
            "icon": "music",
            "templateMode": "music",
            "showLora": False,
            "showPromptTranslate": True,
            "disableAspect": True,
            "hideUserPrompt": False,
            "userPromptPlaceholder": "만들고 싶은 음악의 분위기를 설명해주세요 (예: 밝은 팝, 피아노 중심, 봄 느낌)",
            "userPromptLabel": "음악 설명 (Tags)",
            "generateLabel": "음악 생성하기",
            "generateIcon": "music",
            # 음악 전용 UI 컴포넌트 표시 플래그
            "musicMode": True,
            "musicParams": {
                "lyrics": {
                    "label": "가사 (Lyrics)",
                    "placeholder": "[verse]\n여기에 가사를 입력하세요\n\n[chorus]\n반복되는 후렴구\n\n[bridge]\n브릿지 부분",
                    "tooltip": "가사를 입력하세요. [verse], [chorus], [bridge] 등의 구조 태그를 사용하면 더 좋은 결과를 얻을 수 있습니다. 비워두면 인스트루멘탈이 생성됩니다.",
                    "rows": 8,
                },
                "bpm": {
                    "label": "BPM (빠르기)",
                    "tooltip": "곡의 빠르기입니다. 60=느린 발라드, 90=편안한 재즈, 120=일반적인 팝, 140=신나는 댄스, 180=빠른 록",
                    "min": 40,
                    "max": 220,
                    "step": 1,
                    "default": 120,
                },
                "duration": {
                    "label": "길이 (초)",
                    "tooltip": "생성할 음악의 길이입니다. 길수록 생성 시간이 오래 걸립니다. (30초≈1분, 60초≈2분, 120초≈4분 소요 예상)",
                    "presets": [
                        {"label": "15초", "value": 15},
                        {"label": "30초", "value": 30},
                        {"label": "60초", "value": 60},
                        {"label": "120초", "value": 120},
                        {"label": "180초", "value": 180},
                    ],
                    "default": 60,
                },
                "keyscale": {
                    "label": "조성 (Key)",
                    "tooltip": "곡의 음악적 분위기입니다. Major(장조)=밝고 경쾌한 느낌, minor(단조)=어둡고 감성적인 느낌. 잘 모르겠다면 'C major'를 추천합니다.",
                    "options": [
                        "C major", "C minor", "C# major", "C# minor",
                        "D major", "D minor", "D# major", "D# minor",
                        "E major", "E minor", "F major", "F minor",
                        "F# major", "F# minor", "G major", "G minor",
                        "G# major", "G# minor", "A major", "A minor",
                        "A# major", "A# minor", "B major", "B minor",
                    ],
                    "default": "C major",
                },
                "timesignature": {
                    "label": "박자",
                    "tooltip": "한 마디의 박자 구성입니다. 4/4=일반적인 대부분의 곡, 3/4=왈츠/발라드, 6/8=느린 셔플 느낌. 잘 모르겠다면 4/4를 추천합니다.",
                    "options": [
                        {"label": "4/4 (기본, 대부분의 곡)", "value": "4"},
                        {"label": "3/4 (왈츠, 느린 발라드)", "value": "3"},
                        {"label": "6/8 (셔플, 마치)", "value": "6"},
                    ],
                    "default": "4",
                },
                "language": {
                    "label": "가사 언어",
                    "tooltip": "가사의 언어를 선택합니다. 인스트루멘탈(가사 없음)이면 영향 없습니다.",
                    "options": [
                        {"label": "한국어", "value": "ko"},
                        {"label": "English", "value": "en"},
                        {"label": "日本語", "value": "ja"},
                        {"label": "中文", "value": "zh"},
                        {"label": "Español", "value": "es"},
                        {"label": "Français", "value": "fr"},
                        {"label": "Deutsch", "value": "de"},
                        {"label": "Italiano", "value": "it"},
                        {"label": "Português", "value": "pt"},
                        {"label": "Русский", "value": "ru"},
                    ],
                    "default": "ko",
                },
            },
        },
    },

    "seethrough-basic": {
        "display_name": "레이어 분리 (See-Through)",
        "description": "이미지 1장을 넣으면 AI가 파츠별로 레이어를 분리하여 PSD 파일로 출력합니다.",
        "hidden": False,
        "category": "image_tools",
        "capability": "separate_layers",
        "mcp_public": True,

        "default_user_prompt": "",
        "style_prompt": "",
        "negative_prompt": "",

        "provider": "comfyui",

        # Img2Img: 노드 27(LoadImage)에 이미지 주입
        "image_input": {"image_node": "27", "input_field": "image"},

        # SeeThrough 전용 플래그
        "seethrough_workflow": True,

        "ui": {
            "icon": "layer-group",
            "templateMode": "utility",
            "showLora": False,
            "showPromptTranslate": False,
            "disableAspect": True,
            "hideUserPrompt": True,
            "generateLabel": "레이어 분리하기",
            # 갤러리에서 제외
            "excludeFromGallery": True,
            # Resolution 슬라이더 노출
            "seeThroughParams": {
                "resolution": {"min": 768, "max": 1472, "step": 64, "default": 1280},
            },
        },
    },
}


