## 다음 세션용 “프로젝트 현황서 + 지시서” (2026-02-04 기준)

대상 저장소: `c:\Works\ComfyUI_FastAPI`  
환경: Windows / FastAPI + 템플릿 기반 프론트  
프론트 핵심 JS: `templates/index.html` 내부 `<script>`에 큰 비중으로 존재

이번 세션까지 목표:  
- NanoBanana(Google) 기반 **그리드 출력 워크플로우 2종**을 안정화
  - (A) **스토리보드 컷보드**: 6컷/9컷 (2×3 / 3×3)
  - (B) **다음 장면 바리에이션**: 4개 (2×2)
- 모델이 자동으로 그리는 **흰색 보더/거터(구분선)** 문제를 프롬프트만으로 해결하기 어려워서  
  서버 저장 직전에 **자동 후처리(보더 제거 후 재합성)** 를 도입

---

## 0) 큰 그림(구조 요약)

- **워크플로우 정의의 “진짜 소스”**: `app/workflow_configs.py`의 `WORKFLOW_CONFIGS`
- **생성 엔진 분기(핵심)**: `app/services/generation.py`
  - 워크플로우 설정의 `provider == "google"`이면 **ComfyUI를 완전히 우회**하고 Google(Gemini/NanoBanana)로 호출
  - 그 외는 ComfyUI 경로
- **구글 프롬프트 합성**: `app/services/google_nano_banana.py`의 `build_google_prompt()`
  - `style_prompt` + `user_prompt`를 합쳐 최종 프롬프트를 생성
  - (이번 세션 변경) negative 문구 접두사는 `Avoid:` 대신 `Keep absent:`를 사용
- **이미지 저장 + 메타 저장**: `app/services/media_store.py`의 `_save_image_and_meta()`
  - PNG 저장 + sidecar JSON(meta) 저장
  - (이번 세션 변경) 특정 워크플로우에 한해 저장 직전에 **그리드 보더 제거 후처리** 수행
- **워크플로우 목록 API**: `app/routers/workflows.py`
- **프론트(웹 UI)**:
  - 입력 옵션 UI: `templates/partials/input_panel.html`
  - 대부분의 동작 로직: `templates/index.html` 내부 JS

---

## 1) 이번 세션에서 추가/변경된 워크플로우

### 1.1 스토리보드 컷보드 (기존 + 폴리싱)
- **ID**: `NanoBanana_StoryboardCutboard`
- **입력**: 이미지 1장 (필수)
- **출력**: 6컷(2×3) 또는 9컷(3×3) “그리드 1장”
- **프롬프트 형태**: 체크리스트(필드) 스타일로 정리 (NanoBanana가 더 잘 따르는 경향)
- **부정형 문장 제거**: `no / do not / avoid` 계열 표현을 전체적으로 제거하고,  
  `absent`, `unchanged`, `border=0` 같은 서술형으로 통일

관련 코드:
- 워크플로우: `app/workflow_configs.py`
- 옵션 UI: `templates/partials/input_panel.html` (`#storyboard-options-wrap`)
- 프론트 UI 적용: `templates/index.html`의 `applyStoryboardToolUiForWorkflow()`
- 프롬프트 조립: `templates/index.html`의 `handleGenerateClick()` 내부  
  `// Tool-specific prompt augmentation (NanoBanana Storyboard Cutboard)`

### 1.2 다음 장면 바리에이션 (신규)
- **ID**: `NanoBanana_WhatsNextVariations`
- **목적**: 입력 이미지의 맥락을 바탕으로 “그 다음 전개”를 **4개**(2×2)로 자동 상상하여 출력
- **입력**: 이미지 1장 (필수)
- **프롬프트 입력(UI)**: 기본 목적상 사용자가 다음 내용을 모르는 상태이므로
  - **프롬프트 입력창을 숨김** (`hideUserPrompt: true`)
  - 입력이 없어도 생성 가능
  - (확장 여지) 추후 “고급 토글”로 프롬프트 입력을 다시 열 수 있음

관련 코드:
- 워크플로우: `app/workflow_configs.py`
- 옵션 UI: `templates/partials/input_panel.html` (`#whatsnext-options-wrap`)
- 프론트 UI 적용: `templates/index.html`의 `applyWhatsNextToolUiForWorkflow()`
- 프롬프트 조립: `templates/index.html`의 `handleGenerateClick()` 내부  
  `// Tool-specific prompt augmentation (NanoBanana What's Next Variations)`

---

## 2) 흰색 보더/거터 문제 해결: 저장 직전 “자동 후처리” 도입 (핵심)

