# 내부 MCP 서버

> 최종 업데이트: 2026-08-17
>
> 서버 이름: `LC AI Canvas`
>
> 구현 버전: `0.7.0`
>
> 전송: Streamable HTTP `/mcp/`

2026-08-17 검증 워크스테이션에서 endpoint 초기화 HTTP 200, Codex 공유 설정의
`lc_ai_canvas` 등록·활성화, 현재 13개 도구와 5개 공개 생성 capability를 확인했습니다.
읽기, 첨부 중복 제거, 멱등성 재시도, 1K 기본 생성·참고 편집, Game UI low 2×2,
캐릭터 턴어라운드·표정 시트·스토리보드, 로컬 RMBG 배경 제거, job/result polling,
이미지 content와 그룹 ZIP 다운로드가 통과했습니다.

## 현재 공개 도구

| 도구 | 역할 | 쓰기·비용 경계 |
|---|---|---|
| `list_generation_capabilities` | 공개 생성 capability 목록 | 읽기 전용 |
| `get_generation_capability` | capability 입력·출력 계약 | 읽기 전용 |
| `plan_generation` | 비용 없는 옵션 계획·모호성 판정과 단기 plan ID 발급 | 읽기 전용, provider 비용 없음 |
| `list_image_assets` | 소유한 active image/input 목록 | 읽기 전용 |
| `get_image_asset` | 소유 자산 메타데이터와 이미지 content | 읽기 전용 |
| `create_input_image_asset` | 클라이언트 첨부를 input 자산으로 등록 | 로컬 자산 쓰기, provider 비용 없음 |
| `create_managed_image_asset` | 기본 생성 또는 소유 자산 참고 편집 | 비동기 생성, provider 비용 발생 가능 |
| `create_game_ui_assets` | 고정 2×2 Game UI 그룹 생성 | 비동기 생성, provider 비용 발생 가능 |
| `create_character_sheet` | 참고 캐릭터의 턴어라운드 또는 표정 시트 생성 | 비동기 생성, provider 비용 발생 가능 |
| `create_storyboard` | 참고 이미지와 이야기로 6·9컷 스토리보드 생성 | 비동기 생성, provider 비용 발생 가능 |
| `remove_background` | 소유 이미지 한 장의 배경을 고정 RMBG-2.0으로 제거 | 로컬 비동기 생성, provider API 비용 없음 |
| `get_generation_job` | 소유 작업 상태 조회 | 읽기 전용 |
| `get_generation_result` | 완료 결과 메타데이터와 이미지 content | 읽기 전용 |

모든 공개 생성 쓰기 도구는 먼저 `plan_generation`을 통과해야 합니다. OpenRouter 기반 요청에서 사용자가 모델,
비율, 크기, 품질, 개수 또는 배경 모드를 명시하지 않았거나 용도에서 명확하게 추론할 수
없다면 `selection_mode=clarify`로 호출합니다. 응답의 `missing_decisions`가 비어 있지 않으면
LLM은 항목을 한 번의 짧은 질문으로 묶어 확인해야 하며 이때는 `plan_id`가 발급되지 않습니다.

사용자가 “알아서 추천해줘”처럼 선택을 명시적으로 위임한 경우에만
`selection_mode=recommend`를 사용합니다. 준비된 계획은 30분 동안 유효한 호출자 소유
`plan_id`, 정확한 `tool_arguments`, 재시도용 `suggested_idempotency_key`를 반환합니다. 쓰기
도구에서 프롬프트·참고 자산·옵션이 계획과 달라지거나 plan ID가 없거나 만료되면 제출 전에
거절하므로 provider 비용이 발생하지 않습니다. 서버 재시작 후에는 계획을 다시 발급받습니다.

`create_input_image_asset`은 base64 또는 PNG/JPEG/WEBP data URL 첨부를 입력 자산으로
등록합니다. `mime_type`은 data URL 사용 여부와 무관하게 필수이고 실제 디코딩 형식과
일치해야 하며 `filename`은 선택입니다. byte·pixel 제한, EXIF 방향, PNG 정규화를
적용하고 동일 소유자·동일 정규화 SHA-256 재시도는 기존 active 입력을 반환합니다.

