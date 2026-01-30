# POC 운영 가이드 (Runbook)

본 문서는 내부 POC 테스트를 3–4일 내에 안정적으로 수행하기 위한 운영 절차를 요약합니다.

## 1. 사전 준비
- Python venv 활성화(레포 내 `venv/` 존재)
  - PowerShell: `./venv/Scripts/activate`
- 필수 포트 개방(외부 접속 테스트 시)
  - 앱: 8000/TCP, ComfyUI: 8188/TCP
  - Windows 방화벽 허용 및 공유기 포트포워딩
- .env 준비: 레포 루트 `.env` 파일(예시는 `.env.example` 참고)

## 2. 기동/재시작
- 로컬 개발(자동 리로드 포함)
```
./run_server.bat
```
- 운영/베타(안정 모드, reload 없음)
```
./run_server_prod.bat
```
- 외부 접속(임시 공개)
```
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload --access-log false
```
- 종료: Ctrl+C

## 3. 환경변수(.env) 핵심
- Comfy/출력/DB
  - `COMFYUI_SERVER=127.0.0.1:8188`
  - `OUTPUT_DIR=./outputs/`
  - `JOB_DB_PATH=db/app_data.db`
  - (선택) `COMFY_INPUT_DIR=C:/path/to/ComfyUI/input`  ← ControlNet용 업로드/정리에 사용
- 큐/타임아웃
  - `MAX_PER_USER_QUEUE=3`
  - `MAX_PER_USER_CONCURRENT=1`
  - `JOB_TIMEOUT_SECONDS=180`
- 네트워크 타임아웃
  - `COMFY_HTTP_CONNECT_TIMEOUT=3`
  - `COMFY_HTTP_READ_TIMEOUT=10`
  - (WS) `COMFY_WS_CONNECT_TIMEOUT=5`, `COMFY_WS_IDLE_TIMEOUT=120`
- Health 임계치
  - `HEALTHZ_DISK_MIN_FREE_MB=1024`
- 로그
  - `LOG_LEVEL=INFO`, `LOG_FORMAT=json`, `LOG_TO_FILE=true`
  - `LOG_FILE_PATH=logs/app.log`, `LOG_MAX_BYTES=1048576`, `LOG_BACKUP_COUNT=3`
- 진행률 로그(터미널 노이즈)
  - `PROGRESS_LOG_STEP=20`, `PROGRESS_LOG_MIN_MS=1000`, `PROGRESS_LOG_LEVEL=info`
 - 업로드 제한(컨트롤 이미지)
   - `CONTROLS_MAX_BYTES=10485760` (기본 10MB)

## 3.1 베타/운영 시 필수 보안 설정(권장)
- 베타 접속 비밀번호(전체 사용자 공통)
  - `BETA_PASSWORD=원하는비밀번호`
  - 브라우저에서 최초 1회 `/beta-login`에 비밀번호 입력 → 쿠키 저장 후 사용
- 관리자(Admin) 보호(강력 권장)
  - `ADMIN_USER=admin`
  - `ADMIN_PASSWORD=강력한비밀번호`
  - `/admin` 및 `/api/v1/admin/*` 접근 시 인증 요구
- HTTPS 배포 시 쿠키 보안
  - `COOKIE_SECURE=true`
  - HTTPS에서만 쿠키가 전송되게 하여(중간자 공격/도청 위험 감소) 외부 베타에 안전합니다.

변경 시 서버 재시작 필요

## 4. 헬스체크/상태 확인
- `/healthz` (200=OK, 503=FAIL)
  - ComfyUI HTTP 응답, SQLite 쓰기, 디스크 여유, LLM 준비
  - DB 경로는 `JOB_DB_PATH`와 동일 경로를 사용(단일 진실)
- 관리자 배너: `http://127.0.0.1:8000/admin` → 새로고침 가능
- 사용자 화면: 생성 클릭 시 1.5초 사전 검사(FAIL 시 간단 안내 후 차단)

## 5. 일반 운영 플로우
1) 서버/ComfyUI 가동 → `/healthz` OK 확인
2) 브라우저 접속 `http://127.0.0.1:8000`
3) 2–3명 동시 생성 시나리오 실행
4) 문제 발생 시 트러블슈팅 수행

### 5.1 워크플로우 모드(Txt2Img / Img2Img)
- 워크플로우 카드 선택 후, 상단 프롬프트 근처에 모드 탭이 표시됩니다.
  - Txt2Img: 기본 생성(현재 선택 워크플로우 ID로 실행)
  - Img2Img: 편집용 하위 워크플로우가 연결되어 있을 때만 노출(부모 `ui.related.img2img`)
- Img2Img 모드 특징:
  - 입력 이미지(필수) 등록: 썸네일을 드래그-드롭하거나 ‘선택/업로드’로 지정
  - 비율 UI 숨김: 원본 이미지 스케일/비율을 따르므로 화면에서 비활성화됨
  - 프롬프트/추천템플릿: 모드에 따라 해당 워크플로우의 기본값/템플릿로 즉시 전환
  - 실행 시 실제 `workflow_id`는 편집 워크플로우 ID로 자동 스위칭됨(부모와 다를 수 있음)

