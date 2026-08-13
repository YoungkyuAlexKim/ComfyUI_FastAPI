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
from .services.asset_service import AssetService
from .services.generation_commands import (
    DEFAULT_CAPABILITY_DISPATCHER,
    GenerationCommand,
    GenerationContext,
    resolve_client_ip,
)
from .services.generation_controls import GenerationPolicyError
from .services.generation_submission import GenerationSubmissionService
from .services.input_assets import (
    InputAssetError,
    decode_base64_image,
    input_base64_max_characters,
    register_input_image,
)


MCP_INPUT_BASE64_MAX_CHARACTERS = input_base64_max_characters()


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
            elif (
                (key == "url" or key.endswith("_url"))
                and isinstance(value, str)
                and value.startswith("/outputs/")
            ):
                converted[key] = f"{base_url}{value}"
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


def _asset_web_path(row: dict[str, Any], key: str) -> str | None:
    relative_path = row.get(key)
    if not isinstance(relative_path, str) or not relative_path:
        return None
    return f"/outputs/{relative_path}"


def _asset_result(row: dict[str, Any], base_url: str) -> dict[str, Any]:
    content_path = _asset_web_path(row, "storage_path")
    thumbnail_path = _asset_web_path(row, "thumbnail_path")
    return {
        "asset_id": row.get("asset_id"),
        "kind": row.get("kind"),
        "status": row.get("status"),
        "mime_type": row.get("mime_type"),
        "byte_size": row.get("byte_size"),
        "sha256": row.get("sha256"),
        "group_id": row.get("group_id"),
        "source_job_id": row.get("source_job_id"),
        "created_at": row.get("created_at"),
        "updated_at": row.get("updated_at"),
        "content_url": f"{base_url}{content_path}" if content_path else None,
        "thumbnail_url": f"{base_url}{thumbnail_path}" if thumbnail_path else None,
        "metadata": row.get("metadata") if isinstance(row.get("metadata"), dict) else {},
    }


def _asset_image_content(asset_service: AssetService, caller: McpCaller, asset_id: str):
    row = asset_service.get(caller.principal_id, asset_id)
    if not row or row.get("status") != "active" or row.get("kind") not in {"image", "input"}:
        return None
    path = asset_service.resolve_storage_path(row.get("storage_path"))
    if not path or not os.path.isfile(path):
        return None
    return McpImage(path=Path(path)).to_image_content()


