# 운영 런북

> 최종 업데이트: 2026-08-19

## 배포 전 확인

```powershell
.\venv\Scripts\python.exe -m unittest discover -s tests -v
.\venv\Scripts\python.exe -m app.asset_admin audit
git status --short
```

다음을 확인합니다.

- 테스트 성공
- `missing_files`, `missing_metadata`, `missing_group_files`가 모두 0
- 기능 커밋에 `db/app_data.db`, 런타임 `outputs/users`·`outputs/feed`, `backups`,
  `*.secret`이 없음
- `.env`에 관리자 인증이 있고, 직접 연결 또는 신뢰 프록시 중 실제 배포 경계와
  `TRUSTED_PROXY_CIDRS` 설정이 일치함
- 인프라팀이 MCP 사용자 PC별 원본 IP 고유성·재할당 이력, 프록시/VPN의 원본 IP 보존,
  8000 포트의 사내망 제한을 보장함. 허용 대역이 확정되면 선택적으로
  `MCP_ALLOWED_CLIENT_CIDRS`를 함께 설정
- `MCP_PUBLIC_BASE_URL`이 사내 사용자가 실제로 여는 canonical origin과 일치하고,
  온보딩·웹 갤러리·MCP 설정에 `localhost`가 섞이지 않음
- 퇴사·PC 교체 뒤 IP 재할당 정책과 LC AI Canvas 운영자 통보 절차가 확인됨. 재할당이
  현실적이면 owner generation 기능 전까지 신규 사용 허용 절차를 별도로 둠
- `INPUTS_MAX_BYTES`, `INPUTS_MAX_PIXELS`가 프록시 body limit과 일관됨

런타임 설정의 기준은 `.env` 또는 배포 환경의 secret 주입입니다. 루트의
`ipAdress.txt` 같은 호스트별 메모는 애플리케이션이 읽지 않으며 Git에 넣지 않습니다.
API 키를 별도 평문 파일에 보관하는 방식도 운영 설정이나 백업으로 간주하지 않습니다.

## 실행

개발:

```powershell
.\run_server.bat
```

사내 서버:

```powershell
.\run_server_prod.bat
```

운영 실행기는 `0.0.0.0:8000`에서 수신합니다. 외부 노출 여부는 애플리케이션이
아니라 인프라 방화벽과 리버스 프록시가 결정해야 합니다.

`127.0.0.1`은 서버 자체 health 진단과 개발에만 사용합니다. 사내 게시판, 온보딩과
MCP 클라이언트에는 `http://SERVER_IP:8000` 또는 인프라가 정한 공식 hostname만 배포합니다.
서버 PC에서도 MCP를 사내 주소로 등록했다면 웹 갤러리를 같은 origin으로 열어야 합니다.
`localhost`와 사내 IP를 섞으면 서로 다른 source IP와 브라우저 cookie host로 인식됩니다.

`run_server.bat`은 개발용 reload와 health 확인 후 브라우저 열기를 사용합니다.
`run_server_prod.bat`은 브라우저를 열지 않으며 실행 중인 콘솔이 서버 프로세스입니다.
두 batch는 `scripts/start_server.ps1`을 공유하며 다음을 자동으로 수행합니다.

- 기존 8000 포트의 LC AI Canvas가 정상이면 중복 실행 없이 종료
- 포트가 점유됐지만 health가 실패하면 소유 PID를 출력하고 시작 차단
- 포트별 `logs/server-<port>.lock`으로 동시에 시작되는 두 launcher를 원자적으로 차단
- launcher가 시작한 cmd·Python 자식 트리를 감독하고 종료 시 남은 자식을 정리
- Uvicorn 출력을 UTC timestamp가 붙은 `logs/server-<mode>-*.log`에 보존
- 공식 launcher에서는 중복 `LOG_TO_FILE` handler를 끄고 위 세션 로그를 단일 기준으로 사용
- 시작 오류 시 더블클릭 콘솔을 `pause`로 유지

자동화 환경에서 오류 pause를 끄려면 `LC_CANVAS_NO_PAUSE=1`을 설정합니다. 서버를
시작하지 않고 중복·포트 상태만 검사할 수도 있습니다.

```powershell
.\scripts\start_server.ps1 -Mode Production -CheckOnly -NoBrowser
```

별도 포트와 임시 DB·outputs에서 실제 시작·health·로그·프로세스 정리를 회귀 검사할 수
있습니다. 현재 8000번 운영 서버와 운영 데이터는 건드리지 않습니다.

```powershell
.\scripts\smoke_server_launcher.ps1
```

수동 진단은 다음 명령을 사용합니다.

```powershell
Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue
Invoke-RestMethod http://127.0.0.1:8000/healthz | ConvertTo-Json -Depth 5
```

이미 listener와 정상 health 응답이 있으면 실행기가 기존 서버 정보를 출력합니다.
비정상 점유일 때는 출력된 PID의 실행 파일과 명령행을 확인한 뒤에만 종료합니다.

```powershell
cd C:\Works\ComfyUI_FastAPI
.\run_server_prod.bat
```

