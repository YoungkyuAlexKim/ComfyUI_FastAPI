from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect, Request, BackgroundTasks, Form, UploadFile, File
from fastapi.responses import HTMLResponse, JSONResponse, Response
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from typing import Optional, List, Tuple
import time
import os
import asyncio
import json
import uuid
from datetime import datetime, timezone
import hashlib
from io import BytesIO
import sqlite3
import shutil

try:
    from PIL import Image
except Exception:
    Image = None

from .comfy_client import ComfyUIClient
from .config import SERVER_CONFIG, WORKFLOW_CONFIGS, get_prompt_overrides, get_default_values, get_workflow_default_prompt
from .config import QUEUE_CONFIG, JOB_DB_PATH
from .config import HEALTHZ_CONFIG
from .config import COMFY_INPUT_DIR
from .job_manager import JobManager, RoutingJobManager, Job
from .job_store import JobStore
from .logging_utils import setup_logging
from .config import UPLOAD_CONFIG
from .auth.user_management import _ensure_anon_id_cookie, _get_anon_id_from_request, _get_anon_id_from_ws, ANON_COOKIE_NAME, ANON_COOKIE_PREFIX
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
from .routers.characters import router as characters_router
from .routers.global_characters import router as global_characters_router
from .ws.manager import manager
from .ws.routes import router as ws_router
from .schemas.api_models import EnqueueResponse, JobStatusResponse, CancelActiveResponse, TranslateResponse
from .services.generation import run_generation_processor
from .services.generation_commands import (
    dispatch_legacy_web_request,
    generation_context_from_http_request,
)
from .services.openrouter_client import (
    OpenRouterUpstreamError,
    generate_text,
    gpt_image_timeout_seconds,
    is_configured as openrouter_is_configured,
)
from .beta_access import beta_enabled, is_request_authed, beta_cookie_name, expected_cookie_value
from .auth.user_management import _parse_bool as _parse_bool_cookie_secure
from .rate_limiter import SlidingWindowRateLimiter

logger = setup_logging()

templates = Jinja2Templates(directory="templates")
app = FastAPI(title="ComfyUI FastAPI Server", version="0.4.0 (Jobs & Queues)")
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
app.include_router(characters_router)
app.include_router(global_characters_router)

# --- Beta access gate (shared password) ---
@app.middleware("http")
async def beta_access_middleware(request: Request, call_next):
    """
    Simple beta gate:
      - Enabled when BETA_PASSWORD is set.
      - If not authed, web pages redirect to /beta-login
      - API requests return 401 JSON to avoid frontend JSON parse issues.
    """
    if not beta_enabled():
        return await call_next(request)

    path = request.url.path or ""
    # Allow login endpoints and health check without auth
    if path.startswith("/beta-login") or path == "/healthz":
        return await call_next(request)

    if is_request_authed(request.cookies):
        return await call_next(request)

    # APIs should return JSON 401 (not redirect), otherwise fetch().json() breaks.
    if path.startswith("/api/"):
        return JSONResponse(status_code=401, content={"detail": "beta_auth_required"})

    return RedirectResponse(url="/beta-login", status_code=303)

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
    # RMBG2 (Background Removal) params - only used when workflow supports it
    rmbg_mask_blur: Optional[int] = None
    rmbg_mask_offset: Optional[int] = None
    # Direct image-to-image input
    input_image_id: Optional[str] = None  # 기존에 저장된 이미지 id
    # Optional multi-image input (used by specific providers/workflows; backward-compatible)
    # 규칙: input_image_ids가 비어있지 않으면 우선 사용, 아니면 input_image_id 사용
    input_image_ids: Optional[List[str]] = None
    input_image_filename: Optional[str] = None  # 이미 Comfy input에 업로드된 파일명(있으면 재업로드 생략)
    # Optional LoRA strengths (per-slot) – forward-compatible
    # Example: [{"slot":"character","unet":1.0,"clip":1.0},{"slot":"style","unet":0.8,"clip":0.8}]
    loras: Optional[List[dict]] = None
    # --- ACE-Step (music/audio) params ---
    lyrics: Optional[str] = None
    bpm: Optional[int] = None
    duration: Optional[int] = None
    steps: Optional[int] = None
    keyscale: Optional[str] = None
    timesignature: Optional[str] = None
    language: Optional[str] = None
    # --- SeeThrough (layer separation) params ---
    seethrough_resolution: Optional[int] = None
    # --- Game UI element maker params ---
    game_ui_background_mode: Optional[str] = None

