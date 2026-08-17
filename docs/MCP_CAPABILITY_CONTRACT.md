# MCP capability 계약

> 최종 업데이트: 2026-08-17

사용자 의도를 provider-neutral capability로 표현하고 내부 `workflow_id`는 공개 API에서
숨깁니다. 웹은 아직 기존 `workflow_id` 요청을 보내지만 서버 입구에서 동일한
`GenerationCommand`로 변환합니다.

## 구현 상태

| capability | 내부 요청 모델 | 웹 | MCP |
|---|---:|---:|---:|
| `create_image/generate` | 구현 | 구현 | `create_managed_image_asset`로 구현·실검증 |
| `create_image/edit` | 구현 | 구현 | 소유 자산 `reference_image_ids`로 구현·실검증 |
| `create_game_ui_assets/default` | 구현 | 구현 | `create_game_ui_assets` 2×2 계약 공개·실검증 |
| `create_character_sheet/turnaround` | 구현 | 구현 | 공개·실검증 |
| `create_character_sheet/expressions` | 구현 | 구현 | 공개·실검증 |
| `create_storyboard/default` | 구현 | 구현 | 공개·실검증 |
| `remove_background/default` | 구현 | 구현 | `remove_background`로 공개·실검증 |
| `separate_layers/default` | 구현 | 구현 | 미공개 |
| `generate_music/default` | 구현 | 구현 | 미공개 |

`app/schemas/capability_requests.py`의 모델 존재가 MCP 공개를 뜻하지 않습니다. MCP에는
도구 구현, 소유권 검증, 결과 변환, 클라이언트 호환 테스트가 완료된 항목만 노출합니다.

현재 공개 계약은 자동 프로토콜·소유권·결과 변환 테스트와 Codex 실클라이언트 검증을
통과했습니다. 기능 조회, 첨부·생성·편집, Game UI ZIP, 캐릭터 시트, 스토리보드와 RMBG를
실제 호출했습니다. RMBG는 반복 생성, 투명 PNG, 멱등성, 로컬 단일 큐와
`comfyui/RMBG-2.0/0.0` 감사 기록을 확인했습니다. 웹 연결도 지속성·takeover 차단 자동
테스트와 실제 사내 주소 브라우저에서 과거·신규 MCP 자산이 함께 보이는 것까지 확인했습니다.
Claude Code 화면 표시와 장시간·다사용자 부하는 별도 운영 검증 범위입니다.

MCP 0.7.1의 모든 공개 생성 쓰기는 공통 `plan_generation`을 먼저 요구합니다.
계획 계약은 capability별 결정 필드와 고정 필드를 분리하고 다음을 보장합니다.

- `clarify`: 누락된 결정과 선택지를 반환하며 plan ID를 발급하지 않음
- `recommend`: 사용자가 선택을 명시적으로 위임한 경우에만 권장값을 채움
- 준비된 계획: 호출자 principal, 프롬프트, 참고 자산, 옵션에 묶인 30분 plan ID 발급
- 쓰기 제출: plan ID 누락·만료·다른 소유자·인자 변경을 provider 호출 전에 거절
- 계획 자체: provider나 로컬 workflow를 실행하지 않음. hosted 가격표가 없으면 예상 비용은
  `null`, 외부 provider가 없는 ComfyUI 로컬 workflow는 알려진 provider 비용 `0.0`

실제 Streamable HTTP 클라이언트에서 모호 요청의 plan 미발급, 명시·위임 계획 발급, 계획
없는 쓰기 거절을 확인했습니다. 클라이언트의 LLM이 대화에서 사용자가 실제로 선택을
위임했는지는 서버가 볼 수 없으므로 tool instruction과 클라이언트 승인 UI가 함께 경계를
구성합니다.

`internal_image_preset/chainsaw_juice_king`은 웹 전용 사내 프리셋이며 공개 MCP 계약에
포함하지 않습니다.

## 공통 요청 규칙

비용이 발생할 수 있는 요청은 다음을 가집니다.

