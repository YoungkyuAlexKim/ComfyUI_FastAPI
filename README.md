# LC AI Canvas

LC AI Canvas는 사내 이미지·게임 UI 자산·캐릭터 시트·스토리보드와 일부 로컬
ComfyUI 도구를 웹과 MCP에서 함께 사용하는 FastAPI 서비스입니다. 두 진입점은 같은
생성 명령, 작업 큐, 비용 통제, 감사 로그와 자산 저장 계층을 사용합니다.

## 현재 제공 범위

| 영역 | 웹 | MCP |
|---|---|---|
| 일반 이미지 | OpenRouter 기반 생성·참고 이미지 편집 | 생성·소유 자산 참고 편집 |
| Game UI | 2×2·3×3·4×4 후보, 개별 PNG·ZIP·묶음 관리 | 검증된 2×2 그룹 생성 |
| 캐릭터 시트 | 턴어라운드·표정 시트 | 턴어라운드·표정 시트 |
| 스토리보드 | 6·9컷 | 6·9컷 |
| 배경 제거 | 로컬 RMBG-2.0 | 로컬 RMBG-2.0 |
| 레이어·음악 | See-Through, ACE-Step | 장시간 로컬 작업이라 비공개 |

호스티드 이미지 모델은 OpenRouter를 통해 호출합니다. 내부 workflow ID에 남아 있는
`NanoBanana`는 기존 요청과 결과의 호환용 이름이며 Google API 직접 연결을 뜻하지 않습니다.

## 빠른 시작

Windows 가상환경과 환경 파일을 준비합니다.

```powershell
python -m venv venv
.\venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env
```

`.env`에는 최소한 `OPENROUTER_API_KEY`, `ADMIN_USER`, `ADMIN_PASSWORD`를 설정합니다.
일반 사내 웹 화면에는 공용 비밀번호가 없고 관리자 화면만 별도 인증합니다. 로컬 기능을
사용하려면 ComfyUI 경로와 주소도 설정합니다.

개발 실행:

```powershell
.\run_server.bat
```

사내 운영 실행:

```powershell
.\run_server_prod.bat
```

공식 실행기는 8000 포트의 기존 health, 포트별 lock, 자식 프로세스와 세션 로그를 관리해
중복 서버와 고아 Uvicorn을 막습니다. 운영 실행은 브라우저를 자동으로 열지 않습니다.

## 접속 주소

개발 전용 로컬 확인에는 `http://127.0.0.1:8000`을 사용할 수 있습니다. 사내 사용자와
운영자는 `http://SERVER_IP:8000` 또는 인프라가 정한 공식 hostname을 사용합니다.

- 생성·갤러리: `/create`
- 피드: `/feed`
- Codex·Claude Code 연결 안내: `/mcp-connect`
- API 문서: `/docs`
- 상태 확인: `/healthz`
- 관리자 사용·비용 통계: `/admin`
- MCP endpoint: `/mcp/`

서버 PC에서 MCP를 사내 IP로 등록했다면 웹도 같은 공식 주소로 열어야 합니다.
`localhost`와 사내 IP는 각각 `127.0.0.1`과 LAN IP로 관찰되고 브라우저 쿠키의 host도
달라 별도 작업공간으로 보입니다. 일반 사내 사용자에게는 `localhost`를 안내하지 않습니다.
운영에서는 `MCP_PUBLIC_BASE_URL`을 공식 origin으로 설정하는 것을 권장합니다.

## 검증

비용 없는 기본 회귀 검사는 다음과 같습니다.

```powershell
.\venv\Scripts\python.exe -m unittest discover -s tests -v
.\venv\Scripts\python.exe -m app.asset_admin audit
.\venv\Scripts\python.exe -m scripts.smoke_game_ui_browser
.\venv\Scripts\python.exe -m scripts.smoke_mcp_connect_browser
.\venv\Scripts\python.exe -m scripts.smoke_linked_mcp_gallery_browser
.\scripts\smoke_server_launcher.ps1
```