WORKFLOW_DIR = "./workflows/"
OUTPUT_DIR = SERVER_CONFIG["output_dir"]
SERVER_ADDRESS = SERVER_CONFIG["server_address"]



"""
Filesystem helpers were extracted to app/services/media_store.py.
Imports above wire them in; local duplicates removed to reduce main.py size.
"""

_comfy_job_manager = JobManager(worker_count=1)
_external_job_manager = JobManager(worker_count=4)  # env에서 startup 시 재설정
job_manager = RoutingJobManager(_comfy_job_manager, _external_job_manager, WORKFLOW_CONFIGS)
job_store = JobStore(JOB_DB_PATH)
from .feed_store import FeedStore
feed_store = FeedStore(JOB_DB_PATH)
try:
    app.state.connection_manager = manager
    app.state.job_manager = job_manager
    app.state.job_store = job_store
    app.state.feed_store = feed_store
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

# --- Helpers ---
def _wait_for_input_visibility(filename: str, timeout_sec: float = 1.5, poll_ms: int = 50) -> bool:
    try:
        if not isinstance(COMFY_INPUT_DIR, str) or not COMFY_INPUT_DIR or not isinstance(filename, str) or not filename:
            return True
        import time as _t
        import os as _os
        target = _os.path.join(COMFY_INPUT_DIR, filename)
        deadline = _t.time() + max(0.05, timeout_sec)
        while _t.time() < deadline:
            if _os.path.exists(target):
                return True
            _t.sleep(max(0.01, poll_ms / 1000.0))
        return _os.path.exists(target)
    except Exception as e:
        logger.debug({"event": "wait_input_visibility_failed", "file": filename, "error": str(e)})
        return True

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
    existing = request.cookies.get(ANON_COOKIE_NAME)
    if existing and isinstance(existing, str) and existing.startswith(ANON_COOKIE_PREFIX):
        anon_id = existing
    else:
        # Use a deterministic value for both template + cookie (avoid mismatch between UI and backend owner_id)
        anon_id = ANON_COOKIE_PREFIX + uuid.uuid4().hex
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


@app.get("/feed", response_class=HTMLResponse, tags=["Page"])
async def feed_page(request: Request):
    existing = request.cookies.get(ANON_COOKIE_NAME)
    if existing and isinstance(existing, str) and existing.startswith(ANON_COOKIE_PREFIX):
        anon_id = existing
    else:
        anon_id = ANON_COOKIE_PREFIX + uuid.uuid4().hex
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


