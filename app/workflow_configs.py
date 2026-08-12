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

    "NanoBanana_Img2Img": {
        "hidden": True,
        "display_name": "기본 워크플로우 — 편집",
        "description": "이미지를 입력으로 받아 자연어로 편집합니다. (단일 입력)",

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
            # Phase C: multi-image img2img 지원 (최대 14장)
            # UI에서 선택 순서가 곧 모델에 전달되는 순서입니다.
            "imageInputMulti": {"enabled": True, "max": 14},
        },
    },

    "NanoBanana_TurnaroundSheet": {
        "display_name": "턴어라운드 시트 (캐릭터)",
        "description": "캐릭터 1장을 넣으면 정면/측면/후면 등 턴어라운드 시트로 만들어줍니다.",
        "hidden": False,

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

    "NanoBanana_Relight": {
        "display_name": "리라이트 (조명 바꾸기)",
        "description": "이미지 1장을 넣으면 구도/캐릭터는 유지하고 조명(라이팅)만 바꿔줍니다.",
        "hidden": False,

        # 툴 워크플로우: 프롬프트 입력을 숨기므로, 기본 프롬프트는 간단한 영어로 고정합니다.
        "default_user_prompt": "Relight the provided image according to the selected lighting requirements.",
        "style_prompt_position": "prepend",
        "style_prompt": (
            "TASK: Perform a controlled, surgical relighting of Image 1.\n"
            "CHANGE ONLY: Illumination direction, intensity, softness, shadow behavior, highlights, reflections, and the explicitly selected color mood.\n"
            "PRESERVE EXACTLY: Subject identity, facial features, pose, anatomy, outfit, objects, object positions, shapes, textures, composition, crop, camera angle, perspective, background structure, and rendering style.\n"
            "Do not redraw, restyle, beautify, add, remove, move, or replace scene content. Preserve existing text and logos; do not add new ones.\n"
            "Make light and shadows physically coherent with the scene geometry and selected light direction.\n"
            "OUTPUT: One clean relit image with the original framing and aspect ratio."
        ),
        "negative_prompt": "",

        "provider": "openrouter",
        "openrouter": {"model": "google/gemini-3-pro-image", "mode": "image-edit"},

        # 입력 이미지가 필수인 도구
        "image_input": {"image_node": "_openrouter", "input_field": "image"},

        "ui": {
            "icon": "sun",
            "templateMode": "nanobanana",
            "showLora": False,
            "showPromptTranslate": False,
            "generateLabel": "조명 바꾸기",
            "hideUserPrompt": True,
            # 리라이트는 입력 비율 유지가 자연스럽습니다. (프론트에서 aspect_ratio는 auto로 강제)
            "disableAspect": True,
            "relightTool": {
                "enabled": True,
                "lightingStylePresets": [
                    {
                        "value": "motivated",
                        "label": "기본(영화 조명 · 추천)",
                        "desc": "장면 속 광원(창문/램프)처럼 ‘그럴듯한’ 조명. 자연스럽고 영화적인 느낌.",
                        "prompt": "Motivated lighting (cinematic, realistic).",
                    },
                    {
                        "value": "natural",
                        "label": "자연광(내추럴)",
                        "desc": "햇빛 같은 자연광 위주. 인공조명 느낌을 최소화.",
                        "prompt": "Natural lighting (sunlight), realistic.",
                    },
                    {
                        "value": "high_key",
                        "label": "밝게(하이 키)",
                        "desc": "전체적으로 밝고 그림자가 약함. 산뜻/로맨스/코미디 분위기.",
                        "prompt": "High-key lighting: bright overall, minimal shadows.",
                    },
                    {
                        "value": "low_key",
                        "label": "어둡게(로우 키)",
                        "desc": "강한 대비와 깊은 그림자. 느와르/호러/긴장감 분위기.",
                        "prompt": "Low-key lighting: strong contrast, deep shadows.",
                    },
                    {
                        "value": "rembrandt",
                        "label": "렘브란트(삼각형 빛)",
                        "desc": "한쪽 볼에 삼각형 하이라이트가 생기는 클래식 초상 조명.",
                        "prompt": "Rembrandt lighting: classic portrait triangle highlight on the cheek.",
                    },
                    {
                        "value": "chiaroscuro",
                        "label": "키아로스쿠로(극적 대비)",
                        "desc": "밝은 부분만 강하게 살리고 어두운 부분은 깊게 떨어뜨림(극적 대비).",
                        "prompt": "Chiaroscuro lighting: dramatic contrast of bright light and deep shadow.",
                    },
                    {
                        "value": "silhouette",
                        "label": "실루엣(역광)",
                        "desc": "뒤에서 강한 빛. 피사체는 윤곽 중심으로 어둡게 보임.",
                        "prompt": "Silhouette lighting: strong backlight, subject mostly dark silhouette.",
                    },
                    {
                        "value": "butterfly",
                        "label": "버터플라이(글래머)",
                        "desc": "정면 위쪽에서 내려오는 빛. 코 아래 나비 모양 그림자(글래머).",
                        "prompt": "Butterfly lighting: light from above/front, butterfly shadow under the nose.",
                    },
                    {
                        "value": "split",
                        "label": "스플릿(반쪽 조명)",
                        "desc": "옆에서 빛을 주어 얼굴이 정확히 반으로 나뉨(한쪽 밝고 한쪽 어둠).",
                        "prompt": "Split lighting: side light, face split into bright and dark halves.",
                    },
                    {
                        "value": "bottom",
                        "label": "바텀(공포)",
                        "desc": "아래에서 위로 비추는 빛. 공포/불길한 그림자 연출.",
                        "prompt": "Bottom lighting: light from below, dramatic horror shadows.",
                    },
                ],
                "lightQualityPresets": [
                    {
                        "value": "soft",
                        "label": "부드럽게(소프트)",
                        "desc": "빛이 퍼져서 그림자가 부드럽고 전체가 균일해짐.",
                        "prompt": "Soft light: diffused, gentle shadows.",
                    },
                    {
                        "value": "hard",
                        "label": "강하게(하드)",
                        "desc": "그림자 경계가 선명하고 대비가 강해짐(드라마틱).",
                        "prompt": "Hard light: crisp shadows, strong contrast.",
                    },
                ],
                "colorMoodPresets": [
                    {
                        "value": "none",
                        "label": "색감 유지(변경 없음)",
                        "desc": "원본 색감/톤을 그대로 유지(조명만 바꾸고 색보정은 최소).",
                        "prompt": "Keep original colors. Color grading: unchanged.",
                    },
                    {
                        "value": "film_noir",
                        "label": "필름 누아르(흑백)",
                        "desc": "흑백(모노크롬) + 강한 대비 + 깊은 그림자. 클래식 느와르 분위기.",
                        "prompt": "Film noir tone: black-and-white monochrome, high contrast, deep shadows, subtle film grain.",
                    },
                    {
                        "value": "teal_orange",
                        "label": "틸&오렌지(영화 톤)",
                        "desc": "피부톤은 따뜻하게, 그림자/배경은 차가운 청록 계열로 대비.",
                        "prompt": "Color grading: teal and orange (skin warm, shadows/background cool teal).",
                    },
                    {
                        "value": "neon",
                        "label": "네온(사이버펑크)",
                        "desc": "핑크/블루/그린 네온 느낌의 컬러 라이팅.",
                        "prompt": "Neon lighting color mood: vibrant pink/blue/green neon highlights.",
                    },
                    {
                        "value": "golden_hour",
                        "label": "골든 아워(따뜻한 햇살)",
                        "desc": "해질녘/해뜰녘처럼 따뜻한 황금빛 조명.",
                        "prompt": "Golden hour lighting: warm golden sunlight, soft romantic mood.",
                    },
                    {
                        "value": "warm_cool",
                        "label": "웜 vs 쿨 대비",
                        "desc": "따뜻한 하이라이트(오렌지/레드)와 차가운 그림자(블루) 대비.",
                        "prompt": "Warm vs cool contrast: warm highlights and cool shadows.",
                    },
                    {
                        "value": "gel_cto",
                        "label": "컬러젤: CTO(따뜻한 주황)",
                        "desc": "색온도를 따뜻하게 보정하는 주황 계열 젤.",
                        "prompt": "Color gel: CTO (warm orange color temperature).",
                    },
                    {
                        "value": "gel_ctb",
                        "label": "컬러젤: CTB(차가운 블루)",
                        "desc": "색온도를 차갑게 보정하는 푸른 계열 젤.",
                        "prompt": "Color gel: CTB (cool blue color temperature).",
                    },
                    {
                        "value": "gel_amber",
                        "label": "컬러젤: Bastard Amber",
                        "desc": "클래식한 따뜻한 황금빛(앰버) 톤.",
                        "prompt": "Color gel: Bastard Amber (classic warm golden tint).",
                    },
                    {
                        "value": "gel_congo_blue",
                        "label": "컬러젤: Congo Blue",
                        "desc": "깊고 진한 청색. 밤/신비로운 무드에 적합.",
                        "prompt": "Color gel: Congo Blue (deep saturated blue).",
                    },
                    {
                        "value": "gel_rose_pink",
                        "label": "컬러젤: Rose Pink",
                        "desc": "부드러운 핑크 톤. 로맨틱/감정적 분위기.",
                        "prompt": "Color gel: Rose Pink (soft romantic pink).",
                    },
                    {
                        "value": "gel_medium_red",
                        "label": "컬러젤: Medium Red",
                        "desc": "진홍색 계열 레드. 위험/열정 같은 강한 감정 표현.",
                        "prompt": "Color gel: Medium Red (crimson red).",
                    },
                    {
                        "value": "gel_dark_green",
                        "label": "컬러젤: Dark Green",
                        "desc": "에메랄드/다크그린 톤. 미스터리/공포/병원 무드.",
                        "prompt": "Color gel: Dark Green (emerald green).",
                    },
                ],
                "defaults": {"lightingStyle": "motivated", "lightQuality": "soft", "colorMood": "none"},
            },
        },
    },

    "NanoBanana_StoryboardCutboard": {
        "display_name": "스토리보드 컷보드 (6컷/9컷)",
        "description": "입력 이미지 1장을 기준으로, 6컷(2×3) 또는 9컷(3×3) 스토리보드 컷보드를 한 장의 그리드 이미지로 만들어줍니다.",
        "hidden": False,

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

    "BasicWorkFlow_PixelArt": {
        "display_name": "픽셀 아트",
        "description": "레트로 감성의 픽셀 아트 스타일 이미지를 생성합니다",
        # 테스트 동안 워크플로우 목록에서 숨김 처리
        "hidden": True,

        # 기본 프롬프트는 비워두고, placeholder로만 안내합니다.
        "default_user_prompt": "",

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
        # UI schema
        "ui": {
            "icon": "th",
            "userPromptPlaceholder": "무엇을 만들고 싶으신가요? 태그를 콤마(,)로 입력해 주세요. (예: 1girl, solo, hanbok)",
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

        # UI 힌트
        "ui": {
            "icon": "paint-brush",
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

    "LOSstyle_Qwen": {
        "display_name": "LOS 스타일",
        "description": "Qwen 이미지 베이스 + Lightning LoRA 고정, 스타일 LoRA 조절형(컨트롤넷 없음)",

        # 기본 프롬프트는 비워두고, placeholder로만 안내합니다.
        "default_user_prompt": "",

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

        # UI 힌트: 컨트롤넷 비노출, 스타일 LoRA만 노출(캐릭터 LoRA는 숨김)
        "ui": {
            # 슬라임/젤리 느낌에 가장 가까운 무료 아이콘: droplet(물방울)
            "icon": "droplet",
            "showLora": True,
            "showStyleLora": True,
            "showCharacterLora": False,
            # LOS 스타일: 한국어 자연어 → 이미지 생성용 영어 프롬프트 변환 버튼 사용
            "showPromptTranslate": True,
            "userPromptPlaceholder": "어떤 장면을 만들고 싶으신가요? 한 문장으로 적어주세요. (예: 도서관에서 슬라임을 안고 있는 소녀, 따뜻한 조명)",
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

        # 입력 이미지 1장/2장에 따라 내부 워크플로우(JSON)를 자동 선택합니다.
        # - 1장: 기존 single-input 워크플로우(이 엔트리 자체)
        # - 2장: dual-input 워크플로우(아래 hidden 엔트리)
        "comfy_variants_by_input_count": {
            1: "LOSStyle_Klein_Img2Img",
            2: "LOSStyle_Klein_Img2Img_dualInput",
        },

        # 프롬프트: 단일 positive conditioning만 사용 (negative는 ConditioningZeroOut 기반)
        # - CLIPTextEncode(107) inputs.text
        "prompt_node": "107",
        "prompt_input_key": "text",
        # Negative prompt node 없음(워크플로우 구조상 별도 네거티브 텍스트 인코딩을 쓰지 않음)
        # "negative_prompt_node": 없음

        # 기본 프롬프트는 비워두고, placeholder로만 안내합니다.
        "default_user_prompt": "",

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
            "showLora": True,
            "showStyleLora": True,
            "showCharacterLora": False,
            "showPromptTranslate": True,
            "templateMode": "natural",
            "disableAspect": True,
            "userPromptPlaceholder": "무엇을 어떻게 바꾸고 싶으신가요? (예: 슬라임을 제거하고 강아지로 교체해 주세요)",
            # 1~2장까지 선택 UI(썸네일 그리드)를 활성화합니다.
            "imageInputMulti": {"enabled": True, "max": 2},
        },
    },

    "LOSStyle_Klein_Img2Img_dualInput": {
        # LOSStyle_Klein_Img2Img wrapper에서만 사용되는 내부 워크플로우(목록 비노출)
        "hidden": True,
        "display_name": "LOS 스타일 — 편집 (Klein) — 2장",
        "description": "입력 이미지 2장을 기반으로 LOS 스타일 Klein(Flux2) Img2Img 편집을 수행합니다.",

        "default_user_prompt": "",
        "style_prompt": "LOSart",
        "negative_prompt": "",

        # Prompt: CLIPTextEncode(92:74).inputs.text
        "prompt_node": "92:74",
        "prompt_input_key": "text",

        # Seed: Seed (rgthree)(100).inputs.seed -> RandomNoise(92:73)가 이를 참조
        "seed_node": "100",
        "seed_input_key": "seed",

        # Dual input images:
        # - 1번째 이미지: LoadImage(76).inputs.image
        # - 2번째 이미지: LoadImage(81).inputs.image
        "image_inputs": [
            {"ordinal": 1, "image_node": "76", "input_field": "image"},
            {"ordinal": 2, "image_node": "81", "input_field": "image"},
        ],
        # UI gate only
        "image_input": {"image_node": "76", "input_field": "image"},

        # LoRA: 스타일 LoRA 강도 조절(노드 92:88)
        "loras": {
            "style": {
                "node": "92:88",
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

        "ui": {
            "showLora": True,
            "showStyleLora": True,
            "showCharacterLora": False,
            "showPromptTranslate": True,
            "templateMode": "natural",
            "disableAspect": True,
            "userPromptPlaceholder": "무엇을 어떻게 바꾸고 싶으신가요?",
            # 내부 워크플로우를 직접 선택할 일은 없지만, 안전하게 동일 설정 유지
            "imageInputMulti": {"enabled": True, "max": 2},
        },
    },

    "Flux2Klein_ImageEdit": {
        "display_name": "간단 이미지 편집",
        "description": "이미지 1장(또는 2장)을 넣고, 원하는 변경을 글로 적으면 Klein(Flux2)로 편집합니다.",
        "hidden": False,

        # 기본 프롬프트는 비워두고, placeholder로만 안내합니다.
        "default_user_prompt": "",
        "style_prompt": "",
        "negative_prompt": "",

        # Wrapper routing: pick an internal ComfyUI workflow by input image count.
        # NOTE: generation.py에서 이 키를 읽어 workflow_path를 바꿉니다.
        "comfy_variants_by_input_count": {
            1: "Flux2Klein_i2i_singleInput",
            2: "Flux2Klein_i2i_dualInput",
        },

        # UI gate only: 존재만으로 "입력 이미지 필요"를 인지하게 합니다.
        # 실제 LoadImage 노드 주입은 variant config에서 처리됩니다.
        "image_input": {"image_node": "102", "input_field": "image"},

        "ui": {
            "icon": "edit",
            "templateMode": "utility",
            "showLora": False,
            "showPromptTranslate": True,
            # Img2Img는 입력 비율을 따르는 것이 자연스럽습니다.
            "disableAspect": True,
            "generateLabel": "이미지 편집하기",
            "userPromptPlaceholder": "무엇을 어떻게 바꾸고 싶으신가요? (예: 머리색을 은발로 바꾸고, 배경을 밤하늘로 바꿔주세요)",
            # 1~2장까지 선택 UI(썸네일 그리드)를 활성화합니다.
            "imageInputMulti": {"enabled": True, "max": 2},
        },
    },

    "Flux2Klein_i2i_singleInput": {
        # wrapper에서만 사용되는 내부 워크플로우(목록 비노출)
        "hidden": True,
        "display_name": "이미지 편집 (Klein) — 1장",
        "description": "입력 이미지 1장을 기반으로 Klein(Flux2) Img2Img 편집을 수행합니다.",

        "default_user_prompt": "",
        "style_prompt": "",
        "negative_prompt": "",

        # Prompt: CLIPTextEncode.inputs.text
        "prompt_node": "75:74",
        "prompt_input_key": "text",

        # Seed: Seed (rgthree).inputs.seed (RandomNoise가 이를 참조)
        "seed_node": "100",
        "seed_input_key": "seed",

        # Input image: LoadImage(102).inputs.image
        "image_input": {"image_node": "102", "input_field": "image"},

        "ui": {
            "templateMode": "utility",
            "showLora": False,
            "showPromptTranslate": True,
            "disableAspect": True,
            "userPromptPlaceholder": "무엇을 어떻게 바꾸고 싶으신가요?",
        },
    },

    "Flux2Klein_i2i_dualInput": {
        # wrapper에서만 사용되는 내부 워크플로우(목록 비노출)
        "hidden": True,
        "display_name": "이미지 편집 (Klein) — 2장",
        "description": "입력 이미지 2장을 기반으로 Klein(Flux2) Img2Img 편집을 수행합니다.",

        "default_user_prompt": "",
        "style_prompt": "",
        "negative_prompt": "",

        # Prompt: CLIPTextEncode.inputs.text
        "prompt_node": "92:74",
        "prompt_input_key": "text",

        # Seed: Seed (rgthree).inputs.seed (RandomNoise가 이를 참조)
        "seed_node": "100",
        "seed_input_key": "seed",

        # Dual input images:
        # - 1번째 이미지: LoadImage(76).inputs.image
        # - 2번째 이미지: LoadImage(81).inputs.image
        "image_inputs": [
            {"ordinal": 1, "image_node": "76", "input_field": "image"},
            {"ordinal": 2, "image_node": "81", "input_field": "image"},
        ],
        # UI gate only (서버는 image_inputs를 사용하지만, 프론트는 image_input 존재 여부로만 표시 판단)
        "image_input": {"image_node": "76", "input_field": "image"},

        "ui": {
            "templateMode": "utility",
            "showLora": False,
            "showPromptTranslate": True,
            "disableAspect": True,
            "userPromptPlaceholder": "무엇을 어떻게 바꾸고 싶으신가요?",
            # 내부 워크플로우를 직접 선택할 일은 없지만, 안전하게 동일 설정 유지
            "imageInputMulti": {"enabled": True, "max": 2},
        },
    },

    # ──────────────────────────────────────────────
    # ACE-Step 1.5 XL — 음악(오디오) 생성
    # ──────────────────────────────────────────────
    "AceStep15XL": {
        "display_name": "🎵 음악 생성 (ACE-Step)",
        "description": "텍스트 설명과 가사를 입력하여 AI 음악(MP3)을 생성합니다.",

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


