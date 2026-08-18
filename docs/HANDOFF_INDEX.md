# 문서 인덱스와 현재 체크포인트

> 최종 업데이트: 2026-08-18

이 파일은 다음 작업자가 가장 먼저 읽는 현재 상태 요약입니다. 상세 설계와 절차는 아래의
역할별 문서가 기준이며, 완료된 일회성 작업 일지는 Git 이력에서 확인합니다.

## 현재 기준선

- 코드 기준: `36d2952` 이후 현재 작업 트리
- MCP: 0.8.0, Streamable HTTP `/mcp/`, 도구 13개, 공개 생성 capability 5개
- 자동 회귀: 전체 `unittest` 성공 여부를 기준으로 관리
- 운영 자산 audit: catalog row 1,298개, active Game UI 그룹 5개 (2026-08-18)
- 정합성: `missing_files=0`, `missing_metadata=0`, `missing_group_files=0`
- 실제 클라이언트: Codex 앱·IDE, Claude Code 직접 업로드·연속 편집 검증 완료
- 지원 보류: Claude Desktop은 DNS·HTTPS 프록시 정책 재협의 전까지 미지원
- 온보딩: Codex·Claude Code 탭, Edge E2E와 390px 반응형 검증

자산 개수는 운영 중 계속 바뀝니다. 고정 숫자가 아니라 전체 테스트 성공, audit 누락 0,
DB·파일 정합성을 회귀 기준으로 사용합니다.

## 구현·검증 상태

| 영역 | 상태 | 확인 범위 |
|---|---|---|
| 기본 이미지 생성 | 완료 | 1K 반복 생성, 멱등성, polling, actual cost |
| 참고 이미지 편집 | 완료 | multipart 직접 첨부·소유 자산 편집, Claude Code 연속 편집 |
| Game UI | 완료 | 웹 2×2·3×3·4×4, MCP 2×2, 그룹 ZIP·수명주기 |
| 캐릭터 시트 | 완료 | 턴어라운드 3뷰, 표정 4개 실호출 |
| 스토리보드 | 완료 | 6컷 실호출; gutter fallback 품질 관찰 필요 |
| RMBG | 완료 | 반복·연속 큐, 투명 PNG, 외부 provider cost 0.0 |
| 비용·감사 | 완료 | IP·기능·모델별 actual cost와 미수집 구분 |
| 웹↔MCP 갤러리 연결 | 완료 | 영구 연결, takeover 차단, 원본 owner 유지, 선택·휴지통 관리 |
| 결과 미리보기 | 서버 계약 완료 | 경량 ImageContent, 원본 링크, 로컬 다운로드·열기 지침 |
| 장시간·다사용자 부하 | 미검증 | 단일 개발자 환경 밖의 운영 표본 필요 |

현재 합의한 Codex·Claude Code 1차 기능 범위에는 사내 파일럿을 막는 기능 누락이 없습니다. 남은 항목은
클라이언트별 실기기 확인, 인프라 운영 전제, 외부 백업과 장시간 표본입니다.

## 현재 운영 결정

### MCP 신원

MCP는 OAuth 대신 서버가 관찰한 사내 클라이언트 IP의 해시를 principal로 사용합니다.
이 결정은 다음 인프라 전제를 가집니다.

- 사용자 PC별 원본 IP가 동시에 고유함
- 프록시·VPN에서도 원본 IP가 보존됨
- 8000 포트와 `/mcp`가 사내망으로 제한됨
- IP 재할당 시점과 이전 사용자를 추적할 수 있음

검증 호스트는 `10.100.90.242/24`의 직접 연결이며 Uvicorn은
`--no-proxy-headers --host 0.0.0.0 --port 8000`으로 실행됩니다.
`TRUSTED_PROXY_CIDRS`와 `MCP_ALLOWED_CLIENT_CIDRS`는 현재 비어 있습니다.

### 웹 갤러리 연결

웹은 서명 쿠키 principal, MCP는 IP principal을 사용하므로 원본 소유권은 자동 병합하지
않습니다. 같은 IP의 사용자가 갤러리에서 한 번 `연결하기`를 누르면 웹이 해당 MCP owner의
이미지를 함께 조회합니다. 연결은 DB에 유지되고 owner를 이전하지 않으며 한 MCP workspace를
다른 웹 principal이 자동으로 가져갈 수 없습니다. 연결된 이미지는 웹에서 선택·휴지통
이동·복구할 수 있고 Game UI는 묶음 전체에 적용됩니다. 쇼케이스 공유는 계속 차단합니다.