@app.get("/beta-login", response_class=HTMLResponse, tags=["Page"])
async def beta_login_page(request: Request):
    # Minimal inline HTML to avoid loading /static before auth
    html = """
<!doctype html>
<html lang="ko">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>베타 접속</title>
    <style>
      body { font-family: system-ui, -apple-system, Segoe UI, Roboto, Arial, sans-serif; background: #0b1220; color: #e5e7eb; margin: 0; }
      .wrap { max-width: 520px; margin: 10vh auto; padding: 24px; }
      .card { background: rgba(255,255,255,0.06); border: 1px solid rgba(255,255,255,0.12); border-radius: 14px; padding: 20px; }
      h1 { font-size: 20px; margin: 0 0 10px; }
      p { margin: 0 0 16px; color: rgba(229,231,235,0.9); line-height: 1.5; }
      label { display: block; margin-bottom: 8px; font-weight: 600; }
      input { width: 100%; box-sizing: border-box; padding: 12px 12px; border-radius: 10px; border: 1px solid rgba(255,255,255,0.18); background: rgba(0,0,0,0.25); color: #fff; }
      button { margin-top: 12px; width: 100%; padding: 12px 14px; border-radius: 10px; border: 0; background: #2563eb; color: #fff; font-weight: 700; cursor: pointer; }
      .hint { margin-top: 10px; font-size: 12px; color: rgba(229,231,235,0.7); }
      .tips { margin-top: 12px; font-size: 12px; color: rgba(229,231,235,0.78); line-height: 1.55; }
      .tips strong { color: #ffffff; }
      .err { margin-top: 10px; color: #fecaca; }
    </style>
  </head>
  <body>
    <div class="wrap">
      <div class="card">
        <h1>베타 접속 비밀번호</h1>
        <p>이 서비스는 베타 기간 동안 비밀번호가 필요합니다.</p>
        <form method="post" action="/beta-login">
          <label for="pw">비밀번호</label>
          <input id="pw" name="password" type="password" autocomplete="current-password" required />
          <button type="submit">접속하기</button>
        </form>
        <div class="hint">비밀번호는 공지받은 값을 입력해 주세요.</div>
        <div class="tips">
          <strong>접속이 반복해서 로그인 화면으로 돌아오나요?</strong><br/>
          - 이 베타 잠금은 <strong>쿠키(로그인 정보 저장)</strong>가 필요합니다. 브라우저에서 쿠키가 차단되어 있으면 접속이 안 될 수 있어요.<br/>
          - 카카오톡/인스타그램 등 <strong>앱 안의 브라우저</strong>에서 열면 쿠키가 제대로 저장되지 않는 경우가 있습니다. 가능한 <strong>Chrome/Safari(기본 브라우저)</strong>로 열어 주세요.<br/>
          - 그래도 안 되면 시크릿/인프라이빗 창에서 다시 시도하거나, 해당 사이트의 쿠키/사이트 데이터를 삭제 후 재시도해 주세요.
        </div>
      </div>
    </div>
  </body>
</html>
""".strip()
    return HTMLResponse(content=html, headers={"Cache-Control": "no-store"})


