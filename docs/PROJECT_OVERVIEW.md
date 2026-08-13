# 프로젝트 구조와 설계 기준

> 최종 업데이트: 2026-08-13

## 서비스 정의

LC AI Canvas는 사내 생성 요청을 웹 UI와 MCP에서 받아 동일한 실행·통제·저장
파이프라인으로 처리하는 FastAPI 서비스입니다. 사용자에게는 목적 중심 기능을
제공하고, 모델·공급자·내부 워크플로우 ID는 서버가 결정합니다.

```text
웹 생성 ─┐
         ├─ GenerationCommand ─ CapabilityDispatcher ─ JobManager
MCP 생성 ┘                                      │
                                                ├─ OpenRouter
                                                └─ ComfyUI
                                                       │
웹/MCP 자산 API ─────────────── AssetService ──────────┴─ 파일 + SQLite
```

## 제품 기능

| capability | 현재 웹 구현 | 실행 경로 | MCP 상태 |
|---|---|---|---|
| `create_image` | 기본 생성·참고 이미지 편집 | OpenRouter | 텍스트 생성·소유 자산 참고 편집 공개 |
| `create_game_ui_assets` | 2×2 후보 시트와 그룹 내보내기 | GPT Image 2/OpenRouter | 2×2 고정 계약 공개 |
| `create_character_sheet` | 턴어라운드·표정 시트 | OpenRouter | 계약만 준비 |
| `create_storyboard` | 6·9컷 스토리보드 | OpenRouter | 계약만 준비 |
| `remove_background` | RMBG | ComfyUI | 계약만 준비 |
| `separate_layers` | See-Through PSD | ComfyUI | 계약만 준비 |
| `generate_music` | ACE-Step | ComfyUI | 계약만 준비 |

`NanoBanana*` 워크플로우 ID는 기존 웹 요청과 결과 메타데이터의 호환성을 위해
유지합니다. 현재 provider는 `openrouter`이며 Google API 직접 호출 코드는 사용하지
않습니다. Flux Klein, Qwen, Pixel Art·MK Style, 별도 조명 변경 워크플로우는 제거된
상태입니다. 조명 변경은 범용 이미지 편집 프롬프트로 처리합니다.

## 핵심 모듈

- `app/main.py`: 앱 구성, 미들웨어, 생성 API, 서비스 수명주기
- `app/workflow_configs.py`: 내부 워크플로우 표시·모델·UI 설정
- `app/services/generation_commands.py`: capability와 내부 워크플로우의 단일 매핑
- `app/services/generation_submission.py`: 통제 승인 후 큐 등록
- `app/services/generation_controls.py`: 한도·비용·멱등성·감사 이벤트
- `app/services/generation.py`: OpenRouter/ComfyUI 실행 처리
- `app/job_manager.py`, `app/job_store.py`: 실행 큐와 영속 작업 기록
- `app/services/asset_service.py`, `app/asset_store.py`: 자산 소유권·수명주기·카탈로그
- `app/services/input_assets.py`: 웹/MCP 입력 이미지의 공통 검증·정규화·등록
- `app/asset_admin.py`: 백필, audit, SQLite 및 완전 백업 검증 CLI
- `app/mcp_server.py`: 내부망용 Streamable HTTP MCP 어댑터
- `app/routers/*`: 이미지, 입력, 피드, 캐릭터, 관리자 API

## 요청 흐름

### 웹

1. `/create`가 기존 `anon_id`를 서명된 `lc_principal` 쿠키로 승격합니다.
2. `POST /api/v1/generate`가 기존 `workflow_id` 요청을 capability 명령으로 바꿉니다.
3. 서버가 provider, model, workflow와 감사 필드를 확정합니다.
4. `GenerationControlService`가 kill switch, 한도, 비용 확인, 멱등성을 검사합니다.
5. 작업 큐가 실행하고 WebSocket 및 작업 조회 API로 진행률을 전달합니다.
6. 결과는 `AssetService`를 통해 저장되고 갤러리 카탈로그에 등록됩니다.

### MCP

