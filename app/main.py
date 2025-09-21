from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect, Request, BackgroundTasks, Form, UploadFile, File
from fastapi.responses import HTMLResponse, JSONResponse
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
from llm.prompt_translator import PromptTranslator
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
from .routers.health import router as health_router
from .ws.manager import manager
from .ws.routes import router as ws_router
from .schemas.api_models import EnqueueResponse, JobStatusResponse, CancelActiveResponse, TranslateResponse

logger = setup_logging()
try:
    translator = PromptTranslator(model_path="./models/gemma-3-4b-it-Q6_K.gguf")
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
app.include_router(health_router)

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
    # ControlNet options
    control_enabled: Optional[bool] = None  # True => strength 1.0, False/None => 0.0
    control_image_id: Optional[str] = None  # previously saved control image id
    # Forward-compatible: optional multi-slot controls (ignored when not configured)
    controls: Optional[List[dict]] = None

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
    # Ensure anon id and pass it to template for WS query param alignment
    existing = request.cookies.get(ANON_COOKIE_NAME)
    if existing and isinstance(existing, str) and existing.startswith(ANON_COOKIE_PREFIX):
        anon_id = existing
    else:
        anon_id = ANON_COOKIE_PREFIX + uuid.uuid4().hex
    response = templates.TemplateResponse("index.html", {
        "request": request,
        "anon_id": anon_id,
        "default_user_prompt": "",  # 워크플로우별로 설정되므로 빈 값
        "default_style_prompt": default_values.get("style_prompt", ""),
        "default_negative_prompt": default_values.get("negative_prompt", ""),
        "default_recommended_prompt": default_values.get("recommended_prompt", ""),
        "workflows_sizes_json": json.dumps(default_values.get("workflows_sizes", {})), # ✨ 사이즈 정보 추가
        "workflow_default_prompts_json": json.dumps(default_values.get("workflow_default_prompts", {})), # 워크플로우별 기본 프롬프트
        "workflow_control_slots_json": json.dumps(default_values.get("workflow_control_slots", {})),
    })
    _ensure_anon_id_cookie(request, response)
    return response

# Workflows routes moved to app/routers/workflows.py