`create_managed_image_asset`은 `reference_image_ids`를 생략하면 텍스트→이미지, 소유한
active 이미지 또는 입력 자산 ID를 넣으면 기존 이미지 편집으로 실행됩니다.
일반 이미지 MCP는 Nano Banana Pro, Nano Banana 2, Nano Banana 2 Lite, GPT Image 2를
명시적으로 선택할 수 있습니다. 비율은 square·landscape·portrait이며 참고 이미지 편집은
원본 비율을 유지하는 auto를 추가로 지원합니다. 크기는 모델별 1K·2K이고 GPT Image 2만
low·medium·high 품질 선택을 추가로 요구합니다. Lite는 1K 전용입니다.
`create_game_ui_assets`는 웹의 3×3·4×4 선택과 별개로 현재 검증된 2×2/4개/2K 계약만
공개하며 child 이미지 4개와 그룹 ZIP을 생성합니다. 자산 목록·조회는 현재 MCP IP
principal 소유 범위만 반환하며 휴지통과 다른 소유자의 존재를 노출하지 않습니다.

`create_character_sheet`는 호출자 소유의 active 참고 이미지 한 장을 필수로 받고,
턴어라운드 3·5·8뷰 또는 표정 4·9개를 한 장의 시트로 만듭니다. `create_storyboard`도
소유 참고 이미지 한 장을 필수로 받고 6컷 2×3 또는 9컷 3×3 시트를 만듭니다. 현재 MCP
구현은 서버 선택 GPT Image 2를 사용합니다. 1K/low는 저비용 계약 확인용 초안이며,
모호한 크기·품질·개수는 계획 단계에서 확인하거나 사용자가 선택을 위임한 경우에만
2K/medium 권장값을 적용합니다.

2026-08-17 실클라이언트 1K/low 표본은 턴어라운드 3뷰, 표정 2×2/4개, 스토리보드
2×3/6컷을 정확히 생성했고 모두 MCP image content로 반환됐습니다. actual cost는 각각
`$0.009739`, `$0.011109`, `$0.010429`였습니다. 스토리보드 표본은 정확한 6패널과
연속성을 유지했지만 자동 gutter 제거는 `separator_detection_failed` fallback이어서 얇은
패널 구분선이 남았습니다.

같은 날 MCP 0.6.0 운영 실클라이언트에서 12개 도구와 `plan_generation`을 다시 확인했습니다.
모호한 일반 이미지 요청은 모델·비율·크기를 `missing_decisions`로 반환하고 plan ID를 발급하지
않았으며, 선택 위임 요청은 Nano Banana 2·square·1K 권장 계획을 발급했습니다. GPT Image 2
landscape·1K·low 명시 계획도 입력을 그대로 고정했고, 계획 없는 쓰기 호출은 큐 등록 전에
거절됐습니다. 이 검증은 provider 생성 도구를 호출하지 않아 추가 API 비용이 없습니다.

`remove_background`는 호출자 소유의 active image/input 한 장을 요구하며 로컬 ComfyUI의
`RMBG2` workflow와 `RMBG-2.0` 모델로 고정됩니다. `mask_blur=0`, `mask_offset=0`이 안전한
기본값이고 각각 0~64, -64~64 범위에서 계획 단계에 명시할 수 있습니다. 외부 provider API
비용은 정확히 `$0.00`이지만 로컬 GPU 시간과 인프라 자원은 소비합니다. See-Through 레이어
분리와 ACE-Step 음악 생성은 장시간 로컬 workflow이므로 MCP 비공개 상태를 유지합니다.

2026-08-17 운영 Streamable HTTP에서 MCP 0.7.0 초기화, 13개 도구와 5개 공개 capability를
확인한 뒤 실제 RMBG 작업을 두 번 실행했습니다. 첫 작업
`96c09f9834e64d0380e4a6ec1a67af47`은 약 4.6초, warm 반복
`4e0619bfb85a4424ababeb6e430bce58`은 약 1.2초에 완료됐습니다. 256×256 RGBA PNG,
알파 범위 0~255, MCP text+image content, provider `comfyui`, model `RMBG-2.0`, 예상 비용
`0.0`을 확인했습니다. 동일 plan·멱등성 키 재호출은 새 작업 없이 기존 job을 반환했습니다.
이 검증은 외부 provider API를 호출하지 않았습니다.

같은 날 격리 DB·outputs에서 실제 RMBG 두 작업을 즉시 연속 제출한 단일 큐 스모크도
통과했습니다. 제출 직후 상태는 각각 running·queued였고 첫 작업 0.971초, 둘째 0.413초,
작업 사이 간격 0.036초로 실행 구간이 겹치지 않았습니다. MCP image content 2건과 완료된
ComfyUI provider API actual cost `0.0` 기록 2건, 비용 미수집 0건을 확인했으며 임시 자산은
종료 시 제거했습니다.