- `idempotency_key`: 동일 의도 재시도에 재사용, 8~128자
- `cost_confirmed`: 비용 확인 정책을 통과하기 위한 명시적 사용자 확인

principal, client IP, request ID, source, resolved provider/model/workflow는 서버가
확정합니다. 클라이언트 요청에 같은 이름의 값이 있어도 덮어씁니다.

## 디스패치 경계

`CapabilityDispatcher`가 `capability + variant`를 내부 workflow로 매핑합니다.

```text
create_image + generate       → NanoBanana
create_image + edit           → NanoBanana_Img2Img
create_game_ui_assets + default        → GameUI_Elements
create_character_sheet + turnaround    → NanoBanana_TurnaroundSheet
create_character_sheet + expressions   → NanoBanana_ExpressionPortraitSheet
create_storyboard + default             → NanoBanana_StoryboardCutboard
remove_background + default             → RMBG2
separate_layers + default               → seethrough-basic
generate_music + default                → AceStep15XL
```

왼쪽 계약은 안정적으로 유지하고 오른쪽 workflow, provider, model은 서버 내부에서
교체할 수 있습니다. `NanoBanana` 이름은 현재 OpenRouter workflow의 호환용 ID입니다.

각 Job에는 source, principal, 검증된 client IP, request/idempotency ID, capability,
variant, resolved workflow/provider/model을 저장합니다. `X-Forwarded-For`는 바로 앞 peer가
`TRUSTED_PROXY_CIDRS`에 속할 때만 사용합니다.

MCP principal의 신뢰 경계는 사람 계정이 아니라 서버가 관찰한 IP입니다. 사용자별 원본 IP의
고유성·재할당 이력, 프록시/VPN의 원본 IP 보존, 8000 포트의 사내망 제한은 인프라팀 운영
전제로 둡니다. 웹 서명 쿠키 principal과 MCP IP principal의 원본 소유권과 MCP 자산 목록은
자동으로 합치지 않습니다.

같은 IP의 웹 사용자는 별도 인증 계정 없이 MCP 생성 이미지의 웹 갤러리 표시만 한 번
명시적으로 연결할 수 있습니다. 서버가 요청 IP에서 대상 MCP principal을 계산하고 한 MCP
workspace당 한 웹 principal만 허용합니다. 연결은 owner 이전이 아닌 가역적 조회 권한이며,
웹 편집은 input 복사본으로 분리합니다. `MCP_WEB_LINK_ENABLED=false`이면 이 연결 계층을
fail-closed로 제외합니다.

서버 PC에서 `localhost`와 사내 IP는 서로 다른 source IP와 브라우저 host이므로 별도 웹·MCP
principal이 됩니다. 운영에서는 웹과 MCP 모두 `MCP_PUBLIC_BASE_URL`에 대응하는 canonical
사내 origin을 사용합니다. 일반 원격 PC는 두 경로가 직접 연결되는 한 같은 원본 IP로
관찰됩니다.

현재 MCP principal은 IP만의 결정적 해시입니다. 퇴사·PC 교체 뒤 같은 IP가 다른 사용자에게
재할당되면 이전 owner가 다시 선택될 수 있습니다. 인프라팀의 재할당 정책상 필요하면
`IP + allocation generation`으로 기존 workspace를 retired 처리하고 같은 IP에 새 owner를
발급하는 운영 계층을 추가해야 합니다. 이는 현재 계약에 아직 구현되지 않은 운영 항목입니다.

## capability별 핵심 제약

- 이미지 편집은 최소 한 개의 `reference_image_ids`가 필요합니다.
- MCP 기본 생성은 Nano Banana Pro·Nano Banana 2·Nano Banana 2 Lite·GPT Image 2,
  `square|landscape|portrait`, 편집 전용 `auto`, 모델별 `1K|2K`, 참고 이미지 최대 14장을 공개합니다.
  GPT Image 2는 `low|medium|high`를 추가로 요구하고 Lite는 1K만 허용합니다.
  provider별 실제 참고 이미지 한도는 실행 시 더 작게 제한될 수 있습니다.
