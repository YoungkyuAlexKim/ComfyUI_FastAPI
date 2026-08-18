"""Internal-network MCP facade for stable generation capabilities."""

from __future__ import annotations

import base64
from contextvars import ContextVar
from dataclasses import dataclass
from io import BytesIO
import json
import os
from pathlib import Path
from typing import Annotated, Any, Literal
import uuid

from mcp.server import MCPServer
from mcp.server.mcpserver.utilities.types import Image as McpImage
from mcp.types import Annotations, CallToolResult, ImageContent, TextContent, ToolAnnotations
from PIL import Image, ImageOps
from pydantic import Field

from .auth.mcp_identity import (
    mcp_client_ip_allowed,
    parse_allowed_mcp_networks,
    principal_for_mcp_ip,
)
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
from .services.generation_planning import (
    EphemeralGenerationPlanStore,
    HostedGenerationPlanner,
    PUBLIC_GENERATION_CAPABILITIES,
    generation_capability_contract,
    list_generation_capability_contracts,
)
from .services.input_assets import input_max_bytes


MCP_SPECIALIZED_IMAGE_MODEL = "openai/gpt-image-2"


def _character_sheet_user_prompt(sheet_type: str, count: int, prompt: str) -> str:
    hint = str(prompt or "").strip()
    if sheet_type == "turnaround":
        views = {
            3: "Exact ordered views (3 total): front, left side, back.",
            5: "Exact ordered views (5 total): front, 3/4 front left, left side, back, 3/4 back right.",
            8: (
                "Exact ordered views (8 total): front, 3/4 front left, left side, "
                "3/4 back left, back, 3/4 back right, right side, 3/4 front right."
            ),
        }[count]
        parts = ["Create a character turnaround sheet from the provided character reference."]
        if hint:
            parts.extend(["", "ADDITIONAL REQUIREMENTS:", hint])
        parts.extend(
            [
                "",
                "VIEW SPECIFICATION:",
                views,
                "Create each listed view exactly once and place them left to right in this order.",
            ]
        )
        return "\n".join(parts)

    parts = ["Create a portrait expression sheet from the provided character reference."]
    if hint:
        parts.extend(
            [
                "",
                "STYLE OVERRIDE (user):",
                hint,
                "",
                "RULES:",
                "- Apply style only. Keep character identity consistent with the input image.",
                "- Do not add text, labels, captions, watermarks, or logos.",
            ]
        )
    if count == 4:
        grid = "Exact grid: 2 columns x 2 rows."
        count_line = "Exact count: 4 portraits."
        expressions = "Expressions: neutral, happy, angry, sad."
    else:
        grid = "Exact grid: 3 columns x 3 rows."
        count_line = "Exact count: 9 portraits."
        expressions = (
            "Expressions: neutral, happy, angry, sad, surprised, sleepy, "
            "embarrassed (blush), worried, determined."
        )
    parts.extend(
        [
            "",
            "EXPRESSION SPECIFICATION:",
            count_line,
            grid,
            expressions,
            "Place expressions in the listed order from left to right, then top to bottom.",
            "Create each listed expression exactly once.",
        ]
    )
    return "\n".join(parts)


def _storyboard_user_prompt(prompt: str, cuts: int) -> str:
    story = str(prompt or "").strip()
    grid = "2x3" if cuts == 6 else "3x3"
    return "\n".join(
        [
            f"STORY: {story}",
            f"CUTS: {cuts}",
            f"GRID: {grid}",
            "",
            "SHOT PLAN:",
            "- Vary establishing, medium, close-up, detail, and high-angle or low-angle shots only where they support the story.",
            "- Keep screen direction and spatial continuity clear between adjacent panels.",
            "",
            "FORMAT:",
            "- output: 1 image",
            "- layout: grid, panels edge-to-edge, border=0, gutter=0, padding=0, margin=0",
            "- chronological order: left to right, then top to bottom",
            "- no captions, labels, logos, or watermarks",
        ]
    )


@dataclass(frozen=True)
class McpCaller:
    principal_id: str
    client_ip: str
    client_ip_source: str
    base_url: str


_caller_context: ContextVar[McpCaller | None] = ContextVar("mcp_caller", default=None)


def _principal_for_ip(client_ip: str) -> str:
    """Compatibility alias for existing integrations and tests."""

    return principal_for_mcp_ip(client_ip)


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
            parse_allowed_mcp_networks(os.getenv("MCP_ALLOWED_CLIENT_CIDRS"))
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
        if not mcp_client_ip_allowed(client_ip, os.getenv("MCP_ALLOWED_CLIENT_CIDRS")):
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


def _result_image_path(structured_result: dict[str, Any]) -> Path | None:
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
    return candidate