class McpGenerationService:
    def __init__(self, job_manager, job_store, controls, asset_service: AssetService):
        self.job_manager = job_manager
        self.job_store = job_store
        self.asset_service = asset_service
        self.submissions = GenerationSubmissionService(job_manager, controls)

    def _reference_image_ids(
        self,
        caller: McpCaller,
        values: list[str] | None,
        *,
        max_count: int,
    ) -> list[str]:
        reference_ids: list[str] = []
        for value in values or []:
            asset_id = str(value or "").strip()
            if asset_id and asset_id not in reference_ids:
                reference_ids.append(asset_id)
        if len(reference_ids) > max_count:
            raise ValueError(f"At most {max_count} reference images are supported")
        for asset_id in reference_ids:
            row = self.asset_service.get(caller.principal_id, asset_id)
            if not row or row.get("status") != "active" or row.get("kind") not in {"image", "input"}:
                raise ValueError(f"Reference image not found: {asset_id}")
            path = self.asset_service.resolve_storage_path(row.get("storage_path"))
            if not path or not os.path.isfile(path):
                raise ValueError(f"Reference image file is unavailable: {asset_id}")
        return reference_ids

    def create_image(
        self,
        caller: McpCaller,
        *,
        prompt: str,
        aspect_ratio: str,
        image_size: str,
        idempotency_key: str,
        cost_confirmed: bool,
        reference_image_ids: list[str] | None = None,
    ) -> dict[str, Any]:
        reference_ids = self._reference_image_ids(caller, reference_image_ids, max_count=14)
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
            variant="edit" if reference_ids else "generate",
            parameters={
                "user_prompt": prompt.strip(),
                "aspect_ratio": aspect_ratio,
                "image_size": image_size,
                "input_image_ids": reference_ids or None,
                "input_image_id": reference_ids[0] if reference_ids else None,
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

    def create_game_ui_assets(
        self,
        caller: McpCaller,
        *,
        prompt: str,
        background_mode: str,
        image_quality: str,
        idempotency_key: str,
        cost_confirmed: bool,
        reference_image_ids: list[str] | None = None,
    ) -> dict[str, Any]:
        reference_ids = self._reference_image_ids(caller, reference_image_ids, max_count=3)
        context = GenerationContext(
            principal_id=caller.principal_id,
            source="mcp",
            client_ip=caller.client_ip,
            client_ip_source=caller.client_ip_source,
            request_id=uuid.uuid4().hex,
            idempotency_key=idempotency_key,
        )
        command = GenerationCommand(
            capability="create_game_ui_assets",
            variant="default",
            parameters={
                "user_prompt": prompt.strip(),
                "aspect_ratio": "square",
                "image_size": "2K",
                "image_quality": image_quality,
                "game_ui_background_mode": background_mode,
                "game_ui_grid": "2x2",
                "input_image_ids": reference_ids or None,
                "input_image_id": reference_ids[0] if reference_ids else None,
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
            "output_contract": {
                "grid": "2x2",
                "asset_count": 4,
                "image_size": "2K",
                "background_mode": background_mode,
            },
            "next_action": "Poll get_generation_job until status is complete or error.",
        }

    def create_input_image_asset(
        self,
        caller: McpCaller,
        *,
        image_base64: str,
        mime_type: str,
        filename: str | None,
    ) -> dict[str, Any]:
        raw_bytes, data_url_mime = decode_base64_image(image_base64)
        declared_mime = str(mime_type or "").strip().lower()
        if data_url_mime and declared_mime and data_url_mime != declared_mime:
            raise InputAssetError("mime_type_mismatch", "Data URL and mime_type do not match")
        row, duplicate = register_input_image(
            self.asset_service,
            caller.principal_id,
            raw_bytes,
            filename=filename,
            content_type=data_url_mime or declared_mime,
            deduplicate=True,
        )
        result = _asset_result(row, caller.base_url)
        result["duplicate"] = duplicate
        result["next_action"] = "Use asset_id in reference_image_ids for an image or Game UI request."
        return result

    def list_image_assets(
        self,
        caller: McpCaller,
        *,
        asset_kind: str,
        limit: int,
        offset: int,
    ) -> dict[str, Any]:
        kinds = ("image", "input") if asset_kind == "all" else (asset_kind,)
        rows = self.asset_service.list_assets(
            caller.principal_id,
            kinds=kinds,
            include_trash=False,
            limit=limit,
            offset=offset,
        )
        total = self.asset_service.count_assets(
            caller.principal_id,
            kinds=kinds,
            include_trash=False,
        )
        next_offset = offset + len(rows) if offset + len(rows) < total else None
        return {
            "asset_kind": asset_kind,
            "items": [_asset_result(row, caller.base_url) for row in rows],
            "total": total,
            "limit": limit,
            "offset": offset,
            "next_offset": next_offset,
        }

    def get_image_asset(self, caller: McpCaller, asset_id: str) -> dict[str, Any]:
        row = self.asset_service.get(caller.principal_id, asset_id)
        if not row or row.get("status") != "active" or row.get("kind") not in {"image", "input"}:
            # Keep cross-owner and missing-asset responses indistinguishable.
            raise ValueError("Image asset not found")
        path = self.asset_service.resolve_storage_path(row.get("storage_path"))
        if not path or not os.path.isfile(path):
            raise ValueError("Image asset file is unavailable")
        return _asset_result(row, caller.base_url)

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


def create_mcp_integration(job_manager, job_store, controls, asset_service: AssetService) -> McpIntegration:
    service = McpGenerationService(job_manager, job_store, controls, asset_service)
    server = MCPServer(
        name="lc-ai-canvas",
        title="LC AI Canvas",
        version="0.4.0",
        instructions=(
            "LC AI Canvas is the company's managed image-asset pipeline. Use "
            "create_managed_image_asset only when the user asks for the company generator or LC AI "
            "Canvas, needs centrally billed/audited/stored output, or the current client has no native "
            "image generator. For ad-hoc images in clients with a native generator and no managed-workflow "
            "need, prefer the native tool. This tool incurs company API cost. Reuse the same "
            "idempotency_key when retrying one intent. If cost confirmation is required, ask the user and "
            "retry with cost_confirmed=true. Poll get_generation_job, then call get_generation_result. "
            "Use list_image_assets and get_image_asset to discover only this caller's managed images. "
            "Use create_input_image_asset to register a client attachment before referencing it. "
            "create_game_ui_assets produces the fixed, supported 2x2 Game UI asset group."
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
                    "name": "create_managed_image_asset",
                    "variants": ["generate", "edit"],
                    "supports": [
                        "text-to-image",
                        "owner-scoped-reference-images",
                        "managed-storage",
                        "central-audit",
                    ],
                    "status": "available",
                },
                {
                    "name": "create_game_ui_assets",
                    "variants": ["default"],
                    "supports": [
                        "2x2-candidate-sheet",
                        "four-managed-assets",
                        "group-zip",
                        "owner-scoped-reference-images",
                    ],
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
        capability: Literal["create_managed_image_asset", "create_game_ui_assets"],
    ) -> dict[str, Any]:
        if capability == "create_game_ui_assets":
            return {
                "name": capability,
                "variants": ["default"],
                "description": (
                    "Create four related Game UI element candidates from one prompt as a fixed 2x2 group, "
                    "with managed child assets and a group ZIP."
                ),
                "inputs": {
                    "prompt": {"type": "string", "required": True, "max_length": 8000},
                    "reference_image_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                        "max_items": 3,
                        "required": False,
                    },
                    "background_mode": {
                        "enum": ["transparent", "opaque"],
                        "default": "transparent",
                    },
                    "image_quality": {
                        "enum": ["low", "medium", "high"],
                        "default": "medium",
                    },
                    "idempotency_key": {"type": "string", "required": True, "min_length": 8},
                    "cost_confirmed": {"type": "boolean", "default": False},
                },
                "output": {"grid": "2x2", "asset_count": 4, "image_size": "2K"},
                "asynchronous": True,
            }
        return {
            "name": capability,
            "variants": ["generate", "edit"],
            "description": (
                "Create one company-managed image asset from text, or edit caller-owned reference "
                "images, with centralized API billing, audit logging, job tracking, and LC AI Canvas storage."
            ),
            "inputs": {
                "prompt": {"type": "string", "required": True, "max_length": 8000},
                "aspect_ratio": {"enum": ["square", "landscape", "portrait"], "default": "square"},
                "image_size": {"enum": ["1K", "2K"], "default": "2K"},
                "reference_image_ids": {
                    "type": "array",
                    "items": {"type": "string"},
                    "max_items": 14,
                    "required": False,
                    "behavior": "When present, edit these owner-scoped image assets.",
                },
                "idempotency_key": {"type": "string", "required": True, "min_length": 8},
                "cost_confirmed": {"type": "boolean", "default": False},
            },
            "asynchronous": True,
        }

    @server.tool(
        title="List image assets",
        description=(
            "List active managed image assets owned by this MCP caller. Use input assets when selecting "
            "uploaded references and image assets when selecting generated gallery results."
        ),
        annotations=read_annotations,
        structured_output=True,
    )
    async def list_image_assets(
        asset_kind: Literal["image", "input", "all"] = "image",
        limit: Annotated[int, Field(ge=1, le=100)] = 50,
        offset: Annotated[int, Field(ge=0, le=1_000_000)] = 0,
    ) -> dict[str, Any]:
        return service.list_image_assets(
            _current_caller(),
            asset_kind=asset_kind,
            limit=limit,
            offset=offset,
        )

    @server.tool(
        title="Get image asset",
        description=(
            "Get one active image asset owned by this MCP caller, including metadata and image content."
        ),
        annotations=read_annotations,
    )
    async def get_image_asset(
        asset_id: Annotated[str, Field(min_length=1, max_length=128)],
    ) -> CallToolResult:
        caller = _current_caller()
        structured = service.get_image_asset(caller, asset_id)
        content = [TextContent(type="text", text=json.dumps(structured, ensure_ascii=False))]
        image_content = _asset_image_content(asset_service, caller, asset_id)
        if image_content is not None:
            content.append(image_content)
        return CallToolResult(content=content, structuredContent=structured)

    @server.tool(
        title="Register input image asset",
        description=(
            "Register one PNG, JPEG, or WEBP client attachment as an owner-scoped LC AI Canvas input "
            "asset. The image is decoded, bounded, normalized to PNG, cataloged, and deduplicated by "
            "content. Use the returned asset_id in reference_image_ids. This does not call an AI provider."
        ),
        annotations=ToolAnnotations(
            readOnlyHint=False,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    async def create_input_image_asset(
        image_base64: Annotated[
            str,
            Field(
                min_length=4,
                max_length=MCP_INPUT_BASE64_MAX_CHARACTERS,
                description="Plain base64 or a PNG/JPEG/WEBP data URL",
            ),
        ],
        mime_type: Literal["image/png", "image/jpeg", "image/webp"],
        filename: Annotated[str | None, Field(max_length=255)] = None,
    ) -> CallToolResult:
        caller = _current_caller()
        try:
            structured = service.create_input_image_asset(
                caller,
                image_base64=image_base64,
                mime_type=mime_type,
                filename=filename,
            )
        except InputAssetError as exc:
            raise RuntimeError(f"{exc.code}: {exc.message}") from exc
        content = [TextContent(type="text", text=json.dumps(structured, ensure_ascii=False))]
        image_content = _asset_image_content(asset_service, caller, str(structured["asset_id"]))
        if image_content is not None:
            content.append(image_content)
        return CallToolResult(content=content, structuredContent=structured)

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
        title="Create managed image asset",
        description=(
            "Queue one company-managed image asset using LC AI Canvas. With no reference_image_ids this "
            "is text-to-image; with caller-owned active image IDs it is an image edit. Use this when the user "
            "requests the company generator, needs centrally billed/audited/stored output, or the current "
            "client has no native image generator. In clients with native image generation, do not use "
            "this for an ad-hoc image unless a managed company workflow is requested. This consumes "
            "company API budget. Use one stable idempotency_key per user intent and poll the returned job."
        ),
        annotations=ToolAnnotations(
            readOnlyHint=False,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=True,
        ),
        structured_output=True,
    )
    async def create_managed_image_asset(
        prompt: Annotated[str, Field(min_length=1, max_length=8000, description="Complete image request")],
        idempotency_key: Annotated[
            str,
            Field(min_length=8, max_length=128, description="Stable unique key for this generation intent"),
        ],
        aspect_ratio: Literal["square", "landscape", "portrait"] = "square",
        image_size: Literal["1K", "2K"] = "2K",
        reference_image_ids: Annotated[list[str] | None, Field(max_length=14)] = None,
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
                reference_image_ids=reference_image_ids,
            )
        except GenerationPolicyError as exc:
            raise RuntimeError(f"{exc.code}: {exc.message}") from exc

    @server.tool(
        title="Create Game UI assets",
        description=(
            "Queue the stable LC AI Canvas Game UI capability. It creates exactly four related candidates "
            "in a 2x2 sheet, registers four managed child images, and produces one group ZIP. This consumes "
            "company API budget. Optional references must be active image assets owned by this caller."
        ),
        annotations=ToolAnnotations(
            readOnlyHint=False,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=True,
        ),
        structured_output=True,
    )
    async def create_game_ui_assets(
        prompt: Annotated[str, Field(min_length=1, max_length=8000)],
        idempotency_key: Annotated[str, Field(min_length=8, max_length=128)],
        reference_image_ids: Annotated[list[str] | None, Field(max_length=3)] = None,
        background_mode: Literal["transparent", "opaque"] = "transparent",
        image_quality: Literal["low", "medium", "high"] = "medium",
        cost_confirmed: bool = False,
    ) -> dict[str, Any]:
        try:
            return service.create_game_ui_assets(
                _current_caller(),
                prompt=prompt,
                background_mode=background_mode,
                image_quality=image_quality,
                idempotency_key=idempotency_key,
                cost_confirmed=cost_confirmed,
                reference_image_ids=reference_image_ids,
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
