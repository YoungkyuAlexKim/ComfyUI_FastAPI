# 세션 인계 문서 — Flux2 Klein “간단 이미지 편집” + NanoBanana/ComfyUI Job 분리(동시 4) + 캐릭터 아이콘 바(클리핑/스크롤) (2026-02-05)

대상 저장소: `c:\Works\ComfyUI_FastAPI`  
환경: Windows / FastAPI + Jinja 템플릿 프론트 (`templates/index.html` 내 JS 큼)  

이 문서는 다음 세션(동료 AI)이 **프로젝트 개요 → 현재까지 반영된 변경 → 남은 문제/할 일**을 바로 이해하고, 곧바로 코드 작업을 이어갈 수 있도록 최대한 구체적으로 정리한 인계서입니다.

---

## 0) 이 프로젝트는 무엇인가?

- **웹 UI**에서 워크플로우를 선택하고 프롬프트/입력 이미지를 넣어 이미지를 생성/편집합니다.
- 생성 엔진은 2갈래입니다.
  - **ComfyUI(로컬)**: 한 머신에서 보통 한 번에 1개 작업만 안정적으로 처리 → 큐 관리가 중요
  - **NanoBanana(Google API)**: 병렬 처리 가능 → 동시 실행 제한(풀)과 별도 대기열이 중요

핵심 파일 지도:
- **워크플로우 설정(중심)**: `app/workflow_configs.py` (`WORKFLOW_CONFIGS`)
- **생성 처리(라우팅/업로드/다운스케일/Google 호출)**: `app/services/generation.py`
- **워크플로우 목록 API**: `app/routers/workflows.py` (`GET /api/v1/workflows`)
- **Job(큐) 관리**: `app/job_manager.py`, `app/main.py`의 `/api/v1/generate`
- **프론트(핵심)**: `templates/index.html` (UI 로직 대부분)
- **배너 매핑**: `static/js/app_config.js` (`window.APP_CONFIG.banners.map`)
- **운영용 글로벌 캐릭터 파일**: `outputs/global/characters/**` (git 추적 허용)

---

## 1) 최근 커밋(큰 흐름)

최근 커밋 로그 예시(로컬 기준):
- `146701a` 나노바나나와 일반 워크플로우들(comfyui 사용하는) 의 job 분리함
- `21b2606` flux 2 klein 워크플로우 추가
- `520f85c` 운영용 카메오 캐릭터 업로드
- `3312609` 글로벌 캐릭터 추가_꺼멍_미오_비비안

> 다음 세션에서는 `git log -5 --oneline`로 실제 상태를 먼저 확인하세요.

---

## 2) 이번까지 반영된 핵심 기능/변경 사항(요약)

### 2.1 Flux2 Klein “간단 이미지 편집” 워크플로우 추가(ComfyUI img2img)

목표:
- 기존 CJK/LOS/OHD에서 쓰던 **Flux2 Klein** 모델을 **LoRA 없이도** “도구형 이미지 편집”으로 제공
- 입력 이미지 **1장/2장**에 따라 내부적으로 **서로 다른 ComfyUI 워크플로우(JSON)**를 로드

구성:
- 워크플로우 JSON
  - `workflows/Flux2Klein_i2i_singleInput.json` (LoadImage 1개)
  - `workflows/Flux2Klein_i2i_dualInput.json` (LoadImage 2개)
- 워크플로우 설정(노출되는 것은 wrapper 1개)
  - `app/workflow_configs.py`
    - `Flux2Klein_ImageEdit` (UI에 보이는 항목, 표시명: **“간단 이미지 편집”**)
    - 내부 실행용(hidden):
      - `Flux2Klein_i2i_singleInput`
      - `Flux2Klein_i2i_dualInput`

서버 동작 핵심:
- `app/services/generation.py`
  - `comfy_variants_by_input_count` 설정 키를 읽어서,
  - 사용자가 선택한 입력 이미지 개수(1 vs 2)에 따라 `effective_workflow_id`로 실제 JSON을 선택해 실행합니다.
  - `image_inputs`(복수 입력) 매핑을 지원하도록 확장되어, dualInput에서 **1번/2번 입력을 각각 올바른 LoadImage 노드에 주입**합니다.

UI 동작 핵심:
- `templates/index.html`
  - `ui.imageInputMulti`가 켜져 있으면 입력 이미지를 **여러 장(썸네일 그리드)**로 선택 가능
  - `max=2`일 때는 UI를 **컴팩트하게** 줄이고,
  - 안내문구로 “1번/2번의 의미”를 보여줍니다(예: reference_image1/2).

### 2.2 Flux2 Klein 배너 추가

- 배너 이미지 파일: `static/img/banner/img_banner_Flux2Klein_ImageEdit.png`
- 배너 매핑: `static/js/app_config.js`
  - `Flux2Klein_ImageEdit` → `/static/img/banner/img_banner_Flux2Klein_ImageEdit.png`
  - 배너 이미지에 텍스트가 포함되어 있어 `showTitle:false`, `showDescription:false`로 설정

### 2.3 ComfyUI img2img 입력 다운스케일(1536) 정책

- `app/services/generation.py`에서 ComfyUI img2img 입력 업로드 전에
  - **긴 변 1536px 상한**, **비율 유지**, **원본 보존(업로드 bytes만 축소)** 적용
- 메타에 downscale 기록:
  - `app/services/media_store.py`의 `_save_image_and_meta()`
  - `comfy_img2img_input_downscale` 필드

### 2.4 outputs/global/characters 커밋 허용(.gitignore)

문제:
- `outputs/`를 폴더째 ignore하면, 예외 규칙이 있어도 하위 파일이 추적되지 않는 케이스가 발생

