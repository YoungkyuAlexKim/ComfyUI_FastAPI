from typing import Dict, List, TypedDict


class PromptTemplate(TypedDict, total=False):
    title: str  # 버튼에 표시할 제목
    text: str   # 프롬프트 필드에 추가될 실제 태그/문구
    # 옵션형 템플릿: text 내 '[ITEM]' 자리에 무작위 옵션을 치환합니다.
    # 만약 텍스트에 [ITEM]이 없으면, 선택된 옵션을 뒤에 붙입니다.
    options: List[str]


# 워크플로우별 추천 프롬프트 템플릿 정의
# 필요 시 언제든 이 파일만 수정하여 관리할 수 있습니다.
PROMPT_TEMPLATES: Dict[str, List[PromptTemplate]] = {
    # 픽셀 아트: 게임 리소스 지향 (Danbooru 태그 위주)
    "BasicWorkFlow_PixelArt": [
        {"title": "1인 전신", "text": "1girl, solo, full_body, standing, looking_at_viewer"},
        {"title": "배경 온리(숲길)", "text": "scenery, no_humans, forest, path, sunlight, trees"},
        {"title": "인물+배경(벚꽃)", "text": "1girl, solo, full_body, outdoors, cherry_blossoms, petals, spring"},
        {"title": "치비 스프라이트", "text": "chibi, super_deformed, full_body, simple_background"},
        {"title": "게임 아이템: 음식", "text": "no_humans, food, [ITEM], simple_background, transparent_background, white_background, centered, floating", "options": [
            "onigiri", "dango", "takoyaki", "ramen", "bread", "apple", "shortcake", "taiyaki"
        ]},
        {"title": "게임 아이템: 무기", "text": "no_humans, item icon, sword, katana, bow_(weapon), axe, spear, staff, shield, simple_background, white_background"},
        {"title": "몬스터: 슬라임", "text": "monster, slime, blue_slime, green_slime, red_slime, multiple_slime, grass"},
    ],
    # MK 스타일: 아니메/일러스트 지향 (Danbooru 태그 위주)
    "BasicWorkFlow_MKStyle": [
        {"title": "1인 전신", "text": "1girl, solo, full_body, standing, looking_at_viewer"},
        {"title": "배경 온리(도시 야경)", "text": "scenery, no_humans, cityscape, night, neon_lighting, starry_sky"},
        {"title": "인물+배경(교실)", "text": "1girl, solo, upper_body, classroom, window, sunlight"},
        {"title": "치비 캐릭터", "text": "chibi, super_deformed, simple_background"},
        {"title": "게임 아이템: 음식", "text": "no_humans, food, [ITEM], simple_background, transparent_background, white_background, centered, floating", "options": [
            "onigiri", "dango", "takoyaki", "ramen", "bread", "apple", "shortcake", "taiyaki"
        ]},
        {"title": "게임 아이템: 무기", "text": "no_humans, item icon, sword, katana, bow_(weapon), axe, spear, staff, shield, simple_background, white_background"},
        {"title": "몬스터: 슬라임", "text": "monster, slime, blue_slime, green_slime, red_slime, multiple_slime, grass"},
    ],
    # 픽셀레이터(입력 이미지 변환): 추가 프롬프트로 세부 스타일 지정
    "ILXL_Pixelator": [
        {"title": "캐릭터 스프라이트", "text": "1girl, solo, full_body, standing, simple_background"},
        {"title": "배경 온리(성문)", "text": "scenery, no_humans, castle, gate, stone, medieval"},
        {"title": "인물+배경(해변)", "text": "1girl, solo, outdoors, beach, waves, seashell"},
        {"title": "치비 스프라이트", "text": "chibi, super_deformed, full_body, simple_background"},
        {"title": "게임 아이템: 음식", "text": "no_humans, food, [ITEM], simple_background, transparent_background, white_background, centered, floating", "options": [
            "onigiri", "dango", "takoyaki", "ramen", "bread", "apple", "shortcake", "taiyaki"
        ]},
        {"title": "게임 아이템: 무기", "text": "no_humans, item icon, sword, katana, bow_(weapon), axe, spear, staff, shield, simple_background, white_background"},
        {"title": "몬스터: 슬라임", "text": "monster, slime, blue_slime, green_slime, red_slime, multiple_slime, grass"},
    ],
    # LOS 스타일: 스타일 LoRA 중심. 기본 품질 태그 포함

    # 자연어 서술형 템플릿(LOSstyle_Qwen 전용)
    "LOSstyle_Qwen": [
        {
            "title": "1인 전신",
            "text": "A cute, stylized chibi girl with short brown hair in a school uniform, standing full-body on soft grass under a bright blue sky with gentle clouds. A simple, clean background emphasizes the character."
        },
        {
            "title": "2인 전신",
            "text": "Two stylized chibi girls standing side by side on a quiet street, one with bright red twin-tails and the other with a blonde bob cut. A simple, symmetric composition that highlights their shapes."
        },
        {
            "title": "상황설정1",
            "text": "A stylized chibi girl in a simple dress, seen from above inside a cozy library with tall shelves. She gently holds a smiling blue slime character, with soft shadows adding depth."
        },
        {
            "title": "상황설정2",
            "text": "Two chibi girls holding hands on a grassy field at night beneath a full, glowing moon. One wears a robe with long red hair, the other has flowing blonde hair and a long skirt; a calm scene with drifting clouds."
        },
        {
            "title": "상황설정3",
            "text": "A chibi boy with slicked-back black hair kneels in quiet prayer inside a church. Colored light filters through stained glass, casting dappled rays across the floor, clearly defining the silhouette."
        },
        {
            "title": "상황설정4",
            "text": "A chibi girl with short blue hair lies on a soft bed next to a small dog in a warm inn room. Wooden walls and stone textures frame the scene; the dynamic angle adds a playful, cozy feeling."
        },
        {
            "title": "상황설정5",
            "text": "A chibi boy astronaut floating weightlessly in space, surrounded by twinkling stars and a nearby planet. The composition hints at a subtle fisheye lens feel around the character."
        },
        {
            "title": "상황설정6",
            "text": "A chibi girl with a ribbon, robe, and hat stands at night, looking up with bright curiosity. A friendly blue slime companion rests nearby; the scene is tilted at a dramatic dutch angle."
        },
        {
            "title": "상황설정7",
            "text": "A chibi girl with blue hair and a fur-trimmed coat sits on a park bench at night. A cheerful blue slime sits beside her; the scene is framed with a gentle dutch angle."
        },
        {
            "title": "동적 앵글",
            "text": "A dynamic, tilted view of a chibi girl in mid-air, as if flying or leaping through the sky. The perspective is dramatic and playful, accentuating motion."
        },
        {
            "title": "몬스터: 슬라임",
            "text": "A simple, cheerful scene with no humans: several colorful slime characters—blue, red, and others—resting together on grass. Clear shapes keep the composition clean and friendly."
        }
    ],

    # Img2Img 편집용 자연어 템플릿(한국어)
    "LOSstyle_Qwen_ImageEdit": [
        {
            "title": "슬라임→강아지 교체",
            "text": "이미지에서 파란 슬라임을 제거하고, 강아지로 교체해 주세요."
        },
        {
            "title": "발렌타인데이 분위기 + 의상 변경",
            "text": "배경을 발렌타인데이 분위기로 바꿔 주세요. 소녀의 의상을 흰색 드레스로 바꾸고, 모자는 제거해 주세요."
        },
        {
            "title": "날씨 변경(비 오는 밤)",
            "text": "장면을 비 오는 밤으로 바꿔 주세요. 바닥에 은은한 빗물 반사를 추가하고, 주 피사체의 선명도는 유지해 주세요."
        },
        {
            "title": "카메라 각도: 하이앵글",
            "text": "카메라를 더 위에서 내려다보는 하이 앵글로 바꿔 주세요. 피사체 비율은 자연스럽게 유지하고, 원근감은 과하지 않게 해 주세요."
        },
        {
            "title": "텍스트 추가(영문 워터마크)",
            "text": "이미지 오른쪽 아래에 'I was generated from LC-Canvas'라는 영문 텍스트를 추가해 주세요. 크기는 작게, 가독성이 좋도록 흰색에 약한 그림자를 적용해 주세요."
        },
        {
            "title": "사이드뷰로 회전",
            "text": "캐릭터를 사이드뷰(측면)로 회전해 주세요. 머리 방향과 시선은 자연스럽게 유지하고, 포즈와 비율은 크게 변경하지 말아 주세요."
        },
        {
            "title": "카메라를 바라보며 미소",
            "text": "오른쪽의 파란색 슬라임이 카메라를 바라보며 고개를 돌려 자연스럽게 미소 짓도록 해 주세요."
        },
        {
            "title": "반 고흐 스타일",
            "text": "이미지를 반 고흐 스타일의 그림으로 바꿔주세요. 특유의 붓터치와 소용돌이 무늬 질감을 강조해 주세요."
        }
    ],
}


