# 문서 인덱스

> 최종 업데이트: 2026-08-13

이 파일은 현재 유효한 문서의 역할과 우선순위를 설명합니다. 구현과 문서가 다르면
코드를 확인하고 같은 변경에서 문서도 함께 수정합니다.

## 시작점

- `../README.md`: 설치, 실행, 검증, 주요 문서 링크
- `PROJECT_OVERVIEW.md`: 현재 아키텍처와 데이터 흐름의 기준 문서
- `OPERATIONS.md`: 배포, 백업, 마이그레이션, 장애 대응

## 기능별 문서

- `asset-infrastructure.md`: 자산 카탈로그, principal, 접근 제어, 전환 상태
- `mcp.md`: 현재 공개된 MCP 도구, 클라이언트 설정, 네트워크 보안
- `MCP_CAPABILITY_CONTRACT.md`: provider-neutral capability와 구현 상태
- `game-ui-elements-mvp.md`: Game UI 엘리먼트 MVP 범위와 제약

## 문서 유지 규칙

- 현재 구조를 설명하는 문서는 날짜를 파일명에 넣지 않고 고정 이름을 사용합니다.
- 완료된 일회성 작업계획은 삭제합니다. 필요한 이력은 Git에서 조회합니다.
- 환경 변수를 추가하면 `.env.example`과 `OPERATIONS.md`를 함께 검토합니다.
- capability나 MCP 도구를 변경하면 `PROJECT_OVERVIEW.md`, `mcp.md`,
  `MCP_CAPABILITY_CONTRACT.md`를 함께 검토합니다.
- 저장·소유권·백업 정책을 변경하면 `asset-infrastructure.md`와 `OPERATIONS.md`를
  함께 검토합니다.
- 구현되지 않은 기능은 반드시 `계획` 또는 `계약만 준비`라고 표시합니다.
