## 다음 세션 인계 문서 — NanoBanana 캐릭터 멘션 + UI/후처리 정리 (2026-02-04)

대상 저장소: `c:\Works\ComfyUI_FastAPI`  
환경: Windows / FastAPI + Jinja 템플릿 프론트(`templates/index.html`에 JS가 큼)

이 문서는 **다음 세션(동료 AI)**가 “코드 탐색으로 토큰을 낭비하지 않도록” 아래를 한 번에 이해하는 것을 목표로 합니다.

- **현재 핵심 기능이 어디에 붙어 있는지**
- **이번 세션에서 추가/수정한 기능들**
- **다음 세션에서 할 작업(특히 ‘공용 캐릭터 레지스트리’)의 추천 구조**

---

## 0) 큰 그림(현재 아키텍처)

- **워크플로우 설정의 진짜 원본**: `app/workflow_configs.py`의 `WORKFLOW_CONFIGS`
- **생성 라우팅(ComfyUI vs Google)**: `app/services/generation.py`
  - `provider == "google"`이면 ComfyUI를 우회하고 Google(Gemini/NanoBanana) 호출
- **구글 프롬프트 합성**: `app/services/google_nano_banana.py`
  - `build_google_prompt()`가 `style_prompt`/`user_prompt`/negative 지시문을 합쳐 최종 프롬프트 생성
- **이미지 저장/메타 저장**: `app/services/media_store.py`
  - PNG 저장 + sidecar JSON(meta) 저장

프론트(웹 UI):
- UI: `templates/*.html`
- 핵심 동작 JS: `templates/index.html` 내부 `<script>`
- 아이콘: FontAwesome CDN `6.4.0` (free) — `templates/base.html`

---

## 1) 이번 세션 핵심 변경 요약(무엇이 달라졌나)

### 1.1 그리드 보더 제거 후처리 강화(9컷/4컷)
파일: `app/services/media_store.py`
- `_remove_grid_borders_and_stitch()`에서
  - separator 주변 제거 폭 확대(`sep_pad=2`)
  - 패널 크롭(trim) 더 공격적으로(`trim=4`)
  - 최종 외곽 테두리 남는 경우 “면도(shave)” 단계 추가
- meta에 튜닝값을 기록하도록 추가:
  - `meta.postprocess.tuning`

목표: **내용이 1~2px 잘려도 괜찮으니 보더가 안 보이게**.

### 1.2 NanoBanana 워크플로우를 기본 진입에서 숨김(비용/발견 방지)
파일:
- `app/routers/workflows.py`
  - `GET /api/v1/workflows?include_google=1` 옵션 추가
  - 기본은 `provider=google` 워크플로우를 목록에서 제외
- `app/main.py`
  - `/newfeature` 페이지 라우트 추가(템플릿은 `index.html` 동일)
- `templates/index.html`
  - `/newfeature`에서만 `/api/v1/workflows?include_google=1`로 로드

결과:
- `/create`: NanoBanana(google provider) 자체가 목록에 안 뜸
- `/newfeature`: NanoBanana 포함

### 1.3 워크플로우 카테고리/표기/아이콘 개선
파일:
- `templates/index.html`
  - 카테고리 라벨 변경:
    - “자연어 프롬프트” → “사내 게임 스타일”
    - “나노바나나” → “나노바나나 Pro”
  - 워크플로우 아이콘이 고정(`fa-project-diagram`)이던 문제 해결:
    - 이제 `wf.ui.icon`을 읽어서 `<i class="fas fa-${icon}">`로 렌더
- `app/workflow_configs.py`
  - NanoBanana 워크플로우 이름 변경:
    - `NanoBanana.display_name`: “기본 워크플로우”
    - `NanoBanana_Img2Img.display_name`: “기본 워크플로우 — 편집”
  - 주요 워크플로우에 `ui.icon` 값 추가
  - 아이콘 이슈:
    - CJK 아이콘으로 톱(saw) 시도했으나 표시 안 됨 → `glass-water`로 변경(주스 컵 느낌)
    - LOS: `droplet`, OHD: `dog` 등

---

## 2) 이번 세션 핵심 피쳐: `@이름` 캐릭터 멘션(레퍼런스 자동 적용)

