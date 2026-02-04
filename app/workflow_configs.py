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
        "description": "Google Gemini 기반 자연어 프롬프트로 이미지를 생성합니다.",
        "hidden": False,

        "default_user_prompt": "A cozy cafe interior, warm lighting, cinematic, highly detailed",
        "style_prompt": "",
        "negative_prompt": "",

        # Provider routing (handled in app/services/generation.py)
        "provider": "google",
        # 정책: 나노바나나는 항상 Nano Banana Pro(3 Pro Image) + 2K 출력으로 고정
        "google": {"model": "gemini-3-pro-image-preview", "mode": "text-to-image"},

        "ui": {
            "icon": "magic",
            # Separate category for NanoBanana family
            "templateMode": "nanobanana",
            "showLora": False,
            "showPromptTranslate": True,
            "related": {"img2img": "NanoBanana_Img2Img"},
            "modeTabLabels": {"txt2img": "생성", "img2img": "편집"},
        },
    },

    "NanoBanana_Img2Img": {
        "hidden": True,
        "display_name": "기본 워크플로우 — 편집",
        "description": "이미지를 입력으로 받아 자연어로 편집합니다. (단일 입력)",

        "default_user_prompt": "Remove the logo and make it look like watercolor",
        "style_prompt": "",
        "negative_prompt": "",

        "provider": "google",
        "google": {"model": "gemini-3-pro-image-preview", "mode": "image-edit"},

        # 존재만으로 UI가 '입력 이미지 필요'로 인지하도록 둡니다.
        # (ComfyUI workflow JSON에는 주입하지 않으며, google provider 경로에서만 사용)
        "image_input": {"image_node": "_google", "input_field": "image"},

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
        "default_user_prompt": (
            "Create a character turnaround sheet based on the provided character image.\n"
            "Keep the original character identity and style consistent across all views."
        ),
        "style_prompt_position": "prepend",
        "style_prompt": (
            "You are making a character turnaround sheet for a game art pipeline.\n"
            "Use the provided character image as the identity reference.\n"
            "Output a clean turnaround sheet in ONE image: front, 3/4 front, side, back, 3/4 back.\n"
            "Keep the character design consistent across all views (face, proportions, outfit, colors, accessories).\n"
            "Use a simple neutral background, consistent lighting, and clear separation between views.\n"
            "Characters/objects/outfits: use only what is present in the reference image.\n"
            "Text elements: absent (captions, labels).\n"
            "Branding: absent (watermark, logos)."
        ),
        "negative_prompt": "",

        "provider": "google",
        "google": {"model": "gemini-3-pro-image-preview", "mode": "image-edit"},

        # 입력 이미지가 필수인 도구
        "image_input": {"image_node": "_google", "input_field": "image"},

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

        # 툴 워크플로우: 프롬프트 입력을 숨기므로, 내부 기본 프롬프트는 영어로 고정하는 것이 안정적입니다.
        "default_user_prompt": (
            "Create a portrait expression sheet based on the provided character image.\n"
            "Keep the original character identity and style consistent."
        ),
        "style_prompt_position": "prepend",
        "style_prompt": (
            "You are making a portrait expression sheet for a game art pipeline.\n"
            "Use the provided character image as the identity reference.\n"
            "Keep the character design consistent across all portraits (face, proportions, outfit, colors, accessories).\n"
            "Portrait framing: head and shoulders.\n"
            "Use consistent lighting and a simple neutral background.\n"
            "Style: match the reference image style.\n"
            "Text elements: absent (captions, labels).\n"
            "Branding: absent (watermark, logos)."
        ),
        "negative_prompt": "",

        "provider": "google",
        "google": {"model": "gemini-3-pro-image-preview", "mode": "image-edit"},

        # 입력 이미지가 필수인 도구
        "image_input": {"image_node": "_google", "input_field": "image"},

        "ui": {
            "templateMode": "nanobanana",
            "showLora": False,
            "showPromptTranslate": True,
            "generateLabel": "표정 포트레이트 만들기",
            # 툴 UI로만 조작하도록 프롬프트 입력은 숨김(혼동 방지)
            "hideUserPrompt": True,
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
        "default_user_prompt": "Relight the provided image. Change lighting only.",
        "style_prompt_position": "prepend",
        "style_prompt": (
            "You are relighting an existing image.\n"
            "Keep the original subject identity and style consistent.\n"
            "Composition/camera/background: keep unchanged.\n"
            "Characters/outfits/objects: keep unchanged.\n"
            "Output: one single clean image.\n"
            "Text elements: absent.\n"
            "Branding: absent."
        ),
        "negative_prompt": "",

        "provider": "google",
        "google": {"model": "gemini-3-pro-image-preview", "mode": "image-edit"},

        # 입력 이미지가 필수인 도구
        "image_input": {"image_node": "_google", "input_field": "image"},

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
            "ROLE: film trailer director, cinematographer, storyboard artist\n"
            "TASK: storyboard cutboard (single image grid) for a 10–15 second cinematic sequence\n"
            "INPUT: 1 reference image\n"
            "\n"
            "ANALYSIS:\n"
            "- Identify subjects, positions, environment, time of day, lighting\n"
            "\n"
            "STYLE:\n"
            "- Match reference image style exactly (linework, shading/rendering, proportions, palette)\n"
            "\n"
            "CHARACTER:\n"
            "- Keep the same identity/design across all panels (face, hair, outfit, colors)\n"
            "\n"
            "SCENE:\n"
            "- Use the characters/objects/outfits/locations already present in the reference image\n"
            "- Keep environment, time of day, lighting style consistent\n"
            "- Keep a consistent cinematic color grade\n"
            "\n"
            "ALLOWED CHANGES:\n"
            "- framing, camera angle, camera distance\n"
            "- lens feel and depth of field (wide: deeper DOF, close-up: shallower DOF)\n"
            "- implied camera motion through composition\n"
            "- subtle plausible action within the same scene\n"
            "\n"
            "STORY ARC:\n"
            "- Setup → Escalation → Turning Point → Resolution\n"
            "\n"
            "FORMAT:\n"
            "- output: 1 image\n"
            "- layout: grid, panels edge-to-edge, border=0, gutter=0, padding=0, margin=0\n"
            "- text: absent\n"
            "- branding: absent\n"
            "\n"
            "USER FIELDS (provided below):\n"
            "- STORY: one short sentence describing what happens\n"
            "- CUTS: 6 or 9\n"
            "- GRID: 2x3 or 3x3\n"
        ),
        "negative_prompt": "",

        "provider": "google",
        "google": {"model": "gemini-3-pro-image-preview", "mode": "image-edit"},

        # 입력 이미지가 필수인 도구 (google provider 경로에서만 사용)
        "image_input": {"image_node": "_google", "input_field": "image"},

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
        },
    },

    "NanoBanana_WhatsNextVariations": {
        "display_name": "다음 장면 바리에이션 (4개)",
        "description": "입력 이미지 1장을 기준으로, 같은 화풍/같은 캐릭터로 ‘다음에 벌어질 법한 상황’ 4가지를 2×2 그리드 한 장으로 보여줍니다.",
        "hidden": False,

        "default_user_prompt": "",
        "style_prompt_position": "prepend",
        "style_prompt": (
            "ROLE: film director, cinematographer, storyboard artist\n"
            "TASK: next-beat variations (multiple plausible continuations) in one grid image\n"
            "INPUT: 1 reference image\n"
            "\n"
            "ANALYSIS:\n"
            "- Identify subjects, positions, environment, time of day, lighting\n"
            "\n"
            "STYLE:\n"
            "- Match reference image style exactly (linework, shading/rendering, proportions, palette)\n"
            "\n"
            "CHARACTER:\n"
            "- Keep the same identity/design across all panels (face, hair, outfit, colors)\n"
            "\n"
            "SCENE CONTINUITY:\n"
            "- Keep location and time of day consistent\n"
            "- Keep lighting style unchanged\n"
            "- Keep a consistent cinematic color grade\n"
            "\n"
            "VARIATIONS:\n"
            "- Create 4 distinct plausible next situations after the reference moment\n"
            "- Keep changes believable within the same world\n"
            "- Keep the same cast\n"
            "\n"
            "FORMAT:\n"
            "- output: 1 image\n"
            "- grid: 2x2\n"
            "- layout: panels edge-to-edge, border=0, gutter=0, padding=0, margin=0\n"
            "- text: absent\n"
            "- branding: absent\n"
            "\n"
            "USER FIELDS (provided below):\n"
            "- STORY: one short sentence describing what happens next\n"
        ),
        "negative_prompt": "",

        "provider": "google",
        "google": {"model": "gemini-3-pro-image-preview", "mode": "image-edit"},

        "image_input": {"image_node": "_google", "input_field": "image"},

        "ui": {
            "templateMode": "nanobanana",
            "showLora": False,
            "showPromptTranslate": False,
            "generateLabel": "다음 장면 4개 만들기",
            # 기본 목적이 "자동으로 다음 전개를 상상"이므로 프롬프트 입력은 숨김(선택 입력이 필요하면 추후 고급 토글로 열 수 있음)
            "hideUserPrompt": True,
            # 항상 2x2 그리드(정사각)로 고정하므로 비율 선택 UI는 숨김
            "disableAspect": True,
            "whatsNextTool": {"enabled": True},
        },
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
        # UI schema
        "ui": {
            "icon": "th",
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
            # 컵/음료(주스) 느낌 아이콘
            "icon": "glass-water",
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

        # UI 힌트: 컨트롤넷 비노출, 스타일 LoRA만 노출(캐릭터 LoRA는 숨김)
        "ui": {
            # 슬라임/젤리 느낌에 가장 가까운 무료 아이콘: droplet(물방울)
            "icon": "droplet",
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
            "icon": "dog",
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
            "showLora": True,
            "showStyleLora": True,
            "showCharacterLora": False,
            "showPromptTranslate": True,
            "templateMode": "natural",
            "disableAspect": True,
        },
    },
}