서버 PC에서 `localhost`로 연 웹은 `127.0.0.1`, 사내 주소로 연결한 MCP는 LAN IP로
관찰되어 서로 다른 workspace가 됩니다. 실제로 이 두 owner가 분리 저장되는 것을 확인했고,
웹을 정식 사내 주소로 다시 열어 연결하자 해당 IP에서 만든 과거·신규 MCP 이미지가 모두
갤러리에 나타났습니다. 운영자와 사내 사용자는 웹과 MCP에 같은 canonical 사내 origin을
사용하고 `localhost`는 개발 전용으로 제한합니다.

### IP 재할당

현재 MCP owner는 IP만으로 결정되므로 같은 IP가 다른 사람에게 재할당되면 과거 workspace가
재사용될 수 있습니다. 전용 owner 세대 교체나 workspace 폐기 UI는 아직 구현되지 않았습니다.
인프라팀의 DHCP·퇴사·PC 교체 정책을 확인한 뒤 필요하면 다음 흐름을 구현합니다.

1. 기존 IP workspace를 retired 상태로 잠금
2. 웹 연결을 해제하고 사용자 자산은 보존 정책에 따라 보관 또는 삭제
3. 비용·감사 이력은 이전 owner에 보존
4. 같은 IP에 새 allocation generation과 새 owner를 발급

DB와 파일을 수동으로 일부만 지우는 방식은 사용하지 않습니다. 새 세대 owner가 구현되기
전에는 IP 재할당 사실을 확인한 운영자가 신규 사용을 허용하기 전에 별도 판단해야 합니다.

### 결과 표시

`get_generation_result`는 최대 768px WebP user-preview를 첫 `ImageContent`로 반환하고
원본 링크와 `presentation.required=true` 계약을 함께 제공합니다. 로컬 다운로드·이미지
보기 도구가 있는 Codex·Claude Code에는 원본을 세션용 PNG로 내려받아 실제로 연 뒤 답하도록
지시합니다. 다만 서버가 클라이언트 화면을 강제로 제어할 수는 없습니다.

Codex에서 로컬 PNG 다운로드와 이미지 보기로 썸네일을 표시한 표본은 통과했지만 새 세션이
후처리를 한 차례 생략한 사례도 있었습니다. 이를 반영한 0.8.0 응답 계약과 기존 작업의
비용 없는 재조회는 통과했습니다. 모든 클라이언트에서 네이티브 인라인 표시를 보장한다고
문서화하지 않으며, 원본 링크를 항상 유지합니다.

## 다음 확인 순서

1. 인프라팀에 IP 고유성, DHCP 예약, 퇴사·PC 교체 뒤 재할당 정책과 이력 보존을 확인
2. 완전 백업 목적지를 별도 볼륨 또는 NAS로 확정하고 예약 작업·복구 훈련 수행
3. actual cost 표본을 모아 모델·크기·품질별 보수적 사전 비용표 결정
4. 여러 사용자·장시간 운영에서 외부 API 동시성과 로컬 RMBG 단일 큐 관찰
5. 필요성이 확인되면 IP workspace retirement와 owner generation 기능 설계

See-Through와 ACE-Step의 MCP 공개, 일반 ChatGPT Chat 모드용 앱·플러그인, MCP 삭제·취소
도구와 MCP Apps UI는 현재 필수 범위가 아닙니다.

## 문서 역할

- `../README.md`: 설치·실행·접속·문서 진입점
- `PROJECT_OVERVIEW.md`: 현재 아키텍처, 신원과 데이터 흐름
- `OPERATIONS.md`: 배포, 백업, 신원·IP 운영, 장애 대응
- `mcp.md`: 공개 도구, 대화 정책, 클라이언트 설정과 결과 표시
- `MCP_CAPABILITY_CONTRACT.md`: provider-neutral 요청·디스패치 계약
- `asset-infrastructure.md`: 자산 카탈로그, 소유권, 수명주기와 백업
- `game-ui-elements-mvp.md`: Game UI 그리드·저장·검증 계약
- `../app/resources/refs/README.md`: 정적 mount 밖 서버 전용 레퍼런스

## 문서 유지 규칙

- 현재 구조를 설명하는 문서에는 날짜를 파일명에 넣지 않습니다.
- 시점별 실험 과정은 반복해서 붙이지 않고 이 파일의 기준선 또는 Git 이력으로 남깁니다.
- 환경 변수를 바꾸면 `.env.example`과 `OPERATIONS.md`를 함께 검토합니다.
- capability나 MCP 도구를 바꾸면 `PROJECT_OVERVIEW.md`, `mcp.md`,
  `MCP_CAPABILITY_CONTRACT.md`를 함께 검토합니다.
- 저장·소유권·백업을 바꾸면 `asset-infrastructure.md`와 `OPERATIONS.md`를 함께 검토합니다.
- 구현되지 않은 기능은 반드시 `계획`, `미검증` 또는 `선택 기능`으로 표시합니다.
