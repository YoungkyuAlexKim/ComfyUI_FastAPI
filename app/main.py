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

try:
    translator = PromptTranslator(model_path="./models/gemma-3-4b-it-Q6_K.gguf")
except FileNotFoundError as e:
    print(f"경고: {e}. 프롬프트 번역 기능이 비활성화됩니다.")
    translator = None

templates = Jinja2Templates(directory="templates")
app = FastAPI(title="ComfyUI FastAPI Server", version="0.4.0 (Jobs & Queues)")

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


# --- Anonymous user ID helpers ---
ANON_COOKIE_NAME = "anon_id"
ANON_COOKIE_PREFIX = "anon-"

def _ensure_anon_id_cookie(req: Request, resp: HTMLResponse) -> str:
    existing = req.cookies.get(ANON_COOKIE_NAME)
    if existing and isinstance(existing, str) and existing.startswith(ANON_COOKIE_PREFIX):
        return existing
    new_id = ANON_COOKIE_PREFIX + uuid.uuid4().hex
    # ~180 days
    max_age = 60 * 60 * 24 * 180
    resp.set_cookie(
        key=ANON_COOKIE_NAME,
        value=new_id,
        httponly=True,
        samesite="lax",
        secure=False,
        max_age=max_age,
    )
    return new_id

def _get_anon_id_from_request(req: Request) -> str:
    value = req.cookies.get(ANON_COOKIE_NAME)
    if value and isinstance(value, str) and value.startswith(ANON_COOKIE_PREFIX):
        return value
    # Fallback anonymous namespace when no cookie is present (should be rare for API calls)
    return ANON_COOKIE_PREFIX + "guest"


# For WebSocket cookie access
def _get_anon_id_from_ws(websocket: WebSocket) -> str:
    value = websocket.cookies.get(ANON_COOKIE_NAME)
    if value and isinstance(value, str) and value.startswith(ANON_COOKIE_PREFIX):
        return value
    return ANON_COOKIE_PREFIX + "guest"

# --- Paths and saving helpers ---
def _user_base_dir(anon_id: str) -> str:
    return os.path.join(OUTPUT_DIR, "users", anon_id)

def _date_partition_path(base_dir: str, dt: datetime) -> str:
    return os.path.join(base_dir, dt.strftime("%Y"), dt.strftime("%m"), dt.strftime("%d"))

def _build_web_path(abs_path: str) -> str:
    # Assumes OUTPUT_DIR is served at /outputs
    abs_outputs = os.path.abspath(OUTPUT_DIR)
    abs_target = os.path.abspath(abs_path)
    rel = os.path.relpath(abs_target, abs_outputs).replace("\\", "/")
    return f"/outputs/{rel}"

def _save_image_and_meta(anon_id: str, image_bytes: bytes, req: "GenerateRequest", original_filename: str) -> Tuple[str, str]:
    now = datetime.now(timezone.utc)
    user_dir = _user_base_dir(anon_id)
    dated_dir = _date_partition_path(user_dir, now)
    os.makedirs(dated_dir, exist_ok=True)

    image_id = uuid.uuid4().hex
    image_filename = f"{image_id}.png"
    image_path = os.path.join(dated_dir, image_filename)

    with open(image_path, "wb") as f:
        f.write(image_bytes)

    # Thumbnail (webp preferred; fallback to jpg)
    thumb_rel_dir = os.path.join(dated_dir, "thumb")
    os.makedirs(thumb_rel_dir, exist_ok=True)
    thumb_webp_path = os.path.join(thumb_rel_dir, f"{image_id}.webp")
    thumb_jpg_path = os.path.join(thumb_rel_dir, f"{image_id}.jpg")
    thumb_path_written = None
    if Image is not None:
        try:
            with Image.open(BytesIO(image_bytes)) as im:
                im = im.convert("RGB")
                # Resize keeping aspect ratio: short side 384px
                max_side = 384
                im.thumbnail((max_side, max_side))
                try:
                    im.save(thumb_webp_path, format="WEBP", quality=80, method=6)
                    thumb_path_written = thumb_webp_path
                except Exception:
                    im.save(thumb_jpg_path, format="JPEG", quality=80)
                    thumb_path_written = thumb_jpg_path
        except Exception:
            thumb_path_written = None
    
    # Sidecar metadata
    sha256 = hashlib.sha256(image_bytes).hexdigest()
    meta = {
        "id": image_id,
        "owner": anon_id,
        "workflow_id": req.workflow_id,
        "aspect_ratio": req.aspect_ratio,
        "seed": req.seed,
        "prompt": req.user_prompt,
        "original_filename": original_filename,
        "mime": "image/png",
        "bytes": len(image_bytes),
        "sha256": sha256,
        "created_at": now.isoformat(),
        "status": "active",
        "thumb": _build_web_path(thumb_path_written) if thumb_path_written else None,
        "tags": [],
    }
    meta_path = os.path.join(dated_dir, f"{image_id}.json")
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)

    return image_path, meta_path

