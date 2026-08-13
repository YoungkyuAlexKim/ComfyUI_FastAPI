# LC AI Canvas

사내에서 이미지·게임 UI 자산·캐릭터 시트·스토리보드와 일부 로컬 도구를
한곳에서 실행하고 관리하는 FastAPI 서비스입니다. 웹 UI와 MCP는 같은 생성
명령, 작업 큐, 비용 통제, 감사 로그, 자산 저장 계층을 사용합니다.

## 현재 구성

- 호스티드 이미지 생성: OpenRouter를 통한 Gemini 및 GPT Image 2
- 로컬 ComfyUI: RMBG 배경 제거, See-Through 레이어 분리, ACE-Step 음악 생성
- 저장: 파일시스템 원본 + SQLite 자산 카탈로그
- 사용자 경계: 웹은 서명 쿠키, MCP는 사내망에서 확인된 클라이언트 IP
- 운영 통제: 일일 요청·비용 한도, 동시성, 멱등성, 확인 정책, 감사 이벤트
- MCP: 소유자 이미지 조회, 클라이언트 첨부 등록, 기본 생성·기존 자산 편집,
  Game UI 2×2 그룹 생성, 작업 결과 조회

내부 워크플로우 이름에 남아 있는 `NanoBanana`는 호환용 ID입니다. 현재
호스티드 모델 호출은 Google API에 직접 연결하지 않고 OpenRouter를 사용합니다.

## 빠른 시작

Windows 가상환경을 만든 뒤 의존성과 환경 파일을 준비합니다.

```powershell
python -m venv venv
.\venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env
```

`.env`에 최소한 `OPENROUTER_API_KEY`, `BETA_PASSWORD`, `ADMIN_USER`,
`ADMIN_PASSWORD`를 설정합니다. 로컬 ComfyUI 기능을 사용할 경우 관련 경로와
서버 주소도 설정합니다.

```powershell
.\run_server.bat
```

`run_server.bat`은 개발용으로 reload를 켜고 브라우저를 자동으로 엽니다.
`run_server_prod.bat`은 운영용 단일 프로세스를 실행하며 브라우저를 자동으로 열지
않습니다. 공통 실행기는 기존 8000 포트의 health를 먼저 확인해 중복 서버를 막고,
비정상 포트 점유 PID와 `logs/server-*.log`를 남깁니다. 더블클릭 시작 오류는 콘솔을
유지하므로 메시지와 로그를 함께 확인할 수 있습니다.

- 생성 화면: `http://127.0.0.1:8000/create`
- 피드: `http://127.0.0.1:8000/feed`
- API 문서: `http://127.0.0.1:8000/docs`
- 상태 확인: `http://127.0.0.1:8000/healthz`

사내 서버 실행은 `run_server_prod.bat`을 사용합니다. 두 실행 스크립트 모두
Uvicorn의 자동 프록시 헤더 신뢰를 끄며, 신뢰 가능한 프록시는
`TRUSTED_PROXY_CIDRS`에서만 지정합니다.

## 검증

```powershell
.\venv\Scripts\python.exe -m unittest discover -s tests -v
.\venv\Scripts\python.exe -m app.asset_admin audit
```

운영 DB 백업은 다음 명령으로 생성하고 무결성까지 검사할 수 있습니다.

```powershell
.\venv\Scripts\python.exe -m app.asset_admin backup-db
```

이 명령은 SQLite만 백업합니다. 실제 복구 가능성을 확보하려면 `outputs`와
`db/principal_cookie.secret`을 함께 묶는 다음 명령을 정기 작업에 사용합니다.

```powershell
.\scripts\backup_app_data.ps1 -DestinationRoot E:\LC-AI-Canvas-Backups
.\venv\Scripts\python.exe -m app.asset_admin verify-backup E:\LC-AI-Canvas-Backups\lc-ai-canvas-...
.\scripts\test_restore_backup.ps1 -BackupPath E:\LC-AI-Canvas-Backups\lc-ai-canvas-...
```

완전 백업은 파일별 checksum manifest와 DB·카탈로그 정합성 검증을 통과해야만
완료됩니다. 정기 작업 등록, 보존 정책과 복구 절차는 `docs/OPERATIONS.md`를 따릅니다.

## 문서

- [프로젝트 구조와 데이터 흐름](docs/PROJECT_OVERVIEW.md)
- [운영 런북](docs/OPERATIONS.md)
- [자산 인프라](docs/asset-infrastructure.md)
- [MCP 설치와 보안](docs/mcp.md)
- [MCP capability 계약](docs/MCP_CAPABILITY_CONTRACT.md)
- [게임 UI 엘리먼트 MVP](docs/game-ui-elements-mvp.md)
- [문서 인덱스](docs/HANDOFF_INDEX.md)

## 중요한 운영 원칙

- `db/app_data.db`, 런타임 `outputs/users`·`outputs/feed`, 백업 파일, 쿠키 서명 키를
  기능 커밋에 넣지 않습니다. 검토된 번들 자산 `outputs/global/characters`만 예외입니다.
- MCP `/mcp`는 OAuth가 없는 현재 단계에서 반드시 사내망으로 제한합니다.
- `PRINCIPAL_IDENTITY_MODE=compat`은 기존 쿠키 전환 기간에만 사용하고,
  전환 확인 후 `enforced`로 변경합니다.
- 신규 기능은 내부 `workflow_id`가 아니라 capability 계약과 `AssetService`를
  통해 연결합니다.
