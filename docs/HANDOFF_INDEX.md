# 문서 인덱스

> 최종 업데이트: 2026-08-17

이 파일은 현재 유효한 문서의 역할과 우선순위를 설명합니다. 구현과 문서가 다르면
코드를 확인하고 같은 변경에서 문서도 함께 수정합니다.

## 최근 검증 체크포인트

현재 기능 구현 기준 커밋은 `793f36d`이며 2026-08-17에 다음을 확인했습니다.

- 프로젝트 가상환경의 전체 단위·통합 테스트 138개 통과
- 격리 Edge E2E에서 Game UI 4×4 생성, 16셀 분할, ZIP, 그룹 선택·삭제·복구,
  새로고침, 관리자 그룹 카드까지 통과
- Game UI 전용 422×180 배너 연결, 이미지 배너 스크림 투명도 0과 강제 저밝기 필터
  제거를 실제 Edge 계산 스타일로 확인
- 실서버 `/healthz` 정상, 기존 갤러리·원본·삭제·관리자 복구와 GPT Image 2 생성 정상
- MCP 0.7.0은 hosted 4개와 로컬 RMBG-2.0 배경 제거 1개를 공개하고 총 13개 도구 제공
- 동일 PC의 실제 웹 갤러리에서 한 번 클릭 연결 후 기존 MCP 생성 이미지 2개와 `MCP`
  표시가 나타나는 것을 확인
- read-only 운영 audit에서 자산 1,278개, active Game UI 그룹 5개,
  누락 파일·메타데이터·그룹 파일 0

현재 합의한 1차 기능 범위에는 운영을 막는 필수 누락이 없습니다. 생성·편집, Game UI,
캐릭터 시트, 스토리보드, RMBG, 계획·비용·IP 감사·큐·멱등성·자산 반환 기반을 구현하고
실제 호출했습니다. 남은 항목은 운영 표본, 배포 gate, 품질 조정 또는 선택 기능입니다.

Game UI 묶음은 자식 자산과 그룹을 한 SQLite 트랜잭션으로 등록하며 실패 파일을 보상
정리합니다. 웹 갤러리는 `preserve_groups=true`로 4·9·16셀 묶음을 페이지 사이에서
나누지 않고, 구형 자식 삭제·복구 요청도 서버에서 전체 그룹으로 승격합니다. 영구
비우기는 ZIP·원본 시트·master·파생본과 카탈로그 행을 함께 제거합니다. 실서버
GPT Image 2 2K/Medium 4×4 표본도 정상 결과를 확인했습니다.

Codex IDE 실클라이언트에서 기존 MCP 9개 도구를 모두 호출했습니다. 읽기, 첨부 중복 제거,
동일 키 재시도, 새 키 1K 반복 생성, 소유 이미지 참고 편집, Game UI low 2×2 생성,
job/result content와 자식 이미지 4개 조회가 통과했습니다. MCP IP 소유 출력은 기존 IP
소유권 검사를 통과한 뒤에만 브라우저용 beta gate를 우회하며, 실서버 그룹 ZIP도 쿠키 없이
다운로드해 22개 엔트리를 확인했습니다. 당시 가격표가 없는 사전 예상 비용이 0으로
표시되던 문제는 이후 `null`과 `cost_estimate_available=false`로 고쳤고, 완료 후 공급자가
보고한 actual cost는 IP·기능·모델별 관리자 통계에서 확인할 수 있습니다. 표본을 더 모아
모델별 보수적 사전 비용 추정 정책을 설정하는 일은 남아 있습니다.

이후 MCP 0.5.0에서 `create_character_sheet`와 `create_storyboard`를 추가했습니다. 실제
Streamable HTTP 클라이언트로 같은 캐릭터 참고 이미지를 사용해 1K/low 턴어라운드 3뷰,
표정 4개, 스토리보드 6컷을 생성했고 모두 exact count/grid, 소유 자산 저장, job/result
polling, MCP image content를 통과했습니다. provider actual cost는 순서대로 `$0.009739`,
`$0.011109`, `$0.010429`였습니다. 스토리보드 자동 gutter 제거는 이 표본에서
`separator_detection_failed` fallback이었으며 얇은 패널 구분선은 남았습니다.

MCP 0.6.0에서는 OpenRouter 기반 네 공개 capability에 공통 `plan_generation`을 적용했습니다.
모델·비율·크기·품질·개수·배경 모드 중 모호한 결정을 반환하고 plan ID를 발급하지 않으며,
사용자가 선택을 위임한 경우에만 권장값으로 준비된 계획을 만듭니다. 30분 plan ID는 호출자,
프롬프트, 참고 자산, 전체 옵션에 묶이고 계획과 다른 쓰기 호출을 큐 등록 전에 거절합니다.
운영 Streamable HTTP 실클라이언트에서 12개 도구, 모호 요청, 위임 추천, GPT Image 2 명시
계획, 계획 없는 쓰기 거절을 모두 확인했습니다. provider 생성은 호출하지 않아 추가 비용은
발생하지 않았습니다.

