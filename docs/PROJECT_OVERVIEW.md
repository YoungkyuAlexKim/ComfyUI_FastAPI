# 프로젝트 구조와 설계 기준

> 최종 업데이트: 2026-08-17

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
| `create_game_ui_assets` | 2×2·3×3·4×4 후보 시트, 그룹 내보내기·삭제·복구 | GPT Image 2/OpenRouter | 2×2 고정 생성 계약 공개 |
| `create_character_sheet` | 턴어라운드·표정 시트 | OpenRouter | 웹·MCP 공개/실검증 |
| `create_storyboard` | 6·9컷 스토리보드 | OpenRouter | 웹·MCP 공개/실검증 |
| `remove_background` | RMBG-2.0 | ComfyUI | 소유 이미지 배경 제거 공개 |
| `separate_layers` | See-Through PSD | ComfyUI | 무거운 로컬 workflow로 비공개 |
| `generate_music` | ACE-Step | ComfyUI | 무거운 로컬 workflow로 비공개 |

`NanoBanana*` 워크플로우 ID는 기존 웹 요청과 결과 메타데이터의 호환성을 위해
유지합니다. 현재 hosted provider는 `openrouter`이며 Google API 직접 호출 코드는 사용하지
않습니다. Flux Klein, Qwen, Pixel Art·MK Style, 별도 조명 변경 워크플로우는 제거된
상태입니다. 조명 변경은 범용 이미지 편집 프롬프트로 처리합니다.

## 핵심 모듈

- `app/main.py`: 앱 구성, 미들웨어, 생성 API, 서비스 수명주기
- `app/workflow_configs.py`: 내부 워크플로우 표시·모델·UI 설정
- `app/services/generation_commands.py`: capability와 내부 워크플로우의 단일 매핑
- `app/services/generation_submission.py`: 통제 승인 후 큐 등록
- `app/services/generation_controls.py`: 한도·비용·멱등성·감사 이벤트
- `app/services/generation_planning.py`: hosted/local 공개 계약·모호성 판정·단기 plan ID 고정
- `app/principal_link_store.py`: 웹 principal과 동일-IP MCP workspace의 영구·가역 연결 및 감사
- `app/routers/principal_links.py`: 현재 요청 IP만 대상으로 하는 연결 상태·연결·해제 API
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
3. 비용 없는 계획 도구가 capability별 선택을 확인하고 호출자·프롬프트·참고 자산·옵션에
   묶인 단기 plan ID를 발급합니다. 모호한 선택이 남으면 쓰기 계획을 발급하지 않습니다.
4. MCP 생성 도구는 준비된 plan ID를 검증한 뒤 동일한 capability dispatcher와 generation
   control을 통과합니다.
5. 소유자 범위 자산 목록·조회, 첨부 등록, 참고 이미지 검증도 같은 `AssetService`를
   사용합니다.
6. 첨부 이미지는 웹과 MCP 모두 공통 디코딩·크기 제한·PNG 정규화 계층을 통과합니다.
7. 완료 결과는 구조화 메타데이터와 MCP 이미지 content로 반환됩니다.

MCP IP principal은 사람 계정이 아닙니다. NAT 또는 DHCP 환경의 사용자 병합·변경 가능성은
현재 사내망 운영 제약으로 수용하며, 인프라 협의에 따라 확인된 IP의 해시를 principal과
감사 기준으로 계속 사용합니다. 사람 단위 인증 전환은 현재 계획에 포함하지 않습니다.
웹 서명 쿠키 principal과 MCP IP principal의 원본 소유권은 분리됩니다. 다만 같은 원본 IP의
웹 사용자가 갤러리에서 한 번 명시적으로 연결하면 MCP 생성 이미지를 웹 갤러리에서 함께 볼
수 있습니다. 이 연결은 자산 owner를 바꾸지 않는 가역적 조회 관계이며, 편집에는 웹 input
복사본을 사용합니다. MCP의 자산 목록에 웹 자산을 역으로 합치지는 않습니다.
2026-08-17 실제 동일 PC 브라우저에서도 연결 안내를 누른 뒤 기존 MCP 이미지 2개가
`MCP` 표시와 함께 웹 갤러리에 나타나는 것을 확인했습니다.

이 구조의 운영 전제는 사용자 PC별 원본 IP 고유성·재할당 이력, 프록시/VPN 도입 시 원본
IP 보존, 8000 포트의 사내망 제한을 인프라팀이 책임지는 것입니다. 이 전제가 유지되면
별도 OAuth는 현재 1차 범위에 필요하지 않습니다. 애플리케이션의
`MCP_ALLOWED_CLIENT_CIDRS`는 선택적인 2차 방어이며 인프라 방화벽을 대신하지 않습니다.

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
- `principal_links`, `principal_link_events`