### 5.2 입력 이미지 등록 방법
- 갤러리 썸네일 드래그-드롭(생성이미지/컨트롤/입력)
  - 생성/컨트롤 이미지는 서버가 `/api/v1/inputs/copy`를 통해 입력 보관함으로 복사 후 등록
  - 입력 보관함의 이미지는 즉시 선택
- 파일 드롭/업로드 허용(png/jpg/webp) — 서버가 용량 검증, 썸네일/메타 생성
- 등록 후 입력 이미지 미리보기 표시, ‘지우기’로 해제 가능

## 6. 트러블슈팅
- 생성 버튼이 바로 실패/대기 반복
  - `/healthz`/ADMIN 배너에서 FAIL 원인 확인 → ComfyUI 재기동 → 재확인
- 요청이 쌓이거나 429 빈번
  - `.env`의 `MAX_PER_USER_QUEUE` 조정(예: 5)
- 처리 지연/멈춤 느낌
  - `COMFY_HTTP_READ_TIMEOUT` 10→15 조정
  - 진행률 로그 스텝 `PROGRESS_LOG_STEP` 20→25/50 (노이즈 감소)
  - ControlNet 사용 시 입력 이미지 업로드가 지연될 수 있음(WS 진행률은 정상)
- 디스크 부족 경고
  - 저장소 확보 또는 `HEALTHZ_DISK_MIN_FREE_MB` 조정
- 로그 위치
  - 콘솔 + (옵션) 파일 `logs/app.log` (json)
 - 정적 파일 제공
   - `outputs/` 폴더는 `/outputs`로 서빙되어 응답의 `url`이 `/outputs/...`로 시작해야 브라우저에서 접근 가능

### 6.1 Img2Img 관련
- 탭이 안 보임: 해당 워크플로우에 `ui.related.img2img` 링크가 없을 수 있음(숨김)
- 드래그-드롭 미등록: 브라우저 콘솔 에러 확인. 부모 워크플로우가 아닌 ‘편집 워크플로우’의 `image_input` 유무 기준으로 검사됨
- 비율 버튼이 보임: 모드 전환 후 새로고침/탭 토글로 숨김 재적용(프론트 캐시 이슈 시)

## 7. 데이터/정리
- 사용자 갤러리: `GET /api/v1/images?page=&size=`
- 사용자 소프트삭제: `POST /api/v1/images/{id}/delete`
- 입력 보관함: `GET /api/v1/inputs`, `POST /api/v1/inputs/upload`, `POST /api/v1/inputs/copy`
- 관리자 이미지: `GET /api/v1/admin/images?user_id=&page=&size=&include=&from_date=&to_date=`
- 휴지통 비우기: `POST /api/v1/admin/purge-trash`
- 잡 스냅샷 DB: `db/app_data.db` (SQLite)
 - 컨트롤/생성 이미지 임시 파일 정리
   - `COMFY_INPUT_DIR`가 설정된 경우, 생성 파이프라인 완료 시 ComfyUI input 폴더의 업로드 파일을 베스트에포트로 삭제

### 7.1 로컬 데이터 초기화(개발/테스트 후 비우기)
- 초기화 대상: 작업 DB + 갤러리(생성/컨트롤/입력) 파일
```
./reset_local_data.bat
```

## 8. 권장 값(단일 GPU)
- `MAX_PER_USER_CONCURRENT=1`
- `MAX_PER_USER_QUEUE=0~5`
- `JOB_TIMEOUT_SECONDS=180`
- 로그: 개발 DEBUG/text, POC INFO/json(+파일)

## 부록: 리허설 체크리스트
- [ ] Img2Img 탭 표시(편집 워크플로우가 연결된 경우)
- [ ] 입력 이미지 드래그-드롭/업로드 등록 → 미리보기 표시
- [ ] Txt2Img/Img2Img 전환 시 프롬프트/템플릿 즉시 스위칭
- [ ] `/healthz` OK → ADMIN 배너 OK
- [ ] 2–3명 동시 생성: 대기/ETA/취소/타임아웃/완료 정상
- [ ] ComfyUI 중단 시: 사용자 사전 차단, 잡 error, ADMIN FAIL
- [ ] 삭제/복구/스위프 동작 및 ‘삭제됨’ 표시 확인
- [ ] `.env` 변경 후 재시작 → 설정 반영
- [ ] 로그: enqueue → job_start → job_progress(스텝) → job_complete 순서 확인

---
참고: 레거시 `BasicWorkFlow_LOSStyle`는 제거되었으며, 현재는 `LOSstyle_Qwen` + `LOSStyle_Klein_Img2Img` 조합을 사용합니다.
