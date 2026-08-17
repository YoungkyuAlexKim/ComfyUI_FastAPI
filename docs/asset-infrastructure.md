# 자산 인프라

> 최종 업데이트: 2026-08-17
>
> 상태: 운영 데이터 백필 완료, 호환 전환 중

## 기준 구조

파일시스템은 바이트를 저장하고 SQLite는 소유권, 종류, 상태, 검색 경로의 기준
카탈로그입니다. 웹과 MCP 자산 도구는 폴더를 직접 순회하지 않고
`AssetService`를 사용합니다.

주요 테이블:

- `assets`: 이미지, 입력 이미지, 오디오
- `asset_groups`: Game UI 그룹
- `schema_migrations`: 카탈로그와 백필 버전
- `principal_links`, `principal_link_events`: 웹↔MCP 갤러리 연결과 감사 이력

저장 경로는 `OUTPUT_DIR` 기준 상대 경로로 기록합니다. 기존 파일은 백필 중 이동하거나
이름을 바꾸지 않습니다.

신규 Game UI 묶음은 파일·manifest·ZIP을 먼저 준비하고 자식 이미지 레코드와 그룹
레코드를 한 SQLite 트랜잭션으로 등록합니다. 준비나 등록이 실패하면 해당 요청에서 만든
신규 파일만 보상 정리해 부분 묶음이 카탈로그에 남지 않도록 합니다.

## 현재 마이그레이션 결과

2026-08-13 기능 구현 및 실서버 스모크 체크포인트에서 다음을 검증했습니다.

- 자산 1,265개
- Game UI 그룹 5개
- migration marker `asset_backfill=1`, `asset_catalog=2`
- 손상 JSON 0
- 누락 원본 0
- 누락 메타데이터 0
- 누락 그룹 파일 0
- 기존 폴더 조회와 카탈로그 조회 70명 × 3종 비교 불일치 0

이 수치는 체크포인트 기록이며 운영 중 생성·삭제·복구에 따라 변합니다. 현재 값은 다음 명령으로
확인합니다.

```powershell
.\venv\Scripts\python.exe -m app.asset_admin audit
```

가장 최근인 2026-08-17 read-only 재감사 스냅샷은 자산 1,278개, active Game UI 그룹 5개이며
`missing_files`, `missing_metadata`, `missing_group_files`가 모두 0입니다. 이전 스냅샷과의
개수 차이는 운영 중 생성·삭제·복구에 따라 달라질 수 있으므로 고정 개수보다 누락 0과
카탈로그 무결성을 성공 기준으로 사용합니다.

## 백필과 재조정

미리보기:

```powershell
.\venv\Scripts\python.exe -m app.asset_admin backfill --dry-run
```

등록:

```powershell
.\venv\Scripts\python.exe -m app.asset_admin backfill
```

최초 애플리케이션 시작은 백필 migration marker가 없으면 전체 백필을 실행합니다.
이후 시작은 카탈로그에 없는 legacy sidecar를 재조정하고 감사합니다. 백필은 등록 오류가
없을 때만 완료 marker를 기록합니다.

## 저장과 상태 변경

- 원본, JSON, 그룹 ZIP은 임시 sibling 파일에 기록 후 `os.replace`로 확정합니다.
- 이미지·썸네일·메타데이터와 DB는 가능한 범위의 보상 로직을 사용합니다.
- 상태 변경은 sidecar와 카탈로그를 함께 갱신하고 DB 실패 시 sidecar를 되돌립니다.
- Game UI는 자식 하나의 상태 변경 요청도 전체 묶음으로 승격하고, 모든 자식·manifest·
  `asset_groups` 상태를 한 SQLite 트랜잭션으로 전환합니다.
- 사용자·관리자 갤러리는 Game UI를 하나의 선택 및 상태 변경 단위로 취급합니다.
- Game UI 휴지통 purge는 그룹 디렉터리의 ZIP·원본 시트·master·파생본을 제거한 뒤
  자식과 그룹 카탈로그 행을 한 트랜잭션으로 삭제합니다. 일반 자산 purge는 모든 대상
  파일 삭제 후에만 카탈로그 행을 삭제합니다.
- 피드 게시 DB 실패 시 방금 복사한 파일을 정리합니다.
- 브라우저/MCP 입력 이미지는 공통 검증 계층에서 실제 디코딩, byte·pixel 제한, EXIF
  방향 보정, PNG 정규화를 거친 뒤 저장합니다.
- 신규 입력 자산은 카탈로그 등록이 실패하면 방금 쓴 원본·썸네일·sidecar를 보상 삭제합니다.
- MCP 첨부 재시도는 소유자+정규화 SHA-256 범위의 기존 active 입력을 재사용합니다.

파일시스템과 SQLite를 하나의 ACID 트랜잭션으로 묶을 수는 없으므로 정기 audit와 백업은
여전히 필요합니다.

## 접근 경계

