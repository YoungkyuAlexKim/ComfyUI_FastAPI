# ComfyUI_FastAPI 코드베이스 인수인계서(지속 업데이트용)

> 작성일: 2026-02-08  
> 목적: **다음 세션(또는 동료 AI)이 즉시 개발/운영을 이어갈 수 있도록**, 현재 코드베이스 구조와 설계 의도를 최대한 구체적으로 기록합니다.  
> 업데이트 원칙: 이 문서는 “한 번 쓰고 끝”이 아니라, 앞으로 계속 보강/수정하면서 프로젝트의 단일 진실원(Single Source of Truth)로 사용합니다.

---

### 1) 이 프로젝트는 무엇인가(한 줄 정의)
**로컬 ComfyUI(Stable Diffusion 계열)와 외부 Google Gemini 이미지 모델(NanoBanana)을 하나의 웹 UX로 묶어 제공하는 FastAPI 기반 이미지 생성/편집 서버**입니다.

- **같은 UX**: 잡 큐(대기열), 진행률, 취소, 결과 저장, 갤러리, 쇼케이스(피드), 관리자 페이지
- **다른 실행 엔진**:
  - **ComfyUI**: 로컬 서버(대체로 “단일 레인”에 가깝고 자원 제약이 큼)
  - **Google(NanoBanana)**: 외부 API(동시 실행 가능하나 비용/쿼터 이슈 존재)

---

### 2) 철학/설계 방향(왜 이렇게 만들었나)
- **(A) “툴(도구)” 지향 UX**
  - 단순 txt2img뿐 아니라 “턴어라운드/표정 시트/리라이트/스토리보드/다음 장면” 같은 **구체적 목적의 도구 워크플로우**를 제공
  - 사용자는 복잡한 프롬프트를 직접 설계하기보다, **옵션 선택 중심**으로 안정적인 결과를 얻도록 유도

- **(B) 복잡도는 서버/설정에 숨기고 UI는 통일**
  - 워크플로우별 “노드 매핑/파라미터/LoRA/입력 이미지 필요 여부/툴 옵션/UI 힌트”를 `app/workflow_configs.py`에 집중
  - 프론트는 `/api/v1/workflows`로 받은 UI 스키마를 기반으로 “보이는 UI만” 렌더링

- **(C) 인프라를 가볍게(이식성/로컬 친화)**
  - Redis/Celery 없이도 운영 가능하게:
    - 이미지/메타: 파일시스템 + JSON sidecar
    - 운영 데이터: SQLite(`db/app_data.db`)
    - 비동기 처리: 내부 쓰레드 기반 잡 워커(`JobManager`)

- **(D) 실사용의 불편/함정 방지**
  - 모바일/인앱 브라우저의 쿠키 차단 대비: **`X-Anon-Id` 헤더 부착**
  - ComfyUI WS “완료 이벤트 놓침” 문제 대비: history 폴링 보완
  - Windows 파일 잠금/삭제 실패 대비: cleanup 재시도

---

### 3) 빠른 시작(로컬)
- 실행
  - `python run.py`
  - 접속: `http://127.0.0.1:8000`
  - API 문서: `http://127.0.0.1:8000/docs`

- 의존성
  - `requirements.txt`: `fastapi`, `uvicorn[standard]`, `jinja2`, `python-multipart`, `Pillow`, `requests`, `python-dotenv`, `websocket-client`

---

### 4) 디렉터리/파일 구조(상위 수준)
- `run.py`
  - uvicorn 실행 스크립트(개발용 reload 포함)

- `app/main.py`
  - FastAPI 앱 본체
  - 미들웨어(베타 게이트, 로깅)
  - 라우터 등록(`app/routers/*`)
  - 잡 매니저/스토어 초기화 및 startup 이벤트에서 워커 시작
  - 핵심 API: `POST /api/v1/generate`, `GET /api/v1/jobs/{id}` 등(일부는 라우터로 분리)