`create_managed_image_asset`은 웹과 같은 dispatcher, 생성 통제, 멱등성 저장소, 큐,
감사 로그, 비용 추적, `AssetService` 저장 경로를 사용합니다. 완료 결과는 구조화
메타데이터와 MCP 이미지 content를 함께 반환합니다.

## 대화에서의 도구 선택과 확인

LLM은 사용자의 목적이 명확하면 불필요한 모델 질문을 만들지 않고, 목적이나 비용 경계가
달라질 때만 확인합니다.

- “배경 지워줘”, “누끼 따줘”, “투명 PNG로 만들어줘”: `remove_background`를 선택하고
  기본 `mask_blur=0`, `mask_offset=0`으로 계획합니다. 원본을 덮어쓰지 않고 새 PNG를
  만들며 외부 provider API 비용이 없으므로 별도 비용 질문은 필요하지 않습니다. 클라이언트의
  일반 쓰기 승인 UI는 표시될 수 있습니다.
- “배경 정리해줘”: 제거·교체·흐림 중 의미가 모호하므로 한 번의 짧은 질문으로 확인합니다.
- 새로운 장면으로 배경 교체: 현재 managed 이미지 편집 API를 사용하므로 모델·비율·크기와
  GPT Image 2 품질 중 빠진 결정을 묶어서 질문하고 provider 비용 발생 사실을 알립니다.
- 단순 배경 흐림 또는 사용자가 제공한 배경과의 합성: 현재 전용 로컬 MCP 도구가 없어
  managed 이미지 편집으로 처리하면 provider 비용이 발생합니다. RMBG 마스크를 이용한 로컬
  후처리는 향후 선택 기능이며 현재 1차 필수 범위가 아닙니다.

사용자가 모델·크기·품질과 실행 의사를 이미 명확히 밝혔으면 같은 내용을 반복해서 묻지
않습니다. “가장 저렴하게 알아서”처럼 선택을 위임한 경우에만 `selection_mode=recommend`를
사용합니다. 그 외 hosted 모호성은 `selection_mode=clarify`로 해결합니다.

생성 제출 응답의 `estimated_cost_usd`는 운영 가격표가 일치할 때만 숫자입니다. 가격표가
없으면 `null`, `cost_estimate_available=false`이며 무료라는 뜻이 아닙니다. 단, ComfyUI 로컬
workflow는 외부 provider 비용이 없으므로 알려진 값 `0.0`을 반환합니다. 완료 후
provider actual cost는 관리자 `사용·비용 통계`에서 IP·기능·모델별로 집계됩니다.

이 도구는 클라이언트의 일반 이미지 생성기를 대체하기 위한 것이 아닙니다. 다음
경우에 사용합니다.

- 클라이언트에 자체 이미지 생성 기능이 없음
- 회사 비용·감사·저장 정책이 필요한 결과
- LC AI Canvas 또는 사내 생성기를 사용하라는 명시적 요청
- 향후 사내 전용 capability가 필요한 작업

자체 이미지 생성기가 있는 클라이언트의 일회성 이미지에는 기본 도구를 우선할 수
있습니다.

## 호출 흐름

1. `list_generation_capabilities` 또는 `get_generation_capability`
2. 클라이언트 첨부가 필요하면 `create_input_image_asset`으로 등록
3. 기존 참고 이미지가 필요하면 `list_image_assets`와 `get_image_asset`으로 소유 자산 확인
4. 명시·추론 가능한 선택만 넣어 `plan_generation(selection_mode=clarify)` 호출
5. `missing_decisions`가 있으면 한 번에 묶어 사용자에게 질문하고 다시 계획
6. 사용자가 선택을 위임한 경우에만 `selection_mode=recommend` 사용
7. 준비된 계획의 `tool_arguments`, `plan_id`, `suggested_idempotency_key`로 해당 생성 도구 호출
8. `get_generation_job`을 완료 또는 오류까지 polling
9. 완료 후 `get_generation_result`
10. hosted 비용 확인이 요구되면 사용자에게 확인하고 같은 계획·키로
    `cost_confirmed=true` 재호출

같은 사용자 의도의 네트워크 재시도는 새 키를 만들지 않습니다.

## 네트워크와 신원

현재 운영 결정은 OAuth 없이 사내망에서 확인한 클라이언트 IP의 해시를 principal과 감사
기준으로 사용하는 것입니다. 인프라의 방화벽 또는 리버스 프록시가 `/mcp`를 회사
네트워크에서만 접근 가능하게 만들어야 합니다.

