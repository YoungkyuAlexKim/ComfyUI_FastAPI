#
세션 인계 문서 — NanoBanana 일반 노출 전환 + Admin 운영툴 확장(휴지통 완전삭제/사용통계) + Dual Img2Img 정리 + 다음 작업(Quota 에러 UX) (2026-02-06)

대상 저장소: `c:\Works\ComfyUI_FastAPI`  
환경: Windows / FastAPI + Jinja 템플릿 프론트 (대부분 로직이 `templates/index.html`에 있음)

이 문서는 “완전히 새 창에서 들어온 동료 AI”가 **프로젝트가 무엇인지 → 지금까지 반영된 변경 → 현재 동작 방식 → 다음 작업 요청서**를 바로 이해하고 곧바로 코드 작업을 이어갈 수 있도록 최대한 구체적으로 적었습니다.

---

## 0) 이 프로젝트는 무엇인가?

사용자가 웹 UI에서 워크플로우를 선택하고 프롬프트/입력 이미지를 넣어 **이미지 생성/편집**을 수행하는 서비스입니다.

생성 엔진은 2갈래입니다.

- **ComfyUI(로컬)**: 한 머신에서 동시 처리에 제약이 커서 큐(대기열) 관리가 중요
- **NanoBanana(Google API / Gemini 계열)**: 병렬 처리 가능하지만 **요금/쿼터 제한**이 존재 → 동시 실행 제한/대기열 관리 + “쿼터 에러 UX”가 중요

---

## 1) 코드 구조(핵심 파일 지도)

### 서버(Backend)
- **메인 앱/라우팅**: `app/main.py`
- **워크플로우 목록 API**: `app/routers/workflows.py` (`GET /api/v1/workflows`)
- **이미지 생성 처리(ComfyUI/Google 라우팅 포함)**: `app/services/generation.py`
- **Job/큐 관리(Comfy 1 lane vs Nano 4 lane 분리)**: `app/job_manager.py`
- **작업 히스토리 DB**: `app/job_store.py` (SQLite: `db/app_data.db`)
- **이미지 저장/메타/status(trash) 처리**: `app/services/media_store.py`
- **Admin 운영 API + Admin 페이지**: `app/routers/admin.py`, `templates/admin.html`

### 프론트(Frontend)
- **메인 UI(대부분 로직이 여기에 있음)**: `templates/index.html`
- **입력 패널(캐릭터 멘션 UI 등)**: `templates/partials/input_panel.html`
- **정적 JS 설정(배너 매핑 등)**: `static/js/app_config.js`
- **CSS**: `static/css/*.css` (특히 `components.css`)

### 워크플로우 JSON
- `workflows/*.json`

---

## 2) 이번까지 반영된 변경 사항(중요한 것만)

### 2.1 NanoBanana를 이제 `/create`에서 기본 노출로 전환
이전:
- 비용 때문에 Google(provider=google) 워크플로우는 기본 목록에서 숨김
- `/newfeature`에서만 `include_google=1`로 노출

현재:
- `/api/v1/workflows`가 이제 **기본값으로 Google 워크플로우도 포함**해서 반환
- `templates/index.html`도 `/newfeature` 분기 없이 **항상 `/api/v1/workflows`**만 호출
- `/newfeature` 라우트는 **완전 제거**됨 → 이제 `/newfeature`는 404

관련 변경 파일:
- `app/routers/workflows.py` (include_google default를 true로 변경)
- `templates/index.html` (`loadWorkflows()`에서 newfeature 분기 제거)
- `templates/partials/input_panel.html` (주석 문구 정리)
- `app/main.py` (`/newfeature` 라우트 삭제)

### 2.2 NanoBanana “캐릭터 멘션(@Name)” 기능의 newfeature 제한 해제
이전에는 `/newfeature`에서만 동작하도록 게이트가 있었는데, 이제 **워크플로우 조건(provider=google, NanoBanana base workflow 등)**만 충족하면 `/create`에서도 동작하도록 변경됨.