JSON sidecar는 호환·복구 자료로 유지하지만 갤러리 목록과 소유권의 기준은 SQLite
카탈로그입니다. 사용자 JSON sidecar는 정적 URL로 제공하지 않습니다.

## 신원과 접근 제어

- 웹: 검증된 principal ID + HMAC 서명 HTTP-only 쿠키
- MCP: 서버가 확인한 IP에서 파생한 principal
- 베타 페이지/API: `BETA_PASSWORD`
- 관리자: `ADMIN_USER`, `ADMIN_PASSWORD`; 미설정 시 기본 차단
- 사용자 결과 URL: 해당 owner, 같은 MCP IP 또는 명시적으로 연결된 웹 principal만 접근
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

사전 비용 가격표가 요청의 모델·크기·품질과 일치하지 않으면 비용은 0이 아니라
`null/unknown`입니다. 완료 뒤 provider가 보고한 actual cost를 기록하며, 완료된 로컬
ComfyUI 작업은 알려진 외부 provider API actual cost `0.0`을 기록합니다. 관리자
`사용·비용 통계`에서 IP·기능·모델별로 확인하고 미수집 완료 건을 별도로 구분합니다.

## 1차 기반 완료와 남은 운영·선택 작업

현재 합의한 1차 기능 범위에는 운영을 막는 필수 누락이 없습니다. 생성·편집, Game UI,
캐릭터 시트, 스토리보드, RMBG 배경 제거, 계획·비용·소유권·큐·멱등성·자산·감사와
웹↔MCP 갤러리 연결 흐름은 구현과 실제 호출·화면 검증을 마쳤습니다. 다음은 실사용이나
배포 환경에서 결정할 항목입니다.

- 실사용 actual cost 표본을 더 모은 뒤 모델·크기·품질별 보수적 사전 비용 가격표 설정.
  초기 요청·비용 한도와 확인 임계값은 0(무제한/비활성)으로 유지
- `principal_identity_cookie_issued` 로그로 기존 브라우저 쿠키 승격을 관찰한 후
  `PRINCIPAL_IDENTITY_MODE=enforced` 전환
- 완전 백업 명령을 외부 백업 볼륨의 정기 작업으로 등록하고 실제 복구 훈련
- `ASSET_CATALOG_FALLBACK_ENABLED=false` catalog-only canary는 통과했습니다. 외부 백업과
  복구 훈련·관찰 gate를 충족한 뒤 `media_store.py`의 구형 폴더 스캔 fallback 제거
- 운영 UI에 자산 감사 및 저장소 통계 연결
- 공개 RMBG 배경 제거의 로컬 단일 큐 운영 표본 확대; See-Through·ACE-Step은 MCP 비공개 유지
- 단순 배경 흐림·사용자 제공 배경 합성은 필요성이 확인될 때 RMBG 마스크 기반 로컬
  후처리로 검토. 현재는 전용 MCP 도구가 없어 managed 이미지 편집을 사용하면 provider 비용 발생
- 휴지통 이동·작업 취소 같은 MCP 관리 기능은 필요성이 확인될 때만 명시적 확인 계약으로
  검토하며 영구 삭제·관리자 정책 변경은 계속 비공개

정기 백업 등록·복구 훈련, principal readiness, catalog-only parity는 CLI와 PowerShell
도구가 준비됐습니다. 운영 실행기의 중복 감지·포트별 lock·자식 프로세스 감독·고유 로그
보존과 Windows 공유 로그 회전 fallback도 구현됐습니다.
남은 항목은 외부 백업 위치 지정과 실제 관찰 기간처럼 배포 환경에서만 확정할 수 있는
gate, 그리고 충분한 표본에 기반한 모델별 사전 비용 가격표입니다. 알 수 없는 사전 비용의
`null` 처리와 IP·기능·모델별 actual cost 운영 통계는 구현됐습니다. MCP endpoint 초기화, Codex 설정 등록과
13개 공개 도구 중 기존 생성·자산 도구, 캐릭터 시트·스토리보드, 비용 없는 계획과 로컬
RMBG-2.0 배경 제거의 실클라이언트 호출은 2026-08-17에 확인했습니다. 실제 RMBG 작업은
약 4.6초, warm 반복은 약 1.2초에 완료돼 투명 PNG와 MCP image content를 반환했고 provider,
model, 알려진 provider API 예상 비용이 각각 `comfyui`, `RMBG-2.0`, `0.0`으로 기록됐습니다.
격리된 실제 2건 연속 제출도 running·queued 상태와 비중첩 실행, MCP image content 2건,
provider API actual cost `0.0` 기록 2건을 통과했습니다.
MCP IP 소유 그룹 ZIP도 브라우저 beta 쿠키 없이 해당 IP에서 다운로드됩니다. 명시적으로
연결된 웹 principal도 접근할 수 있고 관계없는 IP·principal과 JSON sidecar에는 404를 반환합니다.
