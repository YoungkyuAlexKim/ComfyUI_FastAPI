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
    "AceStep15XL": [
        # ── Tier 1: 높은 품질 ──
        {"title": "🌊 Lo-fi 힐링", "tier": 1,
         "text": "Dusty vinyl-crackle texture over a mellow hip-hop drum loop with lazy swing. Warm Rhodes electric piano plays soft jazzy chords while a detuned tape-wobble bass sits underneath. Relaxed and hazy with filtered high frequencies."},
        {"title": "🌃 일렉트로닉/하우스", "tier": 1,
         "text": "Pulsing synthesizer arpeggios over a four-on-the-floor kick drum with sizzling open hi-hats. Layered saw-wave pads build into a euphoric drop with sidechained bass compression. Bright, modern, and uplifting electronic production."},
        {"title": "🔥 힙합/랩", "tier": 1,
         "text": "rap, minimal, spoken word, dark, minimal beats with heavy basslines; sharp snares; spoken-word flow intertwined with rhythmic delivery; male vocals. introspective and raw energy."},
        {"title": "🌆 신스웨이브", "tier": 1,
         "text": "Pulsing analog synthesizer arpeggios with a retro drum machine pattern featuring gated snare reverb. Warm saw-wave pads and a soaring lead synth play nostalgic melodies over a driving electronic bass line. 80s neon-soaked atmosphere with vintage analog warmth and chorus effects."},
        {"title": "🧘 앰비언트/뉴에이지", "tier": 1,
         "text": "Slowly evolving synthesizer pads with shimmering high harmonics and deep sub-bass drones. Crystal singing bowl tones and gentle wind chimes float over a bed of warm reverb. Spacious, meditative, and tranquil with no rhythmic pulse, pure atmospheric texture."},
        {"title": "🎧 드럼앤베이스", "tier": 1,
         "text": "Rapid breakbeat drum patterns with choppy snare rolls and deep rolling sub-bass. Atmospheric synth pads and reverb-drenched vocal samples float over the frenetic rhythm. Dark, intense, and high-velocity electronic production with heavy bass compression."},
        # ── Tier 2: 좋은 품질 ──
        {"title": "🎹 피아노 발라드", "tier": 2,
         "text": "Expressive solo piano with sustain pedal, playing gentle arpeggiated chords and a lyrical melody. Soft string pads swell underneath during choruses. Slow tempo with rubato phrasing and intimate room reverb."},
        {"title": "🎵 K-Pop", "tier": 2,
         "text": "Punchy synthesizer stabs and a tight electronic drum pattern with snappy hi-hats and deep sub-bass. Catchy vocal melody with layered harmonies over a driving four-on-the-floor groove. Bright, polished, and high-energy production."},
        {"title": "🎸 팝 록", "tier": 2,
         "text": "Driving electric guitar power chords with a punchy drum kit on a four-on-the-floor beat. Melodic bass line locks with the kick drum while a bright lead guitar plays hooky riffs. Energetic and anthemic with layered backing vocals."},
        {"title": "🎶 어쿠스틱 포크", "tier": 2,
         "text": "Fingerpicked steel-string acoustic guitar in a gentle waltz-time pattern with open tuning resonance. A soft harmonica plays a wistful counter-melody while light tambourine taps keep rhythm. Warm, earthy, and nostalgic."},
        {"title": "🎤 R&B", "tier": 2,
         "text": "Smooth Rhodes electric piano chords with a laid-back drum machine groove and deep sub-bass. Silky vocal melody with falsetto runs and breathy ad-libs over lush pad harmonies. Warm, sultry, and groove-driven."},
        {"title": "🌸 시티팝", "tier": 2,
         "text": "Bright slap bass with a tight drum groove and shimmering chorus-effect electric guitar. Lush synthesizer pads and a punchy brass section accent the upbeat melody. Nostalgic 80s Japanese city-pop production with warm analog warmth."},
        {"title": "🌴 보사노바", "tier": 2,
         "text": "Gentle nylon-string guitar playing syncopated bossa nova chord patterns with soft thumb-and-finger technique. A breathy female vocal delivers a smooth, whispery melody over light brushed percussion and a warm acoustic bass. Intimate, tropical, and effortlessly cool."},
        {"title": "🎷 재즈 카페", "tier": 2,
         "text": "Brushed snare drum with a lazy swing feel and warm upright bass walking chromatic lines. A breathy tenor saxophone improvises behind the beat over lush piano voicings with extended ninth and thirteenth chords. Intimate and mellow."},
        {"title": "👶 동요/키즈", "tier": 2,
         "text": "A cheerful children's song with a bright ukulele strumming a simple down-up pattern on major chords with a crisp nylon-string tone. A glockenspiel doubles the vocal melody with sparkling bell-like clarity. A young female voice sings with pure, innocent tone over a bouncy, playful rhythm."},
        {"title": "🌙 어반 힙합 J-Pop", "tier": 2,
         "text": "Electronic hip-hop beat with crisp drum machine patterns and a deep synthesized bass line. Atmospheric synth pads and glitchy vocal chops create an urban nighttime mood. A female vocalist sings smooth J-pop melodies alternating with rhythmic spoken-word rap verses."},
        {"title": "⚡ J-Pop 팝 록", "tier": 2,
         "text": "Bright and energetic J-pop rock with driving power chord electric guitar and a punchy drum kit at an upbeat tempo. Catchy synth hooks and shimmering keyboards layer over a tight bass groove. Powerful female vocal with an enthusiastic, youthful delivery singing an infectious hook melody."},
        # ── Tier 3: 실험적 (결과 편차 있음) ──
        {"title": "🕺 펑크/소울", "tier": 3,
         "text": "Tight slap bass groove locking with a crisp hi-hat pattern and syncopated snare hits. Rhythmic clavinet chops and wah-wah guitar stabs punctuate the groove. Brass section plays short staccato horn stabs on the off-beats."},
        {"title": "🌍 레게/스카", "tier": 3,
         "text": "Off-beat guitar skanks with a deep one-drop bass pattern and rim-shot snare on beat three. Organ bubbles underneath while a brass section plays melodic horn lines. Laid-back, sunny, and rhythmically infectious."},
        {"title": "🪩 디스코", "tier": 3,
         "text": "Four-on-the-floor kick drum with sizzling open hi-hats and a tight funky bass line playing syncopated octave jumps. Lush string section plays sweeping sustained chords while rhythmic guitar scratches on the off-beats. Bright, groovy, and euphoric with shimmering production."},
        {"title": "🪕 컨트리", "tier": 3,
         "text": "Bright steel-string acoustic guitar with a steady boom-chick strumming pattern and a twangy pedal steel guitar sliding between notes. Fiddle plays lively double-stop fills while an upright bass keeps a walking country shuffle. Warm, rootsy, and down-home."},
        {"title": "🎷 블루스", "tier": 3,
         "text": "Twelve-bar blues shuffle with a lazy swing drum groove and a warm overdriven electric guitar bending expressive blue notes. Hammond organ sustains rich chords underneath while an electric bass walks a steady pattern. Raw, soulful, and deeply emotional with gritty analog tone."},
        {"title": "🏖️ 레게톤/라틴팝", "tier": 3,
         "text": "Dembow drum pattern with a crisp snare on the off-beat and deep 808 sub-bass. Latin percussion including congas and timbales add rhythmic layers while a bright synth hook repeats over reggaeton groove. Hot, danceable, and infectious latin energy."},
        {"title": "🎷 재즈 펑크/퓨전", "tier": 3,
         "text": "Tight slap bass locking with a crisp funk drum groove and syncopated hi-hat patterns. Electric piano plays jazzy extended chords with chorus effect while a distorted guitar and saxophone trade rapid-fire melodic phrases. Virtuosic, groovy, and technically complex fusion arrangement."},
        {"title": "💃 탱고", "tier": 3,
         "text": "Dramatic bandoneón playing passionate legato phrases with sharp staccato accents over a tight rhythmic pulse. Pizzicato double bass drives the habanera rhythm while a solo violin adds emotional counter-melodies. Intense, sensual, and deeply expressive Argentine tango."},
        {"title": "🃏 애시드 재즈 보컬", "tier": 3,
         "text": "Smooth acid jazz with a funky slap bass groove and Rhodes electric piano playing jazzy seventh chords with tremolo. Tight drum kit with hi-hat-heavy patterns and muted brass stabs on syncopated accents. A sultry alto female vocal with husky chest resonance and a slightly raspy edge, delivering cool, stylized phrases with confident attitude and jazz-inflected phrasing."},
    ],
}