### 2.1 목표 UX
- 사용자는 `/newfeature`의 NanoBanana 기본 워크플로우(txt2img)에서
  - 프롬프트에 `@제임스 @마리안 ...`처럼 쓰기만 하면 됨
- 서버가 캐릭터별 레퍼런스 6장을 **캐릭터당 1장 몽타주(레퍼런스 시트)**로 합쳐서
  - Google image-edit(img2img)로 자동 전환하여 호출
- 등록되지 않은 `@이름`은 비용 보호를 위해 **생성 차단**

### 2.2 데이터 저장(개인 캐릭터)
신규 파일: `app/character_store.py`
- SQLite(`db/app_data.db` / `JOB_DB_PATH`)에 `character_registry` 테이블을 런타임 자동 생성
- 키 정책:
  - `(owner_id(anon_id), name)` 유니크
- 저장 값:
- `reference_image_ids` (JSON 문자열) — **정확히 6개**
  - `thumbnail_image_id` (기본: 첫 레퍼런스)
  - `status` / `created_at` / `updated_at`

### 2.3 API(개인 캐릭터)
신규 파일: `app/routers/characters.py` (+ `app/main.py`에서 router include)

엔드포인트:
- `GET /api/v1/characters?include=active|all|...`
- `POST /api/v1/characters`
  - body: `{ name, reference_image_ids }`
  - 검증:
    - name: `^[A-Za-z0-9가-힣_-]{1,32}$` (공백 금지)
- reference_image_ids: 중복 제거 후 **정확히 6장**
    - 각 id는 내 `inputs` 또는 내 `generated gallery`에 존재해야 함
- `POST /api/v1/characters/{name}/delete` (soft-delete)

스키마 추가:
- `app/schemas/api_models.py`에 `CharacterItem`, `CharactersResponse`, `CharacterUpsertRequest/Response` 추가

### 2.4 몽타주(레퍼런스 시트) 생성
신규 파일: `app/services/character_refs.py`
- 입력: 이미지 bytes list
- 출력: 단일 PNG bytes
- 기본 구성:
- 6장 → 3x2 그리드(`cols=3`, `rows=2`)
  - `tile_size=512`
  - gutter/border 없음(edge-to-edge)
  - center-crop to square 후 리사이즈(외곽 손실 OK 정책)

### 2.5 서버 호출 전환(`@` 감지 시 txt2img → image-edit)
수정 파일: `app/services/generation.py`

핵심 포인트:
- google provider 경로에서 `is_txt2img`이면서 `user_prompt`에 `@`가 있으면:
  1) `@([A-Za-z0-9가-힣_-]{1,32})` 토큰 추출(중복 제거)
  2) `CharacterStore`에서 해당 name 조회 (없으면 **RuntimeError로 중단**)
  3) 레퍼런스 6장을 로드(입력/갤러리 둘 다 지원)
  4) 캐릭터별로 몽타주 PNG bytes 생성
  5) `request.user_prompt`를 증강:
     - REFERENCE SHEETS 순서 안내문 + `@` 토큰은 제거(텍스트만 남김)
  6) `generate_text_to_image()` 대신 `generate_image_edit(images=[몽타주들])`로 호출
- 안전장치:
  - 한 번에 캐릭터 최대 4명까지
- 메타 기록:
  - `request.character_mentions`를 채워 `media_store.py`가 meta에 `character_mentions` 기록

### 2.6 프론트 UI(등록/관리 + 안전장치 + 하이라이트)
수정 파일:
- `templates/partials/input_panel.html`
  - “캐릭터” 섹션 추가 (`#character-mentions-wrap`)
  - 경고 문구 영역 추가 (`#character-mentions-warning`)
  - 프롬프트 영역에 하이라이트 레이어 추가 (`#user-prompt-highlights`)
- `templates/index.html`
  - 캐릭터 관리 모달:
    - 이름 입력 + 입력 보관함에서 6장 선택(업로드 포함) + 저장/삭제
  - 빠른 삽입 칩:
    - 등록된 캐릭터를 칩으로 보여주고 클릭 시 프롬프트에 `@이름` 삽입
  - **클라이언트 비용 보호(중요)**:
    - 프롬프트에 미등록 `@이름`이 있으면 “이미지 생성하기” 버튼을 **즉시 비활성화**
    - `Ctrl+Enter` 등 우회도 `handleGenerateClick()` 초반에서 재차 차단
  - **프롬프트 하이라이트(등록된 @만 링크 스타일)**:
    - 등록된 `@이름`만 파란색 밑줄 스타일로 표시
    - 미등록 `@이름`은 평문처럼 표시(색칠 안 함)
    - 등록된 `@이름`을 클릭하면 캐릭터 관리 모달을 열도록 동작(textarea 클릭 위치 기반)