관련 변경 파일:
- `templates/index.html` (`isNewFeaturePage()` 게이트 제거)

### 2.3 Dual Img2Img(LOS/OHD/Flux2) 구조 정리
“입력 이미지 1장 vs 2장”에 따라 내부 워크플로우(JSON)를 바꾸는 구조를 LOS/OHD에도 적용.

특히 Dual 입력 워크플로우에서 **출력 사이즈/스케줄러 기준을 1번 이미지로 통일**하는 배선 수정이 반영되어 있음.

작업된 주요 파일:
- `workflows/Flux2Klein_i2i_dualInput.json` (1번 이미지 기준 통일 + steps/cfg)
- `workflows/LOSStyle_Klein_Img2Img_dualInput.json` (Flux2 dual 구조 기반 + LOS LoRA)
- `workflows/OHDStyle_Klein_Img2Img_dualInput.json` (Flux2 dual 구조 기반 + OHD LoRA)
- `app/workflow_configs.py`
  - LOS img2img: 1장/2장 자동 라우팅(`comfy_variants_by_input_count`)
  - OHD img2img: 1장/2장 자동 라우팅(`comfy_variants_by_input_count`)
  - UI에서 img2img 입력을 2장까지 선택 가능(`ui.imageInputMulti = {enabled:true, max:2}`)

공통 파라미터:
- **steps = 6**
- **cfg = 1.2**

### 2.4 갤러리 삭제 UX 문구 변경
사용자가 “복구 가능”으로 오해하지 않도록 삭제 확인 문구를 “삭제할까요?”로 변경.

관련 변경 파일:
- `templates/index.html` (선택삭제 confirm 문구)

### 2.5 Admin 운영툴 확장

#### (A) 전체 사용자 휴지통 완전삭제
기존:
- 특정 사용자만 `휴지통 비우기` 가능 (완전삭제)

추가:
- **모든 사용자 휴지통을 한 번에 완전삭제**하는 운영 버튼 + API

관련:
- API: `POST /api/v1/admin/purge-trash-all` (`app/routers/admin.py`)
- UI: `templates/admin.html` 버튼 추가

#### (B) 사용 통계(운영자 대시보드)
운영자가 보고 싶은 지표:
- 하루하루 총 이미지 생성 호출 수
- 인기 워크플로우(사용량 순위)
- 날짜 클릭 시 해당 날짜 워크플로우 랭킹 상세

구현:
- API: `GET /api/v1/admin/usage?days=30`
  - 일별 totals + 일별 워크플로우 랭킹 + 기간 합산 top workflows
- UI: Admin 탭에 `사용 통계` 탭 추가(마스터-디테일 UX)

중요: 기존 DB에는 workflow_id가 없던 레코드가 있으므로 과거 데이터는 `(unknown)`이 나올 수 있음.  
지금부터 생성되는 job은 workflow_id/payload를 DB에 저장하므로 앞으로는 대부분 정상 표기됨.

관련 변경 파일:
- `app/routers/admin.py` (usage endpoint 추가)
- `templates/admin.html` (사용 통계 탭/드릴다운 UI 추가)
- `app/job_store.py` (jobs 테이블에 `workflow_id`, `payload_json` 저장 추가)
- `app/main.py` (job_store.upsert_job에 payload/workflow_id 함께 저장하도록 보강)

DB 마이그레이션 주의:
- 기존 DB에 컬럼이 없을 수 있으므로 `ALTER TABLE` 후 인덱스 생성 순서가 중요함.

### 2.6 업로드 용량 제한 완화(3MB → 3.5MB)
NanoBanana 2K 결과를 inputs로 다시 올릴 때 3.3MB 정도가 종종 발생하여 제한을 상향.

- `CONTROLS_MAX_BYTES=3670016`
- `INPUTS_MAX_BYTES=3670016`

관련:
- `.env` (서버 재시작 필요)
- 입력 제한 적용은 `app/config.py` → `UPLOAD_CONFIG["inputs_max_bytes"]` → `app/routers/inputs.py`에서 사용

