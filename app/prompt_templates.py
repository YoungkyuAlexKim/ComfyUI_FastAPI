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
    # LOS 스타일: 스타일 LoRA 중심. 기본 품질 태그 포함

    # 자연어 서술형 템플릿(LOSstyle_Qwen 전용, 한국어)
    "LOSstyle_Qwen": [
        {
            "title": "1인 전신",
            "text": "짧은 갈색 머리의 귀여운 소녀가 교복을 입고 서 있는 전신 장면. 푸른 하늘과 옅은 구름 아래 부드러운 잔디 위, 단정하고 깔끔한 배경으로 캐릭터를 강조해 주세요."
        },
        {
            "title": "2인 전신",
            "text": "조용한 거리 위에 나란히 서 있는 두 명의 귀여운 소녀 장면. 한 명은 밝은 빨간색 트윈테일, 다른 한 명은 금발 보브컷. 단순하고 대칭적인 구도로 실루엣을 강조해 주세요."
        },
        {
            "title": "상황설정1",
            "text": "단순한 원피스를 입은 귀여운 소녀가 아늑한 도서관 내부에서 위쪽 시점으로 보이는 장면. 높은 책장이 늘어서 있고, 부드러운 그림자로 깊이감을 더해 주세요. 소녀는 미소 짓는 파란 슬라임을 가볍게 안고 있습니다."
        },
        {
            "title": "상황설정2",
            "text": "밤하늘 아래 보름달이 밝게 비추는 풀밭에서 손을 잡고 있는 두 명의 귀여운 소녀. 한 명은 긴 빨간 머리에 로브, 다른 한 명은 흩날리는 금발과 긴 스커트를 입고 있습니다. 천천히 떠가는 구름으로 차분한 분위기를 표현해 주세요."
        },
        {
            "title": "상황설정3",
            "text": "검은 머리를 뒤로 넘긴 귀여운 소년이 교회 안에서 조용히 무릎을 꿇고 기도하는 장면. 스테인드글라스를 통과한 색색의 빛이 바닥에 점점이 드리워지며, 실루엣을 선명하게 드러내 주세요."
        },
        {
            "title": "상황설정4",
            "text": "짧은 파란 머리의 귀여운 소녀가 작은 강아지 옆에서 포근한 침대에 누워 있는 장면. 따뜻한 여관 방의 나무 벽과 돌 질감이 어우러지며, 약간의 역동적인 각도로 아늑하고 발랄한 느낌을 더해 주세요."
        },
        {
            "title": "상황설정5",
            "text": "귀여운 소년 우주비행사가 무중력 상태로 떠 있는 장면. 반짝이는 별들과 가까운 행성이 보이며, 캐릭터 주변의 공간감을 은은하게 강조해 주세요."
        },
        {
            "title": "상황설정6",
            "text": "리본과 로브, 모자를 쓴 귀여운 소녀가 밤하늘을 호기심 가득 바라보는 장면. 옆에는 친근한 파란 슬라임이 있고, 살짝 기울어진 구도로 극적인 느낌을 주세요."
        },
        {
            "title": "상황설정7",
            "text": "파란 머리에 퍼 트리밍 코트를 입은 귀여운 소녀가 밤의 공원 벤치에 앉아 있는 장면. 옆에 즐거운 파란 슬라임이 있고, 부드럽게 기울어진 구도로 담아 주세요."
        },
        {
            "title": "동적 앵글",
            "text": "하늘을 나는 듯하거나 도약하는 귀여운 소녀를 역동적으로 담아 주세요. 기울어진 시점과 움직임이 강조되도록 연출해 주세요."
        },
        {
            "title": "몬스터: 슬라임",
            "text": "사람 없이 슬라임들만 등장하는 단순하고 즐거운 장면. 파란색과 빨간색 등 다양한 색의 슬라임이 잔디 위에 함께 모여 쉬고 있으며, 형태가 또렷하게 보이도록 깔끔하게 표현해 주세요."
        }
    ],

    # OHD 스타일: LOS 스타일과 동일한 자연어 프리셋을 재사용합니다.
    # (스타일 LoRA만 다르고, 입력 방식/UX는 동일하게 유지)
    "OHDstyle_Qwen": [
        {
            "title": "1인 전신",
            "text": "짧은 갈색 머리의 귀여운 소녀가 교복을 입고 서 있는 전신 장면. 푸른 하늘과 옅은 구름 아래 부드러운 잔디 위, 단정하고 깔끔한 배경으로 캐릭터를 강조해 주세요.",
        },
        {
            "title": "2인 전신",
            "text": "조용한 거리 위에 나란히 서 있는 두 명의 귀여운 소녀 장면. 한 명은 밝은 빨간색 트윈테일, 다른 한 명은 금발 보브컷. 단순하고 대칭적인 구도로 실루엣을 강조해 주세요.",
        },
        {
            "title": "상황설정1",
            "text": "단순한 원피스를 입은 귀여운 소녀가 아늑한 도서관 내부에서 위쪽 시점으로 보이는 장면. 높은 책장이 늘어서 있고, 부드러운 그림자로 깊이감을 더해 주세요. 소녀는 미소 짓는 파란 슬라임을 가볍게 안고 있습니다.",
        },
        {
            "title": "상황설정2",
            "text": "밤하늘 아래 보름달이 밝게 비추는 풀밭에서 손을 잡고 있는 두 명의 귀여운 소녀. 한 명은 긴 빨간 머리에 로브, 다른 한 명은 흩날리는 금발과 긴 스커트를 입고 있습니다. 천천히 떠가는 구름으로 차분한 분위기를 표현해 주세요.",
        },
        {
            "title": "상황설정3",
            "text": "검은 머리를 뒤로 넘긴 귀여운 소년이 교회 안에서 조용히 무릎을 꿇고 기도하는 장면. 스테인드글라스를 통과한 색색의 빛이 바닥에 점점이 드리워지며, 실루엣을 선명하게 드러내 주세요.",
        },
        {
            "title": "상황설정4",
            "text": "짧은 파란 머리의 귀여운 소녀가 작은 강아지 옆에서 포근한 침대에 누워 있는 장면. 따뜻한 여관 방의 나무 벽과 돌 질감이 어우러지며, 약간의 역동적인 각도로 아늑하고 발랄한 느낌을 더해 주세요.",
        },
        {
            "title": "상황설정5",
            "text": "귀여운 소년 우주비행사가 무중력 상태로 떠 있는 장면. 반짝이는 별들과 가까운 행성이 보이며, 캐릭터 주변의 공간감을 은은하게 강조해 주세요.",
        },
        {
            "title": "상황설정6",
            "text": "리본과 로브, 모자를 쓴 귀여운 소녀가 밤하늘을 호기심 가득 바라보는 장면. 옆에는 친근한 파란 슬라임이 있고, 살짝 기울어진 구도로 극적인 느낌을 주세요.",
        },
        {
            "title": "상황설정7",
            "text": "파란 머리에 퍼 트리밍 코트를 입은 귀여운 소녀가 밤의 공원 벤치에 앉아 있는 장면. 옆에 즐거운 파란 슬라임이 있고, 부드럽게 기울어진 구도로 담아 주세요.",
        },
        {
            "title": "동적 앵글",
            "text": "하늘을 나는 듯하거나 도약하는 귀여운 소녀를 역동적으로 담아 주세요. 기울어진 시점과 움직임이 강조되도록 연출해 주세요.",
        },
        {
            "title": "몬스터: 슬라임",
            "text": "사람 없이 슬라임들만 등장하는 단순하고 즐거운 장면. 파란색과 빨간색 등 다양한 색의 슬라임이 잔디 위에 함께 모여 쉬고 있으며, 형태가 또렷하게 보이도록 깔끔하게 표현해 주세요.",
        },
    ],

    # CJK 캐릭터 (Klein): "주제 + 헤어/용모 + 옆 물체 1개 + 심플 회색 배경" 형식의 프리셋
    # - 숨겨진 마스터 프롬프트(CJKUnit / dot eyes / tiny legs)는 서버에서 자동으로 앞에 붙습니다.
    # - 과도하게 한 장르(예: 세라복)로 쏠리지 않도록 직업/판타지/일상/취미를 섞었습니다.
    "CJKStyle_Klein_Character": [
        {
            "title": "캐주얼 스트리트 + 헤드폰",
            "text": "a character wearing an oversized hoodie, with over-ear headphones worn on her head.\n\nblack hair in a short curly bob. side-swept bangs. pinky cheek.\n\na single portable radio is positioned next to her.\n\nfeatured in simple gray background.",
        },
        {
            "title": "마법사(위치) + 마법서",
            "text": "a fantasy witch character wearing a pointed hat and a simple cape.\n\npurple long wavy hair. braided crown. pinky cheek.\n\na single spellbook is positioned next to her.\n\nfeatured in simple gray background.",
        },
        {
            "title": "기사(나이트) + 검",
            "text": "a fantasy knight character wearing light armor and a small cloak.\n\nsilver hair in a braided ponytail. straight bangs. pinky cheek.\n\na single sword is positioned next to her.\n\nfeatured in simple gray background.",
        },
        {
            "title": "우주비행사 + 헬멧",
            "text": "a sci-fi astronaut character wearing space helmet.\n\nlight_blue hair in a short pixie cut. no bangs. pinky cheek.\n\na single space controller is positioned next to her.\n\nfeatured in simple gray background.",
        },
        {
            "title": "셰프 + 프라이팬",
            "text": "a cheerful chef character wearing a white apron.\n\nbrown hair in a messy bun. loose strands. pinky cheek.\n\na single frying pan is positioned next to her.\n\nfeatured in simple gray background.",
        },
        {
            "title": "간호사 + 구급상자",
            "text": "a nurse character with big collar.\n\npink hair in a neat low bun. straight bangs. pinky cheek.\n\na single first-aid kit is positioned next to her.\n\nfeatured in simple gray background.",
        },
        {
            "title": "탐정 + 돋보기",
            "text": "a cute detective character wearing a trench coat , with cape, and a small hat.\n\ndark_green shoulder-length hair. center part. slight waves. pinky cheek.\n\na single magnifying glass is positioned next to her.\n\nfeatured in simple gray background.",
        },
        {
            "title": "아이돌 무대의상 + 마이크",
            "text": "a pop idol character wearing a shiny stage outfit.\n\nblonde long hair in twin tails with curled ends. star-shaped golden hair ornament. pinky cheek.\n\na single microphone is positioned next to her.\n\nfeatured in simple gray background.",
        },
        {
            "title": "전통 기모노 + 부채",
            "text": "a traditional kimono character wearing a patterned obi.\n\nblack hair in a traditional updo. hair bun with hair sticks. pinky cheek.\n\na single folding fan is positioned next to her.\n\nfeatured in simple gray background.",
        },
        {
            "title": "스포츠(테니스) + 라켓",
            "text": "a sporty tennis character wearing a visor and athletic outfit.\n\nlight_green hair in a high ponytail tied with a ribbon. wispy bangs. pinky cheek.\n\na single tennis racket is positioned next to her.\n\nfeatured in simple gray background.",
        },
        {
            "title": "스케이트보더 + 보드",
            "text": "a skateboarder character wearing a beanie and hoodie.\n\norange hair in a spiky short cut. shaved sides. pinky cheek.\n\na single skateboard is positioned next to her.\n\nfeatured in simple gray background.",
        },
    ],

    # CJK 펫 (Klein): "펫 주제 + 소품/의상 + 표정/질감 + 심플 회색 배경" 프리셋
    # - 트리거(CJKPet.)는 서버의 숨김 마스터 프롬프트로 자동 주입되므로, 프리셋에는 포함하지 않습니다.
    "CJKStyle_Klein_Pet": [
        {
            "title": "블루 버드(베레모)",
            "text": "a rounded bird pet. blue color. beak. with necklace. beret.\n sleepy eyes.\n\nsimple gray background",
        },
        {
            "title": "3단 아이스크림 펫",
            "text": "a single ice cream pet with three layered flavor. long cone.\n\ncreamy. sleepy eyes with smiling mouth.\n\nsimple gray background",
        },
        {
            "title": "푸딩 펫(강아지귀)",
            "text": "a rounded pudding pet with doggy ears. yellow and brown color. on white dish.\n\ncreamy. sleepy eyes with smiling mouth.\n\nsimple gray background",
        },
        {
            "title": "딸기 펫(왕관/망토)",
            "text": "a rounded small strawberry pet wearing big crown. smiling. on the cardboard box.\n\nfur trimmed red cape.\n\nsimple gray background",
        },
        {
            "title": "만두 고래 펫(헬멧/스카프)",
            "text": "round dumpling whale pet with small yellow cheeks. bright fins color. bulged cheek. smiling. raising a fin. wavy cream colored tail.\n\nwearing horned iron helmet. red scarf.\n\nbending body. wet.\n\nagainst simple gray background.",
        },
        {
            "title": "크리스마스 캔디 펫",
            "text": "a christmas candy pet with ribbon. smiling.\n\nagainst simple gray background.",
        },
        {
            "title": "스케이트보드 마우스 펫",
            "text": "a mouse pet riding sci-fi skateboard with bumper. wearing baseball cap. smiling with sleepy eyes.\n\nagainst simple gray background.",
        },
    ],

    # CJK 아이템 (Klein): 게임 아이템/오브젝트 어셋 프리셋
    # - 트리거(CJKUnit.)는 서버의 숨김 마스터 프롬프트로 자동 주입되므로, 프리셋에는 포함하지 않습니다.
    "CJKStyle_Klein_Items": [
        {
            "title": "여행 캐리어",
            "text": "A stylized teal rolling suitcase with dark vertical stripes, featuring four wheels, a retractable handle, and a small pink side tag with thick black outlines.",
        },
        {
            "title": "보물상자 파우치",
            "text": "A stylized wooden treasure chest pouch with a golden central band, featuring a heavy grey chain handle and thick black outlines.",
        },
        {
            "title": "칠면조 플레이트",
            "text": "A stylized roasted Thanksgiving turkey on a white plate, garnished with green leaves, orange fruit, and red berries, featuring thick black outlines.",
        },
        {
            "title": "드릴 비트",
            "text": "A stylized conical drill bit with spiraling metallic blue and grey grooves, attached to a vibrant orange mechanical base.",
        },
        {
            "title": "정원 가위",
            "text": "A stylized pair of garden shears featuring long metallic blades and brown wooden handles decorated with swirl patterns.",
        },
        {
            "title": "전기톱",
            "text": "A stylized chainsaw with a vibrant orange motor housing, a dark grey guide bar featuring diagonal shading, and a sturdy black handle.",
        },
        {
            "title": "꼬치 음식",
            "text": "a food skewer with a thick black outline, featuring chunks of grilled meat, a red tomato slice, and a green vegetable slice on a wooden stick.",
        },
        {
            "title": "마법소녀 지팡이",
            "text": "a magical girl wand with a thick black outline, featuring a pink circular head with a yellow star, white wings, and a teal ribbon bow.",
        },
        {
            "title": "할로윈 호박 파우치",
            "text": "A stylized orange pumpkin-shaped pouch with a carved jack-o'-lantern face, and halloween ribbons, featuring a thin black handle and thick black outlines.",
        },
    ],

    # LOS Img2Img (Klein): 기존 LOS 편집 템플릿을 그대로 재사용합니다.
    "LOSStyle_Klein_Img2Img": [
        {
            "title": "슬라임→강아지 교체",
            "text": "이미지에서 파란 슬라임을 제거하고, 강아지로 교체해 주세요.",
        },
        {
            "title": "발렌타인데이 분위기 + 의상 변경",
            "text": "배경을 발렌타인데이 분위기로 바꿔 주세요. 소녀의 의상을 흰색 드레스로 바꾸고, 모자는 제거해 주세요.",
        },
        {
            "title": "날씨 변경(비 오는 밤)",
            "text": "장면을 비 오는 밤으로 바꿔 주세요. 바닥에 은은한 빗물 반사를 추가하고, 주 피사체의 선명도는 유지해 주세요.",
        },
        {
            "title": "카메라 각도: 하이앵글",
            "text": "카메라를 더 위에서 내려다보는 하이 앵글로 바꿔 주세요. 피사체 비율은 자연스럽게 유지하고, 원근감은 과하지 않게 해 주세요.",
        },
        {
            "title": "텍스트 추가(영문 워터마크)",
            "text": "이미지 오른쪽 아래에 'I was generated from LC-Canvas'라는 영문 텍스트를 추가해 주세요. 크기는 작게, 가독성이 좋도록 흰색에 약한 그림자를 적용해 주세요.",
        },
        {
            "title": "사이드뷰로 회전",
            "text": "캐릭터를 사이드뷰(측면)로 회전해 주세요. 머리 방향과 시선은 자연스럽게 유지하고, 포즈와 비율은 크게 변경하지 말아 주세요.",
        },
        {
            "title": "카메라를 바라보며 미소",
            "text": "오른쪽의 파란색 슬라임이 카메라를 바라보며 고개를 돌려 자연스럽게 미소 짓도록 해 주세요.",
        },
        {
            "title": "반 고흐 스타일",
            "text": "이미지를 반 고흐 스타일의 그림으로 바꿔주세요. 특유의 붓터치와 소용돌이 무늬 질감을 강조해 주세요.",
        },
    ],

    # OHD Img2Img (Klein): 기존 OHD 편집 템플릿을 그대로 재사용합니다.
    "OHDStyle_Klein_Img2Img": [
        {
            "title": "슬라임→강아지 교체",
            "text": "이미지에서 파란 슬라임을 제거하고, 강아지로 교체해 주세요.",
        },
        {
            "title": "발렌타인데이 분위기 + 의상 변경",
            "text": "배경을 발렌타인데이 분위기로 바꿔 주세요. 소녀의 의상을 흰색 드레스로 바꾸고, 모자는 제거해 주세요.",
        },
        {
            "title": "날씨 변경(비 오는 밤)",
            "text": "장면을 비 오는 밤으로 바꿔 주세요. 바닥에 은은한 빗물 반사를 추가하고, 주 피사체의 선명도는 유지해 주세요.",
        },
        {
            "title": "카메라 각도: 하이앵글",
            "text": "카메라를 더 위에서 내려다보는 하이 앵글로 바꿔 주세요. 피사체 비율은 자연스럽게 유지하고, 원근감은 과하지 않게 해 주세요.",
        },
        {
            "title": "텍스트 추가(영문 워터마크)",
            "text": "이미지 오른쪽 아래에 'I was generated from LC-Canvas'라는 영문 텍스트를 추가해 주세요. 크기는 작게, 가독성이 좋도록 흰색에 약한 그림자를 적용해 주세요.",
        },
        {
            "title": "사이드뷰로 회전",
            "text": "캐릭터를 사이드뷰(측면)로 회전해 주세요. 머리 방향과 시선은 자연스럽게 유지하고, 포즈와 비율은 크게 변경하지 말아 주세요.",
        },
        {
            "title": "카메라를 바라보며 미소",
            "text": "오른쪽의 파란색 슬라임이 카메라를 바라보며 고개를 돌려 자연스럽게 미소 짓도록 해 주세요.",
        },
        {
            "title": "반 고흐 스타일",
            "text": "이미지를 반 고흐 스타일의 그림으로 바꿔주세요. 특유의 붓터치와 소용돌이 무늬 질감을 강조해 주세요.",
        },
    ],
}