기존 서버를 교체할 때는 먼저 관리자 화면에서 active job이 0인지 확인한 뒤 해당
listener의 PID만 종료합니다. 포트에 연결된 프로세스를 확인하지 않고 광범위하게 Python
프로세스를 종료하지 않습니다.

### 로컬 초기화 스크립트

`reset_local_data.bat`은 개발 환경을 완전히 다시 시작할 때만 쓰는 파괴적 도구입니다.
운영 서버나 복구 절차에서 실행하지 않습니다. 이 스크립트는 `db/app_data.db`와 WAL,
`outputs/users`를 삭제하므로 이미지·입력·오디오·Game UI 파일과 작업·피드·통제 등 DB
레코드를 잃습니다. `outputs/feed`와 `outputs/global` 파일을 일관된 복구 세트로 다루는
도구도 아닙니다. 실행이 꼭 필요하면 서버를 중지하고 외부 완전 백업을 검증한 뒤에만
명시적으로 `YES`를 입력합니다.

## 운영 DB Git 추적 해제 최초 배포

`db/app_data.db`를 Git index에서 제거한 커밋 `d1e23e0`은 일반 코드 배포와 다르게
취급합니다. 이 커밋을 아직 적용하지 않은 clone에서 최초로 받을 때 해당 호스트 DB가
삭제되거나 merge 충돌이 생길 수 있으므로 blind `git pull`을 하지 않습니다.

각 배포 호스트에서 커밋 적용 전에 다음 순서를 지킵니다.

1. 서버와 worker를 중지하고 active job이 없는지 확인합니다.
2. 외부 백업 볼륨에 DB+outputs+principal secret 완전 백업을 만들고 검증합니다.
3. `db/app_data.db`를 저장소 밖의 임시 안전 경로에도 복사하고 크기와 SHA-256을 기록합니다.
   원본을 이동하거나 삭제하지 않습니다.
4. 추적 해제 커밋을 적용합니다. 적용 중 modify/delete 충돌이 나면 자동 해결하지 않고
   운영 DB를 보존한 상태로 중단합니다.
5. 적용 후 `db/app_data.db`가 존재하고 적용 전과 hash가 같은지 확인합니다. 파일이
   사라졌다면 서버를 시작하지 말고 3번의 안전 복사본을 같은 경로에 복사합니다.
6. `git check-ignore db/app_data.db`가 성공하고 `git ls-files db/app_data.db`가 비어 있는지
   확인한 뒤 DB 무결성, `asset_admin audit`, 기존 갤러리 스모크를 수행합니다.

모든 배포 호스트가 이 최초 절차를 통과하기 전에는 추적 해제 커밋을 배포 완료로 보지
않습니다. 이후 배포부터 DB는 ignored 운영 파일로 남습니다.

## 상태 확인

서버 재시작 후 다음을 확인합니다.

1. `/healthz` 응답과 디스크 여유 공간
2. `/create`, `/feed`, `/admin` 접근
3. 기존 사용자의 갤러리 목록과 원본 열기
4. 타 사용자 쿠키로 같은 원본 URL 접근 시 404
5. 기본 이미지 생성과 결과 저장
6. 웹 multipart 입력 이미지 업로드와 MCP 직접 multipart 업로드 및 참고 이미지 편집
7. Game UI 웹 2×2·3×3·4×4 생성, 선택 수와 개별 결과 수 일치, ZIP 다운로드
8. 기존 2×2 Game UI 그룹이 갤러리에서 그대로 열리고 ZIP을 받을 수 있는지 확인
9. MCP 13개 도구와 5개 공개 생성 capability 목록, 고정 2×2 Game UI 생성,
   job polling, 결과 조회
10. 소유 input 한 장으로 RMBG 배경 제거, 투명 PNG와 `comfyui/RMBG-2.0/0.0` 감사 기록
11. 같은 PC에서 웹과 MCP를 동일한 canonical 사내 origin으로 열고 MCP 작업공간을 연결한
    뒤 과거·신규 이미지가 `MCP` 표시로 함께 조회되는지 확인
12. 연결된 MCP 이미지와 Game UI 묶음을 선택해 휴지통으로 이동·복구하고, 관계없는 웹
    principal의 같은 요청은 404인지 확인

Game UI의 코드·브라우저 경로는 운영 서버와 운영 데이터를 사용하지 않고 먼저 검사할 수
있습니다. Microsoft Edge가 설치된 Windows 호스트에서 다음 명령을 실행합니다.

```powershell
.\venv\Scripts\python.exe -m scripts.smoke_game_ui_browser
.\venv\Scripts\python.exe -m scripts.smoke_linked_mcp_gallery_browser
```

이 스모크는 임시 DB·outputs와 로컬 가짜 OpenRouter 응답을 사용해 4×4 요청, 16셀 분리,
크기별 다운로드, ZIP manifest, 묶음 보존 페이지네이션, 그룹 선택·삭제·복구, 새로고침 복원,
관리자 화면의 단일 그룹 카드와 Game UI 배너 적용을 검사하고 임시 데이터를 정리합니다.
배너는 실제 Edge 계산 스타일에서 전용 이미지 적용, 스크림 투명도 0, 강제 저밝기 필터
제거까지 확인합니다. 실제 GPT Image 2의 지시 준수율·경계 침범·소형
가독성은 검사하지 않으므로 배포 전 실제 3×3·4×4 표본 확인을 별도로 수행합니다.
2026-08-13 체크포인트에서는 GPT Image 2 2K/Medium 4×4 실서버 표본도 정상 결과를
확인했습니다. 모델·프롬프트·후처리가 바뀌면 이 표본 검사를 다시 수행합니다.