def _control_base_dir(anon_id: str) -> str:
    return os.path.join(_user_base_dir(anon_id), "controls")

def _save_control_image_and_meta(anon_id: str, image_bytes: bytes, original_filename: str) -> Tuple[str, str]:
    now = datetime.now(timezone.utc)
    base_dir = _control_base_dir(anon_id)
    dated_dir = _date_partition_path(base_dir, now)
    os.makedirs(dated_dir, exist_ok=True)

    control_id = uuid.uuid4().hex
    filename = f"{control_id}.png"
    image_path = os.path.join(dated_dir, filename)

    with open(image_path, "wb") as f:
        f.write(image_bytes)

    # Thumbnail
    thumb_rel_dir = os.path.join(dated_dir, "thumb")
    os.makedirs(thumb_rel_dir, exist_ok=True)
    thumb_webp_path = os.path.join(thumb_rel_dir, f"{control_id}.webp")
    thumb_jpg_path = os.path.join(thumb_rel_dir, f"{control_id}.jpg")
    thumb_path_written = None
    if Image is not None:
        try:
            with Image.open(BytesIO(image_bytes)) as im:
                im = im.convert("RGB")
                max_side = 384
                im.thumbnail((max_side, max_side))
                try:
                    im.save(thumb_webp_path, format="WEBP", quality=80, method=6)
                    thumb_path_written = thumb_webp_path
                except Exception:
                    im.save(thumb_jpg_path, format="JPEG", quality=80)
                    thumb_path_written = thumb_jpg_path
        except Exception:
            thumb_path_written = None

    sha256 = hashlib.sha256(image_bytes).hexdigest()
    meta = {
        "id": control_id,
        "owner": anon_id,
        "workflow_id": None,
        "kind": "control",
        "original_filename": original_filename,
        "mime": "image/png",
        "bytes": len(image_bytes),
        "sha256": sha256,
        "created_at": now.isoformat(),
        "status": "active",
        "thumb": _build_web_path(thumb_path_written) if thumb_path_written else None,
        "tags": [],
    }
    meta_path = os.path.join(dated_dir, f"{control_id}.json")
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)

    return image_path, meta_path

def _gather_user_controls(anon_id: str, include_trash: bool = False) -> List[dict]:
    base = _control_base_dir(anon_id)
    if not os.path.isdir(base):
        return []
    items: List[dict] = []
    for root, _, files in os.walk(base):
        for name in files:
            if not name.lower().endswith(".png"):
                continue
            png_path = os.path.join(root, name)
            try:
                stat = os.stat(png_path)
                created = stat.st_mtime
                image_id = os.path.splitext(name)[0]
                meta_path = os.path.join(root, f"{image_id}.json")
                meta = None
                if os.path.exists(meta_path):
                    try:
                        with open(meta_path, "r", encoding="utf-8") as f:
                            meta = json.load(f)
                    except Exception:
                        meta = None
                status = None
                if meta and isinstance(meta, dict):
                    status = meta.get("status")
                if not include_trash and status and status != "active":
                    continue
                thumb_url = None
                if meta and isinstance(meta, dict):
                    thumb_url = meta.get("thumb")
                else:
                    t_webp = os.path.join(root, "thumb", f"{image_id}.webp")
                    t_jpg = os.path.join(root, "thumb", f"{image_id}.jpg")
                    if os.path.exists(t_webp): thumb_url = _build_web_path(t_webp)
                    elif os.path.exists(t_jpg): thumb_url = _build_web_path(t_jpg)

                items.append({
                    "id": image_id,
                    "url": _build_web_path(png_path),
                    "thumb_url": thumb_url,
                    "meta": meta,
                    "status": status or "active",
                    "mtime": created,
                })
            except Exception:
                continue
    items.sort(key=lambda x: x["mtime"], reverse=True)
    return items