def _result_image_content(structured_result: dict[str, Any]):
    candidate = _result_image_path(structured_result)
    if candidate is None:
        return None
    return McpImage(path=candidate).to_image_content()


def _result_preview_content(
    structured_result: dict[str, Any],
    *,
    max_dimension: int = 768,
) -> tuple[ImageContent | None, dict[str, Any] | None]:
    """Return a compact, user-directed preview with an original-image fallback."""

    candidate = _result_image_path(structured_result)
    if candidate is None:
        return None, None

    annotations = Annotations(audience=["user"], priority=1.0)
    try:
        with Image.open(candidate) as source:
            transposed = ImageOps.exif_transpose(source)
            has_alpha = transposed.mode in {"RGBA", "LA"} or (
                transposed.mode == "P" and "transparency" in (transposed.info or {})
            )
            preview = transposed.convert("RGBA" if has_alpha else "RGB")
            resampling = getattr(Image, "Resampling", Image).LANCZOS
            preview.thumbnail((max_dimension, max_dimension), resampling)
            width, height = preview.size
            output = BytesIO()
            preview.save(output, format="WEBP", quality=82, method=4)
            preview_bytes = output.getvalue()
        return (
            ImageContent(
                type="image",
                data=base64.b64encode(preview_bytes).decode("ascii"),
                mimeType="image/webp",
                annotations=annotations,
            ),
            {
                "content_role": "user_preview",
                "variant": "thumbnail",
                "mime_type": "image/webp",
                "width": width,
                "height": height,
                "bytes": len(preview_bytes),
                "max_dimension": max_dimension,
            },
        )
    except Exception:
        original = McpImage(path=candidate).to_image_content().model_copy(
            update={"annotations": annotations}
        )
        return (
            original,
            {
                "content_role": "user_preview",
                "variant": "original_fallback",
                "mime_type": original.mime_type,
                "bytes": candidate.stat().st_size,
                "max_dimension": None,
            },
        )