## 자산 마이그레이션과 감사

기존 파일을 이동하지 않고 등록 대상을 미리 확인합니다.

```powershell
.\venv\Scripts\python.exe -m app.asset_admin backfill --dry-run
```

실제 등록과 감사:

```powershell
.\venv\Scripts\python.exe -m app.asset_admin backfill
.\venv\Scripts\python.exe -m app.asset_admin audit
```

애플리케이션 시작 시 최초 백필이 완료되지 않았다면 자동 실행합니다. 완료 이후
시작에서는 누락된 신규 sidecar를 보수적으로 재등록하고 카탈로그를 감사합니다.

## 백업과 복구

SQLite 온라인 백업:

```powershell
.\venv\Scripts\python.exe -m app.asset_admin backup-db
```

이 명령은 DB만 보호하므로 재해 복구용 정기 작업에는 완전 백업을 사용합니다.

```powershell
.\scripts\backup_app_data.ps1 -DestinationRoot E:\LC-AI-Canvas-Backups
```

Windows 작업 스케줄러에서는 프로그램을 `powershell.exe`, 인수를 다음처럼 지정합니다.

```text
-NoProfile -ExecutionPolicy Bypass -File C:\Works\ComfyUI_FastAPI\scripts\backup_app_data.ps1 -DestinationRoot E:\LC-AI-Canvas-Backups
```

직접 입력하는 대신 검증된 작업 등록 도구를 사용할 수 있습니다. 예약 백업 경로는
프로젝트 밖의 외부 또는 별도 보호 위치여야 합니다.

```powershell
.\scripts\manage_backup_task.ps1 -Action Install `
  -DestinationRoot E:\LC-AI-Canvas-Backups `
  -DailyAt 03:00 -RetentionDays 30 -MinimumBundles 7
.\scripts\manage_backup_task.ps1 -Action Show
```

작업은 설치한 Windows 계정 컨텍스트로 등록됩니다. 설치 직후 한 번 수동 실행해 결과
코드 0과 새 번들 생성을 확인합니다.

```powershell
Start-ScheduledTask -TaskName "LC AI Canvas Complete Backup"
Get-ScheduledTaskInfo -TaskName "LC AI Canvas Complete Backup"
```

예약 제거는 데이터가 아니라 작업 정의만 제거합니다.

```powershell
.\scripts\manage_backup_task.ps1 -Action Remove
```

완전 백업 단위는 다음 세 가지입니다.

- `db/app_data.db`의 검증된 SQLite 백업
- 전체 `outputs` 디렉터리
- `db/principal_cookie.secret` 또는 같은 값을 공급하는 비밀 관리 시스템 secret

`backup-all`은 SQLite online backup을 먼저 만들고 `outputs`와 principal secret을 새
백업 세트에 복사합니다. 파일별 SHA-256 manifest, `PRAGMA integrity_check`, 자산·그룹
파일 정합성 검증이 모두 통과해야 최종 디렉터리 이름으로 승격됩니다. 원본 파일은
이동하지 않고 기존 백업도 덮어쓰지 않습니다. 같은 목적지의 중복 백업은 process mutex로
차단됩니다. `RetentionDays=0`이면 삭제하지 않으며, 보존 기간을 명시한 예약 작업만 새
백업 성공 후 인식 가능한 완전 백업을 최소 보존 개수 밖에서 정리합니다. 알 수 없거나
불완전한 디렉터리는 정리하지 않습니다. 생성·업로드·삭제가 동시에 일어나 정합성을
확보하지 못하면 백업을 실패시키므로, 반복 실패 시 생성 kill switch와 유지보수 창을
사용합니다.

`backup-all`은 API key와 관리자 암호가 있는 `.env` 전체를 복사하지 않습니다. 복구에
필요한 나머지 운영 설정은 승인된 비밀 관리 시스템 또는 별도의 암호화 백업으로
관리합니다.

기존 백업은 언제든 비파괴적으로 다시 검사할 수 있습니다.

```powershell
.\venv\Scripts\python.exe -m app.asset_admin verify-backup E:\LC-AI-Canvas-Backups\lc-ai-canvas-...
.\scripts\test_restore_backup.ps1 -BackupPath E:\LC-AI-Canvas-Backups\lc-ai-canvas-...
```

복구 훈련은 선택한 세트를 OS 임시 staging에 복사해 checksum, SQLite, 자산·그룹 경로,
복원된 principal secret의 서명 round-trip을 검사한 뒤 staging 복사본을 제거합니다.
운영 경로를 덮어쓰거나 바꾸지 않습니다. 실제 HTTP 기동과 브라우저 확인은 아래 수동
복구 절차의 별도 단계입니다. 임시 디스크에는 백업 세트 한 개를 복사할 여유 공간이
필요합니다.