---

## 3) 현재 동작 방식(요약)

### 3.1 워크플로우 목록 노출
- 프론트는 `/api/v1/workflows`를 호출해 워크플로우 리스트를 구성함.
- 이제 Google(provider=google)도 기본 노출됨.

### 3.2 NanoBanana vs ComfyUI 큐 분리
- provider=google (NanoBanana) → 동시 4 worker (env로 조정)
- comfyui → 동시 1 worker

관련 env:
```env
NANOBANANA_MAX_CONCURRENT=4
NANOBANANA_MAX_PER_USER_QUEUE=5
```

### 3.3 휴지통(trash) 개념
- 삭제는 기본적으로 meta.json의 `status`를 `"trash"`로 바꾸는 **소프트 삭제**
- Admin에서 “휴지통 비우기/전체 휴지통 비우기”는 파일(png/thumb/json)을 실제로 삭제하는 **하드 삭제**

---

## 4) 빠른 테스트 체크리스트(다음 세션 시작 시)

1) 서버 실행 후 `/create` 접속
2) 워크플로우 목록에 NanoBanana 계열이 보이는지 확인
3) NanoBanana 작업을 여러 개 요청하여
   - 동시 4개 제한이 동작하는지
   - 대기 메시지가 적절한지
4) LOS/OHD Img2Img에서
   - 입력 이미지 2장 선택 UI가 뜨는지
   - 1장/2장에 따라 내부 워크플로우가 잘 라우팅되는지
5) `/admin` → `사용 통계` 탭에서
   - 최근 7/30일 지표가 표시되는지
   - 날짜 클릭 시 상세 랭킹이 뜨는지

---

## 5) 다음 작업 요청서(중요) — “NanoBanana 쿼터/한도 에러 UX”

배경:
- NanoBanana(Google API)는 “하루 250장” 같은 상한에 빨리 닿을 수 있음.
- 상한 도달 시 Google이 에러를 반환할 텐데, 사용자는 “왜 막혔는지”를 모르면 혼란스러움.

요구사항(목표):
- Google 에러 상황에 따라 사용자가 이해할 수 있도록 **친절한 메시지**를 보여주기.
- 운영자도 로그/통계에서 “쿼터 때문에 막혔는지”를 파악할 수 있도록 하기.

권장 구현 방향:
1) `app/services/google_nano_banana.py` 또는 `app/services/generation.py`에서
   - Google API 실패 응답(HTTP status + body)을 분류
   - 대표 케이스:
     - 429 Too Many Requests(분당 제한)
     - 403/429 RESOURCE_EXHAUSTED(일일 쿼터/결제/프로젝트 제한)
     - 401/403 Unauthorized(키 문제)
     - 5xx/timeout(일시 장애)
2) 분류 결과를 **사용자 메시지로 매핑**
   - 예: “오늘 생성 한도에 도달했어요. 내일 다시 시도해 주세요.”
   - 예: “요청이 몰려 잠시 대기 중이에요. 잠시 후 다시 시도해 주세요.”
3) 프론트(`templates/index.html`)는 이미 에러 메시지(`result.detail`)를 보여주는 흐름이 있으므로
   - 서버에서 던지는 `detail`을 사용자 친화 문구로 다듬는 것이 1차 목표
4) (선택) Admin/Usage에 “NanoBanana quota error count” 같은 운영 지표 추가

추가 메모:
- 실제 Google 에러 응답 샘플(JSON)이 있으면 메시지 분류 정확도가 크게 올라감.

---

## 6) 운영 주의사항/메모

- `.env`에는 API 키/관리자 비밀번호 등 민감정보가 있으니 **커밋 금지** 권장.
- static 파일 캐시로 인해 프론트 변경이 바로 안 보일 수 있음(필요하면 cache-busting 도입).
- PowerShell에서는 `&&` 체인 명령이 기본으로 안 먹을 수 있으니 명령은 분리 실행 권장.