def _generation_result_tool_result(structured: dict[str, Any]) -> CallToolResult:
    """Return portable image content plus client presentation fallbacks."""

    result = structured.get("result")
    image_url = result.get("image_url") if isinstance(result, dict) else None
    response = dict(structured)
    preview_content, preview_metadata = _result_preview_content(structured)
    if isinstance(image_url, str) and image_url.startswith(("http://", "https://")):
        job_id = str(structured.get("job_id") or "result")
        response["presentation"] = {
            "required": True,
            "preferred": "download_then_native_image_viewer",
            "source_url": image_url,
            "suggested_filename": f"lc-ai-canvas-{job_id}.png",
            "storage_scope": "client_temporary_or_session_workspace",
            "tool_result_visibility_is_user_visibility": False,
            "local_agent_action_required_when_available": True,
            "regenerate_for_preview": False,
            "keep_original_link": True,
            "fallback": "clickable_link",
            "preview": preview_metadata,
            "completion_criteria": [
                "A local agent with download and image-view tools opened the image before its final response.",
                "A host without local tools received the user-preview ImageContent or a compatible UI.",
                "If neither can be ensured, explicitly report preview unavailable and provide the source link.",
            ],
        }

    text = json.dumps(response, ensure_ascii=False)
    if isinstance(image_url, str) and image_url.startswith(("http://", "https://")):
        text += (
            "\n\nUSER-VISIBLE IMAGE PRESENTATION IS REQUIRED. Tool-result visibility alone is not "
            "evidence that the user saw the image. In a local agent such as Codex or Claude Code with "
            "download and image-view tools, you MUST download source_url to the suggested temporary/session "
            "PNG and open that local file before the final response. Do not regenerate for preview and do "
            "not use source_url as the sole inline preview. In a host without local tools, use the returned "
            "user-preview ImageContent or compatible UI. If neither presentation path can be ensured, "
            "explicitly say that the preview may be unavailable. Always include this original link:\n"
            f"[Open image in LC AI Canvas]({image_url})"
        )

    content = []
    if preview_content is not None:
        content.append(preview_content)
    content.append(TextContent(type="text", text=text))
    return CallToolResult(content=content, structuredContent=response)


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
        self.controls = controls
        self.submissions = GenerationSubmissionService(job_manager, controls)
        self.planner = HostedGenerationPlanner()
        self.plan_store = EphemeralGenerationPlanStore()

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

    def plan_generation(
        self,
        caller: McpCaller,
        *,
        capability: str,
        prompt: str,
        options: dict[str, Any] | None,
        selection_mode: str,
        reference_image_ids: list[str] | None = None,
    ) -> dict[str, Any]:
        if capability not in PUBLIC_GENERATION_CAPABILITIES:
            raise ValueError(f"Unsupported generation capability: {capability}")
        max_references = {
            "create_managed_image_asset": 14,
            "create_game_ui_assets": 3,
            "create_character_sheet": 1,
            "create_storyboard": 1,
            "remove_background": 1,
        }[capability]
        reference_ids = self._reference_image_ids(
            caller,
            reference_image_ids,
            max_count=max_references,
        )
        plan = self.planner.plan(
            capability,
            prompt=prompt,
            options=options,
            selection_mode=selection_mode,
            has_reference_images=bool(reference_ids),
        )
        if capability in {"create_character_sheet", "create_storyboard", "remove_background"} and len(reference_ids) != 1:
            plan["missing_decisions"] = ["reference_image_id", *plan["missing_decisions"]]
            plan["questions"] = [
                {
                    "field": "reference_image_id",
                    "question": "Which caller-owned character reference image should be used?",
                    "next_step": "Use list_image_assets or direct multipart upload, then plan again.",
                },
                *plan["questions"],
            ]
            plan["ready_to_generate"] = False
            plan["requires_clarification"] = True

        plan.update(
            {
                "reference_image_ids": reference_ids,
                "estimated_cost_usd": None,
                "cost_estimate_available": False,
                "plan_id": None,
                "suggested_idempotency_key": None,
            }
        )
        if not plan["ready_to_generate"]:
            plan["next_action"] = (
                "Ask one concise bundled question covering missing_decisions and conditional_questions, then call "
                "plan_generation again with the user's choices. Do not call a generation write yet."
            )
            return plan

        resolved = plan["resolved_options"]
        if capability == "create_managed_image_asset":
            tool_arguments = {
                "prompt": plan["prompt"],
                "image_model": resolved["image_model"],
                "aspect_ratio": resolved["aspect_ratio"],
                "image_size": resolved["image_size"],
                "image_quality": resolved.get("image_quality"),
                "reference_image_ids": reference_ids or None,
            }
            internal_capability = "create_image"
        elif capability == "create_game_ui_assets":
            tool_arguments = {
                "prompt": plan["prompt"],
                "background_mode": resolved["background_mode"],
                "image_quality": resolved["image_quality"],
                "reference_image_ids": reference_ids or None,
            }
            internal_capability = capability
        elif capability == "create_character_sheet":
            tool_arguments = {
                "reference_image_id": reference_ids[0],
                "sheet_type": resolved["sheet_type"],
                "count": resolved["count"],
                "prompt": plan["prompt"],
                "image_size": resolved["image_size"],
                "image_quality": resolved["image_quality"],
            }
            internal_capability = capability
        elif capability == "create_storyboard":
            tool_arguments = {
                "reference_image_id": reference_ids[0],
                "prompt": plan["prompt"],
                "cuts": resolved["cuts"],
                "image_size": resolved["image_size"],
                "image_quality": resolved["image_quality"],
            }
            internal_capability = capability
        else:
            tool_arguments = {
                "image_id": reference_ids[0],
                "mask_blur": resolved["mask_blur"],
                "mask_offset": resolved["mask_offset"],
            }
            internal_capability = capability

        estimate_payload = {
            "capability": internal_capability,
            "image_model": resolved.get("image_model"),
            "image_size": resolved.get("image_size"),
            "image_quality": resolved.get("image_quality"),
            "resolved_provider": resolved.get("provider"),
        }
        estimate = self.controls.estimate_cost(estimate_payload)
        issued = self.plan_store.issue(caller.principal_id, capability, tool_arguments)
        plan.update(issued)
        plan["tool_name"] = capability
        plan["tool_arguments"] = tool_arguments
        plan["estimated_cost_usd"] = estimate
        plan["cost_estimate_available"] = estimate is not None
        plan["next_action"] = (
            "Present the resolved plan to the user or native write approval UI, then call tool_name with "
            "tool_arguments, plan_id, suggested_idempotency_key, and cost_confirmed when required."
        )
        return plan

    def remove_background(
        self,
        caller: McpCaller,
        *,
        plan_id: str,
        image_id: str,
        mask_blur: int,
        mask_offset: int,
        idempotency_key: str,
    ) -> dict[str, Any]:
        if isinstance(mask_blur, bool) or not isinstance(mask_blur, int) or not 0 <= mask_blur <= 64:
            raise ValueError("mask_blur must be an integer between 0 and 64")
        if isinstance(mask_offset, bool) or not isinstance(mask_offset, int) or not -64 <= mask_offset <= 64:
            raise ValueError("mask_offset must be an integer between -64 and 64")
        reference_ids = self._reference_image_ids(caller, [image_id], max_count=1)
        if len(reference_ids) != 1:
            raise ValueError("image_id is required")
        self._validate_plan(
            caller,
            plan_id=plan_id,
            capability="remove_background",
            arguments={
                "image_id": reference_ids[0],
                "mask_blur": mask_blur,
                "mask_offset": mask_offset,
            },
        )
        context = GenerationContext(
            principal_id=caller.principal_id,
            source="mcp",
            client_ip=caller.client_ip,
            client_ip_source=caller.client_ip_source,
            request_id=uuid.uuid4().hex,
            idempotency_key=idempotency_key,
        )
        command = GenerationCommand(
            capability="remove_background",
            variant="default",
            parameters={
                "user_prompt": "",
                "aspect_ratio": "square",
                "image_model": "RMBG-2.0",
                "input_image_ids": reference_ids,
                "input_image_id": reference_ids[0],
                "rmbg_mask_blur": mask_blur,
                "rmbg_mask_offset": mask_offset,
            },
            context=context,
        )
        resolved = DEFAULT_CAPABILITY_DISPATCHER.resolve(command)
        submission = self.submissions.submit(resolved, cost_confirmed=False)
        return {
            "job_id": submission.job_id,
            "status": submission.status,
            "queue_position": submission.position,
            "estimated_cost_usd": submission.estimated_cost_usd,
            "cost_estimate_available": submission.estimated_cost_usd is not None,
            "duplicate": submission.duplicate,
            "plan_id": plan_id,
            "output_contract": {
                "format": "PNG",
                "background": "transparent",
                "model": "RMBG-2.0",
                "provider_api_cost_usd": 0.0,
            },
            "next_action": "Poll get_generation_job until status is complete or error.",
        }

    def _validate_plan(
        self,
        caller: McpCaller,
        *,
        plan_id: str,
        capability: str,
        arguments: dict[str, Any],
    ) -> None:
        self.plan_store.validate(
            plan_id,
            principal_id=caller.principal_id,
            capability=capability,
            arguments=arguments,
        )

    def create_image(
        self,
        caller: McpCaller,
        *,
        plan_id: str,
        prompt: str,
        image_model: str,
        aspect_ratio: str,
        image_size: str,
        image_quality: str | None,
        idempotency_key: str,
        cost_confirmed: bool,
        reference_image_ids: list[str] | None = None,
    ) -> dict[str, Any]:
        reference_ids = self._reference_image_ids(caller, reference_image_ids, max_count=14)
        self._validate_plan(
            caller,
            plan_id=plan_id,
            capability="create_managed_image_asset",
            arguments={
                "prompt": str(prompt or "").strip(),
                "image_model": image_model,
                "aspect_ratio": aspect_ratio,
                "image_size": image_size,
                "image_quality": image_quality,
                "reference_image_ids": reference_ids or None,
            },
        )
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
                "image_model": image_model,
                "image_size": image_size,
                "image_quality": image_quality,
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
            "cost_estimate_available": submission.estimated_cost_usd is not None,
            "duplicate": submission.duplicate,
            "plan_id": plan_id,
            "next_action": "Poll get_generation_job until status is complete or error.",
        }

    def create_game_ui_assets(
        self,
        caller: McpCaller,
        *,
        plan_id: str,
        prompt: str,
        background_mode: str,
        image_quality: str,
        idempotency_key: str,
        cost_confirmed: bool,
        reference_image_ids: list[str] | None = None,
    ) -> dict[str, Any]:
        reference_ids = self._reference_image_ids(caller, reference_image_ids, max_count=3)
        self._validate_plan(
            caller,
            plan_id=plan_id,
            capability="create_game_ui_assets",
            arguments={
                "prompt": str(prompt or "").strip(),
                "background_mode": background_mode,
                "image_quality": image_quality,
                "reference_image_ids": reference_ids or None,
            },
        )
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
            "cost_estimate_available": submission.estimated_cost_usd is not None,
            "duplicate": submission.duplicate,
            "plan_id": plan_id,
            "output_contract": {
                "grid": "2x2",
                "asset_count": 4,
                "image_size": "2K",
                "background_mode": background_mode,
            },
            "next_action": "Poll get_generation_job until status is complete or error.",
        }

    def create_character_sheet(
        self,
        caller: McpCaller,
        *,
        plan_id: str,
        reference_image_id: str,
        sheet_type: str,
        count: int | None,
        prompt: str,
        image_size: str,
        image_quality: str,
        idempotency_key: str,
        cost_confirmed: bool,
    ) -> dict[str, Any]:
        allowed_counts = {"turnaround": {3, 5, 8}, "expressions": {4, 9}}
        if sheet_type not in allowed_counts:
            raise ValueError("sheet_type must be turnaround or expressions")
        resolved_count = count if count is not None else (5 if sheet_type == "turnaround" else 9)
        if resolved_count not in allowed_counts[sheet_type]:
            allowed = ", ".join(str(value) for value in sorted(allowed_counts[sheet_type]))
            raise ValueError(f"count for {sheet_type} must be one of: {allowed}")
        reference_ids = self._reference_image_ids(caller, [reference_image_id], max_count=1)
        if len(reference_ids) != 1:
            raise ValueError("reference_image_id is required")
        self._validate_plan(
            caller,
            plan_id=plan_id,
            capability="create_character_sheet",
            arguments={
                "reference_image_id": reference_ids[0],
                "sheet_type": sheet_type,
                "count": resolved_count,
                "prompt": str(prompt or "").strip(),
                "image_size": image_size,
                "image_quality": image_quality,
            },
        )

        context = GenerationContext(
            principal_id=caller.principal_id,
            source="mcp",
            client_ip=caller.client_ip,
            client_ip_source=caller.client_ip_source,
            request_id=uuid.uuid4().hex,
            idempotency_key=idempotency_key,
        )
        command = GenerationCommand(
            capability="create_character_sheet",
            variant=sheet_type,
            parameters={
                "user_prompt": _character_sheet_user_prompt(sheet_type, resolved_count, prompt),
                "aspect_ratio": "landscape" if sheet_type == "turnaround" else "square",
                "image_model": MCP_SPECIALIZED_IMAGE_MODEL,
                "image_size": image_size,
                "image_quality": image_quality,
                "input_image_ids": reference_ids,
                "input_image_id": reference_ids[0],
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
            "cost_estimate_available": submission.estimated_cost_usd is not None,
            "duplicate": submission.duplicate,
            "plan_id": plan_id,
            "output_contract": {
                "sheet_type": sheet_type,
                "count": resolved_count,
                "layout": (
                    f"{resolved_count} horizontal ordered views"
                    if sheet_type == "turnaround"
                    else ("2x2 portraits" if resolved_count == 4 else "3x3 portraits")
                ),
                "image_size": image_size,
                "image_quality": image_quality,
            },
            "next_action": "Poll get_generation_job until status is complete or error.",
        }

    def create_storyboard(
        self,
        caller: McpCaller,
        *,
        plan_id: str,
        reference_image_id: str,
        prompt: str,
        cuts: int,
        image_size: str,
        image_quality: str,
        idempotency_key: str,
        cost_confirmed: bool,
    ) -> dict[str, Any]:
        if cuts not in {6, 9}:
            raise ValueError("cuts must be 6 or 9")
        story = str(prompt or "").strip()
        if not story:
            raise ValueError("prompt is required")
        reference_ids = self._reference_image_ids(caller, [reference_image_id], max_count=1)
        if len(reference_ids) != 1:
            raise ValueError("reference_image_id is required")
        self._validate_plan(
            caller,
            plan_id=plan_id,
            capability="create_storyboard",
            arguments={
                "reference_image_id": reference_ids[0],
                "prompt": story,
                "cuts": cuts,
                "image_size": image_size,
                "image_quality": image_quality,
            },
        )

        context = GenerationContext(
            principal_id=caller.principal_id,
            source="mcp",
            client_ip=caller.client_ip,
            client_ip_source=caller.client_ip_source,
            request_id=uuid.uuid4().hex,
            idempotency_key=idempotency_key,
        )
        command = GenerationCommand(
            capability="create_storyboard",
            variant="default",
            parameters={
                "user_prompt": _storyboard_user_prompt(story, cuts),
                "aspect_ratio": "landscape" if cuts == 6 else "square",
                "image_model": MCP_SPECIALIZED_IMAGE_MODEL,
                "image_size": image_size,
                "image_quality": image_quality,
                "input_image_ids": reference_ids,
                "input_image_id": reference_ids[0],
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
            "cost_estimate_available": submission.estimated_cost_usd is not None,
            "duplicate": submission.duplicate,
            "plan_id": plan_id,
            "output_contract": {
                "cuts": cuts,
                "grid": "2x3" if cuts == 6 else "3x3",
                "image_size": image_size,
                "image_quality": image_quality,
            },
            "next_action": "Poll get_generation_job until status is complete or error.",
        }

    def prepare_input_image_upload(self, caller: McpCaller) -> dict[str, Any]:
        upload_url = f"{caller.base_url.rstrip('/')}/api/v1/mcp/inputs/upload"
        max_bytes = input_max_bytes()
        return {
            "upload_url": upload_url,
            "method": "POST",
            "content_type": "multipart/form-data",
            "file_field": "file",
            "accepted_mime_types": ["image/png", "image/jpeg", "image/webp"],
            "max_bytes": max_bytes,
            "max_megabytes": round(max_bytes / (1024 * 1024), 1),
            "base64_allowed": False,
            "curl_template": (
                f'curl --fail-with-body --form "file=@<LOCAL_IMAGE_PATH>" "{upload_url}"'
            ),
            "next_action": (
                "Upload the local file bytes with multipart/form-data, then use the returned asset_id "
                "in reference_image_ids for plan_generation."
            ),
        }

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
        absolute_result = _absolute_result(item.get("result") or {}, caller.base_url)
        assets = self.asset_service.list_assets_by_source_job(caller.principal_id, str(item.get("id") or ""))
        if assets:
            absolute_result["assets"] = [_asset_result(row, caller.base_url) for row in assets]
        return {
            "job_id": item.get("id"),
            "status": status,
            "ready": True,
            "result": absolute_result,
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
        version="0.8.0",
        instructions=(
            "LC AI Canvas is the company's managed image-asset pipeline. USER-VISIBLE IMAGE PRESENTATION "
            "IS REQUIRED after every ready result; tool-result visibility alone is not proof. In local "
            "Codex or Claude Code clients with download and image-view tools, MUST download result.image_url "
            "to a temporary/session PNG and open it before the final response. In hosts without local tools, "
            "use the returned user-preview ImageContent or compatible UI. If neither path can be ensured, "
            "explicitly report that preview may be unavailable and provide the source link. Never regenerate "
            "for preview or use the source URL as the sole inline preview. Use "
            "create_managed_image_asset only when the user asks for the company generator or LC AI "
            "Canvas, needs centrally billed/audited/stored output, or the current client has no native "
            "image generator. For ad-hoc images in clients with a native generator and no managed-workflow "
            "need, prefer the native tool. Hosted generation tools incur company API cost. Before every "
            "public generation write, call plan_generation. If the user's request leaves any workflow "
            "decision ambiguous, use selection_mode=clarify, ask one concise bundled question containing "
            "the returned missing decisions, and plan again. Use selection_mode=recommend only when the "
            "user explicitly delegates those choices. Never silently choose model, size, aspect, count, "
            "background, or quality. The local remove_background capability is fixed to RMBG-2.0, incurs "
            "no provider API charge, and requires one caller-owned image plus a ready plan. Copy the ready "
            "plan's tool_arguments without changing them. Reuse the "
            "same idempotency_key when retrying one intent. If cost confirmation is required, ask the user and "
            "retry with cost_confirmed=true. Poll get_generation_job, then call get_generation_result. "
            "Use list_image_assets and get_image_asset to discover only this caller's managed images. "
            "Client image uploads MUST use direct multipart file transfer. Never encode an attachment as "
            "base64 or place image bytes in tool arguments. In Codex or Claude Code, call "
            "prepare_input_image_upload and execute the returned upload contract with a local HTTP/file tool. "
            "create_game_ui_assets produces the fixed, supported 2x2 Game UI asset group. "
            "create_character_sheet and create_storyboard require one caller-owned reference image."
        ),
    )

    read_annotations = ToolAnnotations(
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=False,
    )
    planning_annotations = ToolAnnotations(
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=False,
        openWorldHint=False,
    )

    @server.tool(
        title="List generation capabilities",
        description="List generation capabilities currently exposed through this MCP server.",
        annotations=read_annotations,
        structured_output=True,
    )
    async def list_generation_capabilities() -> dict[str, Any]:
        capabilities = list_generation_capability_contracts()
        for item in capabilities:
            item["status"] = "available"
        return {
            "capabilities": capabilities,
            "selection_policy": {
                "plan_required_before_write": True,
                "planning_tool": "plan_generation",
                "clarify_ambiguous_requests": True,
                "recommend_only_when_user_delegates": True,
            },
        }

    @server.tool(
        title="Get generation capability schema",
        description="Get the supported inputs and behavior for one generation capability.",
        annotations=read_annotations,
        structured_output=True,
    )
    async def get_generation_capability(
        capability: Literal[
            "create_managed_image_asset",
            "create_game_ui_assets",
            "create_character_sheet",
            "create_storyboard",
            "remove_background",
        ],
    ) -> dict[str, Any]:
        return generation_capability_contract(capability)

    @server.tool(
        title="Plan generation",
        description=(
            "Plan one public LC AI Canvas generation without calling an AI provider or running a local workflow. "
            "Call this before every generation write. Pass only choices the user explicitly stated or "
            "clearly implied. Use selection_mode=clarify when any workflow option is ambiguous; ask one concise "
            "bundled question from missing_decisions and plan again. Use selection_mode=recommend only when the "
            "user explicitly says to choose or recommend settings. A ready plan returns owner-bound tool arguments "
            "and a short-lived plan_id that the write tool requires."
        ),
        annotations=planning_annotations,
        structured_output=True,
    )
    async def plan_generation(
        capability: Literal[
            "create_managed_image_asset",
            "create_game_ui_assets",
            "create_character_sheet",
            "create_storyboard",
            "remove_background",
        ],
        prompt: Annotated[str, Field(max_length=8000)] = "",
        options: Annotated[
            dict[str, Any] | None,
            Field(description="Only workflow decision fields declared by get_generation_capability"),
        ] = None,
        reference_image_ids: Annotated[list[str] | None, Field(max_length=14)] = None,
        selection_mode: Literal["clarify", "recommend"] = "clarify",
    ) -> dict[str, Any]:
        return service.plan_generation(
            _current_caller(),
            capability=capability,
            prompt=prompt,
            options=options,
            selection_mode=selection_mode,
            reference_image_ids=reference_image_ids,
        )

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
        title="Prepare direct input image upload",
        description=(
            "Return the owner-scoped direct multipart upload contract for a local PNG, JPEG, or WEBP file. "
            "This tool does not upload bytes and does not call an AI provider. Use a local HTTP/file tool to "
            "POST the file itself; never convert it to base64 or place image bytes in MCP arguments."
        ),
        annotations=read_annotations,
        structured_output=True,
    )
    async def prepare_input_image_upload() -> dict[str, Any]:
        return service.prepare_input_image_upload(_current_caller())

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
        description=(
            "Read output metadata and receive a compact user-preview image when a generation job is complete. "
            "User-visible presentation is a required completion step; tool-result visibility alone is not "
            "proof. A local Codex or Claude Code agent with download/image-view tools MUST download source_url "
            "to the suggested temporary/session PNG and open it before its final response. Hosts without "
            "local tools should use the returned user-preview ImageContent or compatible UI. Never regenerate "
            "for preview. If presentation cannot be ensured, say so explicitly and always include the LC AI "
            "Canvas fallback Markdown link."
        ),
        annotations=read_annotations,
    )
    async def get_generation_result(
        job_id: Annotated[str, Field(min_length=16, max_length=64, description="Completed generation job ID")],
    ) -> CallToolResult:
        structured = service.get_result(_current_caller(), job_id)
        return _generation_result_tool_result(structured)

    @server.tool(
        title="Create managed image asset",
        description=(
            "Queue one company-managed image asset using LC AI Canvas. With no reference_image_ids this "
            "is text-to-image; with caller-owned active image IDs it is an image edit. Use this when the user "
            "requests the company generator, needs centrally billed/audited/stored output, or the current "
            "client has no native image generator. In clients with native image generation, do not use "
            "this for an ad-hoc image unless a managed company workflow is requested. This consumes "
            "company API budget. A ready plan_generation result is required; copy its arguments exactly. "
            "Use one stable idempotency_key per user intent and poll the returned job."
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
        plan_id: Annotated[str, Field(min_length=37, max_length=64)],
        idempotency_key: Annotated[
            str,
            Field(min_length=8, max_length=128, description="Stable unique key for this generation intent"),
        ],
        image_model: Literal[
            "google/gemini-3-pro-image",
            "google/gemini-3.1-flash-image",
            "google/gemini-3.1-flash-lite-image",
            "openai/gpt-image-2",
        ],
        aspect_ratio: Literal["auto", "square", "landscape", "portrait"],
        image_size: Literal["1K", "2K"],
        image_quality: Literal["low", "medium", "high"] | None = None,
        reference_image_ids: Annotated[list[str] | None, Field(max_length=14)] = None,
        cost_confirmed: bool = False,
    ) -> dict[str, Any]:
        try:
            return service.create_image(
                _current_caller(),
                plan_id=plan_id,
                prompt=prompt,
                image_model=image_model,
                aspect_ratio=aspect_ratio,
                image_size=image_size,
                image_quality=image_quality,
                idempotency_key=idempotency_key,
                cost_confirmed=cost_confirmed,
                reference_image_ids=reference_image_ids,
            )
        except GenerationPolicyError as exc:
            raise RuntimeError(f"{exc.code}: {exc.message}") from exc

    @server.tool(
        title="Remove image background",
        description=(
            "Queue the fixed local RMBG-2.0 workflow for exactly one active image owned by this caller. "
            "The result is registered as a managed transparent PNG. This uses the internal ComfyUI GPU queue "
            "and incurs no external provider API charge, although local GPU and infrastructure resources are "
            "consumed. A ready plan_generation result is required; copy its arguments exactly."
        ),
        annotations=ToolAnnotations(
            readOnlyHint=False,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
        structured_output=True,
    )
    async def remove_background(
        image_id: Annotated[
            str,
            Field(min_length=1, max_length=128, description="Caller-owned active image or input asset ID"),
        ],
        plan_id: Annotated[str, Field(min_length=37, max_length=64)],
        idempotency_key: Annotated[str, Field(min_length=8, max_length=128)],
        mask_blur: Annotated[int, Field(ge=0, le=64)] = 0,
        mask_offset: Annotated[int, Field(ge=-64, le=64)] = 0,
    ) -> dict[str, Any]:
        try:
            return service.remove_background(
                _current_caller(),
                plan_id=plan_id,
                image_id=image_id,
                mask_blur=mask_blur,
                mask_offset=mask_offset,
                idempotency_key=idempotency_key,
            )
        except GenerationPolicyError as exc:
            raise RuntimeError(f"{exc.code}: {exc.message}") from exc

    @server.tool(
        title="Create Game UI assets",
        description=(
            "Queue the stable LC AI Canvas Game UI capability. It creates exactly four related candidates "
            "in a 2x2 sheet, registers four managed child images, and produces one group ZIP. This consumes "
            "company API budget. A ready plan_generation result is required. Optional references must be "
            "active image assets owned by this caller."
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
        plan_id: Annotated[str, Field(min_length=37, max_length=64)],
        idempotency_key: Annotated[str, Field(min_length=8, max_length=128)],
        background_mode: Literal["transparent", "opaque"],
        image_quality: Literal["low", "medium", "high"],
        reference_image_ids: Annotated[list[str] | None, Field(max_length=3)] = None,
        cost_confirmed: bool = False,
    ) -> dict[str, Any]:
        try:
            return service.create_game_ui_assets(
                _current_caller(),
                plan_id=plan_id,
                prompt=prompt,
                background_mode=background_mode,
                image_quality=image_quality,
                idempotency_key=idempotency_key,
                cost_confirmed=cost_confirmed,
                reference_image_ids=reference_image_ids,
            )
        except GenerationPolicyError as exc:
            raise RuntimeError(f"{exc.code}: {exc.message}") from exc

    @server.tool(
        title="Create character sheet",
        description=(
            "Queue a managed character sheet from exactly one caller-owned active reference image. "
            "Choose turnaround for 3, 5, or 8 ordered full-body views, or expressions for a 4- or "
            "9-portrait grid. The current managed implementation uses a server-selected image model. "
            "This consumes company API budget. A ready plan_generation result is required. Use 1K/low "
            "only for draft validation."
        ),
        annotations=ToolAnnotations(
            readOnlyHint=False,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=True,
        ),
        structured_output=True,
    )
    async def create_character_sheet(
        reference_image_id: Annotated[
            str,
            Field(min_length=1, max_length=128, description="Caller-owned active image or input asset ID"),
        ],
        plan_id: Annotated[str, Field(min_length=37, max_length=64)],
        idempotency_key: Annotated[str, Field(min_length=8, max_length=128)],
        sheet_type: Literal["turnaround", "expressions"],
        count: Annotated[
            int,
            Field(
                ge=3,
                le=9,
                description="Turnaround: 3, 5, or 8. Expressions: 4 or 9.",
            ),
        ],
        image_size: Literal["1K", "2K"],
        image_quality: Literal["low", "medium", "high"],
        prompt: Annotated[
            str,
            Field(max_length=4000, description="Optional style or rendering guidance"),
        ] = "",
        cost_confirmed: bool = False,
    ) -> dict[str, Any]:
        try:
            return service.create_character_sheet(
                _current_caller(),
                plan_id=plan_id,
                reference_image_id=reference_image_id,
                sheet_type=sheet_type,
                count=count,
                prompt=prompt,
                image_size=image_size,
                image_quality=image_quality,
                idempotency_key=idempotency_key,
                cost_confirmed=cost_confirmed,
            )
        except GenerationPolicyError as exc:
            raise RuntimeError(f"{exc.code}: {exc.message}") from exc

    @server.tool(
        title="Create storyboard",
        description=(
            "Queue one managed six- or nine-cut storyboard sheet from a story prompt and exactly one "
            "caller-owned active reference image. The server adds continuity, shot-order, and exact-grid "
            "constraints. The current managed implementation uses a server-selected image model. This "
            "consumes company API budget. A ready plan_generation result is required. Use 1K/low only "
            "for draft validation."
        ),
        annotations=ToolAnnotations(
            readOnlyHint=False,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=True,
        ),
        structured_output=True,
    )
    async def create_storyboard(
        reference_image_id: Annotated[
            str,
            Field(min_length=1, max_length=128, description="Caller-owned active image or input asset ID"),
        ],
        prompt: Annotated[str, Field(min_length=1, max_length=8000, description="Story sequence")],
        plan_id: Annotated[str, Field(min_length=37, max_length=64)],
        idempotency_key: Annotated[str, Field(min_length=8, max_length=128)],
        cuts: Literal[6, 9],
        image_size: Literal["1K", "2K"],
        image_quality: Literal["low", "medium", "high"],
        cost_confirmed: bool = False,
    ) -> dict[str, Any]:
        try:
            return service.create_storyboard(
                _current_caller(),
                plan_id=plan_id,
                reference_image_id=reference_image_id,
                prompt=prompt,
                cuts=cuts,
                image_size=image_size,
                image_quality=image_quality,
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
