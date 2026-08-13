# 내부 MCP 서버

> 서버 이름: `LC AI Canvas`
>
> 구현 버전: `0.4.0`
>
> 전송: Streamable HTTP `/mcp/`

## 현재 공개 도구

| 도구 | 역할 | 쓰기·비용 경계 |
|---|---|---|
| `list_generation_capabilities` | 공개 생성 capability 목록 | 읽기 전용 |
| `get_generation_capability` | capability 입력·출력 계약 | 읽기 전용 |
| `list_image_assets` | 소유한 active image/input 목록 | 읽기 전용 |
| `get_image_asset` | 소유 자산 메타데이터와 이미지 content | 읽기 전용 |
| `create_input_image_asset` | 클라이언트 첨부를 input 자산으로 등록 | 로컬 자산 쓰기, provider 비용 없음 |
| `create_managed_image_asset` | 기본 생성 또는 소유 자산 참고 편집 | 비동기 생성, provider 비용 발생 가능 |
| `create_game_ui_assets` | 고정 2×2 Game UI 그룹 생성 | 비동기 생성, provider 비용 발생 가능 |
| `get_generation_job` | 소유 작업 상태 조회 | 읽기 전용 |
| `get_generation_result` | 완료 결과 메타데이터와 이미지 content | 읽기 전용 |

`create_input_image_asset`은 base64 또는 PNG/JPEG/WEBP data URL 첨부를 입력 자산으로
등록합니다. `mime_type`은 data URL 사용 여부와 무관하게 필수이고 실제 디코딩 형식과
일치해야 하며 `filename`은 선택입니다. byte·pixel 제한, EXIF 방향, PNG 정규화를
적용하고 동일 소유자·동일 정규화 SHA-256 재시도는 기존 active 입력을 반환합니다.

`create_managed_image_asset`은 `reference_image_ids`를 생략하면 텍스트→이미지, 소유한
active 이미지 또는 입력 자산 ID를 넣으면 기존 이미지 편집으로 실행됩니다.
`create_game_ui_assets`는 현재 검증된 2×2/4개/2K 계약만 공개하며 child 이미지 4개와
그룹 ZIP을 생성합니다. 자산 목록·조회는 현재 MCP IP principal 소유 범위만 반환하며
휴지통과 다른 소유자의 존재를 노출하지 않습니다.

캐릭터 시트, 스토리보드, 배경 제거, 레이어 분리, 음악 생성은 내부 capability 계약만
유지합니다. MCP용 파라미터 매핑과 결과 형식·클라이언트 테스트가 끝나지 않아 아직
도구로 공개하지 않습니다.

`create_managed_image_asset`은 웹과 같은 dispatcher, 생성 통제, 멱등성 저장소, 큐,
감사 로그, 비용 추적, `AssetService` 저장 경로를 사용합니다. 완료 결과는 구조화
메타데이터와 MCP 이미지 content를 함께 반환합니다.

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
4. 의도별로 안정적인 `idempotency_key`를 만들고 이미지 또는 Game UI 생성 도구 호출
5. 편집이면 확인한 ID를 `reference_image_ids`에 넣음
6. `get_generation_job`을 완료 또는 오류까지 polling
7. 완료 후 `get_generation_result`
8. 비용 확인이 요구되면 사용자에게 확인하고 같은 키로 `cost_confirmed=true` 재호출

같은 사용자 의도의 네트워크 재시도는 새 키를 만들지 않습니다.

## 네트워크와 신원

현재 MCP 프로토콜 계층에는 OAuth가 없습니다. 인프라의 방화벽 또는 리버스 프록시가
`/mcp`를 회사 네트워크에서만 접근 가능하게 만들어야 합니다.

- `TRUSTED_PROXY_CIDRS`: `X-Forwarded-For`를 제공할 수 있는 신뢰 프록시
- `MCP_ALLOWED_CLIENT_CIDRS`: 선택적 애플리케이션 2차 허용 목록
- `MCP_PUBLIC_BASE_URL`: 결과에 넣을 절대 URL origin

MCP principal은 서버가 해석한 클라이언트 IP의 해시입니다. 요청 본문의 principal이나
IP는 신뢰하지 않습니다. NAT는 여러 사용자를 합칠 수 있고 DHCP 변경은 동일 사용자를
다르게 만들 수 있으므로, 사람 단위 권한이 필요해지면 OAuth 또는 identity-aware
proxy로 교체해야 합니다. capability 및 도구 계약은 그 교체와 독립적입니다.

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
도구는 확인하도록 tool annotation 경계와 맞춥니다. 설정 후 클라이언트를 재시작하고
`codex mcp list` 또는 세션의 `/mcp`로 연결을 확인합니다. 현재 내부망 단계에서는 bearer
token이나 OAuth 설정을 사용하지 않습니다. 형식은 [공식 Codex MCP 문서](https://developers.openai.com/codex/mcp/)를
기준으로 확인합니다.

## 다음 MCP 단계

1. 실프로젝트 표본으로 Game UI MCP 품질과 그룹 다운로드 호환성 검증
2. 캐릭터 시트·스토리보드 등 특화 capability를 개별 안정화 후 공개
3. 확인 절차가 있는 삭제·관리 도구

삭제 도구는 초기 읽기·생성 단계에 포함하지 않습니다.
