# 이미지 저장/히스토리 운영 메모 (점진적 확장 로드맵)

## 목적
- 지금은 DB 없이도 안정적으로 이미지 히스토리를 관리
- 나중에 사용자 인증/확장(오브젝트 스토리지+DB)으로 자연스럽게 이전 가능

## 1) 현재 단계(파일시스템 기반)
- 경로 스킴(생성 이미지)
  - outputs/users/{user_id}/YYYY/MM/DD/{id}.png
  - 썸네일: outputs/users/{user_id}/YYYY/MM/DD/thumb/{id}.webp (환경에 따라 .jpg 폴백)
  - 메타(사이드카): outputs/users/{user_id}/YYYY/MM/DD/{id}.json
- 경로 스킴(컨트롤 이미지)
  - outputs/users/{user_id}/controls/YYYY/MM/DD/{id}.png
- 경로 스킴(입력 보관함 이미지)
  - outputs/users/{user_id}/inputs/YYYY/MM/DD/{id}.png
  - 썸네일/메타 규칙은 컨트롤과 동일
  - 썸네일: outputs/users/{user_id}/controls/YYYY/MM/DD/thumb/{id}.webp (또는 .jpg)
  - 메타: outputs/users/{user_id}/controls/YYYY/MM/DD/{id}.json
- 파일명/키 규칙(현 구현 기준)
  - user_id: 브라우저 익명 쿠키 `anon_id` 값을 사용(예: `anon-xxxxxxxx...`). 추후 로그인 전환 시 그대로 `user_id`로 대체 가능.
  - id: UUID v4 hex(32자리) 사용
  - 현행 JobManager 연계: 이미지 메타의 `owner`는 Job의 `owner_id(anon_id)`로 기록 → 갤러리/관리 API가 동일 키로 필터링
- 메타데이터(현 구현 예시)
  - 생성 이미지: { id, owner, workflow_id, aspect_ratio, seed, prompt, original_filename, mime, bytes, sha256, created_at(ISO8601), status:"active|trash", thumb, tags:[] }
  - 컨트롤 이미지: { id, owner, kind:"control", original_filename, mime, bytes, sha256, created_at(ISO8601), status, thumb, tags:[] }
  - 입력 이미지: { id, owner, kind:"input", original_filename, mime, bytes, sha256, created_at(ISO8601), status, thumb, tags:[] }
  - 주의: 현재는 negative_prompt, 이미지 width/height 등은 메타에 저장하지 않습니다(필요 시 확장).
- 정적 제공
  - FastAPI가 `outputs/`를 `/outputs` 경로로 마운트하여 브라우저가 직접 접근 가능(예: `/outputs/users/.../xxx.png`).
- 매니페스트(선택)
  - outputs/users/{user_id}/manifest.json (append-only, 최근순 인덱스)
  - 서버 시작 시 폴더 스캔 → 매니페스트 재빌드 가능
- 캐시
  - 인메모리 최근 N개 링버퍼 + 디렉토리 감시로 자동 갱신
- API(초기)
  - 사용자 갤러리: GET /api/v1/images?page=&size=  → 최근순 페이지네이션(thumb_url 포함)
  - 사용자 소프트삭제: POST /api/v1/images/{id}/delete → 휴지통 이동
  - 입력 보관함: GET /api/v1/inputs, POST /api/v1/inputs/upload, POST /api/v1/inputs/copy, POST /api/v1/inputs/{id}/delete|restore
  - 관리자 목록: GET /api/v1/admin/users, GET /api/v1/admin/images?user_id=&page=&size=&include=&from_date=&to_date=
  - 관리자 액션: POST /api/v1/admin/images/{id}/delete, POST /api/v1/admin/images/{id}/restore, POST /api/v1/admin/purge-trash
- 삭제/정리 정책
  - 휴지통 보존기간(예: 30일) 이후 영구 삭제(정기 잡)
  - 썸네일/원본/메타 동시 관리(일관성 유지)
  - ComfyUI input 임시파일: 생성 파이프라인 완료 후 `COMFY_INPUT_DIR`에서 업로드 파일을 베스트에포트로 삭제
- 보안 가드
  - 서버가 경로를 조립(클라이언트 경로 신뢰 금지)
  - 허용된 확장자/시그니처 검증, 경로 탐색 방지
- 쿼터(간단)
  - 사용자별 총 바이트/개수 상한, 초과 시 생성 차단 또는 정리 유도

## 2) 다음 단계(오브젝트 스토리지 + RDB)
- 스토리지: S3/MinIO로 키 동일 유지(users/{user_id}/YYYY/MM/DD/{ulid}.png)
- DB: Postgres에 메타 저장(인덱스: user_id, created_at desc, tags, workflow)
- 접근: 프리사인 URL, CDN 캐싱 도입
- 마이그레이션: outputs 스캔 → 업로드 → DB 적재 → 무중단 스위치

### (게스트 → 회원 이관 시 고려)
- 경로: `users/anon-.../` → `users/{user_id}/` 이동(서버 배치 스크립트)
- 메타: `owner` 필드 값을 신규 `user_id`로 교체
- 썸네일/원본/메타 동시 이동(참조 일관성)

## 3) 프론트엔드 UX 백로그
- 갤러리 무한스크롤, 필터(날짜/비율/태그/워크플로우), 검색(프롬프트)
- 라이트박스 좌/우 네비, 즐겨찾기, 태그 편집, 일괄 선택/삭제/복구
- 다운로드 ZIP, 공유 링크(만료형 프리사인)

## 4) 운영/관리(개발자용)
- reindex: 폴더 → 매니페스트/DB 재작성, orphan 검출/정리
- thumbnails: 썸네일 재생성 배치
- quota-report: 사용자별 용량/개수 리포트
- purge-trash: 휴지통 보존기간 경과분 영구 삭제
- backup/restore: 날짜 파티션 단위 백업/복원

## 5) 원칙
- 키/경로 스킴을 초기에 고정 → 이후 이전이 쉬움
- 원본 불변, 메타는 가변(태그/즐겨찾기 등)
- 소프트삭제 기본, 하드삭제는 배치에서만
- 사용자/게스트 네임스페이스 분리(현 구현은 `anon-...` 쿠키 네임스페이스)

(구조 변경 시 이 메모를 함께 업데이트합니다)
