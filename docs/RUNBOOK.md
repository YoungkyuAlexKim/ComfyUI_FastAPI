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

변경 시 서버 재시작 필요

## 4. 헬스체크/상태 확인
- `/healthz` (200=OK, 503=FAIL)
  - ComfyUI HTTP 응답, SQLite 쓰기, 디스크 여유, LLM 준비
- 관리자 배너: `http://127.0.0.1:8000/admin` → 새로고침 가능
- 사용자 화면: 생성 클릭 시 1.5초 사전 검사(FAIL 시 간단 안내 후 차단)

## 5. 일반 운영 플로우
1) 서버/ComfyUI 가동 → `/healthz` OK 확인
2) 브라우저 접속 `http://127.0.0.1:8000`
3) 2–3명 동시 생성 시나리오 실행
4) 문제 발생 시 트러블슈팅 수행

## 6. 트러블슈팅
- 생성 버튼이 바로 실패/대기 반복
  - `/healthz`/ADMIN 배너에서 FAIL 원인 확인 → ComfyUI 재기동 → 재확인
- 요청이 쌓이거나 429 빈번
  - `.env`의 `MAX_PER_USER_QUEUE` 조정(예: 5)
- 처리 지연/멈춤 느낌
  - `COMFY_HTTP_READ_TIMEOUT` 10→15 조정
  - 진행률 로그 스텝 `PROGRESS_LOG_STEP` 20→25/50 (노이즈 감소)
- 디스크 부족 경고
  - 저장소 확보 또는 `HEALTHZ_DISK_MIN_FREE_MB` 조정
- 로그 위치
  - 콘솔 + (옵션) 파일 `logs/app.log` (json)

## 7. 데이터/정리
- 사용자 갤러리: `GET /api/v1/images?page=&size=`
- 사용자 소프트삭제: `POST /api/v1/images/{id}/delete`
- 관리자 이미지: `GET /api/v1/admin/images?user_id=&page=&size=&include=&from_date=&to_date=`
- 휴지통 비우기: `POST /api/v1/admin/purge-trash`
- 잡 스냅샷 DB: `db/app_data.db` (SQLite)

## 8. 권장 값(단일 GPU)
- `MAX_PER_USER_CONCURRENT=1`
- `MAX_PER_USER_QUEUE=0~5`
- `JOB_TIMEOUT_SECONDS=180`
- 로그: 개발 DEBUG/text, POC INFO/json(+파일)

## 부록: 리허설 체크리스트
- [ ] `/healthz` OK → ADMIN 배너 OK
- [ ] 2–3명 동시 생성: 대기/ETA/취소/타임아웃/완료 정상
- [ ] ComfyUI 중단 시: 사용자 사전 차단, 잡 error, ADMIN FAIL
- [ ] 삭제/복구/스위프 동작 및 ‘삭제됨’ 표시 확인
- [ ] `.env` 변경 후 재시작 → 설정 반영
- [ ] 로그: enqueue → job_start → job_progress(스텝) → job_complete 순서 확인
