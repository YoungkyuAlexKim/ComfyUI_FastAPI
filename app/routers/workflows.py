import os
import json
from typing import Optional
from fastapi import APIRouter, Query
from ..logging_utils import setup_logging
from ..config import WORKFLOW_CONFIGS
from ..schemas.api_models import WorkflowsResponse
from ..services.openrouter_client import public_image_model_options


logger = setup_logging()
router = APIRouter(tags=["Workflows"])

WORKFLOW_DIR = "./workflows/"


@router.get("/api/v1/workflows", response_model=WorkflowsResponse)
async def get_workflows(
    include_openrouter: bool = Query(
        default=True,
        description="true면 OpenRouter 워크플로우도 목록에 포함합니다.",
    ),
    include_google: Optional[bool] = Query(
        default=None,
        deprecated=True,
        description="이전 클라이언트 호환용입니다. include_openrouter를 사용하세요.",
    ),
):
    if include_google is not None:
        include_openrouter = bool(include_google)
    workflows = []
    for workflow_id, config in WORKFLOW_CONFIGS.items():
        provider = str(config.get("provider", "comfyui") or "comfyui").strip().lower()
        # 필요하면 비용이 드는 외부 API 워크플로우를 목록에서 숨깁니다.
        if provider == "openrouter" and not include_openrouter:
            continue
        json_path = os.path.join(WORKFLOW_DIR, f"{workflow_id}.json")
        node_count = 0
        if os.path.exists(json_path):
            try:
                with open(json_path, 'r', encoding='utf-8') as f:
                    node_count = len(json.load(f))
            except Exception as e:
                logger.warning({"event": "workflow_list_error", "workflow": json_path, "error": str(e)})
        ui_schema = dict(config.get("ui", {}) or {})
        if provider == "openrouter":
            openrouter_cfg = config.get("openrouter", {}) or {}
            default_model = str(openrouter_cfg.get("model") or "google/gemini-3-pro-image")
            model_options = public_image_model_options()
            allowed_models = [
                str(model_id or "").strip()
                for model_id in (openrouter_cfg.get("allowed_models") or [])
                if str(model_id or "").strip()
            ]
            if allowed_models:
                model_options = [option for option in model_options if option.get("id") in allowed_models]
            default_quality = str(openrouter_cfg.get("default_quality") or "").strip().lower()
            default_resolution = str(openrouter_cfg.get("default_resolution") or "").strip().upper()
            if default_quality:
                for option in model_options:
                    if option.get("id") == default_model:
                        option["default_quality"] = default_quality
            if default_resolution:
                for option in model_options:
                    if option.get("id") == default_model and default_resolution in (option.get("resolutions") or []):
                        option["default_resolution"] = default_resolution
            ui_schema["hostedImageGeneration"] = {
                "default_model": default_model,
                "default_quality": default_quality or None,
                "default_resolution": default_resolution or None,
                "preference_scope": workflow_id if openrouter_cfg.get("workflow_scoped_preferences") else None,
                "model_locked": len(allowed_models) == 1,
                "models": model_options,
            }
        workflows.append({
            "id": workflow_id,
            "name": config.get("display_name", workflow_id.replace("_", " ").title()),
            "description": config.get("description", "워크플로우 설명이 없습니다."),
            "node_count": node_count,
            "hidden": bool(config.get("hidden", False)),
            "provider": provider,
            "category": config.get("category", "other"),
            "capability": config.get("capability"),
            "mcp_public": bool(config.get("mcp_public", False)),
            "style_prompt": config.get("style_prompt", ""),
            "negative_prompt": config.get("negative_prompt", ""),
            "recommended_prompt": config.get("recommended_prompt", ""),
            # expose ui schema & capabilities for flexible frontend rendering
            "ui": ui_schema,
            "sizes": config.get("sizes", {}),
            "image_input": config.get("image_input", None),
            # LoRA slots metadata (if provided)
            "lora_slots": config.get("loras", None),
            # LoRA slider hint (if provided)
            "lora_hint": config.get("lora_hint", None),
        })
    return {"workflows": workflows}


