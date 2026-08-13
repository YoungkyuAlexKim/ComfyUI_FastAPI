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
- 기능 커밋에 `db/app_data.db`, `outputs`, `backups`, `*.secret`이 없음
- `.env`에 관리자 인증과 사내망 프록시 설정이 존재함

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

완전한 백업 단위는 다음 세 가지입니다.

- `db/app_data.db`의 검증된 SQLite 백업
- 전체 `outputs` 디렉터리
- `.env` 또는 비밀 관리 시스템의 설정과 `db/principal_cookie.secret`

DB와 `outputs`는 가능한 한 같은 운영 시점의 스냅샷으로 보관합니다. 복구 시에는
격리된 경로에 먼저 복원하고 `asset_admin audit`와 `PRAGMA integrity_check`를 통과한
뒤 트래픽을 연결합니다.

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
