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
import requests

try:
    from PIL import Image
except Exception:
    Image = None

from .comfy_client import ComfyUIClient
from .config import SERVER_CONFIG, WORKFLOW_CONFIGS, get_prompt_overrides, get_default_values, get_workflow_default_prompt
from .config import QUEUE_CONFIG, JOB_DB_PATH
from .config import HEALTHZ_CONFIG
from .config import COMFY_INPUT_DIR
from .job_manager import JobManager, Job
from .job_store import JobStore
from .logging_utils import setup_logging
from .config import UPLOAD_CONFIG
from .auth.user_management import _ensure_anon_id_cookie, _get_anon_id_from_request, _get_anon_id_from_ws, ANON_COOKIE_NAME, ANON_COOKIE_PREFIX
from .services.media_store import (
    _user_base_dir,
    _date_partition_path,
    _build_web_path,
    _save_image_and_meta,
    _control_base_dir,
    _save_control_image_and_meta,
    _gather_user_controls,
    _gather_user_images,
    _locate_control_meta_path,
    _locate_control_png_path,
    _update_control_status,
    _locate_image_meta_path,
    _update_image_status,
)
from .routers.admin import router as admin_router
from .routers.workflows import router as workflows_router
from .routers.images import router as images_router
from .routers.controls import router as controls_router
from .routers.inputs import router as inputs_router
from .routers.health import router as health_router
from .routers.jobs import router as jobs_router
from .routers.feed import router as feed_router
from .routers.admin_feed import router as admin_feed_router
from .ws.manager import manager
from .ws.routes import router as ws_router
from .schemas.api_models import EnqueueResponse, JobStatusResponse, CancelActiveResponse, TranslateResponse
from .services.generation import run_generation_processor
from .beta_access import beta_enabled, is_request_authed, beta_cookie_name, expected_cookie_value
from .auth.user_management import _parse_bool as _parse_bool_cookie_secure

logger = setup_logging()

templates = Jinja2Templates(directory="templates")
app = FastAPI(title="ComfyUI FastAPI Server", version="0.4.0 (Jobs & Queues)")
app.include_router(admin_router)
app.include_router(ws_router)
app.include_router(workflows_router)
app.include_router(images_router)
app.include_router(controls_router)
app.include_router(inputs_router)
app.include_router(health_router)
app.include_router(jobs_router)
app.include_router(feed_router)
app.include_router(admin_feed_router)

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
    # RMBG2 (Background Removal) params - only used when workflow supports it
    rmbg_mask_blur: Optional[int] = None
    rmbg_mask_offset: Optional[int] = None
    # Direct image-to-image input (non-ControlNet)
    input_image_id: Optional[str] = None  # 기존에 저장된 이미지/컨트롤의 id
    input_image_filename: Optional[str] = None  # 이미 Comfy input에 업로드된 파일명(있으면 재업로드 생략)
    # ControlNet options
    control_enabled: Optional[bool] = None  # True => strength 1.0, False/None => 0.0
    control_image_id: Optional[str] = None  # previously saved control image id
    # Forward-compatible: optional multi-slot controls (ignored when not configured)
    controls: Optional[List[dict]] = None
    # Optional LoRA strengths (per-slot) – forward-compatible
    # Example: [{"slot":"character","unet":1.0,"clip":1.0},{"slot":"style","unet":0.8,"clip":0.8}]
    loras: Optional[List[dict]] = None

WORKFLOW_DIR = "./workflows/"
OUTPUT_DIR = SERVER_CONFIG["output_dir"]
SERVER_ADDRESS = SERVER_CONFIG["server_address"]



"""
Filesystem helpers were extracted to app/services/media_store.py.
Imports above wire them in; local duplicates removed to reduce main.py size.
"""

job_manager = JobManager()
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
    api_key_present = bool(os.getenv("GOOGLE_AI_STUDIO_API_KEY") or os.getenv("GEMINI_API_KEY"))
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
            "workflow_control_slots_json": json.dumps(default_values.get("workflow_control_slots", {})),
            "workflow_prompt_templates_json": json.dumps(default_values.get("workflow_prompt_templates", {})),
        },
    )
    _ensure_anon_id_cookie(request, response)
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
    _ensure_anon_id_cookie(request, response)
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
            job_manager.set_active_cancel_handle(handle)
        except Exception:
            pass
    run_generation_processor(job, progress_cb, _set_cancel_handle)

