# 프로젝트 구조와 설계 기준

> 최종 업데이트: 2026-08-18

## 서비스 정의

LC AI Canvas는 사내 이미지 제작 요청을 웹 UI와 MCP에서 받아 같은 실행·통제·저장
파이프라인으로 처리하는 FastAPI 서비스입니다. 사용자에게는 목적 중심 capability를
제공하고 공급자, 모델과 내부 workflow ID는 서버가 확정합니다.

```text
웹 생성 ─┐
         ├─ GenerationCommand ─ CapabilityDispatcher ─ GenerationControl ─ JobManager
MCP 생성 ┘                                                               │
                                                       ┌──────────────────┴──────────────┐
                                                       │                                 │
                                                  OpenRouter                         ComfyUI
                                                       │                                 │
웹·MCP 자산 API ──────────────────────── AssetService ─┴──────── 파일 + SQLite ─────────┘
```

## 제품 기능

| capability | 웹 | 실행 경로 | MCP |
|---|---|---|---|
| `create_image` | 기본 생성·참고 이미지 편집 | OpenRouter | 생성·소유 자산 편집 공개 |
| `create_game_ui_assets` | 2×2·3×3·4×4, ZIP·묶음 관리 | GPT Image 2/OpenRouter | 검증된 2×2 공개 |
| `create_character_sheet` | 턴어라운드·표정 시트 | OpenRouter | 공개·실검증 |
| `create_storyboard` | 6·9컷 | OpenRouter | 공개·실검증 |
| `remove_background` | RMBG-2.0 | ComfyUI | 공개·실검증 |
| `separate_layers` | See-Through PSD | ComfyUI | 장시간 작업이라 비공개 |
| `generate_music` | ACE-Step | ComfyUI | 장시간 작업이라 비공개 |

`NanoBanana*` workflow ID는 기존 웹 요청과 결과 메타데이터 호환을 위해 유지합니다. 현재
호스티드 공급자는 OpenRouter이며 Google API 직접 호출은 사용하지 않습니다. 조명 변경은
별도 workflow가 아니라 범용 이미지 편집 프롬프트로 처리합니다.

## 핵심 모듈

- `app/main.py`: 앱 구성, 미들웨어, 페이지와 서비스 수명주기
- `app/workflow_configs.py`: 내부 workflow·모델·UI 설정
- `app/schemas/capability_requests.py`: provider-neutral 요청 모델
- `app/services/generation_commands.py`: capability와 workflow 매핑
- `app/services/generation_planning.py`: MCP 선택지·모호성·단기 plan ID
- `app/services/generation_submission.py`: 통제 승인 뒤 큐 등록
- `app/services/generation_controls.py`: 한도·비용·멱등성·감사 이벤트
- `app/services/generation.py`: OpenRouter·ComfyUI 실행
- `app/job_manager.py`, `app/job_store.py`: 외부 API lane, 로컬 단일 lane과 영속 작업
- `app/services/asset_service.py`, `app/asset_store.py`: 자산 소유권·수명주기·카탈로그
- `app/services/input_assets.py`: 직접 업로드 이미지 검증·정규화·등록
- `app/routers/inputs.py`: 웹 업로드와 MCP IP 소유 multipart 업로드
- `app/principal_link_store.py`: 웹 principal과 MCP workspace 연결·감사
- `app/routers/principal_links.py`: 현재 요청 IP의 연결 상태·연결·해제 API
- `app/mcp_server.py`: Streamable HTTP MCP 어댑터와 결과 표시 계약
- `app/asset_admin.py`: 백필, audit와 백업 검증 CLI

## 요청 흐름

### 웹

1. 브라우저의 기존 `anon_id`를 검증해 서명된 `lc_principal` 쿠키로 승격하거나 새
   principal을 발급합니다.
2. `POST /api/v1/generate`가 기존 `workflow_id` 요청을 `GenerationCommand`로 변환합니다.
3. 서버가 capability, provider, model, workflow와 감사 필드를 확정합니다.
4. `GenerationControlService`가 kill switch, 한도, 비용 확인과 멱등성을 검사합니다.
5. 작업 큐가 실행하고 WebSocket·작업 API로 상태를 전달합니다.
6. 결과를 `AssetService`로 저장하고 SQLite 카탈로그에 등록합니다.

### MCP

