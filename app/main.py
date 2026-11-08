from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect, Request, BackgroundTasks, Form, UploadFile, File
from fastapi.responses import HTMLResponse, JSONResponse, Response
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from typing import Literal, Optional, List, Tuple
import time
import os
import asyncio
import json
import uuid
from datetime import datetime, timezone
import hashlib
import secrets
from io import BytesIO
import sqlite3
import shutil

try:
    from PIL import Image
except Exception:
    Image = None

from .config import SERVER_CONFIG, get_default_values
from .config import QUEUE_CONFIG, JOB_DB_PATH
from .config import HEALTHZ_CONFIG
from .job_manager import JobManager, Job
from .job_store import JobStore
from .asset_store import AssetStore
from .logging_utils import setup_logging
from .config import UPLOAD_CONFIG
from .auth.user_management import (
    _ensure_anon_id_cookie,
    _get_anon_id_from_request,
    _get_anon_id_from_ws,
    _set_principal_cookies,
    prepare_request_principal,
    ANON_COOKIE_NAME,
    ANON_COOKIE_PREFIX,
)
from .auth.mcp_identity import principal_for_mcp_ip
from .services.media_store import (
    _user_base_dir,
    _date_partition_path,
    _build_web_path,
    _save_image_and_meta,
    _gather_user_images,
    _locate_image_meta_path,
    _update_image_status,
)
from .routers.admin import router as admin_router
from .routers.workflows import router as workflows_router
from .routers.images import router as images_router
from .routers.inputs import router as inputs_router
from .routers.health import router as health_router
from .routers.jobs import router as jobs_router
from .routers.feed import router as feed_router
from .routers.audio import router as audio_router
from .routers.admin_feed import router as admin_feed_router
from .routers.assets import router as assets_router
from .routers.principal_links import router as principal_links_router
from .ws.manager import manager
from .ws.routes import router as ws_router
from .schemas.api_models import EnqueueResponse, JobStatusResponse, CancelActiveResponse, TranslateResponse
from .services.generation import run_generation_processor
from .services.generation_commands import (
    dispatch_legacy_web_request,
    generation_context_from_http_request,
    resolve_client_ip,
)
from .services.generation_controls import GenerationControlService, GenerationPolicyError
from .services.generation_submission import GenerationSubmissionService
from .services.asset_service import AssetService
from .services.asset_runtime import configure_asset_service
from .services.principal_links import mcp_web_link_enabled
from .mcp_server import create_mcp_integration
from .principal_link_store import PrincipalLinkStore
from .services.openrouter_client import (
    OpenRouterUpstreamError,
    generate_text,
    gpt_image_timeout_seconds,
    is_configured as openrouter_is_configured,
)
from .auth.user_management import _parse_bool as _parse_bool_cookie_secure
from .rate_limiter import SlidingWindowRateLimiter

logger = setup_logging()

templates = Jinja2Templates(directory="templates")
app = FastAPI(title="ComfyUI FastAPI Server", version="0.8.0 (Direct MCP Image Upload)")
app.include_router(admin_router)
app.include_router(ws_router)
app.include_router(workflows_router)
app.include_router(images_router)
app.include_router(inputs_router)
app.include_router(health_router)
app.include_router(jobs_router)
app.include_router(feed_router)
app.include_router(audio_router)
app.include_router(admin_feed_router)
app.include_router(assets_router)
app.include_router(principal_links_router)


@app.middleware("http")
async def principal_session_middleware(request: Request, call_next):
    """Upgrade legacy browser identities to a signed server session."""

    path = request.url.path or ""
    if (
        path == "/healthz"
        or path == "/mcp"
        or path.startswith("/mcp/")
        or path == "/api/v1/mcp/inputs/upload"
        or getattr(request.state, "mcp_output_authorized", False)
    ):
        # Health checks have no browser identity, and MCP derives its principal
        # from the verified client IP. MCP output authorization is established
        # by private_sidecar_middleware before this middleware runs.
        return await call_next(request)
    principal_id, needs_upgrade = prepare_request_principal(request)
    response = await call_next(request)
    if needs_upgrade:
        _set_principal_cookies(request, response, principal_id)
        logger.info(
            {
                "event": "principal_identity_cookie_issued",
                "identity_source": getattr(request.state, "principal_identity_source", "unknown"),
                "principal_hash": hashlib.sha256(principal_id.encode("utf-8")).hexdigest()[:16],
            }
        )
    return response