- `TRUSTED_PROXY_CIDRS`: `X-Forwarded-For`를 제공할 수 있는 신뢰 프록시
- `MCP_ALLOWED_CLIENT_CIDRS`: 선택적 애플리케이션 2차 허용 목록
- `MCP_WEB_LINK_ENABLED`: 같은 IP의 웹 사용자가 MCP 생성 이미지 보기를 명시적으로 연결
- `MCP_PUBLIC_BASE_URL`: 결과에 넣을 절대 URL origin

MCP principal은 서버가 해석한 클라이언트 IP의 해시입니다. 요청 본문의 principal이나
IP는 신뢰하지 않습니다. NAT가 여러 사용자를 합치거나 DHCP 변경이 동일 사용자를 다르게
만들 수 있는 제약은 현재 사내망 운영에서 수용합니다. 사람 단위 인증 전환은 현재 계획에
포함하지 않습니다.

IP principal 운영은 다음을 인프라팀의 명시적 운영 전제로 둡니다.

- 사용자 PC별 원본 IP가 동시에 고유하고 서버까지 그대로 전달될 것
- DHCP 예약·고정 IP 또는 재할당 이력으로 과거 IP 소유자를 필요할 때 확인할 수 있을 것
- VPN·프록시를 도입하면 원본 IP를 보존하고 해당 프록시만 `TRUSTED_PROXY_CIDRS`에 넣을 것
- 8000 포트와 `/mcp`를 승인된 사내망에서만 접근 가능하게 제한할 것
- PC 교체·퇴사·IP 재할당 시 이전 MCP 자산과 비용 이력의 취급을 인프라 운영 절차로 관리할 것

이 전제가 유지되면 초기 운영에 별도 OAuth나 인증용 계정 pairing은 필요하지 않습니다.
`MCP_ALLOWED_CLIENT_CIDRS`는 인프라 방화벽을 대체하지 않는 선택적 2차 방어입니다.

2026-08-17 검증 호스트는 고정 사설 IPv4의 `/24` 사내망에서 리버스 프록시 없이
`0.0.0.0:8000`으로 직접 서비스하고, ComfyUI만 `127.0.0.1:8188`로 제한합니다. 서버 기록에서
로컬 MCP와 다른 PC의 웹 요청이 서로 다른 원본 IP로 구분됐습니다. 검증 호스트의
`TRUSTED_PROXY_CIDRS`와 `MCP_ALLOWED_CLIENT_CIDRS`는 비어 있어 현재 접근 경계는 사내망과
호스트 방화벽에 의존합니다. 네트워크 구조가 바뀌면 이 가정을 다시 검증합니다.

웹의 서명 쿠키 principal과 MCP IP principal은 자동 병합되지 않습니다. 대신
`MCP_WEB_LINK_ENABLED=true`이면 같은 원본 IP에 MCP 생성 이미지가 있을 때 웹 갤러리에
“이 PC에서 만든 AI 이미지” 안내가 나타나며 사용자가 한 번 `연결하기`를 누를 수 있습니다.
요청 본문으로 대상 MCP ID를 고를 수 없고 서버가 현재 IP에서 직접 계산합니다.

연결은 SQLite에 계속 유지되며 서버·Codex·브라우저 재시작으로 풀리지 않습니다. MCP 원본
owner와 감사 기록은 바꾸지 않고 생성 이미지만 웹 갤러리에 `MCP`로 표시합니다. 웹에서
삭제·쇼케이스 공유는 막고, 편집에 쓰면 웹 input 복사본을 만듭니다. 연결 해제는 목록 관계만
지우며 원본을 삭제하지 않습니다. 한 MCP workspace가 다른 웹 principal에 이미 연결돼 있으면
409로 자동 takeover를 차단합니다. IP·브라우저 쿠키가 바뀌면 다시 연결하거나 인프라의
재할당 이력을 확인합니다.

2026-08-17 실제 동일 PC의 웹 갤러리에서 연결 안내와 `연결하기`를 사용한 뒤 기존 MCP
생성 이미지 2개가 `MCP` 표시와 함께 나타나는 것을 확인했습니다. 이 수동 확인은
웹 principal로의 owner 이전 없이 조회 관계만 추가된 상태에서 수행했습니다.

연결 후에도 MCP `list_image_assets`에 기존 웹 자산을 역으로 합치지 않습니다. 따라서 최초
MCP 목록이 비어 있어도 연결 오류가 아니며, 웹→MCP 자산 공유가 필요하면 MCP 첨부 등록을
사용합니다.

