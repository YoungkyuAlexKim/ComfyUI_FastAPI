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
- MCP: 기본 관리형 텍스트→이미지 생성과 작업 결과 조회

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
`db/principal_cookie.secret`도 인프라 백업에 포함해야 합니다.

## 문서

- [프로젝트 구조와 데이터 흐름](docs/PROJECT_OVERVIEW.md)
- [운영 런북](docs/OPERATIONS.md)
- [자산 인프라](docs/asset-infrastructure.md)
- [MCP 설치와 보안](docs/mcp.md)
- [MCP capability 계약](docs/MCP_CAPABILITY_CONTRACT.md)
- [게임 UI 엘리먼트 MVP](docs/game-ui-elements-mvp.md)
- [문서 인덱스](docs/HANDOFF_INDEX.md)

## 중요한 운영 원칙

- `db/app_data.db`, `outputs`, 백업 파일, 쿠키 서명 키를 기능 커밋에 넣지 않습니다.
- MCP `/mcp`는 OAuth가 없는 현재 단계에서 반드시 사내망으로 제한합니다.
- `PRINCIPAL_IDENTITY_MODE=compat`은 기존 쿠키 전환 기간에만 사용하고,
  전환 확인 후 `enforced`로 변경합니다.
- 신규 기능은 내부 `workflow_id`가 아니라 capability 계약과 `AssetService`를
  통해 연결합니다.
