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