- `app/workflow_configs.py`
  - **사실상 제품 기획서**
  - 워크플로우별 설정:
    - provider(`comfyui`/`google`)
    - ComfyUI 노드 매핑(prompt/seed/size/LoRA/입력 이미지 노드 등)
    - Google(NanoBanana) 모델/모드(txt2img vs image-edit)
    - UI 스키마(프롬프트 숨김, 도구 옵션, 멀티 입력 제한, 배너/탭 구조 등)

- `app/services/`
  - `generation.py`: 생성/편집의 **핵심 처리기**
    - provider 라우팅(google/comfyui)
    - Img2Img 입력 이미지 resolve/업로드/다운스케일/cleanup
    - RMBG2 파라미터 오버라이드, LoRA 슬라이더 값 적용
  - `google_nano_banana.py`: Google 호출 + 에러 분류/메시지 정책
  - `media_store.py`: 이미지 저장/썸네일/메타(sidecar) + 입력 보관함(inputs) 관리
  - `feed_media_store.py`: 쇼케이스 게시물 자산을 `outputs/feed`로 복사 및 휴지통/복구/퍼지
  - `character_refs.py`: 캐릭터 레퍼런스 6장을 “레퍼런스 시트(몽타주)”로 구성
  - `global_character_store.py`: `outputs/global/characters` 기반 공용 캐릭터 로드

- `app/job_manager.py`
  - `JobManager`: per-user 대기열, 라운드로빈, 동시성 제한, 취소/타임아웃, 진행률 notify
  - `RoutingJobManager`: **ComfyUI 레인**과 **Google 레인**을 분리 운영

- `app/comfy_client.py`
  - ComfyUI HTTP(`/prompt`, `/upload/image`, `/history/{id}`, `/view`) + WS 진행률 수신
  - WS만 믿지 않고 history 폴링으로 “완료 이벤트 누락”을 보완

- `templates/` + `static/`
  - 서버 렌더링(Jinja2) + 프론트 JS
  - `templates/index.html`에 생성 흐름의 핵심 JS가 인라인으로 포함(WS 연결/생성 요청/대기열 폴링/UI 상태 관리)
  - `static/js/app_config.js`: 로딩 연출/배너/갤러리/라이트박스 등 UX 기본값
  - `templates/feed.html` + `static/js/feed.js`: 쇼케이스(피드) UX

- `workflows/`
  - ComfyUI 워크플로우 JSON(노드 id는 `workflow_configs.py`에서 매핑)

- `outputs/`
  - 생성 결과/썸네일/메타 및 피드 자산 저장

- `db/app_data.db`
  - SQLite: jobs/feed/characters 등 운영 데이터

---

### 5) 핵심 런타임 흐름(사용자 관점)
#### 5.1 익명 사용자 식별(세션/쿠키)
- 쿠키: `anon_id` (prefix: `anon-`)
- 쿠키가 막히는 환경 대비:
  - 프론트(`templates/index.html`)가 `fetch`를 래핑하여 API 요청에 `X-Anon-Id`를 자동 부착
  - 백엔드(`app/auth/user_management.py`)는 쿠키가 없으면 `X-Anon-Id`를 fallback으로 사용

#### 5.2 생성 요청 → 잡 큐 → 진행률/완료
- 프론트:
  - WS 연결: `/ws/status?anon_id=...`
  - 생성 요청: `POST /api/v1/generate` → `{ job_id, status: queued, position }`
  - 대기/ETA 보조:
    - `GET /api/v1/jobs/{job_id}`로 상태/position 조회
    - `GET /api/v1/jobs/metrics`로 평균 처리시간 기반 ETA 계산(“대기 N번째면 대략 N-1 * avg”)

- 백엔드:
  - `JobManager.enqueue(owner_id, "generate", payload)`
  - 워커가 `services/generation.py:run_generation_processor()` 실행
  - provider 결정:
    - `WORKFLOW_CONFIGS[workflow_id]["provider"] == "google"` → NanoBanana 경로
    - else → ComfyUI 경로
  - 결과 저장:
    - `outputs/users/<anon_id>/YYYY/MM/DD/<image_id>.png`
    - `outputs/users/<anon_id>/YYYY/MM/DD/<image_id>.json` (prompt/seed/workflow/input ids 등)
    - `thumb/<image_id>.webp|jpg`