def _gather_user_images(anon_id: str, include_trash: bool = False) -> List[dict]:
    base = _user_base_dir(anon_id)
    if not os.path.isdir(base):
        return []
    items: List[dict] = []
    for root, _, files in os.walk(base):
        # Skip control images directory entirely
        try:
            parts = os.path.normpath(root).split(os.sep)
            if "controls" in parts:
                continue
        except Exception:
            pass
        for name in files:
            if not name.lower().endswith(".png"):
                continue
            png_path = os.path.join(root, name)
            try:
                stat = os.stat(png_path)
                created = stat.st_mtime
                image_id = os.path.splitext(name)[0]
                meta_path = os.path.join(root, f"{image_id}.json")
                meta = None
                if os.path.exists(meta_path):
                    try:
                        with open(meta_path, "r", encoding="utf-8") as f:
                            meta = json.load(f)
                    except Exception:
                        meta = None
                # Exclude control items based on meta.kind
                try:
                    if isinstance(meta, dict) and meta.get("kind") == "control":
                        continue
                except Exception:
                    pass
                status = None
                if meta and isinstance(meta, dict):
                    status = meta.get("status")
                # Skip trashed in normal listings
                if not include_trash and status and status != "active":
                    continue
                thumb_url = None
                if meta and isinstance(meta, dict):
                    thumb_url = meta.get("thumb")
                else:
                    # Try implied thumb path
                    t_webp = os.path.join(root, "thumb", f"{image_id}.webp")
                    t_jpg = os.path.join(root, "thumb", f"{image_id}.jpg")
                    if os.path.exists(t_webp): thumb_url = _build_web_path(t_webp)
                    elif os.path.exists(t_jpg): thumb_url = _build_web_path(t_jpg)

                items.append({
                    "id": image_id,
                    "url": _build_web_path(png_path),
                    "thumb_url": thumb_url,
                    "meta": meta,
                    "status": status or "active",
                    "mtime": created,
                })
            except Exception:
                continue
    # Sort by mtime desc (newest first)
    items.sort(key=lambda x: x["mtime"], reverse=True)
    return items

def _locate_control_meta_path(anon_id: str, image_id: str) -> Optional[str]:
    base = _control_base_dir(anon_id)
    if not os.path.isdir(base):
        return None
    target = f"{image_id}.json"
    for root, _, files in os.walk(base):
        if target in files:
            return os.path.join(root, target)
    return None

def _locate_control_png_path(anon_id: str, image_id: str) -> Optional[str]:
    base = _control_base_dir(anon_id)
    if not os.path.isdir(base):
        return None
    target = f"{image_id}.png"
    for root, _, files in os.walk(base):
        if target in files:
            return os.path.join(root, target)
    return None

def _update_control_status(anon_id: str, image_id: str, status: str) -> bool:
    meta_path = _locate_control_meta_path(anon_id, image_id)
    if not meta_path:
        return False
    try:
        with open(meta_path, "r", encoding="utf-8") as f:
            meta = json.load(f)
        meta["status"] = status
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump(meta, f, ensure_ascii=False, indent=2)
        return True
    except Exception:
        return False

class ConnectionManager:
    def __init__(self):
        self.active_connections: list[WebSocket] = []
        self.user_to_conns: dict[str, list[WebSocket]] = {}
        self.loop: asyncio.AbstractEventLoop | None = None
    def set_loop(self, loop: asyncio.AbstractEventLoop):
        self.loop = loop
    async def connect(self, websocket: WebSocket, user_id: str):
        await websocket.accept()
        self.active_connections.append(websocket)
        self.user_to_conns.setdefault(user_id, []).append(websocket)
    def disconnect(self, websocket: WebSocket, user_id: str):
        try:
            self.active_connections.remove(websocket)
        except ValueError:
            pass
        lst = self.user_to_conns.get(user_id)
        if lst and websocket in lst:
            lst.remove(websocket)
            if not lst:
                self.user_to_conns.pop(user_id, None)
    async def broadcast_json(self, data: dict):
        tasks = [connection.send_json(data) for connection in self.active_connections]
        await asyncio.gather(*tasks, return_exceptions=True)
    async def send_json_to_user(self, user_id: str, data: dict):
        conns = self.user_to_conns.get(user_id, [])
        if not conns:
            return
        tasks = [ws.send_json(data) for ws in list(conns)]
        await asyncio.gather(*tasks, return_exceptions=True)
    def send_from_worker(self, user_id: str, data: dict):
        if not self.loop:
            return
        coro = self.send_json_to_user(user_id, data)
        try:
            asyncio.run_coroutine_threadsafe(coro, self.loop)
        except Exception:
            pass

