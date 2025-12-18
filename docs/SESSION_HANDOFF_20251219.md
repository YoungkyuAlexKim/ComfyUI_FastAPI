# 작업 현황서 + 다음 세션 요청서(핸드오프 문서) — `ComfyUI_FastAPI` (2025-12-19)

이 문서는 **새 대화창에서 다른 동료 AI가 바로 이어서 코딩/운영 대응**을 할 수 있도록, 프로젝트 목적/구조/이번 세션 변경점/운영 이슈/다음 작업 후보를 최대한 구체적으로 정리한 것입니다.  
(대화는 공손한 한국어 + 비개발자도 이해 가능한 설명을 기본으로 합니다.)

---

## 0) 프로젝트 요약(무엇을 하는가)
- **목적**: ComfyUI를 이미지 생성 엔진으로 쓰고, 그 앞에 **FastAPI + 웹 UI(HTML/JS/CSS)**를 붙여 여러 사용자가 동시에 이미지 생성/대기/취소/갤러리/쇼케이스(피드)를 사용하도록 하는 서비스.
- **사용자 구분**: 로그인 대신 브라우저 쿠키 `anon_id`로 사용자 구분.
- **운영 데이터 저장**
  - 결과 이미지/썸네일/메타: **파일 기반**(사이드카 JSON + thumb)
  - Job/피드 메타: `db/app_data.db`(SQLite)

---

## 1) 배포/복사-붙여넣기 운영 규칙(매우 중요)
개발 PC에서 작업 후 **서버 PC에 코드만 복사-붙여넣기 배포** 전제.

### 절대 덮어쓰면 안 되는 것(서버 PC)
- `outputs/`
- `db/` (특히 `db/app_data.db`)
- `venv/`
- `logs/` (가능하면 유지)
- 서버의 `.env` (운영 설정이므로 유지 권장)

---

## 2) 이번 세션에서 들어온 사용자 피드백 & 처리 결과

### 2.1 (버그) Img2Img 입력 이미지 선택/드래그가 “실패”한다
#### 관측된 서버 로그
- `413 Request Entity Too Large`
- 메시지 예: `입력 이미지가 너무 큽니다. 최대 2621440 bytes 까지 허용됩니다.`

#### 결론(원인)
- 서버의 입력 이미지 업로드 제한이 **2.5MB(= 2,621,440 bytes)**였고, 사용자 이미지가 **4.1MB**라서 업로드가 거절됨.

#### 운영 결정
- **2.5MB 제한 유지**(서버 저장공간/운영 안정성 고려).
  - `.env` 기준: `INPUTS_MAX_BYTES=2621440` (권장 유지)

#### 개선(진단/UX 측면)
“이번 원인은 413(용량 제한)”이었지만, 향후 빠른 원인 파악을 위해 에러 메시지/호환성 보완을 추가.
- **에러 메시지 개선**: 실패 시 status/detail을 더 정확히 안내(업로드/복사/응답 이상).
- **파일명 확장자 문제 완화**: 일부 환경에서 업로드 파일명이 `blob` 등 확장자 없이 올 때도, **content-type으로 PNG/JPG/WEBP를 판단해 업로드 허용**.
- **HEIC 안내**: (프론트) HEIC/HEIF 업로드 시 “PNG/JPG로 변환” 안내.

관련 수정 파일:
- `templates/index.html` (업로드/복사 실패 메시지 개선, HEIC 안내)
- `app/routers/inputs.py` (2.5MB 안내 메시지(MB 단위), 확장자 없는 업로드 content-type 허용)

---

### 2.2 (UX) 결과 이미지 메타에 seed(시드)도 보이게 해달라
#### 문제
- 랜덤 seed로 생성하는 경우가 기본인데, 마음에 드는 이미지가 나와도 **라이트박스 메타에 seed가 없어** 재현이 어려움.

#### 해결
- 라이트박스(썸네일/출력 클릭 시 정보 패널)에 **seed 표시 필드 추가**.
- seed 입력을 비웠더라도(랜덤) **실제로 사용된 seed가 항상 확정/저장되도록** 보완.

주의(기존 이미지)
- **이미 저장된 과거 이미지**는 당시 메타에 seed가 없으면 표시 불가.
- **이번 변경 이후 생성분부터** seed가 안정적으로 기록/표시됨.

관련 수정 파일:
- `templates/index.html` (라이트박스에 seed 표시 + 요청 시 seed 자동 생성/전송)
- `app/services/generation.py` (서버에서도 seed가 없으면 강제 확정하여 저장/메타에 남도록 보완)

---

### 2.3 (기능 추가) 배경제거(Remove Background) 워크플로우 `RMBG2` 추가
#### 사용자 요청
- 특정 이미지에 대해 **배경제거(누끼)** 기능을 FastAPI 서비스에 추가.
- 오픈소스 모델/커스텀 노드 기반(ComfyUI 워크플로우 실행)으로 구현.

#### 준비/전제
- ComfyUI 측 커스텀 노드 설치 후, `workflows/RMBG2.json` 워크플로우를 추가.
- 워크플로우 JSON 구조(핵심)
  - 노드 `1`: `AILab_LoadImage` (입력 이미지)
  - 노드 `11`: `RMBG` (모델: `RMBG-2.0`, 배경: Alpha)
  - 노드 `7`: `PreviewImage`