MCP 0.7.0에서는 `remove_background`를 추가했습니다. 호출자 소유 active image/input 한 장을
계획에 고정한 뒤 로컬 `RMBG2`/`RMBG-2.0` workflow로 제출하며 provider API 비용은 알려진
`0.0`으로 감사 기록합니다. See-Through와 ACE-Step은 장시간 로컬 workflow이므로 설정과
공개 도구 양쪽에서 비공개로 고정했습니다.

운영 Streamable HTTP에서 0.7.0 초기화, 13개 도구와 5개 공개 capability를 확인하고 검증용
input `e07d06ce58014136852f3cce94ec0058`로 실제 RMBG 작업을 두 번 실행했습니다. 첫 작업
`96c09f9834e64d0380e4a6ec1a67af47`은 약 4.6초, warm 재검증
`4e0619bfb85a4424ababeb6e430bce58`은 약 1.2초에 완료됐습니다. 투명 RGBA PNG와 MCP
text+image content, provider `comfyui`, model `RMBG-2.0`, 알려진 예상 비용 `0.0`,
누락 파일 0을 확인했습니다. 동일 plan·멱등성 키 재호출도 새 작업 없이 기존 job을 반환했습니다.

### 현재 IP 운영 전제

검증 호스트는 고정 사설 IPv4의 `/24` 사내망에서 리버스 프록시 없이
`0.0.0.0:8000`으로 직접 서비스하고, ComfyUI는 `127.0.0.1:8188`에만 수신합니다. Codex
MCP도 사내 주소의 Streamable HTTP endpoint를 사용하며, DB에서 로컬 MCP와 다른 PC의 웹
요청이 서로 다른 원본 IP로 기록되는 것을 확인했습니다. `TRUSTED_PROXY_CIDRS`와
`MCP_ALLOWED_CLIENT_CIDRS`는 현재 비어 있어 접근 경계는 사내망·호스트 방화벽에 의존합니다.

인프라팀은 사용자 PC별 원본 IP 고유성·재할당 이력, 프록시/VPN의 원본 IP 보존, 8000
포트의 사내망 제한을 책임지는 것으로 합의합니다. 이 전제가 유지되는 동안 별도 OAuth나
인증용 계정 pairing은 1차 범위에 포함하지 않습니다.

웹 쿠키와 MCP IP principal의 원본 소유권은 계속 분리하되, 같은 IP의 웹 사용자가 갤러리에서
한 번 명시적으로 연결할 수 있습니다. 서버가 현재 IP의 MCP principal을 직접 계산하며 입력한
대상 ID는 받지 않습니다. 연결 후 MCP 생성 이미지만 웹 갤러리에 읽기 중심으로 표시하고,
편집에는 웹 input 복사본을 사용합니다. 원본 owner는 바꾸지 않으며 해제해도 삭제되지 않습니다.
다른 웹 principal에 이미 연결된 workspace는 409로 차단하고 연결·충돌·해제를 DB에 감사합니다.
`MCP_WEB_LINK_ENABLED=false`로 신규 연결과 연결 조회 반영을 즉시 끌 수 있습니다.
실제 브라우저 확인에서는 갤러리의 연결 안내와 대상 이미지 2개가 정상 표시됐습니다. 자동
회귀 테스트는 DB 재개방 후 지속성, 같은 연결의 멱등성, 다른 쿠키의 takeover 차단, 편집용
웹 input 복사, 연결 해제 후 원본 보존까지 검사합니다.

전체 테스트는 138개 모두 통과합니다. 공식 실행기는 포트별 lock과 자식 프로세스 감독을
사용하고, 이미 보존하는 고유 `server-*.log`와 중복되는 `app.log` handler는 자식에서
비활성화합니다. 직접 실행 시에도 file handler는 지연 open하며 Windows 회전 잠금이 생기면
프로세스별 로그로 자동 전환해 `WinError 32` traceback 반복을 막습니다. 격리 launcher
스모크에서 startup·health, 공유 `app.log` 미변경, 로깅 오류 0, 종료 후 프로세스·lock 0을
확인했습니다. 운영 인스턴스도 같은 공식 launcher로 재기동한 직후 모든 health component가
정상이었고, 실행 중 포트 lock과 고유 production 로그가 생성됐습니다.

격리된 실제 ComfyUI에 RMBG 두 작업을 즉시 연속 제출한 결과 첫 작업 0.971초 동안 둘째는
queued였고, 둘째는 첫 작업 종료 0.036초 뒤 시작해 0.413초에 완료됐습니다. 실행 구간은
겹치지 않았고 MCP image content 2건, provider API actual cost `0.0` 기록 2건, 비용 미수집
0건을 확인했습니다. 임시 DB·outputs는 종료 시 제거됐습니다.

과거 `b1420ee`의 90개 테스트와 운영 hardening 당시 95개 테스트는 중간 이력입니다.
현재 회귀 기준은 위의 138개 테스트입니다. 자산 수치는 운영 중 생성·삭제·복구에 따라
변하는 스냅샷이며 성공 기준은 고정 숫자가 아니라 DB 무결성과 누락 수치 0입니다.

## 운영 hardening 진행 상태

2026-08-13 중간 체크포인트에서 다음 도구와 검사를 추가했고, 이후 변경은 현재 138개
회귀 테스트에 포함됐습니다.

- 당시 전체 단위·통합 테스트 95개 통과
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
