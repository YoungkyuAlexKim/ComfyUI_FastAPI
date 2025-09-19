# 잡/큐 아키텍처 메모 (현행 구현 + 확장 로드맵)

## 목적
- 다수 사용자 동시 요청을 공정하게 처리하고, 작업(job) 단위로 상태/취소/로그를 일관되게 관리
- 단일 서버 → 다수 워커/복수 GPU로 자연 확장

## 현행 구성
- JobManager (메모리)
  - 레지스트리: `job_id -> { owner_id, type(generate|...), status, progress, result }`
  - 사용자 큐: `owner_id -> deque[job_id]`
  - 스케줄러: 라운드로빈으로 각 사용자 큐에서 1개씩 꺼내 단일 워커로 처리
  - 취소: queued → 즉시 취소, running → ComfyUI `interrupt` 전달(취소 플래그 반영)
  - 알림: notifier로 사용자 스코프 WebSocket에 이벤트 전송(`queued|running|complete|cancelled|error` + `job_id`)
- 사용자 식별: 브라우저 쿠키 `anon_id` (WS 연결 시 `?anon_id=`로 전달)
- API/WS
  - `POST /api/v1/generate` → `{ job_id, status:'queued', position }`
  - `GET /api/v1/jobs/{job_id}` → 상태/진행률/포지션
  - `POST /api/v1/jobs/{job_id}/cancel`
  - `WS /ws/status` → 사용자 채널에 job 이벤트 push
- 프런트 UX
  - 작업별 `job_id` 저장, 이벤트 필터링(내 작업만)
  - 대기 순번/진행률 표시, 완료 시 오버레이/버튼 자동 복구(세이프가드 포함)

## 영속화(경량)
- JobStore(SQLite): `db/app_data.db`
  - 잡 스냅샷을 상태 변경 시 upsert로 기록
  - ADMIN의 최근 잡 목록은 SQLite에서 우선 조회(없으면 인메모리 폴백)
  - 별도 서버/설치 불필요, 파일은 레포 내 `db/` 폴더에 생성

## 로깅
- 구조화 로그(JSON): `comfyui_app` 로거
  - enqueue/enqueue_rejected, job_start, job_progress, job_complete, job_error, ws_connect/disconnect, list_images 등 이벤트 기록
  - 필드: ts, level, event, job_id, owner_id, path 등
  - 기본 콘솔 출력(추후 파일/수집기로 확장 가능)

## 환경변수(.env)
- COMFYUI_SERVER, OUTPUT_DIR, JOB_DB_PATH
- MAX_PER_USER_QUEUE, MAX_PER_USER_CONCURRENT, JOB_TIMEOUT_SECONDS

## 운영/모니터링
- ADMIN: `GET /api/v1/admin/jobs`(최근 N개) + UI 테이블(취소 버튼 포함)
- 로그/메트릭(향후): 처리시간/성공률/실패 사유 집계, 워커별 상태판

## 차후 확장 포인트
- 큐 백엔드: 메모리 → Redis/RabbitMQ 교체(인터페이스 유지)
- 멀티 워커: 워커 등록/헬스체크, 리소스/모델 적합성 기반 라우팅, 동시처리 수 상한
- 우선순위: 업무/워크플로우/사용자 플랜별 가중치, SLA 관리
- 영속화: 잡 상태/이벤트를 DB에 감사로그로 저장
- 인증 전환: `owner_id`를 `user_id`로 교체(코드 구조 변경 없이 값만 변경)

(변경 시 이 문서를 최신화합니다)
