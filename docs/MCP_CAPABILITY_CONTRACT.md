# MCP capability 계약

사용자 의도를 provider-neutral capability로 표현하고 내부 `workflow_id`는 공개 API에서
숨깁니다. 웹은 아직 기존 `workflow_id` 요청을 보내지만 서버 입구에서 동일한
`GenerationCommand`로 변환합니다.

## 구현 상태

| capability | 내부 요청 모델 | 웹 | MCP |
|---|---:|---:|---:|
| `create_image/generate` | 구현 | 구현 | `create_managed_image_asset`로 구현 |
| `create_image/edit` | 구현 | 구현 | 소유 자산 `reference_image_ids`로 구현 |
| `create_game_ui_assets/default` | 구현 | 구현 | `create_game_ui_assets` 2×2 계약으로 구현 |
| `create_character_sheet/turnaround` | 구현 | 구현 | 미공개 |
| `create_character_sheet/expressions` | 구현 | 구현 | 미공개 |
| `create_storyboard/default` | 구현 | 구현 | 미공개 |
| `remove_background/default` | 구현 | 구현 | 미공개 |
| `separate_layers/default` | 구현 | 구현 | 미공개 |
| `generate_music/default` | 구현 | 구현 | 미공개 |

`app/schemas/capability_requests.py`의 모델 존재가 MCP 공개를 뜻하지 않습니다. MCP에는
도구 구현, 소유권 검증, 결과 변환, 클라이언트 호환 테스트가 완료된 항목만 노출합니다.

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
create_game_ui_assets         → GameUI_Elements
create_character_sheet        → Turnaround / Expression workflow
create_storyboard             → Storyboard workflow
remove_background             → RMBG2
separate_layers               → seethrough-basic
generate_music                → AceStep15XL
```

왼쪽 계약은 안정적으로 유지하고 오른쪽 workflow, provider, model은 서버 내부에서
교체할 수 있습니다. `NanoBanana` 이름은 현재 OpenRouter workflow의 호환용 ID입니다.

각 Job에는 source, principal, 검증된 client IP, request/idempotency ID, capability,
variant, resolved workflow/provider/model을 저장합니다. `X-Forwarded-For`는 바로 앞 peer가
`TRUSTED_PROXY_CIDRS`에 속할 때만 사용합니다.

## capability별 핵심 제약

- 이미지 편집은 최소 한 개의 `reference_image_ids`가 필요합니다.
- MCP 참고 이미지는 호출자의 active `image` 또는 `input` 자산이어야 하며 enqueue 전에
  소유권과 실제 파일 존재를 확인합니다.
- MCP 첨부 등록은 PNG/JPEG/WEBP만 허용하고 공통 입력 제한과 카탈로그 저장을 사용합니다.
- Game UI는 현재 `2x2`, 참고 이미지 최대 3장, 2K만 지원합니다.
- 턴어라운드는 3·5·8뷰, 표정 시트는 4·9개 계약을 사용합니다.
- 스토리보드는 참고 이미지 한 장과 6·9컷을 사용합니다.
- 현재 일반 배경 제거 웹 구현은 RMBG입니다. Game UI의 크로마→알파 후처리와는
  별개의 경로입니다.
- See-Through는 PSD 레이어 분리라는 특수 결과 형식을 유지합니다.

## 운영 통제

웹과 MCP 생성은 모두 `GenerationControlService`를 통과합니다.

- 전사 일일 요청 및 예상 비용 한도
- source + principal + idempotency key 범위의 중복 방지
- 전체, MCP, capability별 kill switch
- capability 또는 예상 비용 임계값 기반 확인
- 승인·거절·중복·Job 상태 감사 이벤트
- 예상 비용 예약과 provider 실제 비용 기록

`GENERATION_ENABLED=false`, `MCP_GENERATION_ENABLED=false`는 환경 수준의 hard stop이며
DB의 관리자 설정으로 다시 켤 수 없습니다. 가격은 코드에 고정하지 않고 운영 설정의
`GENERATION_COST_ESTIMATES_JSON` 또는 관리자 정책으로 관리합니다.

관리 API:

- `GET/PUT /api/v1/admin/generation-controls/policy`
- `GET /api/v1/admin/generation-controls/summary`
- `GET /api/v1/admin/generation-controls/events`