#### 연동 구현(서비스 쪽)
- 워크플로우 등록: `app/workflow_configs.py`에 `RMBG2` 설정 추가
  - `image_input`: `{"image_node":"1","input_field":"image"}`
  - 프롬프트는 필요 없으므로 UI에서 숨김 처리
  - 생성 버튼 라벨을 “배경 제거하기”로 변경
- 워크플로우 목록 분류:
  - 기존 분류는 `templateMode === 'natural'`만 자연어로 분리하고 나머지는 태그 기반으로 들어가 UX가 어색했음
  - `RMBG2`는 `templateMode: "utility"`로 지정해 **“도구” 그룹으로 분리**
- 배너 적용:
  - `static/img/banner/img_banner_RMBG2.png`를 `RMBG2` 워크플로우 배너로 매핑
- 투명 PNG(알파) 출력 UX 개선:
  - 썸네일 생성 시 알파가 `RGB`로 강제 변환되며 투명 영역이 검게 굳던 문제를 개선
  - 서버에서 **알파를 유지한 WEBP(가능하면 lossless)**로 썸네일 생성
  - UI에서는 RMBG2 결과에만 **체커보드 배경**을 깔아 투명 영역이 눈에 보이게 함

관련 추가/수정 파일:
- `workflows/RMBG2.json` (신규 워크플로우 파일)
- `app/workflow_configs.py` (RMBG2 등록, `templateMode: "utility"`, `generateLabel`)
- `templates/partials/input_panel.html` (`#user-prompt-wrap` id 부여 → 프롬프트 숨김 제어)
- `templates/index.html`
  - 도구 그룹 분리 렌더링
  - RMBG2 선택 시 프롬프트 숨김
  - 입력 이미지 필수(Img2Img 탭을 누르지 않아도 `image_input` 워크플로우면 필수)
  - 버튼 라벨(배경 제거하기) 적용
  - RMBG2 결과에 체커보드 배경 적용(결과/라이트박스/갤러리)
- `app/services/media_store.py` (썸네일 생성 시 알파 유지 WEBP 생성)
- `static/css/components.css` (체커보드 배경 스타일)
- `static/js/app_config.js` (워크플로우 배너 매핑에 RMBG2 추가)

---

## 3) 서버 배포 시 “이번 세션 변경분” 덮어쓸 파일 목록(코드만)
아래 파일들만 서버로 복사/덮어쓰기 하면 됨(운영 데이터 제외).

### A) 입력 이미지 실패/업로드 호환성 개선
- `templates/index.html`
- `app/routers/inputs.py`

### B) seed 표시/기록 개선
- `templates/index.html`
- `app/services/generation.py`

### C) RMBG2 배경 제거 기능(도구 분리 + 투명 썸네일 + 배너 포함)
- `workflows/RMBG2.json`
- `app/workflow_configs.py`
- `app/services/media_store.py`
- `templates/index.html`
- `templates/partials/input_panel.html`
- `static/css/components.css`
- `static/js/app_config.js`

**주의**: Python/템플릿 변경이 포함되므로 적용 후 **서버 재시작 필요**.

---

## 4) 운영/검수 체크리스트(비개발자용)
### 4.1 입력 이미지 업로드 제한(2.5MB)
- 4MB 이미지 업로드 시: “너무 큽니다(2.5MB)” 안내가 뜨는지
- 1~2MB PNG 업로드 시: 정상 업로드/선택되는지

### 4.2 seed 표시
- seed 칸 비우고 생성 → 결과 클릭(라이트박스) → **seed 값 표시되는지**

### 4.3 RMBG2 배경제거
- 워크플로우 목록에 **‘도구’ 그룹**이 있고, 그 안에 “배경 제거 (RMBG 2.0)”이 있는지
- RMBG2 선택 시:
  - 프롬프트 입력칸이 숨겨지는지
  - 입력 이미지가 필수로 요구되는지
  - 버튼이 “배경 제거하기”로 보이는지
  - 결과 PNG 투명 영역이 **체커보드 배경**으로 보이는지(갤러리/결과/라이트박스)
  - 배너가 `img_banner_RMBG2.png`로 바뀌는지

---

## 5) 다음 세션 작업 후보(요청서)
이번 세션은 많은 반영을 했고, 이후 사용자 피드백은 다음 세션에서 이어서 처리.

### 5.1 RMBG2 전용 UX 추가 후보
- seed 입력은 RMBG2에서 의미가 크지 않을 수 있으니 **seed 입력칸 숨김 옵션**(예: `ui.hideSeed=true`) 추가 고려
- 출력 파일명/다운로드 버튼 문구를 “배경제거 결과 다운로드”처럼 더 명확히

### 5.2 공통 운영 개선
- 에러가 401/403일 때(베타 쿠키/권한 문제) 사용자에게 “로그인/쿠키” 안내를 더 친절하게
- 413(용량 제한) 안내를 화면에서 더 명확히(“2.5MB 이하로 저장해주세요”)


