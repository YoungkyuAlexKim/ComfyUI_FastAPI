## 다음 세션 인계 문서 — 공용 캐릭터 폴더/썸네일 UI + @멘션 스코프 고정 + 다음 작업(ComfyUI img2img 다운스케일 1536) (2026-02-04)

대상 저장소: `c:\Works\ComfyUI_FastAPI`  
환경: Windows / FastAPI + Jinja 템플릿 프론트 (`templates/index.html` 내 JS 큼)  

이 문서는 **다음 세션(동료 AI)**가 초반에 코드베이스 탐색으로 토큰을 낭비하지 않도록, 아래 변경/구조/다음 작업을 한 번에 이해시키는 것이 목표입니다.

- 이번 세션에서 구현된 기능(공용 캐릭터 폴더 기반 등록, 썸네일, UI 개선, @멘션 스코프 제한)
- 현재 동작 규칙(레퍼런스 6장, 공용 폴더 규칙, 멘션 프롬프트 구성)
- 다음 세션의 확정 작업: **ComfyUI img2img 입력 이미지 다운스케일(비율 유지, 긴 변 1536 상한)**

---

## 0) 큰 그림(현재 아키텍처 요약)

- **워크플로우 원본 설정**: `app/workflow_configs.py`의 `WORKFLOW_CONFIGS`
- **생성 라우팅(ComfyUI vs Google)**: `app/services/generation.py`
  - `provider == "google"`이면 Google(Gemini/NanoBanana) 호출
  - 그 외는 ComfyUI 호출
- **Google 최종 프롬프트 합성**: `app/services/google_nano_banana.py`의 `build_google_prompt()`
  - 워크플로우의 `style_prompt`/`negative_prompt`를 `user_prompt`에 합쳐 최종 프롬프트 생성
- **프론트**: `templates/index.html` 내부 스크립트가 핵심

---

## 1) 이번 세션에서 구현된 핵심 변경(무엇이 달라졌나)

### 1.1 공용(전역) 캐릭터: 폴더 기반 등록/조회

**목표**: 운영자가 폴더에 이미지를 넣기만 하면 “공용 캐릭터”로 인식되고, `/newfeature`에서 추천 캐릭터로 노출되며, `@이름`으로 참조 가능.

구현 파일:
- `app/services/global_character_store.py`
  - 공용 캐릭터 폴더 스캔 + 레퍼런스 이미지 6장 선택 + (선택) 썸네일 URL 제공
- `app/routers/global_characters.py`
  - `GET /api/v1/global-characters` 제공
- `app/main.py`
  - 글로벌 라우터 include
- `app/schemas/api_models.py`
  - `GlobalCharacterItem`, `GlobalCharactersResponse` 추가

공용 캐릭터 폴더 규칙:
- 베이스 폴더: `outputs/global/characters/<name>/`
- `<name>` 규칙: `^[A-Za-z0-9가-힣_-]{1,32}$` (공백 불가)
- 레퍼런스 이미지:
  - 지원 확장자: `.png`, `.jpg`, `.jpeg`, `.webp`
  - **최소 6장 필요** (서버는 정렬 규칙으로 6장을 골라 사용)
  - 정렬 우선순위:
    1) 파일명이 `ref_01`~`ref_06`처럼 `ref + 숫자`를 포함
    2) 그 외는 파일명 알파벳/가나다 순
- (선택) 썸네일:
  - 같은 폴더에 `thumb.png`(권장) 또는 `thumb.webp`/`thumb.jpg`/`thumb.jpeg`
  - 대체 이름도 허용: `thumbnail.*`, `avatar.*`

### 1.2 @이름 캐릭터 멘션 기능: “기본 NanoBanana txt2img만” 표시/동작하도록 스코프 고정

문제(기존):
- 나노바나나 계열 툴 워크플로우(스토리보드/다음장면 등)에서도 캐릭터 UI가 떠서 의도와 달랐음.