### 복구 절차

1. 서버와 작업 worker를 중지하고 현재 `db`, `outputs`, principal secret을 별도 rollback
   위치에 보존합니다. 실행 중인 경로에 바로 덮어쓰지 않습니다.
2. 선택한 백업 세트에 `verify-backup`을 실행합니다.
3. 백업의 DB, `outputs`, principal secret을 격리된 staging 경로에 복사합니다.
4. staging 경로를 `JOB_DB_PATH`, `OUTPUT_DIR`, `PRINCIPAL_COOKIE_SECRET_FILE`로 지정한
   상태에서 `asset_admin audit`를 실행해 누락 수치가 모두 0인지 확인합니다.
5. 승인된 유지보수 창에서 세 항목을 한 세트로 운영 경로에 전환하고 `/healthz`, 기존
   갤러리, 원본 열기, 타 소유자 차단을 확인한 뒤 트래픽을 연결합니다.
6. 이상이 있으면 보존한 rollback 세트로 세 항목을 함께 되돌립니다.

principal secret을 다른 시점의 값으로 복원하면 기존 브라우저 쿠키가 모두 무효화됩니다.
복구 훈련은 운영 경로가 아닌 격리된 복사본에서 정기적으로 수행합니다.

## 쿠키 전환

초기에는 다음 설정을 사용합니다.

```dotenv
PRINCIPAL_IDENTITY_MODE=compat
ALLOW_LEGACY_ANON_HEADER=false
```

`compat`에서는 기존의 유효한 `anon_id` 쿠키를 한 번 받아 서명 쿠키로 승격합니다.
활성 사용자 전환 기간이 끝난 뒤 다음으로 바꿉니다.

```dotenv
PRINCIPAL_IDENTITY_MODE=enforced
```

전환 전에 principal secret의 백업을 확인합니다. 키를 잃거나 교체하면 기존 서명
쿠키를 검증할 수 없습니다.

서버는 새 principal 발급과 승격 시 `principal_identity_cookie_issued` 구조화 로그를
남기며 `identity_source`는 `legacy_cookie`, `new_principal`,
`invalid_signed_cookie`, `legacy_cookie_rejected` 중 하나입니다. `compat` 관찰 기간에는
파일 또는 중앙 로그 수집을 켜고 `legacy_cookie` 이벤트의 마지막 발생 시점과 지원
문의를 확인합니다. `legacy_cookie_rejected`는 enforced canary에서 기존 무서명 쿠키가
거부됐음을 뜻합니다.

현재 로그 범위, 마지막 legacy 승격, secret과 완전 백업 검증 상태를 한 번에 확인합니다.

```powershell
.\venv\Scripts\python.exe -m app.principal_admin readiness `
  --observation-days 14 --quiet-days 7 `
  --backup E:\LC-AI-Canvas-Backups\lc-ai-canvas-...
```

`ready_for_enforced=true`여도 비활성 사용자는 로그에 나타나지 않으므로 운영자 검토와
기존 사용자 갤러리 canary를 생략하지 않습니다. `--require-ready`는 조건 미충족 시
exit code 2를 반환해 배포 gate로 사용할 수 있습니다.

`enforced` 전환 조건은 다음과 같습니다.

- principal secret의 외부 백업과 복구 검증 완료
- 합의한 활성 사용자 관찰 기간 동안 `legacy_cookie` 승격이 더 이상 없거나 예외가 정리됨
- 기존 사용자 갤러리 스모크 테스트 완료
- 일부 트래픽 canary 후 `compat`으로 즉시 되돌릴 수 있는 배포 절차 확인

코드가 승격을 지원한다는 이유만으로 자동 전환하지 않습니다.

## 구형 폴더 스캔 fallback 제거 조건

현재 정상 애플리케이션 경로는 `AssetService` 카탈로그를 사용하고 폴더 스캔은 서비스가
구성되지 않은 경우에만 fallback으로 남아 있습니다. 다음 조건을 모두 만족한 뒤 별도
변경으로 제거합니다.

- 모든 실행기와 테스트 경로에서 `AssetService`가 항상 구성됨
- 운영 `asset_backfill` migration 완료
- 합의한 관찰 기간의 시작/reconcile 로그에서 등록 오류가 없고 정기 audit 누락이 0
- 기존 사용자 3종(image/input/audio) 목록과 카탈로그 조회 parity 확인
- 완전 백업 및 staging 복구 훈련 완료

먼저 실제 DB와 outputs에서 비파괴 parity 검사를 수행합니다.

```powershell
.\venv\Scripts\python.exe -m app.asset_admin catalog-canary
```

이 명령은 migration, DB↔파일 inventory, image/input/audio 조회 수, 누락 파일과
AssetService 미연결 시 fail-closed를 검사합니다. 기술 검사가 통과한 뒤 완전 백업과
격리 복구 훈련까지 성공했을 때 다음 설정으로 실서버 canary를 진행합니다.

```dotenv
ASSET_CATALOG_FALLBACK_ENABLED=false
```