# --- HTTP request logging middleware ---
@app.middleware("http")
async def http_logging_middleware(request: Request, call_next):
    path = request.url.path or ""
    # Skip very noisy static mounts
    if path.startswith("/static") or path.startswith("/outputs"):
        return await call_next(request)
    req_id = uuid.uuid4().hex
    request.state.request_id = req_id
    start = time.perf_counter()
    try:
        logger.info({"event": "http_request", "request_id": req_id, "method": request.method, "path": path})
        response = await call_next(request)
        duration_ms = int((time.perf_counter() - start) * 1000)
        try:
            response.headers["X-Request-ID"] = req_id
        except Exception:
            pass
        logger.info({
            "event": "http_response",
            "request_id": req_id,
            "method": request.method,
            "path": path,
            "status_code": getattr(response, "status_code", None),
            "duration_ms": duration_ms,
        })
        return response
    except Exception as e:
        duration_ms = int((time.perf_counter() - start) * 1000)
        logger.error({
            "event": "http_exception",
            "request_id": req_id,
            "method": request.method,
            "path": path,
            "error": str(e),
            "duration_ms": duration_ms,
        })
        raise

# --- Global exception handlers ---
@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    logger.warning({
        "event": "http_error",
        "path": request.url.path,
        "method": request.method,
        "status_code": exc.status_code,
        "detail": exc.detail,
    })
    # Preserve headers (e.g. WWW-Authenticate) so HTTPBasic auth prompts work in browsers.
    # Without this, FastAPI's auth challenges degrade into plain JSON errors and users
    # won't see the credential popup.
    try:
        headers = getattr(exc, "headers", None)
    except Exception:
        headers = None
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail}, headers=headers)

@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    logger.error({
        "event": "unhandled_exception",
        "path": request.url.path,
        "method": request.method,
        "error": str(exc),
    })
    return JSONResponse(status_code=500, content={"detail": "Internal Server Error"})

# --- API 요청 모델 (v3.0 기준) ---
class GenerateRequest(BaseModel):
    user_prompt: str
    aspect_ratio: str  # 'width', 'height' 대신 'aspect_ratio' 사용
    workflow_id: str
    seed: Optional[int] = None
    # Optional output image size (for supported providers/workflows, e.g. Nano Banana)
    # Allowed examples: "1K", "2K"
    image_size: Optional[str] = None
    # Hosted image model override. The server validates this against an allowlist.
    image_model: Optional[str] = None
    # Model-specific quality option (currently GPT Image 2: low/medium/high).
    image_quality: Optional[str] = None
    # Direct image-to-image input
    input_image_id: Optional[str] = None  # 기존에 저장된 이미지 id
    # Optional multi-image input (used by specific providers/workflows; backward-compatible)
    # 규칙: input_image_ids가 비어있지 않으면 우선 사용, 아니면 input_image_id 사용
    input_image_ids: Optional[List[str]] = None
    # Optional LoRA strengths (per-slot) – forward-compatible
    # Example: [{"slot":"character","unet":1.0,"clip":1.0},{"slot":"style","unet":0.8,"clip":0.8}]
    loras: Optional[List[dict]] = None
    # --- Game UI element maker params ---
    game_ui_background_mode: Optional[str] = None
    game_ui_grid: Literal["2x2", "3x3", "4x4"] = "2x2"

OUTPUT_DIR = SERVER_CONFIG["output_dir"]



"""
Filesystem helpers were extracted to app/services/media_store.py.
Imports above wire them in; local duplicates removed to reduce main.py size.
"""

# All remaining workflows run on hosted providers (OpenRouter); workers are tuned at startup.
job_manager = JobManager(worker_count=4)
job_store = JobStore(JOB_DB_PATH)
generation_controls = GenerationControlService(JOB_DB_PATH)
generation_submissions = GenerationSubmissionService(job_manager, generation_controls)
from .feed_store import FeedStore
feed_store = FeedStore(JOB_DB_PATH)
asset_store = AssetStore(JOB_DB_PATH)
asset_service = AssetService(asset_store, SERVER_CONFIG["output_dir"])
principal_link_store = PrincipalLinkStore(JOB_DB_PATH)
configure_asset_service(asset_service)
try:
    app.state.connection_manager = manager
    app.state.job_manager = job_manager
    app.state.job_store = job_store
    app.state.generation_controls = generation_controls
    app.state.feed_store = feed_store
    app.state.asset_service = asset_service
    app.state.principal_link_store = principal_link_store