### 2.1 왜 프롬프트로만 해결이 어려운가?
- 모델이 “그리드”를 만들 때 관성적으로 **흰 여백/테두리/거터**를 넣는 경우가 많아,
  프롬프트를 강하게 써도 **완전 제거가 100% 보장되지 않음**

### 2.2 현재 적용된 해결책(서버 후처리)
파일: `app/services/media_store.py`

- `_save_image_and_meta()`에서 실제 PNG 저장 직전에:
  - `_maybe_postprocess_grid_image()`를 호출
  - 대상 워크플로우:
    - `NanoBanana_StoryboardCutboard`
    - `NanoBanana_WhatsNextVariations`
- 내부 동작 요약:
  - PIL로 이미지를 열고 그레이스케일로 변환
  - 세로/가로 방향으로 “흰색 또는 검은색 띠”를 점수화해 구분선 후보를 찾음
  - (3×3, 2×3, 2×2 등) **기대 그리드 크기**에 맞는 구분선 위치를 고르고
  - 각 패널을 크롭한 뒤 **edge-to-edge로 다시 붙여** 1장 PNG로 저장
- 처리 결과는 meta에 기록:
  - `meta.postprocess.grid_border_removed: true/false`
  - 실패 시 `reason` 포함

### 2.3 현재 테스트 결과(사용자 피드백)
- **3×3(스토리보드 9컷)**: 보더가 “아주 예쁘게” 제거됨 (성공)
- **2×2(다음 장면 바리에이션)**: “동작은 했지만 조금 불완전” (개선 필요)

---

## 3) 다음 세션 1순위 작업: 2×2 후처리 폴리싱

### 3.1 목표
- `NanoBanana_WhatsNextVariations` 결과에서 남는 얇은 보더/잘림/미세 오프셋을 더 줄여
  **2×2도 안정적으로 edge-to-edge**가 되게 만들기

### 3.2 수정 포인트(코드 위치)
파일: `app/services/media_store.py`

주요 함수:
- `_maybe_postprocess_grid_image()`: 워크플로우별로 grid를 정하고 후처리 호출
- `_remove_grid_borders_and_stitch(im, cols, rows)`: 실제 감지/크롭/재합성

조절 후보 파라미터:
- `white_thr`, `black_thr`: “흰 띠/검은 띠” 판정 기준
- separator threshold loop: `(0.92, 0.88, 0.84, 0.80, 0.76)`
- `edge_margin_x/y`: 외곽 테두리 감지/제거 범위
- `trim = 2`: 패널 크롭 시 안쪽으로 더 당기는 값(너무 크면 내용이 잘리고, 너무 작으면 선이 남음)

### 3.3 권장 디버깅 방법
- 실패/불완전 사례 1장을 확보
  - 결과 meta의 `postprocess`를 확인 (성공/실패, reason)
- (추천) 다음 세션에서는 일시적으로 디버그 로그 또는 임시 저장을 넣어
  - 감지된 separator 위치(x/y segments)
  - 최종 크롭 박스(x_panels/y_panels)
  를 확인하면 튜닝이 빠름

---

## 4) UI 관련 변경(참고)

### 4.1 사이드바 정리
- `워크플로우` 헤더(기어 아이콘 + “워크플로우” 텍스트) 제거
  - HTML: `templates/partials/sidebar.html`
  - CSS: `static/css/layout.css`에서 관련 스타일 제거/여백 정리

### 4.2 좌측 상단 로고 배너 배경/테두리 정리
- 투명 PNG 로고 교체 후 보이는 배경/테두리를 정리
  - `.sidebar-header` 배경을 페이지 배경과 통일: `static/css/layout.css`
  - `.brand-banner` 배경 투명 + border 제거: `static/css/components.css`

---

## 5) 현재 Git 상태 주의사항

`git status` 기준 변경 파일이 매우 많습니다.

- 커밋 주의:
  - `db/app_data.db`는 로컬 데이터가 섞일 수 있어 커밋 제외 권장
- 새로 추가된/중요 파일:
  - `app/services/media_store.py` (그리드 후처리 추가)
  - `app/workflow_configs.py` (새 워크플로우 및 프롬프트 정책 변경)
  - `templates/index.html`, `templates/partials/input_panel.html` (UI/프롬프트 조립 로직)

---

## 6) 다음 세션 시작 체크리스트
- [ ] 서버 실행 후 `다음 장면 바리에이션 (4개)`로 2×2 결과 3~5회 생성
- [ ] meta의 `postprocess`를 확인해 실패 유형을 분류
- [ ] `media_store.py` 후처리 파라미터(특히 2×2 케이스) 튜닝

