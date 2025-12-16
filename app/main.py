from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect, Request, BackgroundTasks, Form, UploadFile, File
from fastapi.responses import HTMLResponse, JSONResponse
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
"""
Optional LLM feature (prompt translation)

The service should still start even when `llama-cpp-python` is not installed.
So we import PromptTranslator lazily inside a try/except below.
"""
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
from .ws.manager import manager
from .ws.routes import router as ws_router
from .schemas.api_models import EnqueueResponse, JobStatusResponse, CancelActiveResponse, TranslateResponse
from .services.generation import run_generation_processor
from .beta_access import beta_enabled, is_request_authed, beta_cookie_name, expected_cookie_value
from .auth.user_management import _parse_bool as _parse_bool_cookie_secure

logger = setup_logging()
try:
    from llm.prompt_translator import PromptTranslator  # optional dependency

    translator = PromptTranslator(model_path="./models/gemma-3-4b-it-Q6_K.gguf")
except ModuleNotFoundError as e:
    # Most common case on Windows: `llama-cpp-python` is not installed,
    # so importing `llm.prompt_translator` fails due to missing `llama_cpp`.
    logger.warning({"event": "llm_missing_dependency", "message": str(e)})
    translator = None
except FileNotFoundError as e:
    logger.warning({"event": "llm_load_warning", "message": str(e)})
    translator = None
except Exception as e:
    # Any other initialization error should not block the server
    logger.warning({"event": "llm_init_warning", "message": str(e)})
    translator = None

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
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})

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
try:
    app.state.connection_manager = manager
    app.state.job_manager = job_manager
    app.state.job_store = job_store
except Exception as e:
    logger.debug({"event": "app_state_init_failed", "error": str(e)})

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

@app.get("/", response_class=HTMLResponse, tags=["Page"])
async def read_root(request: Request):
    default_values = get_default_values()
    prompt_translate_enabled = _parse_bool_cookie_secure(
        os.getenv("ENABLE_PROMPT_TRANSLATE"),
        bool(translator is not None),
    )
    # Ensure anon id and pass it to template for WS query param alignment
    existing = request.cookies.get(ANON_COOKIE_NAME)
    if existing and isinstance(existing, str) and existing.startswith(ANON_COOKIE_PREFIX):
        anon_id = existing
    else:
        anon_id = ANON_COOKIE_PREFIX + uuid.uuid4().hex
    response = templates.TemplateResponse("index.html", {
        "request": request,
        "anon_id": anon_id,
        "prompt_translate_enabled": prompt_translate_enabled,
        "default_user_prompt": "",  # 워크플로우별로 설정되므로 빈 값
        "default_style_prompt": default_values.get("style_prompt", ""),
        "default_negative_prompt": default_values.get("negative_prompt", ""),
        "default_recommended_prompt": default_values.get("recommended_prompt", ""),
        "workflows_sizes_json": json.dumps(default_values.get("workflows_sizes", {})), # ✨ 사이즈 정보 추가
        "workflow_default_prompts_json": json.dumps(default_values.get("workflow_default_prompts", {})), # 워크플로우별 기본 프롬프트
        "workflow_control_slots_json": json.dumps(default_values.get("workflow_control_slots", {})),
        "workflow_prompt_templates_json": json.dumps(default_values.get("workflow_prompt_templates", {})),
    })
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
      </div>
    </div>
  </body>
</html>
""".strip()
    return HTMLResponse(content=html)


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
    secure_cookie = _parse_bool_cookie_secure(os.getenv("COOKIE_SECURE"), False)
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
    if translator is None: raise HTTPException(status_code=503, detail="LLM model not loaded.")
    try:
        return {"translated_text": translator.translate_to_danbooru(text)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

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