1. 사내망·방화벽과 선택적 CIDR 정책이 endpoint 접근을 제한합니다.
2. 서버가 실제 peer 또는 신뢰 프록시에서 해석한 원본 IP를 해시해 MCP principal을 만듭니다.
3. 로컬 첨부는 `/api/v1/mcp/inputs/upload`로 multipart 직접 전송하고 반환된 `asset_id`만
   이후 MCP 도구 인자에 사용합니다.
4. `plan_generation`이 비용 없이 capability 선택을 확인합니다. 모호한 결정이 남으면
   plan ID를 발급하지 않습니다.
5. 준비된 plan ID는 호출자, 프롬프트, 참고 자산과 전체 옵션에 묶이며 30분 동안 유효합니다.
6. 쓰기 도구가 plan과 멱등성 키를 검증한 뒤 웹과 같은 dispatcher·통제·큐를 사용합니다.
7. 완료 결과는 구조화 메타데이터, 경량 user-preview와 원본 링크를 반환합니다.

MCP 자산 목록과 조회는 MCP owner의 active image/input만 반환합니다. 웹 자산을 MCP 목록에
자동으로 합치지 않습니다. Base64 입력 도구는 없으며 직접 업로드 endpoint와 MCP 요청이
동일한 source IP를 관찰하므로 같은 MCP owner에 저장됩니다.

## 신원과 접근 제어

| 경계 | 식별 | 용도 |
|---|---|---|
| 웹 | HMAC 서명 HTTP-only 쿠키 | 개인 갤러리·입력·피드 동작 |
| MCP | 서버가 관찰한 원본 IP의 해시 | MCP 자산·작업·비용 감사 |
| 관리자 | `ADMIN_USER`, `ADMIN_PASSWORD` | 운영 정책·통계·복구 |

일반 웹 화면에는 공용 비밀번호가 없습니다. 외부 접근은 사내망과 방화벽에서 차단하며
관리자 인증은 별도로 유지합니다. 결과 URL은 해당 owner, 같은 MCP IP 또는 명시적으로
연결된 웹 principal만 열 수 있습니다. 관계없는 요청과 JSON sidecar에는 404를 반환합니다.

### 웹과 MCP 갤러리 연결

웹 쿠키와 MCP IP는 서로 다른 원본 소유권 공간입니다. `MCP_WEB_LINK_ENABLED=true`이면
같은 IP의 웹 사용자가 갤러리에서 한 번 명시적으로 연결할 수 있습니다.

- 대상 MCP principal은 서버가 현재 요청 IP에서 계산하며 클라이언트가 고르지 못합니다.
- 연결은 SQLite에 영구 저장되지만 자산 owner와 감사 기록을 바꾸지 않습니다.
- 한 MCP workspace는 한 웹 principal에만 연결되어 자동 takeover를 차단합니다.
- 연결된 MCP 이미지는 웹 갤러리에서 선택·휴지통 이동·복구할 수 있습니다. 이때 원래 MCP
  owner는 유지되며 편집 시에는 별도 웹 input 복사본을 만듭니다. 쇼케이스 공유는 차단합니다.
- 연결 해제는 조회 관계만 제거하고 MCP 원본을 삭제하지 않습니다.

브라우저 쿠키는 host별이고 MCP owner는 관찰된 source IP별입니다. 서버 PC에서 웹을
`localhost`로 열고 MCP는 사내 IP로 연결하면 `127.0.0.1`과 LAN IP가 서로 다른 workspace가
되는 것이 정상입니다. 운영자와 사용자는 웹·온보딩·MCP에 같은 canonical 사내 origin을
사용해야 합니다. 일반 원격 PC에서는 웹과 MCP가 모두 직접 연결되는 한 같은 사용자 PC의
원본 IP로 관찰됩니다.

### IP 운영 전제와 재할당

IP principal은 사람 계정이 아닙니다. 현재 구조는 다음을 인프라 운영 전제로 둡니다.

- 사용자 PC별 원본 IP의 동시 고유성
- DHCP 예약 또는 재할당 시점·이력 관리
- 프록시·VPN 도입 시 원본 IP 보존
- 8000 포트와 `/mcp`의 사내망 제한

이 전제가 유지되는 동안 OAuth 전환은 현재 계획에 없습니다. 다만 퇴사·PC 교체 뒤 같은
IP를 다른 사람에게 재할당하면 현재의 결정적 IP 해시가 이전 MCP owner를 다시 가리킵니다.
인프라 정책상 이 상황이 현실적이면 `IP + allocation generation` 매핑을 추가해 기존
workspace를 retired 처리하고 같은 IP에 새 owner를 발급해야 합니다. 이 기능은 아직
구현되지 않았으며, 단순 DB 일부 삭제로 대체하지 않습니다. 비용·감사 이력은 이전 owner에
보존하고 사용자 자산만 별도 보존 정책으로 처리하는 것이 목표입니다.

