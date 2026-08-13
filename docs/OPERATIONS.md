# 운영 런북

> 최종 업데이트: 2026-08-13

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
  `*.secret`이 없음. 검토된 `outputs/global/characters` 번들만 예외
- `.env`에 관리자 인증이 있고, 직접 연결 또는 신뢰 프록시 중 실제 배포 경계와
  `TRUSTED_PROXY_CIDRS` 설정이 일치함
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

`run_server.bat`은 개발용 reload와 health 확인 후 브라우저 열기를 사용합니다.
`run_server_prod.bat`은 브라우저를 열지 않으며 실행 중인 콘솔이 서버 프로세스입니다.
두 batch는 `scripts/start_server.ps1`을 공유하며 다음을 자동으로 수행합니다.

- 기존 8000 포트의 LC AI Canvas가 정상이면 중복 실행 없이 종료
- 포트가 점유됐지만 health가 실패하면 소유 PID를 출력하고 시작 차단
- Uvicorn 출력을 UTC timestamp가 붙은 `logs/server-<mode>-*.log`에 보존
- 시작 오류 시 더블클릭 콘솔을 `pause`로 유지

자동화 환경에서 오류 pause를 끄려면 `LC_CANVAS_NO_PAUSE=1`을 설정합니다. 서버를
시작하지 않고 중복·포트 상태만 검사할 수도 있습니다.

```powershell
.\scripts\start_server.ps1 -Mode Production -CheckOnly -NoBrowser
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
6. 입력 이미지 업로드 및 참고 이미지 편집
7. Game UI 2×2 생성, 개별 결과, ZIP 다운로드
8. 필요 시 MCP capability 목록, 생성, job polling, 결과 조회

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

웹 업로드와 MCP 첨부는 같은 입력 계층을 사용합니다.

```dotenv
INPUTS_MAX_BYTES=10485760
INPUTS_MAX_PIXELS=40000000
```

PNG/JPEG/WEBP만 실제 디코딩하고 EXIF 방향을 반영한 뒤 PNG로 정규화합니다. 원본과
정규화 결과 모두 byte 제한을 적용하고, 디코딩 전후 픽셀 수를 제한합니다. 리버스
프록시의 request body limit도 base64 오버헤드를 고려해 이 값과 맞춥니다.

## MCP 네트워크 경계

- 인프라에서 `/mcp`를 회사 네트워크 요청에만 허용합니다.
- `TRUSTED_PROXY_CIDRS`에는 실제 신뢰 프록시만 넣습니다.
- 필요하면 `MCP_ALLOWED_CLIENT_CIDRS`로 애플리케이션 2차 허용 목록을 설정합니다.
- 잘못된 CIDR 정책은 MCP 요청을 503으로 차단합니다.
- OAuth가 추가되기 전에는 인터넷에 직접 공개하지 않습니다.

## 장애 대응

### 갤러리에 결과가 없음

1. `get_generation_job` 또는 작업 API의 완료 상태 확인
2. `asset_admin audit` 실행
3. `assets.storage_path`와 실제 파일 존재 확인
4. principal이 웹 서명 쿠키 또는 MCP IP와 일치하는지 확인

### DB 잠금

현재 SQLite는 WAL과 `busy_timeout`을 사용합니다. 반복되는 lock 오류가 있으면 동시
프로세스 수, 네트워크 드라이브 사용 여부, 장기 트랜잭션을 먼저 확인합니다. DB를
네트워크 공유 폴더에 두지 않는 것을 권장합니다.

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