@app.post("/beta-login", response_class=HTMLResponse, tags=["Page"])
async def beta_login_submit(request: Request):
    if not beta_enabled():
        return RedirectResponse(url="/", status_code=303)

    try:
        form = await request.form()
        pw = str(form.get("password") or "")
    except Exception:
        pw = ""

    expected = expected_cookie_value()
    if not expected or not pw:
        return RedirectResponse(url="/beta-login", status_code=303)

    # Compare against expected token derived from BETA_PASSWORD
    from .beta_access import _token_for_password  # local import

    if _token_for_password(pw.strip()) != expected:
        # Keep it simple: redirect back (no error detail to avoid leaking behavior)
        return RedirectResponse(url="/beta-login", status_code=303)

    resp = RedirectResponse(url="/", status_code=303)
    # Cookie options: align with anon_id cookie secure setting for HTTPS deployments.
    secure_cookie_env = _parse_bool_cookie_secure(os.getenv("COOKIE_SECURE"), False)
    try:
        xf_proto = (request.headers.get("x-forwarded-proto") or "").split(",")[0].strip().lower()
    except Exception:
        xf_proto = ""
    is_https = (request.url.scheme == "https") or (xf_proto == "https")
    # If the request is HTTP, browsers will not send Secure cookies.
    # Prevent a confusing "login loop" on mobile when COOKIE_SECURE=true but served over HTTP.
    secure_cookie = bool(secure_cookie_env and is_https)
    if secure_cookie_env and not is_https:
        logger.warning(
            {
                "event": "cookie_secure_mismatch",
                "message": "COOKIE_SECURE=true but request is not HTTPS; issuing non-secure beta cookie to avoid login loop",
                "path": request.url.path,
                "scheme": request.url.scheme,
                "x_forwarded_proto": xf_proto,
            }
        )
    resp.set_cookie(
        key=beta_cookie_name(),
        value=expected,
        httponly=True,
        samesite="lax",
        secure=secure_cookie,
        max_age=60 * 60 * 24 * 14,  # 14 days
    )
    return resp

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
        job = job_manager.enqueue(anon_id, "generate", resolved.payload)
    except RuntimeError as e:
        # Queue limit reached
        logger.info({"event": "enqueue_rejected", "owner_id": anon_id, "reason": str(e), "path": "/api/v1/generate"})
        raise HTTPException(status_code=429, detail=str(e))
    position = job_manager.get_position(job.id)
    logger.info(
        {
            "event": "enqueue",
            "owner_id": anon_id,
            "job_id": job.id,
            "position": position,
            "request_id": resolved.command.context.request_id,
            "request_source": resolved.command.context.source,
            "client_ip": resolved.command.context.client_ip,
            "capability": resolved.command.capability,
            "capability_variant": resolved.command.variant,
            "workflow_id": resolved.workflow_id,
            "provider": resolved.provider,
            "model": resolved.model,
        }
    )
    return {"job_id": job.id, "status": "queued", "position": position}


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
async def translate_prompt_endpoint(text: str = Form(...), mode: str = Form("image"), language: str = Form("ko"), context: str = Form("")):
    if not openrouter_is_configured():
        raise HTTPException(status_code=503, detail="번역 기능(API)이 설정되지 않았습니다. 서버 .env에 OPENROUTER_API_KEY를 설정해 주세요.")
    model = os.getenv("OPENROUTER_TEXT_MODEL") or "google/gemini-3.1-flash-lite"
    raw = (text or "").strip()
    if not raw:
        raise HTTPException(status_code=400, detail="번역할 내용을 입력해주세요.")

    mode = (mode or "image").strip().lower()

    if mode == "music_tags":
        # Music description enhancement: convert user input to ACE-Step natural language description
        instruction = (
            "You are a music production prompt writer for ACE-Step AI.\n"
            "Convert the user's request into a music production description.\n\n"
            "STRICT RULES:\n"
            "- Focus on SPECIFIC instruments, playing techniques, arrangement, and sound texture\n"
            "- Do NOT use abstract scene descriptions (no 'sense of wonder', 'enchanting world')\n"
            "- Do NOT include genre labels as keywords (no 'RPG theme', 'village music')\n"
            "- Every sentence must describe something the AI can actually produce as SOUND\n"
            "- Output ONLY the description paragraph, no explanations or labels\n\n"
            "Example 1:\n"
            "User: fantasy RPG village background music\n"
            "Fingerpicked nylon-string acoustic guitar playing a lilting waltz-time melody, "
            "accompanied by a wooden transverse flute weaving gentle counter-melodies. "
            "A celtic harp provides arpeggiated chords underneath while light frame-drum "
            "taps keep a relaxed pulse. Warm string pads swell softly in the background.\n\n"
            "Example 2:\n"
            "User: intense boss battle music\n"
            "Aggressive staccato string ostinatos over pounding double-kick drums and "
            "thunderous taiko hits. Brass section delivers sharp, dissonant power chords "
            "while a choir sings fortissimo Latin phrases. Rapid tempo with relentless "
            "sixteenth-note percussion patterns driving forward momentum.\n\n"
            "Example 3:\n"
            "User: rainy day cafe jazz\n"
            "Brushed snare drum with a lazy swing pattern and warm upright bass playing "
            "chromatic walking lines. A breathy tenor saxophone improvises behind-the-beat "
            "over lush extended piano voicings with ninth and thirteenth chords. Subtle "
            "vinyl crackle and room reverb add intimate warmth.\n\n"
            "Example 4:\n"
            "User: retro 8-bit game music\n"
            "Square-wave lead melody with rapid arpeggiated triangle-wave bass. Pulse-wave "
            "harmony channel playing staccato chords. Noise-channel percussion with snappy "
            "hi-hats and punchy kick patterns. Bright, energetic chiptune arrangement with "
            "frequent pitch bends and echo effects.\n\n"
            f"User: {raw}\n"
        )
    elif mode == "music_lyrics":
        # Lyrics generation: user can provide either tags-based or free-text request
        lang_name = {"ko": "한국어", "en": "English", "ja": "日本語", "zh": "中文",
                     "es": "Español", "fr": "Français", "de": "Deutsch",
                     "it": "Italiano", "pt": "Português", "ru": "Русский"}.get(language, language)
        # context = tags from the tags input field (음악 설명)
        # raw = user's free-text request in the lyrics textarea
        tags_info = (context or "").strip()
        context_block = f"\n음악 설명(tags): {tags_info}" if tags_info else ""
        instruction = (
            "사용자가 음악 생성 AI(ACE-Step)에 넣을 가사를 작성하려 합니다.\n"
            f"아래 사용자의 요청을 바탕으로 어울리는 {lang_name} 가사를 작성해주세요.\n\n"
            "아래 구조 패턴 중 장르와 분위기에 가장 어울리는 것을 하나 골라 사용하세요:\n"
            "A) [verse] [verse] [chorus] [verse] [chorus] — 포크/컨트리/어쿠스틱\n"
            "B) [verse] [pre-chorus] [chorus] [verse] [pre-chorus] [chorus] [bridge] [chorus] — 팝/댄스\n"
            "C) [intro] [verse] [chorus] [verse] [chorus] [bridge] [chorus] [outro] — 록/메탈\n"
            "D) [verse] [chorus] [verse] [chorus] [bridge] [verse] [chorus] — 발라드/R&B\n"
            "E) [verse] [verse] [chorus] [verse] [verse] [chorus] [bridge] [chorus] — 랩/힙합\n"
            "F) [intro] [verse] [chorus] [interlude] [verse] [chorus] [outro] — 일렉트로닉/앰비언트\n"
            "G) [verse] [chorus] [verse] [chorus] — 심플/동요/짧은 곡\n\n"
            "조건:\n"
            "- 사용자가 원하는 분위기, 주제, 감정을 가사에 반영\n"
            "- 각 줄은 짧고 리듬감 있게 (노래로 부를 수 있도록)\n"
            "- 설명/해설 없이, 가사 텍스트만 출력\n"
            f"{context_block}\n\n"
            f"사용자 요청:\n{raw}\n"
        )
    else:
        # Default: image prompt translation
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
            temperature=0.7 if mode.startswith("music") else 0.2,
            top_p=0.95,
            max_tokens=1024 if mode == "music_lyrics" else 256,
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

    if mode in ("music_lyrics", "music_tags"):
        # Music modes: keep multi-line, clean up LLM thinking artifacts
        out = out.strip()
        raw_model_out = out
        # Some hosted models may prepend reasoning/meta lines; strip them defensively.
        cleaned_lines = []
        for line in out.splitlines():
            stripped = line.strip()
            if not stripped:
                cleaned_lines.append(line)
                continue
            # Skip thinking/meta/analysis lines
            if stripped.startswith(("*", "#", "- ", "•")):
                continue
            if stripped.lower().startswith(("here is", "here's", "output:", "result:", "source text", "translation", "note:", "let me", "i will", "the user")):
                continue
            # Skip lines that look like labels (e.g., "Genre:", "Instruments:")
            if len(stripped) < 60 and stripped.endswith(":"):
                continue
            cleaned_lines.append(line)
        out = "\n".join(cleaned_lines).strip()
        # Remove wrapping quotes if present
        if len(out) >= 2 and out[0] == '"' and out[-1] == '"':
            out = out[1:-1].strip()
        # For music_tags: if still empty after filtering, fall back to full output
        if not out and mode == "music_tags":
            # Try to find the last substantial paragraph (likely the actual description)
            paragraphs = [p.strip() for p in raw_model_out.split("\n\n") if p.strip()]
            if not paragraphs:
                # Re-parse from original
                paragraphs = [p.strip() for p in raw_model_out.split("\n\n") if p.strip() and not p.strip().startswith("*")]
            if paragraphs:
                out = paragraphs[-1].strip()
    else:
        # Ensure single-line response (best-effort) for image prompts
        out = out.splitlines()[0].strip()
        # Remove accidental quotes
        out = out.strip().strip('"').strip("'").strip()

    return {"translated_text": out}

