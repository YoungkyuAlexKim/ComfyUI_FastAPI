"""Internal-network MCP facade for stable generation capabilities."""

from __future__ import annotations

from contextvars import ContextVar
from dataclasses import dataclass
import hashlib
import ipaddress
import json
import os
from pathlib import Path
from typing import Annotated, Any, Literal
import uuid

from mcp.server import MCPServer
from mcp.server.mcpserver.utilities.types import Image as McpImage
from mcp.types import CallToolResult, TextContent, ToolAnnotations
from pydantic import Field

from .config import SERVER_CONFIG
from .services.generation_commands import (
    DEFAULT_CAPABILITY_DISPATCHER,
    GenerationCommand,
    GenerationContext,
    resolve_client_ip,
)
from .services.generation_controls import GenerationPolicyError
from .services.generation_submission import GenerationSubmissionService


@dataclass(frozen=True)
class McpCaller:
    principal_id: str
    client_ip: str
    client_ip_source: str
    base_url: str


_caller_context: ContextVar[McpCaller | None] = ContextVar("mcp_caller", default=None)


def _principal_for_ip(client_ip: str) -> str:
    digest = hashlib.sha256(f"mcp-ip:{client_ip}".encode("utf-8")).hexdigest()[:24]
    return f"mcp-ip-{digest}"


def _parse_allowed_networks(raw_value: str | None) -> tuple[ipaddress._BaseNetwork, ...]:
    networks: list[ipaddress._BaseNetwork] = []
    for raw_part in str(raw_value or "").split(","):
        part = raw_part.strip()
        if part:
            networks.append(ipaddress.ip_network(part, strict=False))
    return tuple(networks)