- MCP 참고 이미지는 호출자의 active `image` 또는 `input` 자산이어야 하며 enqueue 전에
  소유권과 실제 파일 존재를 확인합니다.
- MCP 첨부 등록은 필수 `mime_type`과 실제 이미지 형식이 일치하는 PNG/JPEG/WEBP만
  허용하고 공통 입력 제한과 카탈로그 저장을 사용합니다. provider를 호출하지 않으므로
  `GenerationCommand`나 비용 통제를 거치지 않습니다.
- Game UI 웹 경로는 `2x2`·`3x3`·`4x4`를 지원하지만 MCP 공개 요청 모델은 안정성을
  위해 현재 `2x2`, 참고 이미지 최대 3장, 2K로 고정합니다.
- 턴어라운드는 3·5·8뷰, 표정 시트는 4·9개 계약을 사용합니다.
- 스토리보드는 참고 이미지 한 장과 6·9컷을 사용합니다.
- 배경 제거는 호출자 소유 active image/input 한 장, 고정 `RMBG2` workflow와 `RMBG-2.0`
  모델을 사용합니다. `mask_blur` 0~64와 `mask_offset` -64~64는 선택 항목이고 기본값은 0입니다.
  외부 provider API 비용은 알려진 `0.0`으로 기록하지만 로컬 GPU 자원은 소비합니다.
- MCP의 두 hosted 특화 도구인 캐릭터 시트와 스토리보드는 현재 서버가 선택한 GPT Image 2를 사용하며 1K·2K와
  low·medium·high를 공개합니다. 모호한 값은 계획에서 질문하고 선택 위임 시에만
  2K/medium 권장값을 적용합니다.
- 현재 일반 배경 제거 웹·MCP 구현은 RMBG입니다. Game UI의 크로마→알파 후처리와는
  별개의 경로이며 See-Through와 ACE-Step은 MCP에 공개하지 않습니다.
- See-Through는 PSD 레이어 분리라는 특수 결과 형식을 유지합니다.

## 운영 통제

웹과 MCP의 생성 요청은 모두 `GenerationControlService`를 통과합니다. 자산 목록·조회와
첨부 등록은 생성 요청이 아니며 `AssetService`의 소유권·저장 경계를 따릅니다.

- 전사 일일 요청 및 예상 비용 한도
- source + principal + idempotency key 범위의 중복 방지
- 전체, MCP, capability별 kill switch
- capability 또는 예상 비용 임계값 기반 확인
- 승인·거절·중복·Job 상태 감사 이벤트
- 예상 비용 예약과 provider 실제 비용 기록

가격표가 없는 사전 비용은 0이 아니라 `null/unknown`으로 반환합니다. 실제 비용 통계는
관리자 화면과 `GET /api/v1/admin/generation-controls/cost-report`에서 IP·기능·모델별로
확인하며, 완료 후 비용 미수집 건을 별도 집계합니다. 예외적으로 `resolved_provider=comfyui`인
로컬 workflow는 외부 provider API 비용이 없으므로 알려진 `0.0`으로 기록합니다.

`GENERATION_ENABLED=false`, `MCP_GENERATION_ENABLED=false`는 환경 수준의 hard stop이며
DB의 관리자 설정으로 다시 켤 수 없습니다. 가격은 코드에 고정하지 않고 운영 설정의
`GENERATION_COST_ESTIMATES_JSON` 또는 관리자 정책으로 관리합니다.

관리 API:

- `GET/PUT /api/v1/admin/generation-controls/policy`
- `GET /api/v1/admin/generation-controls/summary`
- `GET /api/v1/admin/generation-controls/events`
- `GET /api/v1/admin/generation-controls/cost-report`

MCP는 현재 생성·조회 중심입니다. 자산 영구 삭제와 관리자 정책 변경은 공개 계약이 아니며,
휴지통 이동이나 작업 취소도 실사용 필요성이 확인될 때 별도 확인 계약으로 검토합니다.