이 설정에서 `AssetService`가 없는 저장·조회 경로는 즉시 실패합니다. 기본값 `true`에서는
fallback을 사용할 때 최초 operation별 `asset_catalog_filesystem_fallback` 경고를
남깁니다. 운영 canary와 전체 테스트가 통과한 뒤에만 폴더 순회 코드를 제거합니다.

## 입력 이미지 제한

웹 업로드와 MCP 직접 multipart 첨부는 같은 입력 계층을 사용합니다.

```dotenv
INPUTS_MAX_BYTES=10485760
INPUTS_MAX_PIXELS=40000000
```

PNG/JPEG/WEBP만 실제 디코딩하고 EXIF 방향을 반영한 뒤 PNG로 정규화합니다. 원본과
정규화 결과 모두 byte 제한을 적용하고, 디코딩 전후 픽셀 수를 제한합니다. MCP 입력은
`POST /api/v1/mcp/inputs/upload`의 multipart `file` 필드만 허용합니다. 리버스 프록시의
request body limit은 파일 제한에 multipart header 여유를 더해 설정합니다.

## MCP 네트워크 경계

- 인프라에서 `/mcp`와 `/api/v1/mcp/inputs/upload`를 회사 네트워크 요청에만 허용합니다.
- `TRUSTED_PROXY_CIDRS`에는 실제 신뢰 프록시만 넣습니다.
- 필요하면 `MCP_ALLOWED_CLIENT_CIDRS`로 애플리케이션 2차 허용 목록을 설정합니다.
- `MCP_WEB_LINK_ENABLED=true`는 같은 원본 IP에서만 웹↔MCP 갤러리 연결을 허용합니다.
  네트워크 신원 구조가 바뀌면 우선 `false`로 내려 연결 생성을 중지합니다.
- `MCP_PUBLIC_BASE_URL`에는 사내 사용자가 실제로 여는 공식 origin을 설정하고 운영
  안내에는 `localhost`를 사용하지 않습니다.
- 잘못된 CIDR 정책은 MCP 요청을 503으로 차단합니다.
- 인프라 협의에 따라 OAuth 전환 없이 확인된 IP의 해시를 principal과 감사 기준으로
  사용합니다. NAT·DHCP 제약을 수용하는 사내망 전용 운영이며 인터넷에 직접 공개하지 않습니다.

IP 기반 운영의 책임 경계는 다음과 같습니다.

- 인프라팀: 사용자 PC별 원본 IP 고유성, DHCP 예약·재할당 이력, PC 교체·퇴사 시 IP
  이력 관리, 프록시/VPN의 원본 IP 보존, 8000 포트와 `/mcp`의 사내망 제한
- 애플리케이션: 신뢰 프록시만 `X-Forwarded-For`에 사용, 서버가 확정한 IP의 해시를 MCP
  principal로 사용, IP·기능·모델별 비용 감사, 다른 MCP IP 자산 접근 차단
- 운영자: 네트워크 변경 후 여러 PC 요청이 관리자 비용 화면에서 서로 다른 IP로 기록되는지
  확인하고, 하나의 IP로 합쳐지면 MCP 확대 전에 프록시/NAT 구성을 수정. 서버 PC에서도
  웹과 MCP에 같은 canonical 사내 origin을 사용

이 조건을 인프라가 보장하는 동안 별도 OAuth나 인증용 계정 pairing은 현재 1차 범위에 필요하지
않습니다. `MCP_ALLOWED_CLIENT_CIDRS`는 방화벽을 대체하지 않는 선택적 2차 방어입니다.

2026-08-17 검증 호스트는 고정 사설 IPv4 `/24`, 직접 연결, Uvicorn
`0.0.0.0:8000`, ComfyUI `127.0.0.1:8188` 구조입니다. 리버스 프록시/VPN 프로세스는 없고
로컬 MCP와 다른 PC의 웹 요청이 DB에서 서로 다른 원본 IP로 관찰됐습니다. 검증 호스트의
`TRUSTED_PROXY_CIDRS`와 `MCP_ALLOWED_CLIENT_CIDRS`는 비어 있으므로 네트워크 구조가 바뀌면
이 스냅샷과 신뢰 경계를 다시 확인합니다.

서버 PC에서 `localhost`로 연 웹은 `127.0.0.1` owner에, 사내 주소로 연결한 Codex MCP는
LAN IP owner에 저장되는 것을 확인했습니다. 웹을 사내 주소로 다시 열어 연결하자 해당
LAN IP의 과거·신규 MCP 이미지가 정상 표시됐습니다. 이는 데이터 손실이 아니라 의도한
source-IP·cookie-host 분리입니다. 일반 사내 사용자는 원격 PC에서 공식 주소로 직접
접속하므로 웹과 MCP가 같은 사용자 PC의 원본 IP로 보이는 것이 정상입니다.

### IP 재할당 운영

현재 MCP owner는 source IP의 결정적 해시이므로 퇴사·PC 교체 뒤 같은 IP를 다른 사람에게
재할당하면 이전 workspace가 다시 선택될 수 있습니다. 브라우저 연결 takeover 차단만으로는
MCP 자체의 과거 자산 조회를 막을 수 없습니다.