해결:
- `app/workflow_configs.py`의 `NanoBanana`(기본 워크플로우)만 `ui.characterMentions = True`로 설정
- 프론트의 `canUseCharacterMentions()`에서 다음 조건을 모두 만족해야만 캐릭터 UI를 표시:
  - `/newfeature` 페이지
  - `txt2img` 모드
  - 워크플로우 id가 **`NanoBanana`**
  - `ui.characterMentions === true`
- 서버(`app/services/generation.py`)도 동일하게 `wf_cfg.ui.characterMentions === true`일 때만 `@` 감지 로직이 실행되도록 게이트 추가

### 1.3 캐릭터 레퍼런스 개수: 6장으로 통일

개인 캐릭터(유저 캐릭터) 저장/검증/생성 경로 모두 **6장 필수**로 통일됨.

주요 포인트:
- `app/routers/characters.py`: 저장 시 6장 검증
- `app/services/generation.py`: 멘션 캐릭터 레퍼런스 6장 검증
- `app/character_store.py`:
  - `REQUIRED_CHARACTER_REFERENCE_IMAGE_COUNT = 6`
  - 과거 5장 데이터는 best-effort로 6장으로 보정(첫 이미지 1장 복제)하는 migration 로직 포함

### 1.4 공용 캐릭터 UI: 썸네일 카드 + 수평 스크롤 + 마우스 드래그 스크롤

UI 목표:
- 공용 캐릭터는 텍스트 칩이 아니라 **썸네일 카드(원형 아바타 + 이름)**로 표시
- 가로(수평) 목록 + 마우스 드래그로 스크롤 가능
- “추가(캐릭터 등록/관리)”도 동일한 카드 스타일로 제공

구현:
- `templates/index.html`
  - 공용 캐릭터 목록 fetch: `/api/v1/global-characters` (썸네일 URL 포함)
  - 렌더: `renderCharacterQuickList()`에서
    - 공용/개인 캐릭터를 카드로 렌더
    - “추가 카드”를 목록 맨 앞에 배치
  - 수평 드래그 스크롤: `bindHorizontalDragScroll()`
    - **드래그가 실제로 시작된 경우에만** pointer capture (클릭 방해 이슈 해결)
- `static/css/components.css`
  - `.global-character-row__items`는 `overflow-x: auto` + 스크롤바 숨김 + `cursor: grab`
  - 카드/아바타 크기(현재 40px)

### 1.5 프롬프트 하이라이트(겹쳐쓰기) 제거 + “감지된 캐릭터 바”로 대체

문제:
- textarea 위에 하이라이트 레이어를 덮는 방식은 커서/줄바꿈 싱크가 계속 깨질 수 있음(구조적 한계).

해결:
- 하이라이트 오버레이는 비활성화(숨김)
- 대신 프롬프트 아래에 “감지된 캐릭터” 칩 목록(`prompt-mentions-bar`)을 보여줌
  - 등록/공용/미등록 상태를 칩으로 표시
  - 클릭 시 안내(내 캐릭터는 관리 모달, 공용은 정보 토스트 등)

관련 파일:
- `templates/partials/input_panel.html`: `#prompt-mentions-bar` 추가
- `templates/index.html`: `renderPromptMentionsBar()` 추가, 하이라이트 렌더링 비활성화
- `static/css/components.css`: `.prompt-highlights`는 `display:none`

---

## 2) @이름 멘션 생성이 서버에서 어떻게 처리되는가(핵심 로직)

파일: `app/services/generation.py`