- principal ID는 영문·숫자·`_`·`-`만 허용하고 모든 사용자 경로에서 재검증합니다.
- `OUTPUT_DIR` 또는 사용자 root를 벗어나는 경로는 거부합니다.
- `/api/v1/assets/{asset_id}/content|thumbnail`은 소유자와 active 상태를 확인합니다.
- 기존 `/outputs/users/...` URL은 같은 owner 또는 명시적으로 연결된 웹 principal만 접근할
  수 있으며, 관계없는 principal에는 404를 반환합니다.
- 사용자 및 피드 JSON sidecar는 정적 URL로 제공하지 않습니다.
- 공개 피드 이미지는 사용자 개인 갤러리와 별도의 복사본입니다.

웹 서명 쿠키 principal과 MCP IP principal은 서로 다른 원본 소유권 공간입니다. 자동 병합은
하지 않지만 `MCP_WEB_LINK_ENABLED=true`이면 같은 원본 IP의 웹 사용자가 갤러리 안내에서
한 번 명시적으로 연결할 수 있습니다. 연결 관계는 SQLite `principal_links`에 영구 저장되고
연결·재확인·충돌·해제는 `principal_link_events`에 기록됩니다.

연결 후 웹의 생성 이미지 갤러리는 웹 owner와 연결된 MCP owner를 시간순으로 함께 조회하되
각 catalog row와 파일의 원래 owner는 바꾸지 않습니다. MCP 이미지는 `MCP`로 표시되고 웹에서
직접 삭제하거나 쇼케이스에 공유하지 않습니다. 편집에 사용하면 웹 input으로 복사해 이후
작업을 분리합니다. 연결을 해제하면 목록에서만 빠지고 MCP 원본은 삭제되지 않습니다. 한 MCP
workspace는 한 웹 principal에만 연결할 수 있어 쿠키가 다른 사용자의 자동 takeover를 막습니다.

2026-08-17 실제 동일 PC 웹 갤러리에서 연결 안내를 누른 뒤 MCP 생성 이미지 2개와 `MCP`
표시가 나타나는 것을 확인했습니다. 자동 회귀는 DB 재개방 후 지속성, 멱등 연결, 충돌 차단,
웹 input 복사와 연결 해제 후 원본 보존을 검사합니다.

## 브라우저 principal 전환

기존 사용자는 `anon_id` 폴더와 ID를 그대로 유지합니다. `compat` 모드에서 유효한 기존
쿠키를 받아 HMAC 서명 HTTP-only `lc_principal` 쿠키로 자동 승격합니다. 원시
`X-Anon-Id` fallback은 기본적으로 꺼져 있습니다.

```dotenv
PRINCIPAL_IDENTITY_MODE=compat
ALLOW_LEGACY_ANON_HEADER=false
```

활성 사용자 전환을 확인한 뒤 `enforced`로 변경합니다. 웹 갤러리의 사람 식별을 IP로
바꾸지 않습니다. IP는 감사와 MCP의 현재 내부망 principal에만 사용합니다.

단일 호스트는 `db/principal_cookie.secret`을 자동 생성할 수 있습니다. 이 파일을
백업해야 하며 Git에는 넣지 않습니다. 다중 인스턴스는 모든 호스트에 같은
`PRINCIPAL_COOKIE_SECRET`을 비밀 관리 시스템으로 공급합니다.

## 백업

```powershell
.\venv\Scripts\python.exe -m app.asset_admin backup-db
```

이 명령은 SQLite online backup API와 무결성 검사를 사용하지만 미디어는 복사하지
않습니다. 완전 백업은 다음 명령으로 DB, 전체 `outputs`, principal secret, checksum
manifest를 하나의 검증된 세트로 만듭니다.

```powershell
.\venv\Scripts\python.exe -m app.asset_admin backup-all --destination-root E:\LC-AI-Canvas-Backups
.\scripts\test_restore_backup.ps1 -BackupPath E:\LC-AI-Canvas-Backups\lc-ai-canvas-...
```

운영 DB와 WAL sidecar는 Git ignore 대상이며 운영 파일을 그대로 둔 채 index 추적만
해제합니다. 자세한 예약 실행과 격리 복구 절차는 `OPERATIONS.md`를 따릅니다.

## 남은 전환 작업

- `principal_admin readiness`로 활성 사용자 승격의 quiet window와 검증 백업을 확인한 뒤
  `enforced` 전환
- `manage_backup_task.ps1`로 외부 저장소를 지정하고 `restore-drill`까지 성공시킴
- 검증 호스트의 `ASSET_CATALOG_FALLBACK_ENABLED=false` canary는 통과했습니다. 외부
  완전 백업·복구 gate와 관찰 기간을 마친 뒤 구형 폴더 스캔 코드를 별도 변경으로 제거
- UI가 소유권 확인 자산 endpoint를 기본 URL로 사용하도록 점진 전환