manager = ConnectionManager()
job_manager = JobManager()
job_store = JobStore(JOB_DB_PATH)
logger = setup_logging()

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

@app.get("/api/v1/workflows", tags=["Workflows"])
async def get_workflows():
    workflows = []
    for workflow_id, config in WORKFLOW_CONFIGS.items():
        json_path = os.path.join(WORKFLOW_DIR, f"{workflow_id}.json")
        node_count = 0
        if os.path.exists(json_path):
            try:
                with open(json_path, 'r', encoding='utf-8') as f:
                    node_count = len(json.load(f))
            except Exception as e:
                print(f"Error processing workflow {json_path}: {e}")
        workflows.append({
            "id": workflow_id,
            "name": config.get("display_name", workflow_id.replace("_", " ").title()),  # config에서 가져오기
            "description": config.get("description", "워크플로우 설명이 없습니다."),  # config에서 가져오기
            "node_count": node_count,
            "style_prompt": config.get("style_prompt", ""),
            "negative_prompt": config.get("negative_prompt", ""),
            "recommended_prompt": config.get("recommended_prompt", "") # 추천 프롬프트 추가
        })
    return {"workflows": workflows}

def _processor_generate(job: Job, progress_cb):
    req_dict = job.payload
    request = GenerateRequest(**req_dict)
    workflow_path = os.path.join(WORKFLOW_DIR, f"{request.workflow_id}.json")
    control = None
    multi_controls: List[dict] = []
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
                        if isinstance(stored, str) and stored:
                            multi_controls.append({
                                "slot": slot,
                                "image_filename": stored,
                                "strength": 1.0,
                            })
                            try:
                                time.sleep(0.05)
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
                            if isinstance(stored, str) and stored:
                                uploaded_input_filename = stored
                                control = {"strength": 1.0, "image_filename": stored}
                                try:
                                    time.sleep(0.05)
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

    # Best-effort cleanup of uploaded input in ComfyUI input directory
    try:
        if uploaded_input_filename and isinstance(COMFY_INPUT_DIR, str) and COMFY_INPUT_DIR:
            # ComfyUI may flatten or keep names; try direct match
            candidate = os.path.join(COMFY_INPUT_DIR, uploaded_input_filename)
            if os.path.exists(candidate):
                os.remove(candidate)
    except Exception:
        pass

@app.post("/api/v1/generate", tags=["Image Generation"])
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


@app.get("/api/v1/images", tags=["Images"])
async def list_images(page: int = 1, size: int = 24, request: Request = None):
    anon_id = _get_anon_id_from_request(request)
    logger.info({"event": "list_images", "owner_id": anon_id, "page": page, "size": size})
    items = _gather_user_images(anon_id, include_trash=False)
    size = max(1, min(100, size))
    page = max(1, page)
    start = (page - 1) * size
    end = start + size
    total = len(items)
    slice_items = items[start:end]
    response_items = []
    for it in slice_items:
        response_items.append({
            "id": it["id"],
            "url": it["url"],
            "created_at": datetime.fromtimestamp(it["mtime"], tz=timezone.utc).isoformat(),
            "meta": it.get("meta"),
            "thumb_url": it.get("thumb_url"),
        })
    total_pages = (total + size - 1) // size
    return {
        "items": response_items,
        "page": page,
        "size": size,
        "total": total,
        "total_pages": total_pages
    }


# -------------------- Controls (user) --------------------

@app.post("/api/v1/controls/upload", tags=["Controls"])
async def user_upload_control_image(request: Request, file: UploadFile = File(...)):
    anon_id = _get_anon_id_from_request(request)
    if not file or not isinstance(file.filename, str):
        raise HTTPException(status_code=400, detail="Invalid upload")
    # Basic validation
    name = os.path.basename(file.filename)
    if not name.lower().endswith((".png", ".jpg", ".jpeg", ".webp")):
        raise HTTPException(status_code=400, detail="Unsupported file type")
    data = await file.read()
    # Convert to PNG if not png
    png_bytes = data
    if not name.lower().endswith(".png") and Image is not None:
        try:
            with Image.open(BytesIO(data)) as im:
                im = im.convert("RGB")
                out = BytesIO()
                im.save(out, format="PNG")
                png_bytes = out.getvalue()
        except Exception:
            raise HTTPException(status_code=400, detail="Failed to decode image")
    path, meta = _save_control_image_and_meta(anon_id, png_bytes, name)
    return {"ok": True, "id": os.path.splitext(os.path.basename(path))[0], "url": _build_web_path(path)}