## 자산과 DB

실제 바이트는 기존 파일 위치를 유지합니다.

```text
outputs/users/<principal>/YYYY/MM/DD/<asset_id>.png
outputs/users/<principal>/YYYY/MM/DD/thumb/<asset_id>.webp
outputs/users/<principal>/inputs/YYYY/MM/DD/...
outputs/users/<principal>/audio/YYYY/MM/DD/...
outputs/users/<principal>/YYYY/MM/DD/game_ui_groups/<group_id>/...
outputs/feed/YYYY/MM/DD/...
```

SQLite `db/app_data.db`의 주요 운영 데이터는 다음과 같습니다.

- `assets`, `asset_groups`, `schema_migrations`
- `jobs`
- `generation_control_*`
- `feed_posts`, `feed_likes`, `feed_reactions`
- `character_registry`
- `principal_links`, `principal_link_events`

JSON sidecar는 호환·복구 자료이며 갤러리 목록과 소유권의 기준은 SQLite입니다. 파일과
SQLite를 하나의 ACID 트랜잭션으로 묶을 수 없으므로 보상 로직, 정기 audit와 완전 백업을
함께 사용합니다.

## 실행·비용·결과 표시

외부 API 작업은 별도 동시성 lane, ComfyUI 작업은 GPU 보호를 위한 단일 실행 lane을
사용합니다. 모든 생성 쓰기는 source·principal·idempotency key 범위에서 중복을 막고
provider가 보고한 actual cost를 기록합니다.

가격표가 요청 모델·크기·품질과 일치하지 않으면 사전 비용은 `0`이 아니라
`null/unknown`입니다. 완료된 ComfyUI 작업은 외부 provider API 비용만 알려진 `0.0`으로
기록하며 GPU·전력 원가가 무료라는 뜻은 아닙니다.

`get_generation_result`는 최대 768px WebP user-preview를 첫 `ImageContent`로 두고
`presentation.required=true`와 원본 링크를 함께 반환합니다. 로컬 Codex·Claude Code에는
원본을 세션용 PNG로 다운로드해 이미지 보기로 연 뒤 완료 답변을 하도록 지시합니다. 클라이언트가
이를 항상 수행하거나 네이티브 이미지를 렌더링한다고 보장할 수 없으므로 원본 링크를 유지하고,
표시 불가 시 이를 명시하게 합니다.

## 확장 규칙

1. 사용자 의도는 `capability_requests.py`에 provider-neutral하게 정의합니다.
2. `CAPABILITY_ROUTES`에서 capability와 variant를 내부 workflow에 매핑합니다.
3. 웹과 MCP의 생성 쓰기는 `GenerationCommand`와 `GenerationSubmissionService`를 통과합니다.
4. 결과 파일은 직접 저장하지 않고 `AssetService`를 사용합니다.
5. 비용이 있거나 재시도될 작업에는 계획, 확인 정책과 멱등성 키를 유지합니다.
6. MCP에는 구현·소유권·결과 변환·클라이언트 검증이 끝난 capability만 공개합니다.
7. destructive MCP 기능은 필요성이 확인된 뒤 별도 확인 계약으로 설계합니다.

## 현재 경계

1차 기반에는 생성·편집, Game UI, 캐릭터 시트, 스토리보드, RMBG, 계획·비용·큐·멱등성,
자산·감사와 웹↔MCP 연결이 포함됩니다. 다음은 배포·운영 또는 선택 기능입니다.

- Claude Desktop은 현재 지원하지 않으며, 인프라가 DNS·HTTPS 프록시 기반 원격 MCP를 제공할 때 재검토
- 인프라팀의 IP 재할당 정책 확인과 필요 시 owner generation 기능
- 외부 백업 위치의 예약 작업과 복구 훈련
- actual cost 표본 기반 사전 비용 가격표
- 장시간·다사용자 부하와 RMBG 단일 큐 표본 확대
- 스토리보드 gutter fallback 품질 보강
- 필요성이 확인된 MCP 취소·휴지통 또는 MCP Apps UI

See-Through·ACE-Step MCP 공개, 일반 ChatGPT Chat 모드용 앱과 영구 삭제 도구는 현재
필수 범위가 아닙니다.