except Exception as e:
    logger.debug({"event": "app_state_init_failed", "error": str(e)})


# --- Simple per-user rate limit for /api/v1/generate (optional; env-controlled) ---
_gen_rate_limiter: SlidingWindowRateLimiter | None = None
_gen_rate_limit_cached: int | None = None


def _get_gen_rate_limiter() -> tuple[SlidingWindowRateLimiter | None, int]:
    """
    Returns (limiter_or_none, limit_per_min).
    - When limit_per_min <= 0: disabled.
    """
    global _gen_rate_limiter, _gen_rate_limit_cached
    try:
        limit = int(os.getenv("GEN_RATE_LIMIT_PER_MIN", "0") or "0")
    except Exception:
        limit = 0
    limit = max(0, int(limit))

    if limit <= 0:
        _gen_rate_limiter = None
        _gen_rate_limit_cached = limit
        return None, limit

    if _gen_rate_limiter is None or _gen_rate_limit_cached != limit:
        _gen_rate_limiter = SlidingWindowRateLimiter(max_per_window=limit, window_seconds=60)
        _gen_rate_limit_cached = limit
    return _gen_rate_limiter, limit


def _admin_auth_enabled() -> bool:
    user = os.getenv("ADMIN_USER")
    pw = os.getenv("ADMIN_PASSWORD")
    return bool(user) and bool(pw)


def _is_admin_basic_auth_header(auth_header: str | None) -> bool:
    if not _admin_auth_enabled():
        return False
    try:
        if not isinstance(auth_header, str) or not auth_header:
            return False
        if not auth_header.lower().startswith("basic "):
            return False
        import base64
        import secrets

        raw = auth_header.split(" ", 1)[1].strip()
        decoded = base64.b64decode(raw).decode("utf-8", errors="ignore")
        if ":" not in decoded:
            return False
        username, password = decoded.split(":", 1)
        expected_user = os.getenv("ADMIN_USER", "")
        expected_pw = os.getenv("ADMIN_PASSWORD", "")
        return secrets.compare_digest(username or "", expected_user) and secrets.compare_digest(password or "", expected_pw)
    except Exception:
        return False


@app.middleware("http")
async def feed_trash_access_middleware(request: Request, call_next):
    """
    Feed trash assets must be accessible only to admin.

    - Non-admin: pretend it doesn't exist (404) to avoid leaking deleted content.
    - Admin: allowed (browser already has BasicAuth from /admin).
    """
    path = request.url.path or ""
    if path.startswith("/outputs/feed/trash/"):
        if _is_admin_basic_auth_header(request.headers.get("Authorization")):
            return await call_next(request)
        return Response(status_code=404)
    return await call_next(request)


@app.middleware("http")
async def private_sidecar_middleware(request: Request, call_next):
    """Protect user media while preserving existing output URLs."""

    path = request.url.path or ""
    prefix = "/outputs/users/"
    if path.startswith("/outputs/feed/") and path.lower().endswith(".json"):
        return Response(status_code=404)
    if not path.startswith(prefix):
        return await call_next(request)
    if path.lower().endswith(".json"):
        return Response(status_code=404)

    relative = path[len(prefix) :]
    owner_id = relative.split("/", 1)[0]
    if not owner_id:
        return Response(status_code=404)
    if _is_admin_basic_auth_header(request.headers.get("Authorization")):
        return await call_next(request)

    expected_owner = _get_anon_id_from_request(request)
    is_mcp_owner = owner_id.startswith("mcp-ip-")
    if is_mcp_owner:
        peer_ip = getattr(getattr(request, "client", None), "host", None)
        client_ip, _ = resolve_client_ip(
            peer_ip,
            request.headers.get("x-forwarded-for"),
            os.getenv("TRUSTED_PROXY_CIDRS"),
        )
        expected_owner = principal_for_mcp_ip(client_ip)
    authorized_by_current_ip = secrets.compare_digest(owner_id, expected_owner)
    authorized_by_link = False
    if is_mcp_owner and not authorized_by_current_ip and mcp_web_link_enabled():
        browser_owner = _get_anon_id_from_request(request)
        link_store = getattr(request.app.state, "principal_link_store", None)
        try:
            authorized_by_link = bool(link_store and link_store.is_linked(browser_owner, owner_id))
        except (TypeError, ValueError):
            authorized_by_link = False
    if not authorized_by_current_ip and not authorized_by_link:
        return Response(status_code=404)
    if is_mcp_owner and authorized_by_current_ip:
        # Later middleware may bypass browser-only gates only after this owner
        # check succeeds. Request state cannot be supplied by the HTTP caller.
        request.state.mcp_output_authorized = True
    return await call_next(request)