@app.get("/api/v1/controls", tags=["Controls"])
async def user_list_controls(page: int = 1, size: int = 24, request: Request = None):
    anon_id = _get_anon_id_from_request(request)
    items = _gather_user_controls(anon_id, include_trash=False)
    size = max(1, min(100, size))
    page = max(1, page)
    start = (page - 1) * size
    end = start + size
    total = len(items)
    slice_items = items[start:end]
    response_items = []
    for it in slice_items:
        response_items.append({
            "id": it["id"],
            "url": it["url"],
            "created_at": datetime.fromtimestamp(it["mtime"], tz=timezone.utc).isoformat(),
            "meta": it.get("meta"),
            "thumb_url": it.get("thumb_url"),
        })
    total_pages = (total + size - 1) // size
    return {"items": response_items, "page": page, "size": size, "total": total, "total_pages": total_pages}


@app.post("/api/v1/controls/{image_id}/delete", tags=["Controls"])
async def user_soft_delete_control(image_id: str, request: Request):
    anon_id = _get_anon_id_from_request(request)
    ok = _update_control_status(anon_id, image_id, "trash")
    if not ok:
        raise HTTPException(status_code=404, detail="Control not found")
    return {"ok": True}


@app.post("/api/v1/controls/{image_id}/restore", tags=["Controls"])
async def user_restore_control(image_id: str, request: Request):
    anon_id = _get_anon_id_from_request(request)
    ok = _update_control_status(anon_id, image_id, "active")
    if not ok:
        raise HTTPException(status_code=404, detail="Control not found")
    return {"ok": True}


@app.post("/api/v1/images/{image_id}/delete", tags=["Images"])
async def user_soft_delete_image(image_id: str, request: Request):
    anon_id = _get_anon_id_from_request(request)
    logger.info({"event": "user_soft_delete", "owner_id": anon_id, "image_id": image_id})
    ok = _update_image_status(anon_id, image_id, "trash")
    if not ok:
        raise HTTPException(status_code=404, detail="Image not found")
    return {"ok": True}


# -------------------- Admin (no auth yet) --------------------

def _list_user_ids() -> List[str]:
    users_root = os.path.join(OUTPUT_DIR, "users")
    if not os.path.isdir(users_root):
        return []
    entries = []
    for name in os.listdir(users_root):
        full = os.path.join(users_root, name)
        if os.path.isdir(full):
            entries.append(name)
    return sorted(entries)

def _locate_image_meta_path(anon_id: str, image_id: str) -> Optional[str]:
    base = _user_base_dir(anon_id)
    if not os.path.isdir(base):
        return None
    target = f"{image_id}.json"
    for root, _, files in os.walk(base):
        if target in files:
            return os.path.join(root, target)
    return None

def _update_image_status(anon_id: str, image_id: str, status: str) -> bool:
    meta_path = _locate_image_meta_path(anon_id, image_id)
    if not meta_path:
        return False
    try:
        with open(meta_path, "r", encoding="utf-8") as f:
            meta = json.load(f)
        meta["status"] = status
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump(meta, f, ensure_ascii=False, indent=2)
        return True
    except Exception:
        return False


@app.get("/admin", response_class=HTMLResponse, tags=["Admin"])
async def admin_page(request: Request):
    return templates.TemplateResponse("admin.html", {"request": request})


@app.get("/api/v1/admin/users", tags=["Admin"])
async def admin_users(page: int = 1, size: int = 50, q: Optional[str] = None):
    # Paged + optional substring filter
    users = _list_user_ids()
    if q and isinstance(q, str):
        ql = q.lower()
        users = [u for u in users if ql in u.lower()]
    size = max(1, min(200, size))
    page = max(1, page)
    total = len(users)
    start = (page - 1) * size
    end = start + size
    slice_users = users[start:end]
    total_pages = (total + size - 1) // size
    return {"users": slice_users, "page": page, "size": size, "total": total, "total_pages": total_pages}