인프라팀에는 다음을 확인합니다.

- 사용자 PC별 IP가 고정 또는 DHCP 예약인지
- 퇴사·PC 교체 뒤 IP를 재사용하는지와 재사용 대기 기간
- 이전 사용자, IP와 할당 시작·종료 시각의 이력을 얼마나 보존하는지
- 재할당 전에 LC AI Canvas 운영자에게 통보하거나 해당 IP의 MCP 접근을 잠글 수 있는지
- VPN·프록시·VDI가 여러 사용자를 하나의 source IP로 합치지 않는지

전용 운영 기능이 구현되기 전에는 재할당 사실을 확인한 IP를 새 사용자가 즉시 MCP에
사용하게 두지 않습니다. 서버를 정지하거나 DB·파일을 수동으로 일부 삭제하지 말고 먼저
완전 백업과 영향 범위를 확인합니다. 단순 정리는 같은 결정적 owner ID를 다시 만들고
비용·감사·링크·백업 이력을 불일치시킬 수 있습니다.

재할당이 실제 운영에서 발생하면 다음 기능을 별도 변경으로 구현합니다.

1. 기존 IP workspace를 retired·접근 차단
2. 웹 연결 해제와 사용자 자산의 보관·삭제 정책 적용
3. 비용·감사 이력은 이전 owner에 유지
4. 같은 IP에 새 allocation generation과 새 owner 발급
5. dry-run 대상 수, 완전 백업, 실행 결과와 감사 이벤트 제공

현재 관리자 화면에는 이 전체 절차를 한 번에 수행하는 기능이 없습니다.

초기에는 생성량을 제한하지 않으므로 `GENERATION_DAILY_REQUEST_LIMIT`,
`GENERATION_DAILY_COST_LIMIT_USD`, `GENERATION_COST_CONFIRMATION_THRESHOLD_USD`를 모두
`0`으로 유지합니다. 이는 무제한/비활성을 뜻합니다. `GENERATION_COST_ESTIMATES_JSON`은
차단 여부와 별개로 제출 응답에 정직한 보수적 예상 비용을 표시하는 용도이며, 완료 후
provider actual cost가 별도로 기록됩니다.

가격표에 일치하는 항목이 없으면 제출 응답은 `estimated_cost_usd=null`과
`cost_estimate_available=false`를 반환합니다. 이는 무료 또는 0달러가 아니라 사전 비용을
알 수 없다는 뜻입니다. 명시적으로 등록한 0달러 가격만 알려진 0으로 취급합니다. 비용 한도나
비용 확인 임계값을 0보다 크게 켤 때 해당 요청의 추정값이 없으면 안전하게 제출을 거절하므로,
먼저 실제 사용하는 모델·크기·품질 가격표를 채워야 합니다.

예외적으로 `resolved_provider=comfyui`인 로컬 workflow는 외부 provider API 비용이 없으므로
가격표와 무관하게 알려진 `0.0`을 반환합니다. 이는 로컬 GPU·전력·인프라 자원까지 무료라는
뜻은 아닙니다.

### IP별 비용 통계

관리자 `/admin`의 `사용·비용 통계` 탭은 선택 기간의 실제 비용을 IP·기능·모델별로
보여줍니다. IP는 화면에서 기본 마스킹하고 서버가 확정한 원본 IP로 필터링합니다. 같은
IP에서 여러 웹 쿠키 principal이 사용돼도 IP 비용은 한 행으로 합산합니다.

- API: `GET /api/v1/admin/generation-controls/cost-report`
- 필터: `days`, `client_ip`, `capability`, `model`, `limit`
- `actual_cost_record_count=0`: 실제 비용 합계가 0달러라는 뜻이 아니라 아직 수집값이 없음
- `missing_actual_cost_count`: 완료됐지만 provider actual cost가 기록되지 않은 요청 수
- `unknown_estimate_count`: 가격표가 없어 사전 비용을 알 수 없었던 요청 수

이 통계는 IP를 사람 단위 신원으로 추정하지 않습니다. NAT에서는 여러 사용자가 합쳐지고,
DHCP 변경 시 같은 사용자가 나뉠 수 있으므로 내부 비용 관찰과 이상 탐지용으로 사용합니다.
같은 IP가 다른 사용자에게 재할당됐다면 전체 기간 합계를 한 사람의 비용으로 보지 말고
인프라의 할당 시작·종료 시각에 맞춰 기간을 나눠 해석합니다.
완료된 ComfyUI 로컬 작업은 외부 provider API actual cost가 알려진 `0.0`이므로 미수집으로
분류하지 않습니다. 이는 GPU·전력·인프라 원가가 0이라는 뜻은 아닙니다.

### VS Code Codex 연결 점검

검증 워크스테이션에서는 Codex 공유 설정에 `lc_ai_canvas` Streamable HTTP endpoint가
등록되어 있고 2026-08-17 MCP 초기화 HTTP 200을 확인했습니다. 설정과 서버 상태는 다음
명령으로 확인합니다.

```powershell
codex mcp get lc_ai_canvas
codex mcp list
Invoke-RestMethod http://SERVER_IP:8000/healthz
```