def _processor_generate(job: Job, progress_cb):
    req_dict = job.payload
    request = GenerateRequest(**req_dict)
    workflow_path = os.path.join(WORKFLOW_DIR, f"{request.workflow_id}.json")
    control = None
    multi_controls: List[dict] = []
    uploaded_multi_filenames: List[str] = []
    # Prepare ControlNet overrides if enabled
    uploaded_input_filename: Optional[str] = None
    try:
        if getattr(request, "control_enabled", None):
            # Prefer multi-controls if provided and mapping exists
            wf_cfg = WORKFLOW_CONFIGS.get(request.workflow_id, {}) if isinstance(WORKFLOW_CONFIGS, dict) else {}
            slots_cfg = wf_cfg.get("control_slots") if isinstance(wf_cfg, dict) else None
            provided_controls = []
            try:
                if isinstance(req_dict.get("controls"), list):
                    provided_controls = [c for c in req_dict["controls"] if isinstance(c, dict) and c.get("slot") and c.get("image_id")]
            except Exception:
                provided_controls = []

            if slots_cfg and provided_controls:
                anon_id = job.owner_id
                client_tmp = ComfyUIClient(SERVER_ADDRESS)
                for item in provided_controls:
                    slot = str(item.get("slot"))
                    image_id = str(item.get("image_id"))
                    if slot not in slots_cfg:
                        continue
                    local_png = _locate_control_png_path(anon_id, image_id)
                    if not local_png or not os.path.exists(local_png):
                        continue
                    try:
                        with open(local_png, "rb") as f:
                            data = f.read()
                        stored = None
                        for _attempt in range(3):
                            try:
                                # Use a unique name per job to avoid collisions/stale caches
                                stored = client_tmp.upload_image_to_input(f"{image_id}_{job.id}.png", data, "image/png")
                                if isinstance(stored, str) and stored:
                                    break
                            except Exception:
                                time.sleep(0.15)
                        # Ensure file visible before use (best-effort)
                        if isinstance(stored, str) and stored:
                            try:
                                _ = _wait_for_input_visibility(stored, timeout_sec=1.5, poll_ms=50)
                            except Exception:
                                pass
                            multi_controls.append({
                                "slot": slot,
                                "image_filename": stored,
                                "strength": 1.0,
                            })
                            try:
                                uploaded_multi_filenames.append(stored)
                            except Exception:
                                pass
                            try:
                                time.sleep(0.1)
                            except Exception:
                                pass
                        else:
                            logger.info({"event": "controlnet_upload_failed_multi", "job_id": job.id, "owner_id": job.owner_id, "slot": slot, "error": "upload returned empty"})
                    except Exception as e:
                        logger.info({"event": "controlnet_upload_failed_multi", "job_id": job.id, "owner_id": job.owner_id, "slot": slot, "error": str(e)})
                control = None
            else:
                # Fallback to single control path
                control = {"strength": 0.0}
                if isinstance(request.control_image_id, str) and len(request.control_image_id) > 0:
                    anon_id = job.owner_id
                    local_png = _locate_control_png_path(anon_id, request.control_image_id)
                    if local_png and os.path.exists(local_png):
                        try:
                            with open(local_png, "rb") as f:
                                data = f.read()
                            client_tmp = ComfyUIClient(SERVER_ADDRESS)
                            stored = None
                            for _attempt in range(3):
                                try:
                                    # Use a unique name per job to avoid collisions/stale caches
                                    stored = client_tmp.upload_image_to_input(f"{request.control_image_id}_{job.id}.png", data, "image/png")
                                    if isinstance(stored, str) and stored:
                                        break
                                except Exception:
                                    time.sleep(0.15)
                            # Ensure file visible before use (best-effort)
                            if isinstance(stored, str) and stored:
                                try:
                                    _ = _wait_for_input_visibility(stored, timeout_sec=1.5, poll_ms=50)
                                except Exception:
                                    pass
                                uploaded_input_filename = stored
                                control = {"strength": 1.0, "image_filename": stored}
                                try:
                                    time.sleep(0.1)
                                except Exception:
                                    pass
                            else:
                                logger.info({"event": "controlnet_upload_failed", "job_id": job.id, "owner_id": job.owner_id, "error": "upload returned empty"})
                        except Exception as e:
                            logger.info({"event": "controlnet_upload_failed", "job_id": job.id, "owner_id": job.owner_id, "error": str(e)})
                            pass
        else:
            control = {"strength": 0.0}
    except Exception:
        control = None

    prompt_overrides = get_prompt_overrides(
        user_prompt=request.user_prompt,
        aspect_ratio=request.aspect_ratio,
        workflow_name=request.workflow_id,
        seed=request.seed,
        control=control,
    )

    # Diagnostics: log final control application intent
    try:
        cn_cfg = WORKFLOW_CONFIGS.get(request.workflow_id, {}).get("controlnet")
        apply_node = cn_cfg.get("apply_node") if isinstance(cn_cfg, dict) else None
        image_node = cn_cfg.get("image_node") if isinstance(cn_cfg, dict) else None
        logger.info({
            "event": "controlnet_final_overrides",
            "owner_id": job.owner_id,
            "job_id": job.id,
            "control_enabled": bool(getattr(request, "control_enabled", False)),
            "control_image_id": getattr(request, "control_image_id", None),
            "single_image": (control or {}).get("image_filename") if isinstance(control, dict) else None,
            "multi_count": len(multi_controls),
            "apply_node_inputs": (prompt_overrides.get(apply_node, {}) if apply_node else {}),
            "image_node_inputs": (prompt_overrides.get(image_node, {}) if image_node else {}),
        })
    except Exception as e:
        logger.debug({"event": "job_notifier_position_calc_failed", "error": str(e)})

    # Apply multi-control overrides when available
    try:
        if multi_controls:
            wf_cfg = WORKFLOW_CONFIGS.get(request.workflow_id, {}) if isinstance(WORKFLOW_CONFIGS, dict) else {}
            slots_cfg = wf_cfg.get("control_slots") if isinstance(wf_cfg, dict) else None
            defaults = {}
            try:
                defaults = wf_cfg.get("controlnet", {}).get("defaults", {}) or {}
            except Exception:
                defaults = {}
            if slots_cfg and isinstance(prompt_overrides, dict):
                start_pct = float(defaults.get("start_percent", 0.0))
                end_pct = float(defaults.get("end_percent", 0.33))
                for mc in multi_controls:
                    slot = mc.get("slot")
                    mapping = slots_cfg.get(slot) if isinstance(slots_cfg, dict) else None
                    if not mapping:
                        continue
                    apply_node = mapping.get("apply_node")
                    image_node = mapping.get("image_node")
                    strength = float(mc.get("strength", 1.0))
                    image_filename = mc.get("image_filename")
                    if apply_node:
                        prompt_overrides[apply_node] = {
                            "inputs": {
                                "strength": strength,
                                "start_percent": start_pct,
                                "end_percent": end_pct,
                            }
                        }
                    if image_node and image_filename:
                        prompt_overrides[image_node] = {"inputs": {"image": image_filename}}
    except Exception:
        pass

    # Hard gate: if control is enabled, ensure an image override is present
    try:
        if getattr(request, "control_enabled", False):
            wf_cfg = WORKFLOW_CONFIGS.get(request.workflow_id, {}) if isinstance(WORKFLOW_CONFIGS, dict) else {}
            cn_cfg = wf_cfg.get("controlnet") if isinstance(wf_cfg, dict) else None
            image_node = cn_cfg.get("image_node") if isinstance(cn_cfg, dict) else None
            has_single = bool(isinstance(control, dict) and control.get("image_filename"))
            has_override = bool(image_node and isinstance(prompt_overrides, dict) and image_node in prompt_overrides and isinstance(prompt_overrides[image_node], dict) and isinstance(prompt_overrides[image_node].get("inputs"), dict) and prompt_overrides[image_node]["inputs"].get("image"))
            has_multi = bool(multi_controls)
            if not (has_single or has_override or has_multi):
                logger.info({
                    "event": "controlnet_gate_failed",
                    "owner_id": job.owner_id,
                    "job_id": job.id,
                    "reason": "no image override present",
                    "control_enabled": True,
                    "image_node": image_node,
                    "overrides_keys": list(prompt_overrides.keys()) if isinstance(prompt_overrides, dict) else None,
                })
                raise RuntimeError("ControlNet image not prepared. Please re-select the control image and try again.")
    except Exception:
        # If even gating fails unexpectedly, continue; queue may still succeed
        pass
    # Debug logging for ControlNet application
    try:
        cn_cfg = WORKFLOW_CONFIGS.get(request.workflow_id, {}).get("controlnet")
        apply_node = cn_cfg.get("apply_node") if isinstance(cn_cfg, dict) else None
        image_node = cn_cfg.get("image_node") if isinstance(cn_cfg, dict) else None
        logger.info({
            "event": "controlnet_overrides",
            "owner_id": job.owner_id,
            "job_id": job.id,
            "control_enabled": bool(getattr(request, "control_enabled", False)),
            "control_image_id": getattr(request, "control_image_id", None),
            "uploaded_input_filename": uploaded_input_filename,
            "apply_node_inputs": (prompt_overrides.get(apply_node, {}) if apply_node else {}),
            "image_node_inputs": (prompt_overrides.get(image_node, {}) if image_node else {}),
        })
    except Exception:
        pass
    client = ComfyUIClient(SERVER_ADDRESS)
    # Allow cancellation from job manager
    job_manager.set_active_cancel_handle(client.interrupt)

    try:
        resp = client.queue_prompt(workflow_path, prompt_overrides)
        prompt_id = resp.get('prompt_id') if isinstance(resp, dict) else None
        if not prompt_id:
            raise RuntimeError("Failed to get prompt_id.")

        def on_progress(p: float):
            progress_cb(p)

        images_data = client.get_images(prompt_id, on_progress=on_progress)
        if not images_data:
            raise RuntimeError("Failed to receive generated images.")

        filename = list(images_data.keys())[0]
        image_bytes = list(images_data.values())[0]
        saved_image_path, _ = _save_image_and_meta(job.owner_id, image_bytes, request, filename)
        web_path = _build_web_path(saved_image_path)
        job.result["image_path"] = web_path
    finally:
        # Best-effort cleanup of any uploaded inputs in ComfyUI input directory (single and multi)
        try:
            if isinstance(COMFY_INPUT_DIR, str) and COMFY_INPUT_DIR:
                # Single-control temp file
                if uploaded_input_filename:
                    try:
                        candidate = os.path.join(COMFY_INPUT_DIR, uploaded_input_filename)
                        if os.path.exists(candidate):
                            os.remove(candidate)
                    except Exception as e:
                        logger.debug({"event": "cleanup_uploaded_input_single_failed", "file": uploaded_input_filename, "error": str(e)})
                # Multi-control temp files
                try:
                    for fname in list(uploaded_multi_filenames):
                        if not fname:
                            continue
                        try:
                            candidate = os.path.join(COMFY_INPUT_DIR, fname)
                            if os.path.exists(candidate):
                                os.remove(candidate)
                        except Exception as e:
                            logger.debug({"event": "cleanup_uploaded_input_multi_failed", "fname": fname, "error": str(e)})
                            continue
                except Exception as e:
                    logger.debug({"event": "cleanup_multi_loop_failed", "error": str(e)})
        except Exception as e:
            logger.debug({"event": "cleanup_uploaded_inputs_failed", "error": str(e)})

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