@app.get("/api/v1/admin/jobs", tags=["Admin"])
async def admin_jobs(limit: int = 100):
    try:
        jobs = job_store.fetch_recent(limit=limit)
        if not jobs:
            jobs = job_manager.list_jobs(limit=limit)
        # If coming from DB, artifact_available is present; for in-memory fallback, compute lightweight availability
        if jobs and 'artifact_available' not in jobs[0]:
            def artifact_exists(web_path: str) -> bool:
                try:
                    if not isinstance(web_path, str) or not web_path:
                        return False
                    p = web_path
                    if p.startswith('/outputs/'):
                        rel = p[len('/outputs/') : ]
                    elif p.startswith('outputs/'):
                        rel = p[len('outputs/') : ]
                    else:
                        return False
                    fs_path = os.path.join(OUTPUT_DIR, rel)
                    return os.path.exists(fs_path)
                except Exception:
                    return False
            for j in jobs:
                res = j.get('result') if isinstance(j, dict) else None
                img = res.get('image_path') if isinstance(res, dict) else None
                j['artifact_available'] = artifact_exists(img)
        return {"jobs": jobs}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/v1/admin/jobs/metrics", tags=["Admin"])
async def admin_jobs_metrics(limit: int = 100):
    try:
        avg = job_manager.get_recent_averages(limit=limit)
        return avg
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/v1/admin/jobs/sweep", tags=["Admin"])
async def admin_jobs_sweep(limit: int = 200):
    """Sync artifact_available for recent N jobs. Manual, lightweight page-bounded."""
    try:
        limit = max(1, min(5000, int(limit)))
        jobs = job_store.fetch_recent(limit=limit)
        updated = 0
        for j in jobs:
            try:
                res = j.get('result') if isinstance(j, dict) else None
                img = res.get('image_path') if isinstance(res, dict) else None
                avail = False
                if isinstance(img, str) and img:
                    p = img
                    if p.startswith('/outputs/'):
                        rel = p[len('/outputs/'):]
                    elif p.startswith('outputs/'):
                        rel = p[len('outputs/'):] 
                    else:
                        rel = None
                    if rel:
                        fs_path = os.path.join(OUTPUT_DIR, rel)
                        avail = os.path.exists(fs_path)
                j['artifact_available'] = avail
                job_store.upsert_job(j)
                updated += 1
            except Exception:
                continue
        return {"updated": updated}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/v1/admin/images", tags=["Admin"])
async def admin_images(user_id: str, page: int = 1, size: int = 24, include: str = "all", from_date: Optional[str] = None, to_date: Optional[str] = None):
    include_trash = True
    items = _gather_user_images(user_id, include_trash=include_trash)
    if include == "active":
        items = [it for it in items if it.get("status") == "active"]
    elif include == "trash":
        items = [it for it in items if it.get("status") != "active"]

    # Date range filter (ISO8601 date or datetime strings)
    def parse_iso(s: str) -> Optional[float]:
        try:
            # try full datetime
            return datetime.fromisoformat(s.replace('Z','+00:00')).timestamp()
        except Exception:
            try:
                # try date only
                d = datetime.fromisoformat(s)
                return d.timestamp()
            except Exception:
                return None

    if from_date:
        ts = parse_iso(from_date)
        if ts is not None:
            items = [it for it in items if it.get("mtime", 0) >= ts]
    if to_date:
        ts = parse_iso(to_date)
        if ts is not None:
            items = [it for it in items if it.get("mtime", 0) <= ts]

    size = max(1, min(100, size))
    page = max(1, page)
    start = (page - 1) * size
    end = start + size
    total = len(items)
    slice_items = items[start:end]
    response_items = []
    for it in slice_items:
        response_items.append({
            "id": it["id"],
            "url": it["url"],
            "thumb_url": it.get("thumb_url"),
            "status": it.get("status"),
            "created_at": datetime.fromtimestamp(it["mtime"], tz=timezone.utc).isoformat(),
        })
    total_pages = (total + size - 1) // size
    return {
        "items": response_items,
        "page": page,
        "size": size,
        "total": total,
        "total_pages": total_pages
    }