---

### 6) provider 별 상세(ComfyUI vs Google)
#### 6.1 ComfyUI 경로(로컬)
- 워크플로우 JSON: `workflows/<workflow_id>.json`
- 오버라이드 생성: `app/config.py:get_prompt_overrides()`
  - prompt/negative/seed/size_nodes/latent_image 등 “존재할 때만” 덮어쓰기
- Img2Img 입력:
  - inputs 보관함(`outputs/users/<anon_id>/inputs/...`) 또는 생성 이미지에서 id로 resolve
  - ComfyUI input 폴더로 업로드(`/upload/image`)
  - 큰 입력은 업로드 전에 `max_side=1536`으로 다운스케일(원본은 보관함에 그대로 유지)
  - 잡 완료 후 `COMFY_INPUT_DIR`에서 best-effort cleanup(Windows 잠금 대비 재시도 + job_id 스윕)

#### 6.2 Google NanoBanana 경로(외부)
- API 키: `GOOGLE_AI_STUDIO_API_KEY` 또는 `GEMINI_API_KEY`
- 모델/모드: `workflow_configs.py`의 `google: {model, mode}`로 결정
- 에러 분류 정책:
  - 키/권한/결제 문제(운영자 액션)
  - quota/rate limit(사용자 재시도)
  - bad request(프롬프트/설정 문제)
  - upstream 불안정(일시 장애)
- 캐릭터 멘션 기능(예: `@제임스`)
  - 개인 캐릭터(`character_registry`) 또는 공용 캐릭터(`outputs/global/characters`)
  - 레퍼런스 6장 → 시트로 합성 → image-edit 호출에 이미지로 첨부

---

### 7) 워크플로우 시스템(추가/변경 방법)
#### 7.1 ComfyUI 워크플로우 추가
1) `workflows/<ID>.json` 추가  
2) `app/workflow_configs.py`에 `<ID>` 엔트리 추가  
   - 최소: `display_name`, `description`, `prompt_node`(및 input key), `seed_node`, `sizes` 또는 `size_nodes`, 필요 시 `loras`, `image_input`  
3) 프론트 배너/UX 힌트(선택): `static/js/app_config.js`의 `APP_CONFIG.banners.map`에 배너 매핑

#### 7.2 Google(NanoBanana) 워크플로우 추가
1) `app/workflow_configs.py`에 엔트리 추가
   - `provider: "google"`
   - `google: { model: "...", mode: "text-to-image" | "image-edit" }`
   - 입력 이미지 필요하면 `image_input`을 “UI gate”로만 둠(서버에서만 사용)
2) “툴 워크플로우”라면 `ui.hideUserPrompt`, `ui.<toolName>`, `ui.aspectOptions` 등으로 프론트에서 옵션 UI를 노출

#### 7.3 wrapper → variant 라우팅(입력 개수에 따라 내부 워크플로우 선택)
- 예: `Flux2Klein_ImageEdit`, `LOSStyle_Klein_Img2Img` 등  
- `comfy_variants_by_input_count: { 1: "...single...", 2: "...dual..." }`  
- 서버 `services/generation.py`가 입력 이미지 개수에 따라 `effective_workflow_id`를 선택

---

### 8) 저장 구조(파일시스템)
#### 8.1 생성 결과(갤러리)
- 경로: `outputs/users/<anon_id>/YYYY/MM/DD/`
  - `<image_id>.png`
  - `<image_id>.json` (메타)
  - `thumb/<image_id>.webp|jpg`

#### 8.2 입력 이미지 보관함(inputs)
- 경로: `outputs/users/<anon_id>/inputs/YYYY/MM/DD/`
  - `<input_id>.png`
  - `<input_id>.json`
  - `thumb/<input_id>.webp|jpg`