# --- Helpers ---
def _paginate(items: list, page: int, size: int):
    try:
        size_val = int(size)
    except Exception:
        size_val = 24
    try:
        page_val = int(page)
    except Exception:
        page_val = 1
    size_val = max(1, min(100, size_val))
    page_val = max(1, page_val)
    total = len(items)
    start = (page_val - 1) * size_val
    end = start + size_val
    slice_items = items[start:end]
    total_pages = (total + size_val - 1) // size_val
    return slice_items, {"page": page_val, "size": size_val, "total": total, "total_pages": total_pages}

@app.get("/", tags=["Page"])
async def landing(request: Request):
    resp = RedirectResponse(url="/feed", status_code=303)
    _ensure_anon_id_cookie(request, resp)
    return resp


@app.get("/create", response_class=HTMLResponse, tags=["Page"])
async def create_page(request: Request):
    default_values = get_default_values()
    api_key_present = openrouter_is_configured()
    prompt_translate_enabled = _parse_bool_cookie_secure(
        os.getenv("ENABLE_PROMPT_TRANSLATE"),
        api_key_present,
    )
    # Always require API key for this feature to appear (avoid confusing UI)
    prompt_translate_enabled = bool(prompt_translate_enabled and api_key_present)
    anon_id = _get_anon_id_from_request(request)
    response = templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "anon_id": anon_id,
            "current_page": "create",
            "prompt_translate_enabled": prompt_translate_enabled,
            "default_user_prompt": "",
            "default_style_prompt": default_values.get("style_prompt", ""),
            "default_negative_prompt": default_values.get("negative_prompt", ""),
            "default_recommended_prompt": default_values.get("recommended_prompt", ""),
            "workflows_sizes_json": json.dumps(default_values.get("workflows_sizes", {})),
            "workflow_default_prompts_json": json.dumps(default_values.get("workflow_default_prompts", {})),
            "workflow_prompt_templates_json": json.dumps(default_values.get("workflow_prompt_templates", {})),
        },
    )
    _ensure_anon_id_cookie(request, response, anon_id)
    return response


@app.get("/mcp-connect", response_class=HTMLResponse, tags=["Page"])
async def mcp_connect_page(request: Request):
    """Render the internal onboarding page for supported MCP clients."""
    configured_base = str(os.getenv("MCP_PUBLIC_BASE_URL") or "").strip().rstrip("/")
    public_base_url = configured_base or str(request.base_url).rstrip("/")
    mcp_url = f"{public_base_url}/mcp/"
    anon_id = _get_anon_id_from_request(request)
    response = templates.TemplateResponse(
        "mcp_connect.html",
        {
            "request": request,
            "anon_id": anon_id,
            "current_page": "mcp_connect",
            "mcp_url": mcp_url,
            "canvas_url": f"{public_base_url}/create",
            "codex_add_command": f"codex mcp add lc_ai_canvas --url {mcp_url}",
            "claude_add_command": (
                "claude mcp add --transport http --scope user "
                f"lc_ai_canvas {mcp_url}"
            ),
        },
    )
    _ensure_anon_id_cookie(request, response, anon_id)
    return response


@app.get("/feed", response_class=HTMLResponse, tags=["Page"])
async def feed_page(request: Request):
    anon_id = _get_anon_id_from_request(request)
    response = templates.TemplateResponse(
        "feed.html",
        {
            "request": request,
            "anon_id": anon_id,
            "current_page": "feed",
        },
    )
    _ensure_anon_id_cookie(request, response, anon_id)
    return response


# Workflows routes moved to app/routers/workflows.py

def _processor_generate(job: Job, progress_cb):
    def _set_cancel_handle(handle):
        try:
            # 멀티 워커(나노바나나 동시 실행)에서도 안전하도록 job_id 단위로 cancel handle을 등록합니다.
            job_manager.set_cancel_handle(job.id, handle)
        except Exception:
            pass
    run_generation_processor(job, progress_cb, _set_cancel_handle)

