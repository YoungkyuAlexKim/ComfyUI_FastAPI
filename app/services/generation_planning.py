"""Cost-free option planning for public MCP generation workflows."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import json
from threading import RLock
import time
from typing import Any, Mapping
import uuid

from .openrouter_client import public_image_model_options


PUBLIC_HOSTED_CAPABILITIES = (
    "create_managed_image_asset",
    "create_game_ui_assets",
    "create_character_sheet",
    "create_storyboard",
)
PUBLIC_LOCAL_CAPABILITIES = ("remove_background",)
PUBLIC_GENERATION_CAPABILITIES = PUBLIC_HOSTED_CAPABILITIES + PUBLIC_LOCAL_CAPABILITIES

GENERAL_IMAGE_MODELS = tuple(option["id"] for option in public_image_model_options())
GENERAL_IMAGE_RECOMMENDATION = "google/gemini-3.1-flash-image"
GPT_IMAGE_MODEL = "openai/gpt-image-2"
ASPECT_RATIOS = ("square", "landscape", "portrait")
EDIT_ASPECT_RATIOS = ("auto", *ASPECT_RATIOS)
IMAGE_SIZES = ("1K", "2K")
IMAGE_QUALITIES = ("low", "medium", "high")


def _model_choices() -> list[dict[str, Any]]:
    return [
        {
            "value": item["id"],
            "label": item["label"],
            "description": item["description"],
            "image_sizes": list(item["resolutions"]),
            "image_qualities": [quality["value"] for quality in item.get("qualities") or []],
            "recommended_image_size": item["default_resolution"],
            "recommended_image_quality": item.get("default_quality"),
            "zdr": bool(item.get("zdr", True)),
            "privacy_notice": item.get("privacy_notice") or None,
        }
        for item in public_image_model_options()
    ]


def generation_capability_contract(capability: str) -> dict[str, Any]:
    """Return one authoritative public option and clarification contract."""
    if capability not in PUBLIC_GENERATION_CAPABILITIES:
        raise ValueError(f"Unsupported generation capability: {capability}")

    if capability == "remove_background":
        return {
            "name": capability,
            "provider_cost": False,
            "local_execution": True,
            "execution_class": "fast",
            "asynchronous": True,
            "variants": ["default"],
            "description": (
                "Remove the background from one caller-owned image with the fixed local RMBG-2.0 workflow."
            ),
            "decision_fields": [],
            "optional_processing_fields": ["mask_blur", "mask_offset"],
            "fixed_options": {"provider": "comfyui", "model": "RMBG-2.0"},
            "planning": {
                "tool": "plan_generation",
                "required_before_write": True,
                "default_selection_mode": "clarify",
                "policy": (
                    "One caller-owned reference image is required. mask_blur and mask_offset are optional "
                    "processing controls with safe zero defaults, so no model or cost choice is needed."
                ),
            },
            "inputs": {
                "reference_image_ids": {
                    "type": "array",
                    "min_items": 1,
                    "max_items": 1,
                    "required": True,
                },
                "mask_blur": {
                    "type": "integer",
                    "minimum": 0,
                    "maximum": 64,
                    "default": 0,
                    "required": False,
                },
                "mask_offset": {
                    "type": "integer",
                    "minimum": -64,
                    "maximum": 64,
                    "default": 0,
                    "required": False,
                },
            },
            "output": {
                "type": "single managed image",
                "format": "PNG",
                "background": "transparent",
            },
            "cost": {
                "provider_api_cost_usd": 0.0,
                "note": "Local GPU time and infrastructure usage still apply.",
            },
        }

    common = {
        "name": capability,
        "provider_cost": True,
        "asynchronous": True,
        "planning": {
            "tool": "plan_generation",
            "required_before_write": True,
            "default_selection_mode": "clarify",
            "policy": (
                "If the user did not explicitly choose or clearly imply every decision field, call "
                "plan_generation with selection_mode=clarify and ask its questions before any write. "
                "Use selection_mode=recommend only when the user explicitly delegates the choices."
            ),
        },
    }

    if capability == "create_managed_image_asset":
        return {
            **common,
            "variants": ["generate", "edit"],
            "description": (
                "Create one company-managed image from text, or edit caller-owned reference images."
            ),
            "decision_fields": ["image_model", "aspect_ratio", "image_size", "image_quality"],
            "inputs": {
                "prompt": {"type": "string", "required": True, "max_length": 8000},
                "image_model": {
                    "required": True,
                    "choices": _model_choices(),
                    "recommended_when_delegated": GENERAL_IMAGE_RECOMMENDATION,
                },
                "aspect_ratio": {
                    "enum": list(EDIT_ASPECT_RATIOS),
                    "required": True,
                    "auto_requires_reference_image": True,
                    "recommended_when_delegated": {
                        "generate": "square",
                        "edit": "auto",
                    },
                },
                "image_size": {
                    "enum": list(IMAGE_SIZES),
                    "required": True,
                    "supported_values_depend_on": "image_model",
                },
                "image_quality": {
                    "enum": list(IMAGE_QUALITIES),
                    "required_when": {"image_model": GPT_IMAGE_MODEL},
                    "unsupported_for_other_models": True,
                },
                "reference_image_ids": {
                    "type": "array",
                    "items": {"type": "string"},
                    "max_items": 14,
                    "required": False,
                    "behavior": "When present, edit these owner-scoped image assets.",
                },
            },
            "output": {"type": "single managed image"},
        }

    if capability == "create_game_ui_assets":
        return {
            **common,
            "variants": ["default"],
            "description": "Create four related Game UI candidates and a managed group ZIP.",
            "decision_fields": ["background_mode", "image_quality"],
            "fixed_options": {
                "image_model": GPT_IMAGE_MODEL,
                "aspect_ratio": "square",
                "image_size": "2K",
                "grid": "2x2",
                "asset_count": 4,
            },
            "inputs": {
                "prompt": {"type": "string", "required": True, "max_length": 8000},
                "background_mode": {
                    "enum": ["transparent", "opaque"],
                    "required": True,
                    "recommended_when_delegated": "transparent",
                },
                "image_quality": {
                    "enum": list(IMAGE_QUALITIES),
                    "required": True,
                    "recommended_when_delegated": "medium",
                },
                "reference_image_ids": {
                    "type": "array",
                    "items": {"type": "string"},
                    "max_items": 3,
                    "required": False,
                },
            },
            "output": {"grid": "2x2", "asset_count": 4, "image_size": "2K"},
        }

    if capability == "create_character_sheet":
        return {
            **common,
            "variants": ["turnaround", "expressions"],
            "description": (
                "Create one character turnaround or expression sheet from one owned reference image."
            ),
            "decision_fields": ["sheet_type", "count", "image_size", "image_quality"],
            "fixed_options": {"image_model": GPT_IMAGE_MODEL},
            "inputs": {
                "reference_image_ids": {
                    "type": "array",
                    "min_items": 1,
                    "max_items": 1,
                    "required": True,
                },
                "sheet_type": {
                    "enum": ["turnaround", "expressions"],
                    "required": True,
                    "recommended_when_delegated": "turnaround",
                },
                "count": {
                    "allowed_by_sheet_type": {"turnaround": [3, 5, 8], "expressions": [4, 9]},
                    "required": True,
                    "recommended_when_delegated": {"turnaround": 5, "expressions": 9},
                },
                "prompt": {
                    "type": "string",
                    "required": False,
                    "max_length": 4000,
                    "behavior": "Optional rendering guidance; identity comes from the reference.",
                },
                "image_size": {
                    "enum": list(IMAGE_SIZES),
                    "required": True,
                    "recommended_when_delegated": "2K",
                },
                "image_quality": {
                    "enum": list(IMAGE_QUALITIES),
                    "required": True,
                    "recommended_when_delegated": "medium",
                },
            },
            "output": {"type": "single managed sheet image"},
        }

    return {
        **common,
        "variants": ["default"],
        "description": "Create one coherent six- or nine-cut storyboard from one owned reference image.",
        "decision_fields": ["cuts", "image_size", "image_quality"],
        "fixed_options": {"image_model": GPT_IMAGE_MODEL},
        "inputs": {
            "reference_image_ids": {
                "type": "array",
                "min_items": 1,
                "max_items": 1,
                "required": True,
            },
            "prompt": {"type": "string", "required": True, "max_length": 8000},
            "cuts": {
                "enum": [6, 9],
                "required": True,
                "recommended_when_delegated": 9,
            },
            "image_size": {
                "enum": list(IMAGE_SIZES),
                "required": True,
                "recommended_when_delegated": "2K",
            },
            "image_quality": {
                "enum": list(IMAGE_QUALITIES),
                "required": True,
                "recommended_when_delegated": "medium",
            },
        },
        "output": {"type": "single managed sheet image", "cuts": [6, 9]},
    }


def hosted_capability_contract(capability: str) -> dict[str, Any]:
    """Backward-compatible hosted-only contract helper."""
    if capability not in PUBLIC_HOSTED_CAPABILITIES:
        raise ValueError(f"Unsupported hosted generation capability: {capability}")
    return generation_capability_contract(capability)


def list_hosted_capability_contracts() -> list[dict[str, Any]]:
    return [generation_capability_contract(name) for name in PUBLIC_HOSTED_CAPABILITIES]


def list_generation_capability_contracts() -> list[dict[str, Any]]:
    return [generation_capability_contract(name) for name in PUBLIC_GENERATION_CAPABILITIES]


def _present(value: Any) -> bool:
    return value is not None and (not isinstance(value, str) or bool(value.strip()))


def _enum_value(options: Mapping[str, Any], field: str, allowed: tuple[Any, ...]) -> Any | None:
    value = options.get(field)
    if not _present(value):
        return None
    if value not in allowed:
        raise ValueError(f"{field} must be one of: {', '.join(str(item) for item in allowed)}")
    return value


class HostedGenerationPlanner:
    """Validate explicit choices and identify choices that still need user clarification."""

    def plan(
        self,
        capability: str,
        *,
        prompt: str,
        options: Mapping[str, Any] | None,
        selection_mode: str,
        has_reference_images: bool = False,
    ) -> dict[str, Any]:
        contract = generation_capability_contract(capability)
        mode = str(selection_mode or "clarify").strip().lower()
        if mode not in {"clarify", "recommend"}:
            raise ValueError("selection_mode must be clarify or recommend")
        clean_prompt = str(prompt or "").strip()
        if capability not in {"create_character_sheet", "remove_background"} and not clean_prompt:
            raise ValueError("prompt is required for this capability")
        maximum = 4000 if capability == "create_character_sheet" else 8000
        if len(clean_prompt) > maximum:
            raise ValueError(f"prompt must be at most {maximum} characters")

        supplied = dict(options or {})
        allowed_fields = set(contract["decision_fields"])
        allowed_fields.update(contract.get("optional_processing_fields") or [])
        unknown = sorted(set(supplied) - allowed_fields)
        if unknown:
            raise ValueError(f"Unsupported options for {capability}: {', '.join(unknown)}")

        resolved: dict[str, Any] = deepcopy(contract.get("fixed_options") or {})
        missing: list[str] = []
        applied: list[str] = []
        conditional_questions: list[dict[str, Any]] = []

        def decide(field: str, allowed: tuple[Any, ...], recommendation: Any) -> Any | None:
            value = _enum_value(supplied, field, allowed)
            if value is not None:
                resolved[field] = value
                return value
            if mode == "recommend":
                resolved[field] = recommendation
                applied.append(field)
                return recommendation
            missing.append(field)
            return None

        if capability == "remove_background":
            for field, minimum, maximum in (
                ("mask_blur", 0, 64),
                ("mask_offset", -64, 64),
            ):
                value = supplied.get(field, 0)
                if isinstance(value, bool) or not isinstance(value, int):
                    raise ValueError(f"{field} must be an integer")
                if value < minimum or value > maximum:
                    raise ValueError(f"{field} must be between {minimum} and {maximum}")
                resolved[field] = value

        elif capability == "create_managed_image_asset":
            model = decide("image_model", GENERAL_IMAGE_MODELS, GENERAL_IMAGE_RECOMMENDATION)
            allowed_aspects = EDIT_ASPECT_RATIOS if has_reference_images else ASPECT_RATIOS
            decide("aspect_ratio", allowed_aspects, "auto" if has_reference_images else "square")
            model_metadata = {
                item["id"]: item for item in public_image_model_options()
            }
            supported_sizes = tuple((model_metadata.get(model) or {}).get("resolutions") or IMAGE_SIZES)
            recommended_size = (model_metadata.get(model) or {}).get("default_resolution") or "1K"
            decide("image_size", supported_sizes, recommended_size)
            quality = supplied.get("image_quality")
            if model == GPT_IMAGE_MODEL:
                decide("image_quality", IMAGE_QUALITIES, "medium")
            elif _present(quality):
                if model is None:
                    if quality not in IMAGE_QUALITIES:
                        raise ValueError("image_quality must be low, medium, or high")
                    resolved["image_quality"] = quality
                else:
                    raise ValueError("image_quality is supported only by GPT Image 2")
            if model is None:
                conditional_questions.append(
                    {
                        "field": "image_quality",
                        "required_when": {"image_model": GPT_IMAGE_MODEL},
                        "question": (
                            "If GPT Image 2 is selected, should quality be low, medium, or high?"
                        ),
                        "choices": list(IMAGE_QUALITIES),
                        "recommendation": "medium",
                    }
                )

        elif capability == "create_game_ui_assets":
            decide("background_mode", ("transparent", "opaque"), "transparent")
            decide("image_quality", IMAGE_QUALITIES, "medium")

        elif capability == "create_character_sheet":
            sheet_type = decide("sheet_type", ("turnaround", "expressions"), "turnaround")
            allowed_counts = {
                "turnaround": (3, 5, 8),
                "expressions": (4, 9),
            }
            count = supplied.get("count")
            if _present(count):
                if isinstance(count, bool) or not isinstance(count, int):
                    raise ValueError("count must be an integer")
                if sheet_type is not None and count not in allowed_counts[sheet_type]:
                    allowed = ", ".join(str(item) for item in allowed_counts[sheet_type])
                    raise ValueError(f"count for {sheet_type} must be one of: {allowed}")
                if sheet_type is None and count not in {3, 4, 5, 8, 9}:
                    raise ValueError("count must be one of: 3, 4, 5, 8, 9")
                resolved["count"] = count
            elif mode == "recommend":
                resolved["count"] = 5 if sheet_type == "turnaround" else 9
                applied.append("count")
            else:
                missing.append("count")
            decide("image_size", IMAGE_SIZES, "2K")
            decide("image_quality", IMAGE_QUALITIES, "medium")
            if sheet_type is not None:
                resolved["aspect_ratio"] = "landscape" if sheet_type == "turnaround" else "square"

        else:
            cuts = decide("cuts", (6, 9), 9)
            decide("image_size", IMAGE_SIZES, "2K")
            decide("image_quality", IMAGE_QUALITIES, "medium")
            if cuts is not None:
                resolved["aspect_ratio"] = "landscape" if cuts == 6 else "square"
                resolved["grid"] = "2x3" if cuts == 6 else "3x3"

        questions = [
            self._question(
                capability,
                field,
                resolved,
                has_reference_images=has_reference_images,
            )
            for field in missing
        ]
        return {
            "capability": capability,
            "selection_mode": mode,
            "ready_to_generate": not missing,
            "requires_clarification": bool(missing),
            "missing_decisions": missing,
            "questions": questions,
            "conditional_questions": conditional_questions,
            "resolved_options": resolved,
            "recommendations_applied": applied,
            "provider_cost": bool(contract["provider_cost"]),
            "prompt": clean_prompt,
        }

    @staticmethod
    def _question(
        capability: str,
        field: str,
        resolved: Mapping[str, Any],
        *,
        has_reference_images: bool,
    ) -> dict[str, Any]:
        if field == "image_model":
            return {
                "field": field,
                "question": "Which managed image model should be used?",
                "choices": _model_choices(),
                "recommendation": GENERAL_IMAGE_RECOMMENDATION,
            }
        if field == "aspect_ratio":
            return {
                "field": field,
                "question": (
                    "Should the edit preserve the input ratio automatically, or use square, landscape, or portrait?"
                    if has_reference_images
                    else "Should the output be square, landscape, or portrait?"
                ),
                "choices": list(EDIT_ASPECT_RATIOS if has_reference_images else ASPECT_RATIOS),
                "recommendation": "auto" if has_reference_images else "square",
            }
        if field == "image_size":
            return {
                "field": field,
                "question": "Should this be a 1K draft or a 2K final-size image?",
                "choices": list(IMAGE_SIZES),
                "recommendation": "2K" if capability != "create_managed_image_asset" else "1K",
            }
        if field == "image_quality":
            return {
                "field": field,
                "question": "Which GPT Image 2 quality level should be used?",
                "choices": list(IMAGE_QUALITIES),
                "recommendation": "medium",
            }
        if field == "background_mode":
            return {
                "field": field,
                "question": "Should the Game UI assets have transparent or opaque backgrounds?",
                "choices": ["transparent", "opaque"],
                "recommendation": "transparent",
            }
        if field == "sheet_type":
            return {
                "field": field,
                "question": "Do you want a turnaround sheet or an expression sheet?",
                "choices": ["turnaround", "expressions"],
                "recommendation": "turnaround",
            }
        if field == "count":
            return {
                "field": field,
                "question": "How many views or expressions should the sheet contain?",
                "choices": {"turnaround": [3, 5, 8], "expressions": [4, 9]},
                "depends_on": "sheet_type",
            }
        return {
            "field": "cuts",
            "question": "Should the storyboard contain 6 cuts or 9 cuts?",
            "choices": [6, 9],
            "recommendation": 9,
        }


@dataclass(frozen=True)
class StoredGenerationPlan:
    principal_id: str
    capability: str
    canonical_arguments: str
    expires_at: float


class EphemeralGenerationPlanStore:
    """Short-lived, owner-bound plans that prevent option drift before a paid write."""

    def __init__(self, *, ttl_seconds: int = 1800, max_entries: int = 10_000):
        self.ttl_seconds = max(60, min(7200, int(ttl_seconds)))
        self.max_entries = max(100, min(100_000, int(max_entries)))
        self._lock = RLock()
        self._plans: dict[str, StoredGenerationPlan] = {}

    @staticmethod
    def _canonical(arguments: Mapping[str, Any]) -> str:
        return json.dumps(dict(arguments), ensure_ascii=False, sort_keys=True, separators=(",", ":"))

    def issue(self, principal_id: str, capability: str, arguments: Mapping[str, Any]) -> dict[str, Any]:
        now = time.time()
        plan_id = f"plan_{uuid.uuid4().hex}"
        with self._lock:
            self._plans = {
                key: value for key, value in self._plans.items() if value.expires_at > now
            }
            overflow = len(self._plans) - self.max_entries + 1
            if overflow > 0:
                oldest = sorted(self._plans, key=lambda key: self._plans[key].expires_at)[:overflow]
                for key in oldest:
                    self._plans.pop(key, None)
            self._plans[plan_id] = StoredGenerationPlan(
                principal_id=str(principal_id),
                capability=str(capability),
                canonical_arguments=self._canonical(arguments),
                expires_at=now + self.ttl_seconds,
            )
        return {
            "plan_id": plan_id,
            "expires_in_seconds": self.ttl_seconds,
            "suggested_idempotency_key": f"intent-{plan_id[5:]}",
        }

    def validate(
        self,
        plan_id: str,
        *,
        principal_id: str,
        capability: str,
        arguments: Mapping[str, Any],
    ) -> None:
        now = time.time()
        key = str(plan_id or "").strip()
        with self._lock:
            stored = self._plans.get(key)
            if stored and stored.expires_at <= now:
                self._plans.pop(key, None)
                stored = None
        if not stored:
            raise ValueError("generation_plan_required: plan is missing or expired; call plan_generation again")
        if stored.principal_id != str(principal_id) or stored.capability != str(capability):
            raise ValueError("generation_plan_mismatch: plan owner or capability does not match")
        if stored.canonical_arguments != self._canonical(arguments):
            raise ValueError(
                "generation_plan_mismatch: generation arguments changed; call plan_generation again"
            )