Google provider + txt2img 경로에서:
- `wf_cfg.ui.characterMentions === true`이고, `user_prompt`에 `@`가 있으면:
  1) `@([A-Za-z0-9가-힣_-]{1,32})` 토큰을 **등장 순서대로** 추출(중복 제거)
  2) 각 이름에 대해 조회 우선순위:
     - 개인 캐릭터(`CharacterStore.get_by_name(owner_id, name)`) 우선
     - 없으면 공용 폴더(`get_global_character(name)`) 조회
  3) 레퍼런스 6장을 로드
     - 개인: inputs/gallery에서 id로 PNG bytes 로드
     - 공용: 로컬 파일 경로에서 bytes 로드
  4) 6장을 3×2로 합쳐 “레퍼런스 시트” PNG bytes 생성(`build_character_reference_sheet`)
  5) Google image-edit API로 호출 (레퍼런스 시트들을 `images=[...]`로 전달)
  6) 메타에 `request.character_mentions` 기록

### 현재 “멘션용 내부 프롬프트” 구성(중요)
최근 튜닝 결과로, 멘션 시에는 서버가 `request.user_prompt`를 아래 포맷으로 바꿔 Google에 전달합니다:
- `REFERENCE_SHEETS_ORDER` (1) 이름 / (2) 이름 …
- `USER_PROMPT` (사용자 프롬프트에서 `@`는 제거되고 이름만 남음)
- `RULES_CHECKLIST` (아주 짧은 2줄 스타일/정체성 유지 규칙)

스타일 유지가 완벽하진 않지만, 복잡한 조건문보다 이 “짧은 체크리스트”가 더 나은 경향이 있었음.

---

## 3) 빠른 테스트 시나리오(다음 세션 시작 체크리스트)

1) 공용 캐릭터 폴더에 캐릭터 1개 준비  
   - `outputs/global/characters/가영/`  
   - `ref_01.png`~`ref_06.png` + (선택) `thumb.png`
2) 서버 실행 후 브라우저에서 `/newfeature` 접속
3) `GET /api/v1/global-characters` 호출 시 `가영`이 목록에 보이는지 확인
4) 워크플로우: **NanoBanana(기본 워크플로우)** 선택 + **txt2img 모드** 확인
5) 이때만 캐릭터 섹션이 보이는지 확인(다른 나노바나나 툴 워크플로우에서는 숨김이어야 함)
6) 프롬프트에 `@가영` 입력 → 아래 “감지된 캐릭터” 바에 표시되는지 확인
7) 생성 시 `@가영`이 등록되어 있지 않다는 차단이 걸리지 않고 진행되는지 확인

---

## 4) 다음 세션 확정 작업: ComfyUI img2img 입력 다운스케일(비율 유지, 긴 변 1536 상한)

배경:
- NanoBanana 출력은 기본적으로 큰 해상도(예: landscape 2752×1536, square 2048×2048)라
- 이를 로컬 ComfyUI img2img로 가져가면 **연산량이 커져 매우 느려짐**.

결정된 정책:
- **비율 유지**
- **긴 변(max side) 1536px 상한**
  - 긴 변이 1536을 초과하면 1536으로 축소
  - 1536 이하면 그대로 사용

권장 구현 위치(유력):
- `app/services/generation.py`의 ComfyUI 경로에서
  - 입력 이미지를 `client.upload_image_to_input()` 하기 **직전**
  - bytes를 PIL로 열어서 해상도 판단 후 필요 시 리사이즈

구현 원칙(중요):
- **원본은 보존** (inputs/gallery에 저장된 파일은 그대로)
- ComfyUI로 전달할 때만 축소본 bytes를 생성해서 업로드
- 가능하면 메타에 기록:
  - 원본 해상도, 축소 여부, 축소 후 해상도, 적용된 상한값(1536)

참고할 코드(리사이즈/EXIF 처리 힌트):
- `app/routers/inputs.py`에 이미지 변환(PIL + `ImageOps.exif_transpose`) 예시가 있음

---

## 5) 운영/커밋 주의사항

- `db/app_data.db`는 로컬 데이터가 섞이기 쉬워서 커밋 제외 권장
- 공용 캐릭터 이미지(`outputs/global/characters/...`)는 운영 데이터이므로 보통 커밋 대상이 아님(환경에 따라 별도 배포)