class McpRequestContextMiddleware:
    """Resolve the socket IP once and make it available to MCP tool tasks."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return

        headers = {
            key.decode("latin-1").lower(): value.decode("latin-1")
            for key, value in scope.get("headers", [])
        }
        client = scope.get("client") or (None, None)
        client_ip, client_ip_source = resolve_client_ip(
            client[0],
            headers.get("x-forwarded-for"),
            os.getenv("TRUSTED_PROXY_CIDRS"),
        )
        try:
            allowed_networks = _parse_allowed_networks(os.getenv("MCP_ALLOWED_CLIENT_CIDRS"))
        except ValueError:
            body = b'{"detail":"mcp_client_cidr_policy_invalid"}'
            await send(
                {
                    "type": "http.response.start",
                    "status": 503,
                    "headers": [
                        (b"content-type", b"application/json"),
                        (b"content-length", str(len(body)).encode("ascii")),
                    ],
                }
            )
            await send({"type": "http.response.body", "body": body})
            return
        if allowed_networks:
            try:
                allowed = any(ipaddress.ip_address(client_ip) in network for network in allowed_networks)
            except ValueError:
                allowed = False
            if not allowed:
                body = b'{"detail":"mcp_client_ip_not_allowed"}'
                await send(
                    {
                        "type": "http.response.start",
                        "status": 403,
                        "headers": [
                            (b"content-type", b"application/json"),
                            (b"content-length", str(len(body)).encode("ascii")),
                        ],
                    }
                )
                await send({"type": "http.response.body", "body": body})
                return

        configured_base = str(os.getenv("MCP_PUBLIC_BASE_URL") or "").strip().rstrip("/")
        if configured_base:
            base_url = configured_base
        else:
            scheme = str(scope.get("scheme") or "http")
            host = headers.get("host") or "127.0.0.1:8000"
            base_url = f"{scheme}://{host}"
        caller = McpCaller(
            principal_id=_principal_for_ip(client_ip),
            client_ip=client_ip,
            client_ip_source=client_ip_source,
            base_url=base_url,
        )
        token = _caller_context.set(caller)
        try:
            await self.app(scope, receive, send)
        finally:
            _caller_context.reset(token)


def _current_caller() -> McpCaller:
    caller = _caller_context.get()
    if caller is None:
        raise RuntimeError("MCP request context is unavailable")
    return caller


def _job_dict(job: Any) -> dict[str, Any]:
    if isinstance(job, dict):
        return job
    return {
        "id": job.id,
        "owner_id": job.owner_id,
        "type": job.type,
        "status": job.status,
        "progress": job.progress,
        "created_at": job.created_at,
        "started_at": job.started_at,
        "ended_at": job.ended_at,
        "error": job.error_message,
        "result": job.result,
    }


def _absolute_result(result: Any, base_url: str) -> Any:
    if isinstance(result, dict):
        converted = {key: _absolute_result(value, base_url) for key, value in result.items()}
        for key, value in list(converted.items()):
            if key.endswith("_path") and isinstance(value, str) and value.startswith("/outputs/"):
                converted[f"{key[:-5]}_url"] = f"{base_url}{value}"
        return converted
    if isinstance(result, list):
        return [_absolute_result(value, base_url) for value in result]
    return result


def _result_image_content(structured_result: dict[str, Any]):
    result = structured_result.get("result")
    web_path = result.get("image_path") if isinstance(result, dict) else None
    if not isinstance(web_path, str) or not web_path.startswith("/outputs/"):
        return None
    output_root = Path(str(SERVER_CONFIG.get("output_dir") or "./outputs")).resolve()
    candidate = (output_root / web_path[len("/outputs/") :]).resolve()
    if candidate != output_root and output_root not in candidate.parents:
        return None
    if not candidate.is_file():
        return None
    return McpImage(path=candidate).to_image_content()


class McpGenerationService:
    def __init__(self, job_manager, job_store, controls):
        self.job_manager = job_manager
        self.job_store = job_store
        self.submissions = GenerationSubmissionService(job_manager, controls)

    def create_image(
        self,
        caller: McpCaller,
        *,
        prompt: str,
        aspect_ratio: str,
        image_size: str,
        idempotency_key: str,
        cost_confirmed: bool,
    ) -> dict[str, Any]:
        context = GenerationContext(
            principal_id=caller.principal_id,
            source="mcp",
            client_ip=caller.client_ip,
            client_ip_source=caller.client_ip_source,
            request_id=uuid.uuid4().hex,
            idempotency_key=idempotency_key,
        )
        command = GenerationCommand(
            capability="create_image",
            variant="generate",
            parameters={
                "user_prompt": prompt.strip(),
                "aspect_ratio": aspect_ratio,
                "image_size": image_size,
            },
            context=context,
        )
        resolved = DEFAULT_CAPABILITY_DISPATCHER.resolve(command)
        submission = self.submissions.submit(resolved, cost_confirmed=cost_confirmed)
        return {
            "job_id": submission.job_id,
            "status": submission.status,
            "queue_position": submission.position,
            "estimated_cost_usd": submission.estimated_cost_usd,
            "duplicate": submission.duplicate,
            "next_action": "Poll get_generation_job until status is complete or error.",
        }

    def get_job(self, caller: McpCaller, job_id: str) -> dict[str, Any]:
        job = self.job_manager.get(job_id)
        if job is None and self.job_store is not None:
            job = self.job_store.fetch_by_id(job_id)
        if job is None:
            raise ValueError("Generation job not found")
        item = _job_dict(job)
        if item.get("owner_id") != caller.principal_id:
            # Do not reveal whether another caller's job exists.
            raise ValueError("Generation job not found")
        status = str(item.get("status") or "unknown")
        return {
            "job_id": item.get("id"),
            "status": status,
            "progress": float(item.get("progress") or 0),
            "created_at": item.get("created_at"),
            "started_at": item.get("started_at"),
            "ended_at": item.get("ended_at"),
            "error": item.get("error") if status in {"error", "cancelled"} else None,
            "result_ready": status == "complete",
        }

    def get_result(self, caller: McpCaller, job_id: str) -> dict[str, Any]:
        job = self.job_manager.get(job_id)
        if job is None and self.job_store is not None:
            job = self.job_store.fetch_by_id(job_id)
        if job is None:
            raise ValueError("Generation job not found")
        item = _job_dict(job)
        if item.get("owner_id") != caller.principal_id:
            raise ValueError("Generation job not found")
        status = str(item.get("status") or "unknown")
        if status != "complete":
            return {
                "job_id": item.get("id"),
                "status": status,
                "ready": False,
                "error": item.get("error") if status in {"error", "cancelled"} else None,
            }
        return {
            "job_id": item.get("id"),
            "status": status,
            "ready": True,
            "result": _absolute_result(item.get("result") or {}, caller.base_url),
        }


@dataclass(frozen=True)
class McpIntegration:
    server: MCPServer
    http_app: Any
    lifespan_context_factory: Any


def create_mcp_integration(job_manager, job_store, controls) -> McpIntegration:
    service = McpGenerationService(job_manager, job_store, controls)
    server = MCPServer(
        name="lc-ai-canvas",
        title="LC AI Canvas",
        version="0.1.0",
        instructions=(
            "Generate images only when the user asks. create_image incurs company API cost. "
            "Reuse the same idempotency_key when retrying the same intent. If cost confirmation "
            "is required, ask the user and retry with cost_confirmed=true. Poll get_generation_job, "
            "then call get_generation_result. Only create_image text-to-image is enabled in this MVP."
        ),
    )

    read_annotations = ToolAnnotations(
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=False,
    )

    @server.tool(
        title="List generation capabilities",
        description="List generation capabilities currently exposed through this MCP server.",
        annotations=read_annotations,
        structured_output=True,
    )
    async def list_generation_capabilities() -> dict[str, Any]:
        return {
            "capabilities": [
                {
                    "name": "create_image",
                    "variants": ["generate"],
                    "supports": ["text-to-image"],
                    "status": "available",
                }
            ]
        }

    @server.tool(
        title="Get generation capability schema",
        description="Get the supported inputs and behavior for one generation capability.",
        annotations=read_annotations,
        structured_output=True,
    )
    async def get_generation_capability(
        capability: Literal["create_image"],
    ) -> dict[str, Any]:
        return {
            "name": capability,
            "variant": "generate",
            "description": "Create one image from a text prompt using the hosted API image workflow.",
            "inputs": {
                "prompt": {"type": "string", "required": True, "max_length": 8000},
                "aspect_ratio": {"enum": ["square", "landscape", "portrait"], "default": "square"},
                "image_size": {"enum": ["1K", "2K"], "default": "2K"},
                "idempotency_key": {"type": "string", "required": True, "min_length": 8},
                "cost_confirmed": {"type": "boolean", "default": False},
            },
            "asynchronous": True,
        }

    @server.tool(
        title="Get generation job",
        description="Read the status and progress of a generation job created by this caller.",
        annotations=read_annotations,
        structured_output=True,
    )
    async def get_generation_job(
        job_id: Annotated[str, Field(min_length=16, max_length=64, description="Queued generation job ID")],
    ) -> dict[str, Any]:
        return service.get_job(_current_caller(), job_id)

    @server.tool(
        title="Get generation result",
        description="Read output metadata and receive the image content when a generation job is complete.",
        annotations=read_annotations,
    )
    async def get_generation_result(
        job_id: Annotated[str, Field(min_length=16, max_length=64, description="Completed generation job ID")],
    ) -> CallToolResult:
        structured = service.get_result(_current_caller(), job_id)
        content = [
            TextContent(type="text", text=json.dumps(structured, ensure_ascii=False))
        ]
        image_content = _result_image_content(structured)
        if image_content is not None:
            content.append(image_content)
        return CallToolResult(content=content, structuredContent=structured)

    @server.tool(
        title="Create image",
        description=(
            "Queue one hosted API text-to-image generation. This consumes company API budget. "
            "Use a stable unique idempotency_key per user intent and poll the returned job ID."
        ),
        annotations=ToolAnnotations(
            readOnlyHint=False,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=True,
        ),
        structured_output=True,
    )
    async def create_image(
        prompt: Annotated[str, Field(min_length=1, max_length=8000, description="Complete image request")],
        idempotency_key: Annotated[
            str,
            Field(min_length=8, max_length=128, description="Stable unique key for this generation intent"),
        ],
        aspect_ratio: Literal["square", "landscape", "portrait"] = "square",
        image_size: Literal["1K", "2K"] = "2K",
        cost_confirmed: bool = False,
    ) -> dict[str, Any]:
        try:
            return service.create_image(
                _current_caller(),
                prompt=prompt,
                aspect_ratio=aspect_ratio,
                image_size=image_size,
                idempotency_key=idempotency_key,
                cost_confirmed=cost_confirmed,
            )
        except GenerationPolicyError as exc:
            raise RuntimeError(f"{exc.code}: {exc.message}") from exc

    http_app = server.streamable_http_app(
        streamable_http_path="/",
        json_response=True,
        stateless_http=True,
        host="0.0.0.0",
    )
    wrapped_app = McpRequestContextMiddleware(http_app)
    return McpIntegration(
        server=server,
        http_app=wrapped_app,
        lifespan_context_factory=lambda: http_app.router.lifespan_context(http_app),
    )