#### 8.3 쇼케이스(피드)
- 경로: `outputs/feed/YYYY/MM/DD/`
  - `<post_id>.png`, `thumb/<post_id>.*`, `<post_id>.json`
  - 입력이미지 동봉 시: `<post_id>_input.png` 등
- 휴지통: `outputs/feed/trash/YYYY/MM/DD/...`
  - 일반 사용자는 피드 자산의 휴지통 경로 접근이 막힘(`app/main.py`의 미들웨어로 404 처리)

#### 8.4 공용 캐릭터
- 경로: `outputs/global/characters/<name>/`
  - `ref_01.png` ~ `ref_06.png` 권장
  - `thumb.png` 권장(없으면 썸네일 URL 비어있을 수 있음)

---

### 9) DB( SQLite: db/app_data.db ) 개요
- `jobs` (`app/job_store.py`)
  - 잡 히스토리/상태/결과(result_json)/artifact_available/workflow_id/payload_json
  - 운영자 페이지의 사용 통계도 여기 기반(`/api/v1/admin/usage`)

- `feed_posts`, `feed_likes`, `feed_reactions` (`app/feed_store.py`)
  - 쇼케이스 게시물 + 좋아요/리액션(리액션은 1인 1개, legacy like는 love로 취급)

- `character_registry` (`app/character_store.py`)
  - 개인 캐릭터: (owner_id, name) 유니크
  - reference_image_ids는 JSON 문자열로 저장(정확히 6장 요구)
  - legacy(5장) 데이터는 best-effort로 6장으로 자동 보정 로직 존재

---

### 10) 주요 엔드포인트 요약
#### 유저(일반)
- 페이지
  - `GET /create` 생성 페이지
  - `GET /feed` 쇼케이스 페이지
- 생성/잡
  - `POST /api/v1/generate`
  - `GET /api/v1/jobs/{job_id}`
  - `POST /api/v1/jobs/{job_id}/cancel`
  - `GET /api/v1/jobs/metrics`
- 갤러리/입력 보관함
  - `GET /api/v1/images`
  - `POST /api/v1/images/{image_id}/delete`
  - `GET /api/v1/inputs`
  - `POST /api/v1/inputs/upload`
  - `POST /api/v1/inputs/copy` (generated → inputs)
  - `POST /api/v1/inputs/{image_id}/delete`
  - `POST /api/v1/inputs/{image_id}/restore`
- 쇼케이스
  - `POST /api/v1/feed/publish`
  - `GET /api/v1/feed`
  - `GET /api/v1/feed/{post_id}`
  - `POST /api/v1/feed/{post_id}/reaction`
  - `POST /api/v1/feed/{post_id}/delete`
- 기타
  - `GET /api/v1/workflows`
  - `POST /api/v1/translate-prompt`
- WebSocket
  - `WS /ws/status`

#### 관리자(옵션 BasicAuth)
- `GET /admin` (템플릿 기반 운영 UI)
- 사용자/이미지/입력 관리
  - `GET /api/v1/admin/users`
  - `GET /api/v1/admin/images`
  - `POST /api/v1/admin/images/{id}/delete|restore`
  - `POST /api/v1/admin/purge-trash`(유저 단위) / `POST /api/v1/admin/purge-trash-all`(전체)
  - `GET /api/v1/admin/inputs`
- 잡/통계
  - `GET /api/v1/admin/jobs`
  - `GET /api/v1/admin/jobs/metrics`
  - `POST /api/v1/admin/jobs/sweep`
  - `GET /api/v1/admin/usage`
- 쇼케이스 관리
  - `GET /api/v1/admin/feed`
  - `POST /api/v1/admin/feed/{post_id}/delete|restore|purge`

---

