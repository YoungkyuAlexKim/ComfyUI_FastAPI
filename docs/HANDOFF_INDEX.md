# 문서 인덱스

> 최종 업데이트: 2026-08-13

이 파일은 현재 유효한 문서의 역할과 우선순위를 설명합니다. 구현과 문서가 다르면
코드를 확인하고 같은 변경에서 문서도 함께 수정합니다.

## 최근 검증 체크포인트

기능 구현 기준 커밋은 `b1420ee`이며 2026-08-13에 다음을 확인했습니다.

- 프로젝트 가상환경의 전체 단위·통합 테스트 90개 통과
- 실서버 `/healthz`, SQLite `quick_check`, 자산 audit 정상
- 기존 사용자 갤러리·원본 조회와 unsigned cookie의 compat 승격 정상
- GPT Image 2 1K/Low 생성, 새로고침 후 조회, 삭제, 관리자 복구 정상
- MCP 0.4.0 초기화와 9개 공개 도구 계약 정상
- 검증 직후 카탈로그 자산 1,244개, Game UI 그룹 4개, 누락 파일·메타·그룹 파일 0

자산 수치는 운영 중 증가하는 스냅샷이며 성공 기준은 고정 숫자가 아니라 DB 무결성과
누락 수치 0입니다. 유료 참고 이미지 편집과 신규 Game UI 생성은 이 체크포인트에서
실행하지 않았습니다. Game UI 웹은 이후 2×2·3×3·4×4로 확장했으며 합성 시트 자동
테스트와 격리 Edge E2E로 요청·분할·저장·결과·갤러리·새로고침·manifest·ZIP을
검증했습니다. 이후 실서버 GPT Image 2 2K/Medium 4×4 생성도 정상 결과를 확인했습니다.

2026-08-13 Game UI 확장 작업 기준으로 전체 테스트 102개가 통과했습니다. 묶음 저장은
자식 자산과 그룹을 한 SQLite 트랜잭션으로 등록하며 실패 파일을 보상 정리하고, 웹
갤러리는 `preserve_groups=true`로 4×4 묶음을 페이지 사이에서 나누지 않습니다.
`python -m scripts.smoke_game_ui_browser` 격리 Edge 스모크에서 16셀, ZIP master 16개와
파생본 64개, 부분 삭제 `15/16` 표기, 복구와 새로고침을 확인했습니다. 실서버 4×4 생성 후
운영 audit는 자산 1,265개·그룹 5개·누락 0이며 실제 출력의 분할·갤러리 복원도 정상입니다.

## 운영 hardening 진행 상태

2026-08-13 후속 작업에서 다음 도구와 검사를 추가했습니다.

- 전체 단위·통합 테스트 95개 통과
- 공통 실행기: 정상 인스턴스 중복 방지, 비정상 포트 PID 표시, 실행 로그, 오류 pause
- 완전 백업: 목적지별 중복 실행 차단, 선택적 보존 정책, 작업 스케줄러 관리 도구
- 복구 훈련: 임시 staging 복사본의 checksum·DB·자산·principal secret 검증
- principal readiness: 로그 quiet window와 검증된 완전 백업을 함께 요구
- catalog canary: 실제 파일 inventory와 3종 자산 조회 parity, fail-closed 검사

검증 호스트에서는 3,926개 파일·약 2.14GB 완전 백업과 임시 staging 복구 훈련이
성공했고, 프로젝트 밖 같은 C: 드라이브에 매일 03:00/14일/최소 3세트 예약 작업을
등록해 수동 실행 결과 0까지 확인했습니다. 이는 파일 손상·실수 복구용이며 디스크 고장
대비를 위해 목적지를 별도 볼륨이나 NAS로 교체해야 합니다.

실제 catalog canary는 자산 1,249개와 그룹 4개에서 parity와 누락 0으로 통과했습니다.
`ASSET_CATALOG_FALLBACK_ENABLED=false` 실서버도 health, reconcile, 기존 소유자의
image/input/audio 목록 수와 원본 조회가 정상이며 fallback 경고가 없습니다. 반면
principal 로그에는 최근 `legacy_cookie` 승격이 있어 아직 `enforced`로 바꾸지 않았습니다.
quiet window가 끝날 때까지 `compat`을 유지합니다.

## 시작점

- `../README.md`: 설치, 실행, 검증, 주요 문서 링크
- `PROJECT_OVERVIEW.md`: 현재 아키텍처와 데이터 흐름의 기준 문서
- `OPERATIONS.md`: 배포, 백업, 마이그레이션, 장애 대응

## 기능별 문서

- `asset-infrastructure.md`: 자산 카탈로그, principal, 접근 제어, 전환 상태
- `mcp.md`: 현재 공개된 MCP 도구, 클라이언트 설정, 네트워크 보안
- `MCP_CAPABILITY_CONTRACT.md`: provider-neutral capability와 구현 상태
- `game-ui-elements-mvp.md`: Game UI 엘리먼트 웹 그리드, 저장 계약, MCP 공개 범위와 제약
- `../app/resources/refs/README.md`: 정적 mount 밖의 서버 전용 숨김 레퍼런스

## 문서 유지 규칙

- 현재 구조를 설명하는 문서는 날짜를 파일명에 넣지 않고 고정 이름을 사용합니다.
- 완료된 일회성 작업계획은 삭제합니다. 필요한 이력은 Git에서 조회합니다.
- 환경 변수를 추가하면 `.env.example`과 `OPERATIONS.md`를 함께 검토합니다.
- capability나 MCP 도구를 변경하면 `PROJECT_OVERVIEW.md`, `mcp.md`,
  `MCP_CAPABILITY_CONTRACT.md`를 함께 검토합니다.
- 저장·소유권·백업 정책을 변경하면 `asset-infrastructure.md`와 `OPERATIONS.md`를
  함께 검토합니다.
- 실행 동작을 변경하면 `run_server*.bat`, `reset_local_data.bat`의 사용자 안내와
  `OPERATIONS.md`를 함께 검토합니다.
- 구현되지 않은 기능은 반드시 `계획` 또는 `계약만 준비`라고 표시합니다.
