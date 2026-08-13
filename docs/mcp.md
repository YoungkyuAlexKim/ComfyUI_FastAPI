# Internal MCP server

The application exposes a Streamable HTTP MCP endpoint at `/mcp` (a trailing
slash redirect is normal). The MVP intentionally exposes only the stable hosted
API text-to-image flow as a write tool. Game UI assets and specialized workflows
remain outside MCP until their contracts are stable.

Available tools:

- `list_generation_capabilities`
- `get_generation_capability`
- `create_managed_image_asset`
- `get_generation_job`
- `get_generation_result`

`create_managed_image_asset` enters the same capability dispatcher, generation controls,
idempotency store, queue, audit log, and cost tracking used by the web UI.
Callers are isolated by a deterministic principal derived from the resolved
client IP. The raw resolved IP is retained in generation audit records.
`get_generation_result` returns both structured result metadata and the image
itself as MCP image content, so an agent does not need the legacy browser cookie
to inspect the finished output.

The managed tool is not intended to compete with a client's built-in ad-hoc
image generator. Use it when the client has no native image generator, or when
the user needs company billing, audit records, LC AI Canvas storage, or a
company-specific workflow. The internal provider capability remains
`create_image`; the public MCP name describes the managed product behavior.

## Network and identity

This deployment does not use MCP OAuth yet. The reverse proxy or firewall must
allow `/mcp` only from the company network. Set `TRUSTED_PROXY_CIDRS` before
trusting `X-Forwarded-For`. `MCP_ALLOWED_CLIENT_CIDRS` adds an optional in-app
allowlist, but is not a replacement for the network rule.

IP identity identifies a network endpoint, not necessarily a person. Shared
NAT, DHCP reassignment, or proxy misconfiguration can merge callers. OAuth or a
trusted identity-aware proxy can replace this later without changing tool
contracts.

## Client priority and compatibility

The initial rollout order is:

1. **Claude Code** — adds image generation to a client that does not natively
   produce image output. The current internal-only server can be reached by
   Claude Code running on a company-network workstation.
2. **Codex** — use the MCP tool for managed company output; prefer Codex's native
   image generator for ad-hoc images that do not need the company pipeline.
3. Other MCP clients after protocol validation.

The server stays client-neutral by using Streamable HTTP, standard JSON schemas
and tool annotations, asynchronous job polling, and standard text plus image
tool results. Do not add client-specific response formats unless there is a
tested compatibility requirement.

## Claude Code configuration

Run this on a workstation connected to the company network:

```bash
claude mcp add --transport http lc_ai_canvas http://10.100.90.242:8000/mcp/
```

Then verify it with `claude mcp get lc_ai_canvas`. Claude.ai and its web connector
cannot use a private company-network address directly; that later rollout will
need an approved reachable endpoint or secure tunnel and a separate security
review.

Example requests:

- "회사 이미지 생성기로 파란 수정 아이콘을 만들고 결과를 보여줘."
- "LC AI Canvas를 사용해 16:9 배경 시안을 만들고 작업이 끝날 때까지 확인해줘."
- "회사 비용과 감사 로그가 남도록 이 설명으로 이미지 에셋을 생성해줘."

## Codex configuration

Add this to the user or trusted project `config.toml`, replacing the URL with
the internal domain:

```toml
[mcp_servers.lc_ai_canvas]
url = "https://ai-canvas.internal.example.com/mcp"
```

Restart Codex or open a new session after changing MCP configuration. The server
is intentionally unauthenticated at the protocol layer in this internal-network
phase, so no bearer-token or OAuth setting is required.