@app.post("/api/v1/generate", tags=["Image Generation"], response_model=EnqueueResponse)
async def generate_image(request: GenerateRequest, http_request: Request):
    anon_id = _get_anon_id_from_request(http_request)
    # Rate limit (per anon_id) - 1차 방어용
    limiter, limit = _get_gen_rate_limiter()
    if limiter is not None and limit > 0:
        allowed, remaining, retry_after = limiter.take(anon_id)
        if not allowed:
            msg = f"요청이 너무 많습니다. 1분에 최대 {limit}회까지만 생성할 수 있습니다. {retry_after}초 후 다시 시도해 주세요."
            logger.info(
                {
                    "event": "generate_rate_limited",
                    "owner_id": anon_id,
                    "limit_per_min": limit,
                    "retry_after_sec": retry_after,
                    "path": "/api/v1/generate",
                }
            )
            raise HTTPException(status_code=429, detail=msg, headers={"Retry-After": str(retry_after)})
    try:
        context = generation_context_from_http_request(http_request, anon_id)
        resolved = dispatch_legacy_web_request(request.model_dump(), context)
    except ValueError as e:
        logger.info(
            {
                "event": "generate_command_rejected",
                "owner_id": anon_id,
                "request_id": getattr(getattr(http_request, "state", None), "request_id", None),
                "reason": str(e),
                "path": "/api/v1/generate",
            }
        )
        raise HTTPException(status_code=400, detail=str(e))
    try:
        cost_confirmed = str(http_request.headers.get("x-cost-confirmed") or "").strip().lower() in {
            "1",
            "true",
            "yes",
            "on",
        }
        submission = generation_submissions.submit(resolved, cost_confirmed=cost_confirmed)
    except GenerationPolicyError as e:
        logger.info(
            {
                "event": "generate_policy_rejected",
                "owner_id": anon_id,
                "request_id": resolved.command.context.request_id,
                "capability": resolved.command.capability,
                "reason_code": e.code,
                "path": "/api/v1/generate",
            }
        )
        raise HTTPException(status_code=e.status_code, detail=e.api_detail())
    except RuntimeError as e:
        logger.info({"event": "enqueue_rejected", "owner_id": anon_id, "reason": str(e), "path": "/api/v1/generate"})
        raise HTTPException(status_code=429, detail=str(e))

    if submission.duplicate:
        logger.info(
            {
                "event": "generate_idempotency_replay",
                "owner_id": anon_id,
                "request_id": resolved.command.context.request_id,
                "job_id": submission.job_id,
            }
        )
        return {
            "job_id": submission.job_id,
            "status": "duplicate",
            "position": submission.position,
            "estimated_cost_usd": submission.estimated_cost_usd,
            "cost_estimate_available": submission.estimated_cost_usd is not None,
        }

    logger.info(
        {
            "event": "enqueue",
            "owner_id": anon_id,
            "job_id": submission.job_id,
            "position": submission.position,
            "request_id": resolved.command.context.request_id,
            "request_source": resolved.command.context.source,
            "client_ip": resolved.command.context.client_ip,
            "capability": resolved.command.capability,
            "capability_variant": resolved.command.variant,
            "workflow_id": resolved.workflow_id,
            "provider": resolved.provider,
            "model": resolved.model,
            "estimated_cost_usd": submission.estimated_cost_usd,
        }
    )
    return {
        "job_id": submission.job_id,
        "status": "queued",
        "position": submission.position,
        "estimated_cost_usd": submission.estimated_cost_usd,
        "cost_estimate_available": submission.estimated_cost_usd is not None,
    }


# Images routes moved to app/routers/images.py


# -------------------- Controls (user) --------------------

# Controls upload moved to app/routers/controls.py


# Controls list moved to app/routers/controls.py


# Controls delete/restore moved to app/routers/controls.py


# Images delete moved to app/routers/images.py



@app.post("/api/v1/jobs/{job_id}/cancel", tags=["Image Generation"])
async def cancel_generation_by_id(job_id: str):
    ok = job_manager.cancel(job_id)
    if not ok:
        raise HTTPException(status_code=400, detail="Job not found or not cancellable")
    return {"ok": True}