@app.post("/api/v1/generate", tags=["Image Generation"], response_model=EnqueueResponse)
async def generate_image(request: GenerateRequest, http_request: Request):
    anon_id = _get_anon_id_from_request(http_request)
    try:
        job = job_manager.enqueue(anon_id, "generate", request.model_dump())
    except RuntimeError as e:
        # Queue limit reached
        logger.info({"event": "enqueue_rejected", "owner_id": anon_id, "reason": str(e), "path": "/api/v1/generate"})
        raise HTTPException(status_code=429, detail=str(e))
    position = job_manager.get_position(job.id)
    logger.info({"event": "enqueue", "owner_id": anon_id, "job_id": job.id, "position": position})
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
async def translate_prompt_endpoint(text: str = Form(...)):
    api_key = os.getenv("GOOGLE_AI_STUDIO_API_KEY") or os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise HTTPException(status_code=503, detail="번역 기능(API)이 설정되지 않았습니다. 서버 .env에 GOOGLE_AI_STUDIO_API_KEY를 설정해 주세요.")
    model = os.getenv("PROMPT_TRANSLATE_GOOGLE_MODEL") or "gemini-2.5-flash-lite"
    raw = (text or "").strip()
    if not raw:
        raise HTTPException(status_code=400, detail="번역할 내용을 입력해주세요.")

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

    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    try:
        resp = requests.post(
            url,
            params={"key": api_key},
            json={
                "contents": [
                    {"role": "user", "parts": [{"text": instruction}]}
                ],
                "generationConfig": {
                    "temperature": 0.2,
                    "topP": 0.95,
                    "maxOutputTokens": 256,
                },
            },
            timeout=(5.0, 20.0),
        )
    except Exception as e:
        logger.warning({"event": "prompt_translate_upstream_error", "error": str(e)})
        raise HTTPException(status_code=502, detail="번역 API 호출에 실패했습니다. 잠시 후 다시 시도해 주세요.")

    if not resp.ok:
        detail = None
        err_status = None
        err_reason = None
        try:
            data = resp.json()
            err = (data.get("error") or {}) if isinstance(data, dict) else {}
            if isinstance(err, dict):
                detail = err.get("message")
                err_status = err.get("status")
                # Try to detect a structured reason, e.g. API_KEY_INVALID
                try:
                    details = err.get("details") or []
                    if isinstance(details, list):
                        for d in details:
                            if not isinstance(d, dict):
                                continue
                            r = d.get("reason")
                            if isinstance(r, str) and r:
                                err_reason = r
                                break
                            # google.rpc.ErrorInfo form
                            r2 = d.get("reason") or (d.get("metadata") or {}).get("reason")
                            if isinstance(r2, str) and r2:
                                err_reason = r2
                                break
                except Exception:
                    err_reason = None
        except Exception:
            detail = None
            err_status = None
            err_reason = None

        s = int(resp.status_code)
        low = str(detail or "").lower()
        reason = str(err_reason or "").upper()
        status_txt = str(err_status or "").upper()

        def _looks_like_key_issue() -> bool:
            # Google APIs sometimes return 400 even when the API key is invalid.
            if s in (401, 403):
                return True
            if "api key" in low or "apikey" in low or "api_key" in low:
                return True
            if "key not valid" in low or "invalid api key" in low or "invalid api-key" in low:
                return True
            if "permission" in low or "unauth" in low or "forbidden" in low:
                return True
            if "billing" in low:
                return True
            if reason in ("API_KEY_INVALID", "API_KEY_EXPIRED", "API_KEY_SERVICE_BLOCKED", "API_KEY_HTTP_REFERRER_BLOCKED", "API_KEY_IP_ADDRESS_BLOCKED"):
                return True
            if status_txt in ("PERMISSION_DENIED", "UNAUTHENTICATED"):
                return True
            return False

        def _looks_like_quota_issue() -> bool:
            if s == 429:
                return True
            if "quota" in low or "rate limit" in low or "resource exhausted" in low:
                return True
            if status_txt == "RESOURCE_EXHAUSTED":
                return True
            return False

        # User-friendly messages (avoid leaking upstream internal details)
        if _looks_like_key_issue():
            msg = "번역 API 키(권한)가 올바르지 않거나 비활성화되었습니다. 서버 .env의 GOOGLE_AI_STUDIO_API_KEY를 확인한 뒤 서버를 재시작해 주세요."
            out_status = 401
        elif _looks_like_quota_issue():
            msg = "요청이 너무 많거나 사용량 한도를 초과했습니다. 잠시 후 다시 시도해 주세요."
            out_status = 429
        elif s == 400:
            msg = "요청 내용이 올바르지 않습니다. 문장을 조금 더 자세히 적어주세요."
            out_status = 400
        else:
            msg = detail or f"번역 API 오류 (HTTP {s})"
            out_status = 502

        logger.warning({
            "event": "prompt_translate_bad_status",
            "status": s,
            "out_status": out_status,
            "upstream_status": err_status,
            "reason": err_reason,
            "message": msg,
        })
        raise HTTPException(status_code=out_status, detail=msg)

    try:
        data = resp.json()
    except Exception:
        raise HTTPException(status_code=502, detail="번역 API 응답을 해석하지 못했습니다.")

    out = ""
    try:
        candidates = data.get("candidates") if isinstance(data, dict) else None
        content = (candidates[0] or {}).get("content") if isinstance(candidates, list) and candidates else None
        parts = content.get("parts") if isinstance(content, dict) else None
        out = (parts[0] or {}).get("text") if isinstance(parts, list) and parts else ""
    except Exception:
        out = ""

    out = (out or "").strip()
    if not out:
        raise HTTPException(status_code=502, detail="번역 결과가 비어 있습니다. 잠시 후 다시 시도해 주세요.")

    # Ensure single-line response (best-effort)
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
                        "artifact_available": artifact_available,
                    })
        except Exception:
            pass
        manager.send_from_worker(owner_id, event)

    job_manager.register_processor("generate", _processor_generate)
    job_manager.set_notifier(notifier)
    # Apply queue/timeouts from env
    try:
        job_manager.max_per_user_queue = int(QUEUE_CONFIG.get("max_per_user_queue", 5))
        job_manager.max_per_user_concurrent = int(QUEUE_CONFIG.get("max_per_user_concurrent", 1))
        job_manager.job_timeout_seconds = float(QUEUE_CONFIG.get("job_timeout_seconds", 180))
    except Exception as e:
        logger.debug({"event": "job_manager_env_apply_failed", "error": str(e)})
    job_manager.start()
