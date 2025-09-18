# 이미지 저장/히스토리 운영 메모 (점진적 확장 로드맵)

## 목적
- 지금은 DB 없이도 안정적으로 이미지 히스토리를 관리
- 나중에 사용자 인증/확장(오브젝트 스토리지+DB)으로 자연스럽게 이전 가능

## 1) 현재 단계(파일시스템 기반)
- 경로 스킴
  - outputs/users/{user_id}/YYYY/MM/DD/{ulid}.png
  - 썸네일: outputs/users/{user_id}/YYYY/MM/DD/thumb/{ulid}.jpg
  - 메타(사이드카): outputs/users/{user_id}/YYYY/MM/DD/{ulid}.json
- 파일명/키 규칙
  - user_id: 내부 UUID/ULID(PII 금지), 폴더명으로 사용
  - ulid: 시간 정렬 가능 키(중복 방지/정렬 용이)
- 메타데이터(예시)
  - { id, user_id, prompt, negative_prompt, seed, aspect_ratio, workflow_id,
      image_width, image_height, mime, file_bytes, sha256, created_at,
      tags:[], favorite:boolean, status:"active|trash", trash_until, version }
- 매니페스트(선택)
  - outputs/users/{user_id}/manifest.json (append-only, 최근순 인덱스)
  - 서버 시작 시 폴더 스캔 → 매니페스트 재빌드 가능
- 캐시
  - 인메모리 최근 N개 링버퍼 + 디렉토리 감시로 자동 갱신
- API(초기)
  - GET /api/v1/images?limit=&cursor=  → 최근순 페이지네이션
  - GET /api/v1/images/{id}           → 메타/파일 접근
  - DELETE /api/v1/images/{id}        → 소프트삭제(status=trash, trash_until)
  - POST /api/v1/images/{id}/restore  → 휴지통 복구
- 삭제/정리 정책
  - 휴지통 보존기간(예: 30일) 이후 영구 삭제(정기 잡)
  - 썸네일/원본/메타 동시 관리(일관성 유지)
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
- 사용자/게스트 네임스페이스 분리(guest/{session_id}/...)

(구조 변경 시 이 메모를 함께 업데이트합니다)
