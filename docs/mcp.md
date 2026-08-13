# Internal MCP server

The application exposes a Streamable HTTP MCP endpoint at `/mcp` (a trailing
slash redirect is normal). The MVP intentionally exposes only the stable hosted
API text-to-image flow as a write tool. Game UI assets and specialized workflows
remain outside MCP until their contracts are stable.

Available tools:

- `list_generation_capabilities`
- `get_generation_capability`
- `create_image`
- `get_generation_job`
- `get_generation_result`

`create_image` enters the same capability dispatcher, generation controls,
idempotency store, queue, audit log, and cost tracking used by the web UI.
Callers are isolated by a deterministic principal derived from the resolved
client IP. The raw resolved IP is retained in generation audit records.
`get_generation_result` returns both structured result metadata and the image
itself as MCP image content, so an agent does not need the legacy browser cookie
to inspect the finished output.

## Network and identity

This deployment does not use MCP OAuth yet. The reverse proxy or firewall must
allow `/mcp` only from the company network. Set `TRUSTED_PROXY_CIDRS` before
trusting `X-Forwarded-For`. `MCP_ALLOWED_CLIENT_CIDRS` adds an optional in-app
allowlist, but is not a replacement for the network rule.

IP identity identifies a network endpoint, not necessarily a person. Shared
NAT, DHCP reassignment, or proxy misconfiguration can merge callers. OAuth or a
trusted identity-aware proxy can replace this later without changing tool
contracts.

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
