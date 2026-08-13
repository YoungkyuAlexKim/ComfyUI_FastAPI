# 내부 MCP 서버

> 서버 이름: `LC AI Canvas`
>
> 구현 버전: `0.2.0`
>
> 전송: Streamable HTTP `/mcp/`

## 현재 공개 도구

- `list_generation_capabilities`
- `get_generation_capability`
- `create_managed_image_asset`
- `get_generation_job`
- `get_generation_result`

현재 쓰기 도구는 관리형 텍스트→이미지 생성 하나입니다. 참고 이미지 편집, Game UI,
캐릭터 시트, 스토리보드, 갤러리 조회는 내부 capability 계약만 준비되어 있고 MCP
도구로 아직 공개하지 않았습니다.

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
2. 의도별로 안정적인 `idempotency_key`를 만들고 `create_managed_image_asset`
3. `get_generation_job`을 완료 또는 오류까지 polling
4. 완료 후 `get_generation_result`
5. 비용 확인이 요구되면 사용자에게 확인하고 같은 키로 `cost_confirmed=true` 재호출

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

## 권장 클라이언트 순서

1. Claude Code: 자체 이미지 생성이 없는 클라이언트에 관리형 생성을 추가
2. Codex: 회사 관리형 출력이 필요할 때 사용
3. 다른 MCP 클라이언트: Streamable HTTP 호환성 확인 후 지원

응답은 표준 JSON schema, tool annotation, text/image content를 사용합니다. 검증된
필요가 없으면 특정 클라이언트 전용 응답 포맷을 추가하지 않습니다.

## Claude Code 설정

회사 네트워크에 연결된 워크스테이션에서 실행합니다.

```bash
claude mcp add --transport http lc_ai_canvas http://10.100.90.242:8000/mcp/
claude mcp get lc_ai_canvas
```

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
```

설정 후 새 세션을 엽니다. 현재 내부망 단계에서는 bearer token이나 OAuth 설정을
사용하지 않습니다.

## 다음 MCP 단계

1. 소유자 범위의 자산 목록·조회
2. 기존 자산 ID를 참고 이미지로 쓰는 생성·편집
3. 클라이언트 첨부 이미지를 입력 자산으로 등록
4. 안정화된 Game UI와 특화 capability 공개
5. 확인 절차가 있는 삭제·관리 도구

삭제 도구는 초기 읽기·생성 단계에 포함하지 않습니다.