MCP 클라이언트는 브라우저 beta 쿠키를 사용할 수 없으므로 MCP IP 소유의 `/outputs/users`
URL은 서버가 요청 IP와 경로의 소유자를 먼저 대조한 경우 beta gate를 통과합니다. 웹은
유효한 서명 쿠키와 명시적 연결 관계가 있을 때 연결된 MCP 미디어를 열 수 있습니다. 관계없는
IP·웹 principal의 요청과 JSON sidecar는 계속 404를 반환합니다. 일반 웹 페이지와 웹
principal 출력의 beta·서명 쿠키 경계는 그대로 유지합니다.

## 클라이언트 지원 기준

- Claude Code: 자체 이미지 생성이 없는 환경에 관리형 생성을 추가
- Codex: 회사 비용·감사·저장 경계가 필요한 작업에 사용
- 다른 MCP 클라이언트: Streamable HTTP와 tool annotation 호환성을 확인한 뒤 지원

응답은 표준 JSON schema, tool annotation, text/image content를 사용합니다. 검증된
필요가 없으면 특정 클라이언트 전용 응답 포맷을 추가하지 않습니다.

## Claude Code 설정

회사 네트워크에 연결된 워크스테이션에서 실행합니다.

```powershell
$McpUrl = "http://SERVER_IP:8000/mcp/"  # 실제 사내 주소로 교체
claude mcp add --transport http lc_ai_canvas $McpUrl
claude mcp get lc_ai_canvas
```

기본 scope는 현재 프로젝트에 대한 local 설정입니다. 여러 신뢰 프로젝트에서 공통으로
사용할 때만 `--scope user`를 추가합니다. Claude Code의 현재 HTTP transport와 scope
형식은 [공식 MCP 문서](https://code.claude.com/docs/en/mcp)를 기준으로 확인합니다.

Claude.ai 웹 서비스는 사설 IP에 직접 접근할 수 없습니다. 웹 연결이 필요하면 인프라가
승인한 접근 가능한 도메인, 인증, 별도 보안 검토가 필요합니다.

예시:

- “회사 이미지 생성기로 파란 수정 아이콘을 만들고 결과를 보여줘.”
- “LC AI Canvas를 사용해 16:9 배경 시안을 만들고 완료될 때까지 확인해줘.”
- “회사 비용과 감사 로그가 남도록 이 설명으로 이미지 자산을 생성해줘.”

## Codex 설정

사용자 또는 신뢰할 수 있는 프로젝트의 `config.toml`에 추가합니다.

```toml
[mcp_servers.lc_ai_canvas]
url = "https://ai-canvas.internal.example.com/mcp/"
default_tools_approval_mode = "writes"
```

사용자 설정은 `~/.codex/config.toml`, 신뢰한 프로젝트 설정은 `.codex/config.toml`을
사용합니다. `default_tools_approval_mode = "writes"`는 읽기 도구는 바로 쓰고 첨부·생성
도구는 확인하도록 tool annotation 경계와 맞춥니다. VS Code에서는 Codex 설정의
`MCP servers`에서 등록 상태를 확인하고 확장을 재시작하거나 명령 팔레트의
`Developer: Reload Window`를 실행합니다. 기존 대화가 새 도구 목록을 읽지 못하면 새
Codex 대화를 시작합니다. CLI의 `codex mcp get lc_ai_canvas`와 `codex mcp list`도 같은
공유 설정을 확인합니다. 현재 IP 기반 사내망 운영에서는 bearer token이나 OAuth 설정을
사용하지 않습니다. 형식은 [공식 Codex MCP 문서](https://developers.openai.com/codex/mcp/)를 기준으로
확인합니다.

## 운영 중 조정·선택 기능

1. 실사용 actual cost 표본을 더 모아 모델·크기·품질별 보수적 사전 비용 가격표 설정
2. 스토리보드 gutter 제거 fallback 표본을 더 모으고 필요 시 검출 보강
3. 공개 RMBG 배경 제거의 로컬 단일 큐 장시간·다사용자 운영 표본 확대;
   2건 연속 실행은 통과했으며 See-Through·ACE-Step은 비공개 유지
4. 필요성이 확인될 때만 명시적 확인이 있는 휴지통 이동·작업 취소 도구 검토

현재 합의한 1차 기능 범위에 운영을 막는 필수 누락은 없습니다. 위 항목은 실사용 표본과
불편이 확인될 때 조정할 운영·품질·선택 기능입니다. 영구 삭제와 관리자 정책 변경은 MCP에
공개하지 않으며, 삭제 도구도 초기 읽기·생성 단계의 필수 항목이 아닙니다.