### 11) 보안/접근 제어(운영 시 중요)
- 베타 게이트(공유 비밀번호)
  - `BETA_PASSWORD`가 설정되면:
    - 페이지 요청은 `/beta-login`으로 리다이렉트
    - API는 401 JSON 반환(프론트 JSON 파싱 깨짐 방지)
    - WS도 인증 쿠키 없으면 close(4401)

- 관리자 BasicAuth
  - `ADMIN_USER`, `ADMIN_PASSWORD`가 둘 다 있으면 보호됨
  - 없으면 “개발 편의”로 admin이 열릴 수 있으니 운영 배포 시 주의

- 쿠키 Secure 설정
  - `COOKIE_SECURE=true`인데 HTTP로 서비스하면 “로그인 루프”가 생길 수 있어 방지 로직이 있으나,
  - 운영에서는 HTTPS + Secure 쿠키 권장

---

### 12) 자주 터질 수 있는 함정/체크 포인트
- **ComfyUI input 파일 누락**
  - 일부 워크플로우는 `required_comfy_inputs`(숨김 레퍼런스)를 요구
  - `COMFY_INPUT_DIR` 설정이 비어있으면 preflight 체크가 불완전해질 수 있음

- **Google 쿼터/키 문제**
  - 사용자 메시지는 친절하게 나오지만, 근본 원인은 env/결제/쿼터일 확률이 높음
  - 운영자 페이지의 `/api/v1/admin/usage`는 일부 NanoBanana 에러(kind)를 집계함(환경에 따라 SQLite JSON1 미지원이면 제한)

- **WS 완료 이벤트 누락/무한 대기**
  - ComfyUI 쪽은 `comfy_client.py`에서 history 폴링으로 보완
  - 프론트도 WS+HTTP 폴링을 함께 사용(대기열/상태)

- **Windows 파일 잠금**
  - Comfy input cleanup이 바로 안 될 수 있어 재시도/스윕 로직 존재

---

### 13) 다음 세션 작업을 위한 체크리스트(권장)
아래 항목은 “다음 세션 동료 AI”가 바로 작업을 이어갈 수 있게 하기 위한 공통 체크리스트입니다.

- 워크플로우 추가/수정이라면
  - `app/workflow_configs.py`의 엔트리와 실제 `workflows/*.json`의 노드 id가 일치하는지 확인
  - UI 스키마(툴 옵션/프롬프트 숨김/멀티입력 제한)가 의도대로 동작하는지 확인
  - 배너(`static/js/app_config.js`) 매핑 필요 여부 확인

- Img2Img 관련이라면
  - 입력 이미지가 `inputs` 보관함/갤러리 중 어디서 resolve 되는지 확인
  - 다운스케일 정책(`max_side=1536`)이 품질/속도에 미치는 영향 점검
  - Comfy input cleanup이 실패하는 케이스(파일명 suffix, 경로 포함) 로그 확인

- Google(NanoBanana) 관련이라면
  - 에러 분류(kind)와 사용자 메시지가 요구사항에 맞는지 검토
  - 멘션(@Name) 시 레퍼런스 시트 순서/제한(최대 4명)이 UX 요구와 맞는지 확인

- 운영/안전 관련이라면
  - `BETA_PASSWORD`, `ADMIN_*`, `COOKIE_SECURE` 배포 환경에서의 실제 동작 점검
  - `/api/v1/admin/usage`가 DB JSON1 미지원 환경에서도 문제 없이 fallback 되는지 확인

---

### 14) 문서 업데이트 규칙(권장)
- 변경이 생기면 “코드만” 바꾸지 말고, 아래 중 해당되는 곳을 꼭 갱신합니다.
  - 워크플로우 추가/변경: **섹션 7**(추가 방법) + **섹션 10**(엔드포인트) + 필요한 경우 **섹션 6**
  - 저장 구조/경로 정책 변경: **섹션 8**
  - 운영/보안 정책 변경: **섹션 11**
  - 새로 발견한 함정/장애 사례: **섹션 12**
- 문서 맨 위 작성일 옆에 “최종 업데이트”도 추가하는 것을 권장합니다(추후 필요 시).