- `static/css/components.css`
  - `.prompt-highlights` 레이어 스타일 및 `prompt-highlight-enabled`(textarea 텍스트 투명화) 스타일 추가

주의(프론트):
- textarea 하이라이트 방식이라, padding/line-height/font-family를 textarea와 하이라이트 레이어에서 **일치**시키는 것이 중요

---

## 3) 빠른 테스트 시나리오(다음 세션 시작 체크리스트)

1) 서버 실행 후 브라우저에서 `/newfeature` 접속  
2) NanoBanana 기본 워크플로우 선택 + 생성(txt2img) 모드  
3) “캐릭터 등록/관리”에서 캐릭터 1개 등록(입력 보관함에서 6장 선택)  
4) 프롬프트에 `@이름` 포함 후 생성
   - 등록된 `@이름`: 파란 밑줄 + 클릭 시 관리창 열림
   - 미등록 `@이름`: 생성 버튼 비활성화 + 경고 문구

---

## 4) 다음 세션 큰 작업: 공용(전역) 캐릭터 레지스트리 추가

배경:
- “처음 쓰는 비디자이너”에게 레퍼런스 6장 확보가 진입장벽
- 회사 게임 캐릭터 3~4개를 **샘플로 공용 제공**하려는 요구

권장 방향:
- 개인 캐릭터(`character_registry`)와 별도로 **전역 공용 레지스트리**를 둠
- `@이름` 조회 우선순위:
  1) 개인(내) 캐릭터가 있으면 우선
  2) 없으면 공용 캐릭터에서 찾기
  3) 둘 다 없으면 에러(비용 보호)

추천 구현(다음 AI가 이해하기 쉬운 구조):
- DB 테이블 추가(런타임 best-effort migration 패턴 유지):
  - 예: `global_character_registry`
  - key: `name` 유니크
  - 값: 레퍼런스 6장(파일 경로 또는 asset id), status, timestamps
- 공용 레퍼런스 이미지 저장 위치:
  - 추천: 사용자 저장소(`outputs/users/{anon_id}/...`)와 별개로 분리
  - 예: `outputs/global/characters/<name>/ref_01.png ...`
- 프론트:
  - 캐릭터 영역에 “추천 캐릭터(공용)” 칩 섹션을 추가해 원클릭 삽입
  - 공용 캐릭터는 일반 사용자 UI에서 수정 불가(운영자만 추가/교체)
- 운영자 등록 방식:
  - 1) 공용 ref 이미지 6장을 지정 폴더에 저장
  - 2) DB에 등록하는 간단한 스크립트 or 관리자 API(선택)

### (구현됨) 공용 캐릭터 폴더 기반 로딩 방식
- 폴더 위치: `outputs/global/characters/<name>/`
- `<name>` 규칙: `^[A-Za-z0-9가-힣_-]{1,32}$` (공백 불가)
- 파일 규칙:
  - 지원 확장자: `.png`, `.jpg`, `.jpeg`, `.webp`
  - (선택) 대표 썸네일: 같은 폴더에 `thumb.png`(권장) 또는 `thumb.webp`/`thumb.jpg`
  - 최소 6장 필요(6장은 반드시 있어야 함)
  - 6장 초과는 무시되며, 사용되는 6장은 다음 우선순위로 선택됨:
    1) `ref_01`~`ref_06`처럼 `ref`+숫자가 들어간 파일명
    2) 그 외 파일명 알파벳/가나다순
- 조회 우선순위:
  - 개인 캐릭터가 있으면 개인 우선, 없으면 공용 폴더에서 조회
- 프론트:
  - `/newfeature`에서 “추천(공용)” 칩이 표시되며 클릭 시 `@name`이 삽입됨

---

## 5) Git/운영 주의사항
- `db/app_data.db`는 로컬 데이터가 섞이기 쉬우므로 **커밋 제외 권장**
- 이번 세션은 여러 파일을 크게 건드렸음(프론트 JS, 후처리, API 추가 등)