해결:
- `.gitignore`에서 `outputs/` 대신 `outputs/*`로 무시 대상을 조정하고,
  - `outputs/global/characters/**`는 예외로 추적 가능하게 구성

### 2.5 NanoBanana와 ComfyUI Job 관리 분리(중요)

문제:
- ComfyUI는 사실상 “1차선”(동시 1)이라 엄격한 큐가 필요
- NanoBanana는 API 기반 병렬 가능인데, 같은 큐로 섞으면
  - 순서 꼬임/체감 속도 악화/대기 표시 혼란이 증가

해결(구현):
- `app/job_manager.py`
  - `JobManager`를 **멀티 워커(worker_count)** 지원하도록 확장
  - 취소 핸들을 job 단위로 관리하도록 개선(`set_cancel_handle(job_id, handle)`)
  - `RoutingJobManager` 추가: workflow의 `provider` 기준으로 Comfy/Nano로 분기
- `app/main.py`
  - Comfy용: `_comfy_job_manager = JobManager(worker_count=1)`
  - Nano용: `_nano_job_manager = JobManager(worker_count=4)` (startup에서 env로 재설정)
  - `job_manager = RoutingJobManager(...)`로 라우팅
  - processor에서 cancel handle 등록을 `set_cancel_handle(job.id, handle)`로 변경

환경변수(운영자가 .env에 추가):
```env
# 기존: 전체 공통 분당 생성 제한(유지)
GEN_RATE_LIMIT_PER_MIN=2

# NanoBanana(Google) 동시 실행 제한 (서버 전체)
NANOBANANA_MAX_CONCURRENT=4

# NanoBanana 사용자당 대기열 최대 길이
NANOBANANA_MAX_PER_USER_QUEUE=5
```

UI 폴리싱:
- `templates/index.html`에서 대기 메시지를 NanoBanana일 때
  - `나노바나나 대기중... (n번째)` 형태로 표시(ComfyUI 대기열과 구분)

---

## 3) 캐릭터 아이콘 바(클리핑/스크롤) — 해결됨(단, 캐시 주의)

현상(사용자 보고):
- 글로벌/개인 캐릭터가 많아질수록 캐릭터 아이콘 행이
  - 원래 프레임 밖으로 튀어나오거나,
  - 영역 자체가 넓어지며 아래 UI(프롬프트/비율 버튼)를 “침범”
- 원래 목표:
  - **가로 스크롤(드래그 스크롤)** 가능
  - 프레임 밖은 **클리핑**
  - **“추가” 버튼은 스크롤에서 제외**되어 고정

시도한 해결(이미 코드 반영됨):
- `templates/index.html`의 `renderCharacterQuickList()`에서 DOM 구조 변경:
  - `.global-character-row__wrap`, `.global-character-row__dock`(고정 추가 버튼), `.global-character-row__items`(스크롤 리스트)
- `static/css/components.css`에서:
  - `.global-character-row__wrap { overflow:hidden; min-width:0; }`
  - `.global-character-row__items { overflow-x:auto; flex:1; min-width:0; }`
  - `#character-mentions-wrap`, `#character-quick-list`, `.input-card`에 `overflow-x:hidden` 등 강한 클리핑 추가

처음엔 사용자 화면에서 “아까랑 완전히 똑같다”고 보였으나, **새로고침 후 최신 정적 파일이 반영되면서 정상 동작 확인**:
- 캐릭터가 많아져도 **프레임을 넓히지 않음**
- 프레임 밖 컨텐츠는 **클리핑**
- 아이콘 리스트는 **가로 스크롤/드래그 스크롤 가능**
- “추가” 버튼은 스크롤과 분리되어 **고정**

재발 방지 메모:
- 서비스 서버/브라우저에서 정적 파일 캐시로 인해 변경이 즉시 안 보일 수 있음
- 운영 환경에서 이런 이슈가 반복되면, `templates/base.html`에서 CSS/JS include에 `?v=<버전>`(예: 커밋 해시/APP_VERSION)을 붙이는 **cache-busting** 적용을 권장

다음 세션에서 할 일(선택):
- “정적 파일이 안 바뀌었다”고 오해하는 상황을 줄이기 위해 **cache-busting**을 적용할지 검토

---

## 4) 남은 작업(요청서 형태)

### (A) Flux2Klein dualInput 워크플로우 파라미터 정리/커밋
- `workflows/Flux2Klein_i2i_dualInput.json`
  - `Flux2Scheduler.steps`를 6으로
  - `CFGGuider.cfg`를 1.2로
- 로컬에서 `db/app_data.db`는 변경되기 쉬우니 **커밋 제외 권장**

---

## 5) 빠른 테스트 시나리오(다음 세션 시작 체크)

1) 서버 실행 후 `/create` 접속
2) NanoBanana 기본 워크플로우에서 캐릭터 아이콘이 많을 때
   - 프레임 밖으로 밀어내는지(문제 재현)
   - 드래그로 가로 스크롤 되는지
   - “추가” 버튼이 고정인지
3) NanoBanana를 연속 요청해
   - 동시 4개 제한이 동작하는지(대기 표시 포함)
4) Flux2 Klein “간단 이미지 편집”
   - 이미지 1장 입력 → singleInput JSON으로 실행되는지
   - 이미지 2장 입력 → dualInput JSON으로 실행되는지

---

## 6) 메모(중요한 규칙/주의)

- 사용자 규칙:
  - “항상 최신 수정본 기반으로 로직 패치”
  - 에러 발생 시 CS/HTML/JS/CSS 전반 점검
  - Prettier 규칙 준수
  - JS 수정 시 IIFE(즉시 실행 함수) 형태 주의
- PowerShell 환경에서는 `&&`, `||` 같은 Bash 체인이 기본으로 안 먹습니다(명령은 분리 실행 권장).