실제 로컬 GPU를 사용하는 RMBG 큐 검사는 ComfyUI가 유휴 상태일 때 실행합니다.

```powershell
.\venv\Scripts\python.exe -m scripts.smoke_rmbg_queue
```

2026-08-18 기준 자동 회귀와 운영 audit에서 누락 파일·메타데이터·그룹 파일 0을 성공
기준으로 사용합니다. 운영 자산 수는 계속 바뀌므로 고정 개수보다 DB·파일 정합성을 봅니다.

MCP 0.8.0은 13개 도구와 공개 생성 capability 5개를 제공합니다. Codex 실클라이언트에서
기능 조회, 생성·편집, Game UI, 캐릭터 시트, 스토리보드, RMBG, 작업 polling과 결과 조회를
확인했고 Claude Code 사내 계정에서도 직접 파일 업로드와 연속 이미지 편집이 완료됐습니다.
클라이언트 이미지는 Base64 도구 인자로 보내지 않고 IP 소유권 기반 multipart endpoint로
직접 업로드합니다. 현재 지원 클라이언트는 Codex 앱·IDE와 Claude Code입니다. Claude Desktop
일반 채팅과 ChatGPT 일반 Chat 모드는 현재 MCP 경로와 별개이며 지원 범위가 아닙니다.

## 백업

DB만 백업하려면 다음 명령을 사용합니다.

```powershell
.\venv\Scripts\python.exe -m app.asset_admin backup-db
```

실제 복구 가능한 세트는 DB, 전체 `outputs`, principal cookie secret을 함께 보관해야 합니다.

```powershell
.\scripts\backup_app_data.ps1 -DestinationRoot E:\LC-AI-Canvas-Backups
.\venv\Scripts\python.exe -m app.asset_admin verify-backup E:\LC-AI-Canvas-Backups\lc-ai-canvas-...
.\scripts\test_restore_backup.ps1 -BackupPath E:\LC-AI-Canvas-Backups\lc-ai-canvas-...
```

## 문서

- [문서 인덱스와 현재 체크포인트](docs/HANDOFF_INDEX.md)
- [프로젝트 구조와 설계 기준](docs/PROJECT_OVERVIEW.md)
- [운영 런북](docs/OPERATIONS.md)
- [MCP 도구·설정·신원](docs/mcp.md)
- [MCP capability 계약](docs/MCP_CAPABILITY_CONTRACT.md)
- [자산 인프라](docs/asset-infrastructure.md)
- [게임 UI 엘리먼트 메이커](docs/game-ui-elements-mvp.md)

## 운영 원칙

- `db/app_data.db`, 런타임 `outputs/users`·`outputs/feed`, 백업과 secret을 기능 커밋에
  넣지 않습니다.
- MCP는 서버가 관찰한 사내 클라이언트 IP를 principal과 비용 감사 기준으로 사용합니다.
  인터넷에 직접 공개하지 않습니다.
- 사용자 PC별 원본 IP 고유성, 재할당 이력, 프록시·VPN의 원본 IP 보존과 8000 포트의
  사내망 제한은 인프라 운영 전제입니다.
- 같은 IP의 웹 사용자는 MCP 작업공간을 한 번 명시적으로 연결할 수 있습니다. 연결은
  자산 owner를 옮기지 않으며 다른 웹 principal의 자동 인수를 차단합니다. 연결된 MCP
  이미지는 웹 갤러리에서 선택·휴지통 이동할 수 있지만 쇼케이스 공유는 계속 차단합니다.
- 퇴사·PC 교체 뒤 IP가 다른 사용자에게 재할당되면 현재의 결정적 IP owner가 재사용될
  수 있습니다. 인프라 정책 확인 전에는 이를 해결된 문제로 간주하지 않습니다. 필요하면
  이전 작업공간을 폐기하고 같은 IP에 새 owner 세대를 발급하는 운영 기능을 추가합니다.
- 신규 생성 기능은 내부 `workflow_id`가 아니라 capability 계약과 `AssetService`를 통해
  연결합니다.