@app.get("/api/v1/jobs/{job_id}", tags=["Image Generation"], response_model=JobStatusResponse)
async def job_status(job_id: str):
    j = job_manager.get(job_id)
    if not j:
        raise HTTPException(status_code=404, detail="Job not found")
    return {
        "id": j.id,
        "status": j.status,
        "progress": j.progress,
        "position": job_manager.get_position(job_id),
        "result": j.result,
        "error": j.error_message,
    }

@app.post("/api/v1/cancel", tags=["Image Generation"], response_model=CancelActiveResponse)
async def cancel_active_for_user(request: Request):
    anon_id = _get_anon_id_from_request(request)
    j = job_manager.get_active_for_owner(anon_id)
    if not j:
        raise HTTPException(status_code=400, detail="No active generation to cancel.")
    ok = job_manager.cancel(j.id)
    if not ok:
        raise HTTPException(status_code=500, detail="Failed to cancel job.")
    await manager.send_json_to_user(anon_id, {"status": "cancelling", "job_id": j.id})
    return {"message": "Cancel request sent.", "job_id": j.id}

@app.post("/api/v1/translate-prompt", tags=["Prompt Translation"], response_model=TranslateResponse)
async def translate_prompt_endpoint(text: str = Form(...), mode: str = Form("image")):
    if not openrouter_is_configured():
        raise HTTPException(status_code=503, detail="번역 기능(API)이 설정되지 않았습니다. 서버 .env에 OPENROUTER_API_KEY를 설정해 주세요.")
    model = os.getenv("OPENROUTER_TEXT_MODEL") or "google/gemini-3.1-flash-lite"
    raw = (text or "").strip()
    if not raw:
        raise HTTPException(status_code=400, detail="번역할 내용을 입력해주세요.")

    mode = (mode or "image").strip().lower()

    # Image prompt translation (music modes were retired with the ACE-Step workflow)
    if mode != "image":
        raise HTTPException(status_code=400, detail="지원하지 않는 번역 모드입니다.")
    instruction = (
        "아래 한국어 설명을 이미지 생성 AI가 이해하기 좋은 영어 프롬프트로 변환해줘.\n"
        "조건:\n"
        "- 사용자의 의도를 최대한 그대로 유지\n"
        "- 영어로만 작성\n"
        "- 결과는 가장 베스트 1개만\n"
        "- 설명/해설/옵션/번호/따옴표/마크다운 없이, 프롬프트 문장만 한 줄로 출력\n"
        "- Danbooru 태그 나열이 아니라 자연스러운 영어 프롬프트 문장으로 작성\n\n"
        f"한국어 원문:\n{raw}\n"
    )

    try:
        out = generate_text(
            prompt=instruction,
            model=model,
            temperature=0.2,
            top_p=0.95,
            max_tokens=256,
            timeout=(5.0, 30.0),
        )
    except OpenRouterUpstreamError as e:
        logger.warning({"event": "prompt_translate_upstream_error", "error": str(e)})
        status = getattr(e, "http_status", None)
        if getattr(e, "kind", "") == "openrouter_auth":
            status = 401
        elif getattr(e, "kind", "") in ("openrouter_rate_limited", "openrouter_credits_exhausted"):
            status = 429
        elif getattr(e, "kind", "") == "openrouter_bad_request":
            status = 400
        else:
            status = 502
        raise HTTPException(status_code=status, detail=getattr(e, "public_message", str(e)))

    # Ensure single-line response (best-effort) for image prompts
    out = (out.splitlines() or [""])[0].strip()
    # Remove accidental quotes
    out = out.strip().strip('"').strip("'").strip()

    return {"translated_text": out}

# WebSocket routes moved to app/ws/routes.py

mcp_integration = create_mcp_integration(job_manager, job_store, generation_controls, asset_service)
app.state.mcp_server = mcp_integration.server
app.mount("/mcp", mcp_integration.http_app, name="mcp")
app.mount("/outputs", StaticFiles(directory=SERVER_CONFIG["output_dir"]), name="outputs")
app.mount("/static", StaticFiles(directory="static"), name="static")

# Health route moved to app/routers/health.py