서버를 먼저 실행한 뒤 VS Code 명령 팔레트에서 `Developer: Reload Window`를 실행합니다.
기존 대화가 MCP 도구를 새로 읽지 못하면 새 Codex 대화를 열고
`list_generation_capabilities`부터 호출합니다. MCP 0.8.0은 RMBG 배경 제거를 포함해 13개 도구와
5개 공개 생성 capability를 제공합니다. Codex에서는 읽기, 직접 첨부, 멱등성 재시도,
기본 생성·참고 편집, Game UI 2×2, 캐릭터 턴어라운드 3뷰, 표정 4개, 스토리보드 6컷,
RMBG 반복 생성, job/result polling, MCP image content와 소유 그룹 ZIP 다운로드를
실클라이언트로 확인했습니다.

Claude Code 사내 계정에서도 multipart 직접 업로드와 GPT Image 2 1K 연속 편집 두 건을
확인했습니다. MCP 0.8.0의 모든 공개 생성 쓰기는 먼저 `plan_generation`을 호출합니다. hosted 모호 요청은
`missing_decisions`를 사용자에게 한 번에 질문하고, 사용자가 선택을 위임한 경우에만
`selection_mode=recommend`를 사용합니다. 준비된 plan ID는 30분 동안 메모리에 유지되므로
서버 재시작이나 만료 후에는 다시 계획해야 합니다. plan ID·프롬프트·참고 자산·옵션이
일치하지 않으면 큐 등록 전에 거절됩니다. 계획 호출과 이 거절 경로는 provider 비용을
발생시키지 않습니다.

`remove_background`는 소유한 active image/input 한 장만 받고 `RMBG2`/`RMBG-2.0`으로
고정됩니다. provider API 비용은 `0.0`으로 기록되지만 로컬 단일 ComfyUI 큐와 GPU를
사용합니다. See-Through와 ACE-Step은 무거운 로컬 workflow이므로 MCP에 노출하지 않습니다.

실제 ComfyUI를 사용하되 DB와 outputs는 임시 경로로 격리해 단일 큐를 확인할 수 있습니다.
두 RMBG 작업을 즉시 연속 제출하고, 둘째가 queued 상태였다가 첫째 종료 후 시작하는지,
MCP image content 두 건과 provider API actual cost `0.0` 두 건이 기록되는지 검사합니다.

```powershell
.\venv\Scripts\python.exe -m scripts.smoke_rmbg_queue
```

MCP는 IP principal, 웹은 서명 쿠키 principal을 사용하며 원본 소유권은 자동으로 합치지
않습니다. 같은 PC의 웹 갤러리는 MCP 생성 이미지를 발견하면 한 번 클릭 연결을 제안합니다.
연결 후에도 MCP 목록에 웹 자산이 역으로 나타나지는 않으므로 첫 MCP 자산 목록이 비어 있어도
연결 오류로 판단하지 않습니다.

### 웹 갤러리에서 MCP 작업 공간 연결

1. MCP로 이미지 한 장 이상을 만든 동일 PC에서 MCP 설정과 같은 canonical 사내 origin의
   `/create`를 엽니다. 서버 PC에서도 `localhost`를 사용하지 않습니다.
2. 갤러리의 “이 PC에서 만든 AI 이미지” 안내에서 `연결하기`를 누릅니다.
3. 생성 이미지에 `MCP` 배지가 표시되고 재시작 후에도 남는지 확인합니다.
4. 선택 모드에서 MCP 이미지가 체크되고 선택 삭제하면 active 목록에서 빠지는지 확인합니다.
   Game UI는 한 child 선택이나 `묶음 삭제` 모두 전체 묶음을 휴지통으로 이동해야 합니다.
5. 복구 API 또는 관리자 휴지통에서 복원한 뒤 같은 MCP owner로 다시 나타나는지 확인합니다.
6. MCP 이미지를 편집에 쓰면 웹 input 복사본이 생기는지 확인합니다.
7. 쇼케이스 공유 버튼은 MCP 이미지에 나타나지 않는지 확인합니다.
8. `연결 해제` 후 웹 목록에서만 빠지고 MCP 원본과 audit 누락이 없는지 확인합니다.

2026-08-17 실제 동일 PC에서 `localhost`와 사내 IP의 owner 분리를 먼저 확인한 뒤,
canonical 사내 주소에서 1~3단계를 수행해 해당 IP의 과거·신규 MCP 이미지가 함께
표시되는 것을 확인했습니다. 연결 자산의 선택·휴지통 이동·복구와 MCP owner 보존은 격리
Edge E2E로, 나머지 단계와 연결 지속성·멱등성·충돌 차단은 자동 회귀 테스트로 확인했습니다.

API는 `GET|POST|DELETE /api/v1/principal-links/mcp`입니다. 대상 principal은 입력값을 받지
않고 현재 요청의 검증된 IP에서 계산합니다. `409 mcp_workspace_already_linked`는 같은 IP가
다른 웹 쿠키에 이미 연결된 상태이므로 자동 이전하지 말고 쿠키 초기화·PC 교체·IP 재할당
이력을 확인합니다. 링크와 이벤트는 완전 DB 백업에 포함되는 `principal_links`,
`principal_link_events`에 저장됩니다.