# WebSocket routes moved to app/ws/routes.py

app.mount("/outputs", StaticFiles(directory="outputs"), name="outputs")
app.mount("/static", StaticFiles(directory="static"), name="static")

# Health route moved to app/routers/health.py


@app.on_event("startup")
async def on_startup():
    loop = asyncio.get_running_loop()
    manager.set_loop(loop)

    def notifier(owner_id: str, event: dict):
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
                        p = (j.result.get("image_path") or j.result.get("audio_path")) if isinstance(j.result, dict) else None
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
        manager.send_from_worker(owner_id, event)

    job_manager.register_processor("generate", _processor_generate)
    job_manager.set_notifier(notifier)
    # Apply queue/timeouts from env
    try:
        # ComfyUI lane: 기존 설정 유지
        _comfy_job_manager.max_per_user_queue = int(QUEUE_CONFIG.get("max_per_user_queue", 5))
        _comfy_job_manager.max_per_user_concurrent = int(QUEUE_CONFIG.get("max_per_user_concurrent", 1))
        _comfy_job_manager.job_timeout_seconds = float(QUEUE_CONFIG.get("job_timeout_seconds", 180))

        # OpenRouter lane: 동시 실행(풀) + 사용자 대기열 길이만 별도 env로 제어
        try:
            external_workers = int(os.getenv("OPENROUTER_MAX_CONCURRENT", "4") or "4")
        except Exception:
            external_workers = 4
        external_workers = max(1, min(32, int(external_workers)))
        _external_job_manager.worker_count = external_workers
        try:
            external_q = int(os.getenv("OPENROUTER_MAX_PER_USER_QUEUE", "5") or "5")
        except Exception:
            external_q = 5
        _external_job_manager.max_per_user_queue = max(0, min(50, int(external_q)))
        # Per-user concurrent stays aligned with existing policy (default 1)
        _external_job_manager.max_per_user_concurrent = int(QUEUE_CONFIG.get("max_per_user_concurrent", 1))
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
        _external_job_manager.job_timeout_seconds = external_timeout
    except Exception as e:
        logger.debug({"event": "job_manager_env_apply_failed", "error": str(e)})
    job_manager.start()

    # --- ComfyUI 헬스체크 워치독 ---
    # ComfyUI가 크래시하면 실행 중인 작업이 영원히 대기하는 문제를 방지
    async def _comfyui_health_watchdog():
        """15초마다 ComfyUI 상태를 확인. 연결 불가 시 실행 중인 ComfyUI 작업을 자동 실패 처리."""
        consecutive_failures = 0
        FAIL_THRESHOLD = 2  # 연속 2회 실패 시 (30초간 응답 없음)
        while True:
            await asyncio.sleep(15)
            try:
                import requests as _req
                r = _req.get(f"http://{SERVER_ADDRESS}/system_stats", timeout=5)
                if r.status_code == 200:
                    consecutive_failures = 0
                    continue
            except Exception:
                pass
            consecutive_failures += 1
            if consecutive_failures >= FAIL_THRESHOLD:
                # ComfyUI 응답 없음 — 실행 중인 ComfyUI 작업 강제 실패
                try:
                    for jm in [_comfy_job_manager]:
                        with jm._lock:
                            for job in list(jm._jobs.values()):
                                if job.status == "running":
                                    jm._cancel_requests.add(job.id)
                                    cancel = jm._cancel_handles.get(job.id)
                                    if cancel:
                                        try:
                                            cancel()
                                        except Exception:
                                            pass
                    logger.warning({
                        "event": "comfyui_watchdog_triggered",
                        "consecutive_failures": consecutive_failures,
                        "action": "cancel_running_comfy_jobs",
                    })
                except Exception:
                    pass

    asyncio.create_task(_comfyui_health_watchdog())

    # --- SeeThrough 임시 파일 자동 정리 (24시간 경과 시 삭제) ---
    async def _seethrough_cleanup_loop():
        """30분마다 실행: 24시간 지난 SeeThrough PSD + 파츠 파일 삭제"""
        import glob as _glob
        SEETHROUGH_TTL_HOURS = 24
        while True:
            await asyncio.sleep(30 * 60)  # 30분 간격
            try:
                now = time.time()
                ttl_sec = SEETHROUGH_TTL_HOURS * 3600
                output_base = SERVER_CONFIG.get("output_dir", "./outputs/")
                if not os.path.isdir(output_base):
                    continue
                removed_files = 0
                for root, dirs, files in os.walk(output_base):
                    for fname in files:
                        if not fname.lower().endswith(".psd"):
                            continue
                        fpath = os.path.join(root, fname)
                        try:
                            if now - os.path.getmtime(fpath) > ttl_sec:
                                os.remove(fpath)
                                removed_files += 1
                        except Exception:
                            pass
                if removed_files:
                    logger.info({
                        "event": "seethrough_cleanup",
                        "removed_psd_files": removed_files,
                    })
            except Exception:
                pass

    asyncio.create_task(_seethrough_cleanup_loop())
