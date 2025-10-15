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
    "BasicWorkFlow_LOSStyle": [
        {"title": "1인 전신", "text": "1girl, chibi, solid_oval_eyes, solo, full_body, brown hair, bob cut, school uniform, pleated skirt, standing, thick outline, on grass, blue sky, cloud, building, simple background"},
        {"title": "2인 전신", "text": "2girls, chibi, solid_oval_eyes, blone hair, bob cut, red hair, twin tail, standing, thick outline, street, symmetry,simple background"},
        {"title": "상황설정1", "text": "1girl, solo, solid_oval_eyes, dress, chibi,bob cut, brown hair, holding slime, blue slime_\(creature\), library, from_above, shadow"},
        {"title": "상황설정2", "text": "2girls,chibi, solid_oval_eyes, looking away, standing, dress, long hair, red hair, robe, blonde hair, long skirt, hand_to_hand, night, full_moon, on_grass, cloud"},
        {"title": "상황설정3", "text": "1boy, solo, chibi, solid_oval_eyes, kneeling, praying, armor, hair_slicked_back, black hair, stained_glass, church, dappled_sunlight, light_rays"},
        {"title": "상황설정4", "text": "1girl, chibi, solid_oval_eyes, short hair, blue_hair, solo_focus, lying, on_back, pajamas, dog, dynamic_angle, indoors, bed, bed_sheet, wooden_wall, stone_wall, inn, black_outline, simple_background"},
        {"title": "상황설정5", "text": "1boy, solo, chibi, solid_oval_eyes, astronaut, floating, blonde_hair, space, stars, planet, black outline, simple background, fisheye"},
        {"title": "상황설정6", "text": "1girl, chibi, solid_oval_eyes, solo, brown_hair, ribbon, robe, hat, looking up, full_body, standing, looking_at_viewer, blue slime_\(creature\), night, dutch angle, from above"},
        {"title": "상황설정7", "text": "1girl, chibi, solid_oval_eyes, solo, blue hair, ribbon, fur-trimmed_coat, hat, full_body, sitting, bench, park, looking_at_viewer, blue slime_\(creature\), night, dutch angle"},
        {"title": "동적 앵글", "text": "1girl, chibi, solid_oval_eyes, dynamic_angle, dutch_angle, air_view, flying"},
        {"title": "몬스터: 슬라임", "text": "no_humans, solid_oval_eyes, slime, blue_slime, red_slime, multiple_slime"},
    ],
}