@app.on_event("startup")
async def on_startup():
    if asset_store.migration_version("asset_backfill") < 1:
        asset_backfill = await asyncio.to_thread(asset_service.backfill_legacy)
        if int(asset_backfill.get("errors") or 0) == 0:
            asset_store.mark_migration("asset_backfill", 1)
        logger.info({"event": "asset_catalog_backfill", **asset_backfill})
    else:
        asset_reconcile = await asyncio.to_thread(asset_service.backfill_legacy, only_missing=True)
        asset_audit = await asyncio.to_thread(asset_service.audit)
        logger.info({"event": "asset_catalog_reconcile", **asset_reconcile, "audit": asset_audit})
    app.state.mcp_lifespan_context = mcp_integration.lifespan_context_factory()
    await app.state.mcp_lifespan_context.__aenter__()
    loop = asyncio.get_running_loop()
    manager.set_loop(loop)

    def notifier(owner_id: str, event: dict):
        jid = None
        try:
            jid = event.get("job_id")
            if event.get("status") == "queued" and jid:
                pos = job_manager.get_position(jid)
                event = dict(event)
                event["position"] = pos
        except Exception as e:
            logger.debug({"event": "job_notifier_upsert_failed", "error": str(e)})
        # Persist job snapshot if exists
        try:
            if jid:
                j = job_manager.get(jid)
                if j:
                    # Detect artifact availability on completion (best-effort)
                    artifact_available = False
                    try:
                        p = j.result.get("image_path") if isinstance(j.result, dict) else None
                        if isinstance(p, str) and p:
                            if p.startswith('/outputs/'):
                                rel = p[len('/outputs/') : ]
                            elif p.startswith('outputs/'):
                                rel = p[len('outputs/') : ]
                            else:
                                rel = None
                            if rel:
                                fs_path = os.path.join(OUTPUT_DIR, rel)
                                artifact_available = os.path.exists(fs_path)
                    except Exception:
                        pass
                    job_store.upsert_job({
                        "id": j.id,
                        "owner_id": j.owner_id,
                        "type": j.type,
                        "status": j.status,
                        "progress": j.progress,
                        "created_at": j.created_at,
                        "started_at": j.started_at,
                        "ended_at": j.ended_at,
                        "error": j.error_message,
                        "result": j.result,
                        "payload": j.payload,
                        "workflow_id": (j.payload.get("workflow_id") if isinstance(j.payload, dict) else None),
                        "artifact_available": artifact_available,
                    })
        except Exception:
            pass
        try:
            if jid:
                controlled_job = job_manager.get(jid)
                if controlled_job:
                    generation_controls.sync_job(controlled_job)
        except Exception as e:
            logger.warning({"event": "generation_control_sync_failed", "job_id": jid, "error": str(e)})
        manager.send_from_worker(owner_id, event)

    job_manager.register_processor("generate", _processor_generate)
    job_manager.set_notifier(notifier)
    # Apply queue/timeouts from env
    try:
        # OpenRouter: 동시 실행(풀) + 사용자 대기열 길이를 env로 제어
        try:
            external_workers = int(os.getenv("OPENROUTER_MAX_CONCURRENT", "4") or "4")
        except Exception:
            external_workers = 4
        external_workers = max(1, min(32, int(external_workers)))
        job_manager.worker_count = external_workers
        try:
            external_q = int(os.getenv("OPENROUTER_MAX_PER_USER_QUEUE", "5") or "5")
        except Exception:
            external_q = 5
        job_manager.max_per_user_queue = max(0, min(50, int(external_q)))
        # Per-user concurrent stays aligned with existing policy (default 1)
        job_manager.max_per_user_concurrent = int(QUEUE_CONFIG.get("max_per_user_concurrent", 1))
        try:
            external_timeout = float(os.getenv("OPENROUTER_JOB_TIMEOUT_SECONDS", "330") or "330")
        except Exception:
            external_timeout = 330.0
        external_timeout = max(90.0, min(900.0, external_timeout))
        minimum_external_timeout = gpt_image_timeout_seconds() + 30.0
        if external_timeout < minimum_external_timeout:
            logger.warning({
                "event": "openrouter_job_timeout_adjusted",
                "configured_seconds": external_timeout,
                "minimum_seconds": minimum_external_timeout,
            })
            external_timeout = minimum_external_timeout
        job_manager.job_timeout_seconds = external_timeout
    except Exception as e:
        logger.debug({"event": "job_manager_env_apply_failed", "error": str(e)})
    job_manager.start()


@app.on_event("shutdown")
async def on_shutdown():
    job_manager.stop()
    mcp_lifespan_context = getattr(app.state, "mcp_lifespan_context", None)
    if mcp_lifespan_context is not None:
        await mcp_lifespan_context.__aexit__(None, None, None)