@app.get("/api/v1/admin/controls", tags=["Admin"])
async def admin_controls(user_id: str, page: int = 1, size: int = 24, include: str = "all"):
    include_trash = True
    items = _gather_user_controls(user_id, include_trash=include_trash)
    if include == "active":
        items = [it for it in items if it.get("status") == "active"]
    elif include == "trash":
        items = [it for it in items if it.get("status") != "active"]

    size = max(1, min(100, size))
    page = max(1, page)
    start = (page - 1) * size
    end = start + size
    total = len(items)
    slice_items = items[start:end]
    response_items = []
    for it in slice_items:
        response_items.append({
            "id": it["id"],
            "url": it["url"],
            "thumb_url": it.get("thumb_url"),
            "status": it.get("status"),
            "created_at": datetime.fromtimestamp(it["mtime"], tz=timezone.utc).isoformat(),
        })
    total_pages = (total + size - 1) // size
    return {"items": response_items, "page": page, "size": size, "total": total, "total_pages": total_pages}


class AdminControlUpdateRequest(BaseModel):
    user_id: str


@app.post("/api/v1/admin/controls/{image_id}/delete", tags=["Admin"])
async def admin_control_soft_delete(image_id: str, req: AdminControlUpdateRequest):
    ok = _update_control_status(req.user_id, image_id, "trash")
    if not ok:
        raise HTTPException(status_code=404, detail="Control not found")
    return {"ok": True}


@app.post("/api/v1/admin/controls/{image_id}/restore", tags=["Admin"])
async def admin_control_restore(image_id: str, req: AdminControlUpdateRequest):
    ok = _update_control_status(req.user_id, image_id, "active")
    if not ok:
        raise HTTPException(status_code=404, detail="Control not found")
    return {"ok": True}


@app.post("/api/v1/admin/purge-controls", tags=["Admin"])
async def admin_purge_controls(req: AdminControlUpdateRequest):
    base = _control_base_dir(req.user_id)
    if not os.path.isdir(base):
        return {"deleted": 0}
    deleted = 0
    for root, _, files in os.walk(base):
        for name in files:
            if not name.endswith('.json'):
                continue
            meta_path = os.path.join(root, name)
            try:
                with open(meta_path, 'r', encoding='utf-8') as f:
                    meta = json.load(f)
                if meta.get('status') == 'active':
                    continue
                image_id = os.path.splitext(name)[0]
                png_path = os.path.join(root, f"{image_id}.png")
                t_webp = os.path.join(root, 'thumb', f"{image_id}.webp")
                t_jpg = os.path.join(root, 'thumb', f"{image_id}.jpg")
                for p in [png_path, t_webp, t_jpg, meta_path]:
                    try:
                        if os.path.exists(p):
                            os.remove(p)
                    except Exception:
                        pass
                deleted += 1
            except Exception:
                continue
    return {"deleted": deleted}


class AdminUpdateRequest(BaseModel):
    user_id: str


@app.post("/api/v1/admin/images/{image_id}/delete", tags=["Admin"])
async def admin_soft_delete(image_id: str, req: AdminUpdateRequest):
    ok = _update_image_status(req.user_id, image_id, "trash")
    if not ok:
        raise HTTPException(status_code=404, detail="Image not found")
    return {"ok": True}


@app.post("/api/v1/admin/images/{image_id}/restore", tags=["Admin"])
async def admin_restore(image_id: str, req: AdminUpdateRequest):
    ok = _update_image_status(req.user_id, image_id, "active")
    if not ok:
        raise HTTPException(status_code=404, detail="Image not found")
    return {"ok": True}


@app.post("/api/v1/admin/purge-trash", tags=["Admin"])
async def admin_purge_trash(req: AdminUpdateRequest):
    # Iterate all images of user and permanently delete those with status != active
    base = _user_base_dir(req.user_id)
    if not os.path.isdir(base):
        return {"deleted": 0}
    deleted = 0
    for root, _, files in os.walk(base):
        for name in files:
            if not name.endswith('.json'):
                continue
            meta_path = os.path.join(root, name)
            try:
                with open(meta_path, 'r', encoding='utf-8') as f:
                    meta = json.load(f)
                if meta.get('status') == 'active':
                    continue
                image_id = os.path.splitext(name)[0]
                # Delete image, thumb(s), meta
                png_path = os.path.join(root, f"{image_id}.png")
                t_webp = os.path.join(root, 'thumb', f"{image_id}.webp")
                t_jpg = os.path.join(root, 'thumb', f"{image_id}.jpg")
                for p in [png_path, t_webp, t_jpg, meta_path]:
                    try:
                        if os.path.exists(p):
                            os.remove(p)
                    except Exception:
                        pass
                deleted += 1
            except Exception:
                continue
    return {"deleted": deleted}