## 장애 대응

### 참고 이미지 업로드가 오래 멈춤

1. 최신 도구 목록에 `prepare_input_image_upload`이 있고 `create_input_image_asset`은 없는지
   확인합니다. 이전 도구가 보이면 서버와 클라이언트를 재시작하고 새 대화를 엽니다.
2. Claude Code·Codex는 `prepare_input_image_upload`의 URL에 로컬 파일을 multipart `file`
   필드로 직접 전송해야 합니다. Base64 변환이나 이미지 문자열 도구 인자를 사용하지 않습니다.
3. 서버의 `assets`에 새 `kind=input` 행이 없으면 생성 큐 이전의 전송 문제입니다. 이 상태는
   provider 호출 전이라 이미지 생성 비용이 발생하지 않습니다.
4. 업로드는 완료됐지만 Job이 없으면 반환된 `asset_id`로 `plan_generation`부터 다시
   진행합니다. 이미 등록된 파일을 다시 변환하거나 재업로드하지 않습니다.

### 갤러리에 결과가 없음

1. `get_generation_job` 또는 작업 API의 완료 상태 확인
2. 웹 주소와 MCP 등록 주소가 같은 canonical 사내 origin인지 확인. 서버 PC의
   `localhost`와 사내 IP는 다른 owner이므로 주소를 섞지 않음
3. `GET /api/v1/principal-links/mcp`에서 현재 웹 cookie와 MCP workspace 연결 상태 확인
4. `asset_admin audit` 실행
5. `assets.storage_path`와 실제 파일 존재 확인
6. `generation_control_requests.client_ip`, `assets.owner_id`, `principal_links`를 대조해
   웹 서명 cookie와 MCP IP principal의 범위가 일치하는지 확인

### MCP 생성은 완료됐지만 채팅에 썸네일이 없음

1. `get_generation_result`가 `image,text`, `presentation.required=true`와 원본 링크를
   반환했는지 확인합니다.
2. 도구 출력에 이미지가 보였다는 사실을 최종 사용자 표시로 간주하지 않습니다.
3. 로컬 Codex·Claude Code가 다운로드·이미지 보기 도구를 제공하면 원본을 세션용 PNG로
   내려받아 실제로 열고, 새 이미지를 생성하지 않습니다.
4. 네이티브 표시가 불가능하면 이를 명시하고 LC AI Canvas 원본 링크를 제공합니다.
5. 내부 HTTP URL의 Markdown inline image가 차단돼도 직접 링크 접근이 된다면 생성·저장
   실패가 아니라 클라이언트 렌더링 제한일 수 있습니다.

서버는 경량 user-preview와 지침을 제공하지만 클라이언트의 최종 렌더링을 강제할 수 없습니다.
HTTPS 전환이나 owner 검사를 약화하는 방식으로 우회하지 않습니다.

### DB 잠금

현재 SQLite는 WAL과 `busy_timeout`을 사용합니다. 반복되는 lock 오류가 있으면 동시
프로세스 수, 네트워크 드라이브 사용 여부, 장기 트랜잭션을 먼저 확인합니다. DB를
네트워크 공유 폴더에 두지 않는 것을 권장합니다.

### Windows 파일 로그 회전 경고

공식 실행기는 모든 콘솔 로그를 고유한 `server-<mode>-<timestamp>.log`에 보존하고 자식
프로세스의 중복 `LOG_TO_FILE`을 끕니다. 직접 Uvicorn을 실행해 여러 Python 프로세스가 같은
`LOG_FILE_PATH`를 잡더라도 handler는 파일을 실제 기록할 때까지 열지 않으며, Windows 회전
잠금이 발생하면 긴 `Logging error` traceback 대신 해당 프로세스 전용
`app.pid-<pid>.log`로 한 번만 안내하고 계속 기록합니다.

`smoke_server_launcher.ps1`에서 `.env` 상당의 `LOG_TO_FILE=true` 조건으로도 공유
`app.log` 미변경, startup 완료, `WinError 32` 없음, 종료 후 잔류 프로세스·lock 0을
확인했습니다. 외부 수집기가 필요해지는 다중 worker 배포에서는 stdout 수집을 단일 기준으로
유지하고 여러 worker가 하나의 회전 파일을 직접 쓰게 하지 않습니다.

### OpenRouter 오류

- 401/403: API 키와 권한
- 402: 크레딧
- 429: 공급자 rate limit 또는 사내 한도
- timeout: `GPT_IMAGE_2_TIMEOUT_SECONDS`와 `OPENROUTER_JOB_TIMEOUT_SECONDS`
- ZDR 경로 없음: 모델·공급자의 데이터 정책과 `OPENROUTER_ZDR`

### 즉시 생성 중지

전체 생성:

```dotenv
GENERATION_ENABLED=false
```

MCP만 중지:

```dotenv
MCP_GENERATION_ENABLED=false
```

환경 kill switch는 관리자 DB 설정으로 다시 켤 수 없습니다.
