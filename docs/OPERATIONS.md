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

`run_server.bat`은 개발용 reload와 브라우저 자동 열기를 사용합니다.
`run_server_prod.bat`은 브라우저를 열지 않으며 실행 중인 콘솔이 서버 프로세스입니다.
시작 전에 다음을 확인합니다.

```powershell
Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue
Invoke-RestMethod http://127.0.0.1:8000/healthz | ConvertTo-Json -Depth 5
```

이미 listener와 정상 health 응답이 있으면 서버가 실행 중이므로 실행 파일을 다시 열지
않습니다. 두 번째 Uvicorn은 같은 포트를 bind하지 못해 더블클릭 콘솔이 바로 닫힐 수
있습니다. 시작 오류를 확인할 때는 기존 PowerShell에서 실행해 출력을 보존합니다.

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

완전 백업 단위는 다음 세 가지입니다.

- `db/app_data.db`의 검증된 SQLite 백업
- 전체 `outputs` 디렉터리
- `db/principal_cookie.secret` 또는 같은 값을 공급하는 비밀 관리 시스템 secret

`backup-all`은 SQLite online backup을 먼저 만들고 `outputs`와 principal secret을 새
백업 세트에 복사합니다. 파일별 SHA-256 manifest, `PRAGMA integrity_check`, 자산·그룹
파일 정합성 검증이 모두 통과해야 최종 디렉터리 이름으로 승격됩니다. 원본 파일은
이동하지 않고 기존 백업도 덮어쓰거나 자동 삭제하지 않습니다. 생성·업로드·삭제가
동시에 일어나 정합성을 확보하지 못하면 백업을 실패시키므로, 반복 실패 시 생성
kill switch와 유지보수 창을 사용합니다.

`backup-all`은 API key와 관리자 암호가 있는 `.env` 전체를 복사하지 않습니다. 복구에
필요한 나머지 운영 설정은 승인된 비밀 관리 시스템 또는 별도의 암호화 백업으로
관리합니다.

기존 백업은 언제든 비파괴적으로 다시 검사할 수 있습니다.

```powershell
.\venv\Scripts\python.exe -m app.asset_admin verify-backup E:\LC-AI-Canvas-Backups\lc-ai-canvas-...
```

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

조건을 점검하는 canary에서는 코드를 제거하기 전에 다음 설정으로 서버를 실행합니다.

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