1. 방화벽/리버스 프록시와 선택적 CIDR 정책이 클라이언트를 제한합니다.
2. 서버가 신뢰 가능한 경로로 해석한 IP를 해시해 MCP principal을 만듭니다.
3. MCP 생성 도구도 동일한 capability dispatcher와 generation control을 통과합니다.
4. 소유자 범위 자산 목록·조회, 첨부 등록, 참고 이미지 검증도 같은 `AssetService`를
   사용합니다.
5. 첨부 이미지는 웹과 MCP 모두 공통 디코딩·크기 제한·PNG 정규화 계층을 통과합니다.
6. 완료 결과는 구조화 메타데이터와 MCP 이미지 content로 반환됩니다.

MCP IP principal은 사람 계정이 아닙니다. NAT 또는 DHCP 환경에서는 사용자 병합이나
변경 가능성이 있으므로 향후 OAuth나 identity-aware proxy로 교체할 수 있게 요청
본문과 신원 결정을 분리했습니다.

## 자산과 DB

실제 바이트는 기존 위치를 유지합니다.

```text
outputs/users/<principal>/YYYY/MM/DD/<asset_id>.png
outputs/users/<principal>/YYYY/MM/DD/thumb/<asset_id>.webp
outputs/users/<principal>/inputs/YYYY/MM/DD/...
outputs/users/<principal>/audio/YYYY/MM/DD/...
outputs/users/<principal>/YYYY/MM/DD/game_ui_groups/<group_id>/...
outputs/feed/YYYY/MM/DD/...
```

SQLite `db/app_data.db`는 다음 운영 데이터를 관리합니다.

- `assets`, `asset_groups`, `schema_migrations`
- `jobs`
- `generation_control_*`
- `feed_posts`, `feed_likes`, `feed_reactions`
- `character_registry`

JSON sidecar는 호환·복구 자료로 유지하지만 갤러리 목록과 소유권의 기준은 SQLite
카탈로그입니다. 사용자 JSON sidecar는 정적 URL로 제공하지 않습니다.

## 신원과 접근 제어

- 웹: 검증된 principal ID + HMAC 서명 HTTP-only 쿠키
- MCP: 서버가 확인한 IP에서 파생한 principal
- 베타 페이지/API: `BETA_PASSWORD`
- 관리자: `ADMIN_USER`, `ADMIN_PASSWORD`; 미설정 시 기본 차단
- 사용자 결과 URL: 해당 웹 principal 또는 같은 MCP IP principal만 접근
- 공개 피드: 사용자 갤러리와 별도 복사본 및 수명주기

IP는 웹 갤러리 소유권으로 사용하지 않고 감사 정보로만 기록합니다.

## 확장 규칙

1. 사용자 의도는 `app/schemas/capability_requests.py`에 provider-neutral하게 정의합니다.
2. capability와 variant를 `CAPABILITY_ROUTES`에서 내부 workflow에 매핑합니다.
3. 웹과 MCP의 생성 요청은 `GenerationCommand` 및 `GenerationSubmissionService`를
   통과합니다. 읽기·첨부 자산 도구는 `AssetService`를 직접 사용합니다.
4. 결과 파일은 직접 저장하지 않고 `AssetService`를 사용합니다.
5. 위험하거나 비싼 작업에는 비용 확인과 멱등성 키를 유지합니다.
6. MCP 도구는 실제 구현과 테스트가 끝난 capability만 공개합니다.

## 현재 남은 기반 작업

- `principal_identity_cookie_issued` 로그로 기존 브라우저 쿠키 승격을 관찰한 후
  `PRINCIPAL_IDENTITY_MODE=enforced` 전환
- 완전 백업 명령을 외부 백업 볼륨의 정기 작업으로 등록하고 실제 복구 훈련
- `ASSET_CATALOG_FALLBACK_ENABLED=false` canary 후 `media_store.py`의 구형 폴더 스캔
  fallback 제거
- 운영 UI에 자산 감사 및 저장소 통계 연결
- 실프로젝트 품질 검증 후 캐릭터 시트·스토리보드 등 특화 capability의 단계적 공개

정기 백업 등록·복구 훈련, principal readiness, catalog-only parity는 CLI와 PowerShell
도구가 준비됐습니다. 운영 실행기의 중복 감지·오류 유지·로그 보존도 구현됐습니다.
남은 항목은 외부 백업 위치 지정과 실제 관찰 기간처럼 배포 환경에서만 확정할 수 있는
gate입니다.