@app.post("/api/v1/jobs/{job_id}/cancel", tags=["Image Generation"])
async def cancel_generation_by_id(job_id: str):
    ok = job_manager.cancel(job_id)
    if not ok:
        raise HTTPException(status_code=400, detail="Job not found or not cancellable")
    return {"ok": True}

@app.get("/api/v1/jobs/{job_id}", tags=["Image Generation"])
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

@app.post("/api/v1/cancel", tags=["Image Generation"])
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

@app.post("/api/v1/translate-prompt", tags=["Prompt Translation"])
async def translate_prompt_endpoint(text: str = Form(...)):
    if translator is None: raise HTTPException(status_code=503, detail="LLM model not loaded.")
    try:
        return {"translated_text": translator.translate_to_danbooru(text)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.websocket("/ws/status")
async def websocket_endpoint(websocket: WebSocket):
    qp = websocket.query_params
    user_id = qp.get("anon_id") or _get_anon_id_from_ws(websocket)
    logger.info({"event": "ws_connect", "owner_id": user_id})
    await manager.connect(websocket, user_id)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        logger.info({"event": "ws_disconnect", "owner_id": user_id})
        manager.disconnect(websocket, user_id)
    except Exception as e:
        print(f"💥 WebSocket error: {e}")
        manager.disconnect(websocket, user_id)

app.mount("/outputs", StaticFiles(directory="outputs"), name="outputs")
app.mount("/static", StaticFiles(directory="static"), name="static")

@app.get("/healthz", tags=["Health"])
async def healthz():
	results = {
		"comfyui": {"ok": False, "reason": None},
		"db": {"ok": False, "reason": None},
		"disk": {"ok": False, "reason": None},
		"llm": {"ok": False, "reason": None},
	}
	status_code = 200
	# ComfyUI HTTP ping (lightweight)
	try:
		url = f"http://{SERVER_ADDRESS}/"
		resp = requests.get(url, timeout=(3.0, 5.0))
		results["comfyui"]["ok"] = (resp.status_code >= 200 and resp.status_code < 500)
		if not results["comfyui"]["ok"]:
			results["comfyui"]["reason"] = f"HTTP {resp.status_code}"
	except Exception as e:
		results["comfyui"]["reason"] = str(e)
		status_code = 503
	# DB writeability (temp table insert)
	try:
		conn = sqlite3.connect(JOB_DB_PATH)
		conn.execute("CREATE TABLE IF NOT EXISTS __healthz (id INTEGER PRIMARY KEY AUTOINCREMENT, ts INTEGER)")
		conn.execute("INSERT INTO __healthz (ts) VALUES (?)", (int(time.time()),))
		conn.execute("DELETE FROM __healthz WHERE id IN (SELECT id FROM __healthz ORDER BY id DESC LIMIT 1 OFFSET 50)")
		conn.commit()
		conn.close()
		results["db"]["ok"] = True
	except Exception as e:
		results["db"]["reason"] = str(e)
		status_code = 503
	# Disk free space
	try:
		total, used, free = shutil.disk_usage(OUTPUT_DIR)
		free_mb = int(free / (1024 * 1024))
		min_mb = int(HEALTHZ_CONFIG.get("disk_min_free_mb", 512))
		results["disk"]["ok"] = (free_mb >= min_mb)
		if not results["disk"]["ok"]:
			results["disk"]["reason"] = f"free {free_mb}MB < min {min_mb}MB"
	except Exception as e:
		results["disk"]["reason"] = str(e)
		status_code = 503
	# LLM readiness (optional)
	try:
		results["llm"]["ok"] = (translator is not None)
		if translator is None:
			results["llm"]["reason"] = "model not loaded"
	except Exception as e:
		results["llm"]["reason"] = str(e)
		# LLM 실패만으로는 전체 5xx로 올리지 않음
	# Overall ok?
	overall_ok = results["comfyui"]["ok"] and results["db"]["ok"] and results["disk"]["ok"]
	payload = {"ok": overall_ok, "components": results}
	if not overall_ok and status_code == 200:
		status_code = 503
	return JSONResponse(content=payload, status_code=status_code)


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
        except Exception:
            pass
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
    except Exception:
        pass
    job_manager.start()
