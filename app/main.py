from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect, Request, BackgroundTasks, Form
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

try:
    from PIL import Image
except Exception:
    Image = None

from .comfy_client import ComfyUIClient
from .config import SERVER_CONFIG, WORKFLOW_CONFIGS, get_prompt_overrides, get_default_values, get_workflow_default_prompt
from llm.prompt_translator import PromptTranslator

try:
    translator = PromptTranslator(model_path="./models/gemma-3-4b-it-Q6_K.gguf")
except FileNotFoundError as e:
    print(f"경고: {e}. 프롬프트 번역 기능이 비활성화됩니다.")
    translator = None

templates = Jinja2Templates(directory="templates")
app = FastAPI(title="ComfyUI FastAPI Server", version="0.3.1 (Prompt Suggestion)")

# --- API 요청 모델 (v3.0 기준) ---
class GenerateRequest(BaseModel):
    user_prompt: str
    aspect_ratio: str  # 'width', 'height' 대신 'aspect_ratio' 사용
    workflow_id: str
    seed: Optional[int] = None

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

def _gather_user_images(anon_id: str, include_trash: bool = False) -> List[dict]:
    base = _user_base_dir(anon_id)
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

class ConnectionManager:
    def __init__(self):
        self.active_connections: list[WebSocket] = []
    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)
    def disconnect(self, websocket: WebSocket):
        self.active_connections.remove(websocket)
    async def broadcast_json(self, data: dict):
        tasks = [connection.send_json(data) for connection in self.active_connections]
        await asyncio.gather(*tasks, return_exceptions=True)

manager = ConnectionManager()

# --- 이미지 생성 작업 상태 (단일 사용자 가정) ---
ACTIVE_JOB: dict = {"client": None, "prompt_id": None, "cancelled": False}

@app.get("/", response_class=HTMLResponse, tags=["Page"])
async def read_root(request: Request):
    default_values = get_default_values()
    response = templates.TemplateResponse("index.html", {
        "request": request,
        "default_user_prompt": "",  # 워크플로우별로 설정되므로 빈 값
        "default_style_prompt": default_values.get("style_prompt", ""),
        "default_negative_prompt": default_values.get("negative_prompt", ""),
        "default_recommended_prompt": default_values.get("recommended_prompt", ""),
        "workflows_sizes_json": json.dumps(default_values.get("workflows_sizes", {})), # ✨ 사이즈 정보 추가
        "workflow_default_prompts_json": json.dumps(default_values.get("workflow_default_prompts", {})) # 워크플로우별 기본 프롬프트
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

def _run_generation(request: GenerateRequest, anon_id: str):
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        workflow_path = os.path.join(WORKFLOW_DIR, f"{request.workflow_id}.json")
        prompt_overrides = get_prompt_overrides(
            user_prompt=request.user_prompt,
            aspect_ratio=request.aspect_ratio, # ✨ width, height 대신 aspect_ratio 사용
            workflow_name=request.workflow_id,
            seed=request.seed
        )
        client = ComfyUIClient(SERVER_ADDRESS, manager=manager)
        # 활성 작업 등록
        ACTIVE_JOB["client"] = client
        ACTIVE_JOB["prompt_id"] = None
        ACTIVE_JOB["cancelled"] = False

        prompt_id = client.queue_prompt(workflow_path, prompt_overrides).get('prompt_id')
        if not prompt_id: raise RuntimeError("Failed to get prompt_id.")
        ACTIVE_JOB["prompt_id"] = prompt_id
        images_data = client.get_images(prompt_id)
        if not images_data: raise RuntimeError("Failed to receive generated images.")

        filename = list(images_data.keys())[0]
        image_bytes = list(images_data.values())[0]
        # Save into user/date structured path + sidecar metadata
        saved_image_path, _ = _save_image_and_meta(anon_id, image_bytes, request, filename)
        print(f"✅ Image saved to '{saved_image_path}'")
        web_path = _build_web_path(saved_image_path)
        loop.run_until_complete(manager.broadcast_json({"status": "complete", "image_path": web_path}))
    except Exception as e:
        print(f"❌ Background task error: {e}")
        # 사용자가 취소한 경우 'cancelled' 상태로 브로드캐스트
        if ACTIVE_JOB.get("cancelled"):
            loop.run_until_complete(manager.broadcast_json({"status": "cancelled"}))
        else:
            loop.run_until_complete(manager.broadcast_json({"error": str(e)}))
    finally:
        # 작업 상태 초기화
        ACTIVE_JOB["client"] = None
        ACTIVE_JOB["prompt_id"] = None
        ACTIVE_JOB["cancelled"] = False
        loop.close()

@app.post("/api/v1/generate", tags=["Image Generation"])
async def generate_image(request: GenerateRequest, background_tasks: BackgroundTasks, http_request: Request):
    # ✨ width, height 유효성 검사 로직 제거
    anon_id = _get_anon_id_from_request(http_request)
    background_tasks.add_task(_run_generation, request, anon_id)
    return {"message": "Image generation request received."}


@app.get("/api/v1/images", tags=["Images"])
async def list_images(page: int = 1, size: int = 24, request: Request = None):
    anon_id = _get_anon_id_from_request(request)
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


@app.post("/api/v1/images/{image_id}/delete", tags=["Images"])
async def user_soft_delete_image(image_id: str, request: Request):
    anon_id = _get_anon_id_from_request(request)
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
async def admin_users():
    return {"users": _list_user_ids()}


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

@app.post("/api/v1/cancel", tags=["Image Generation"])
async def cancel_generation():
    try:
        client: ComfyUIClient | None = ACTIVE_JOB.get("client")
        if client is None:
            raise HTTPException(status_code=400, detail="No active generation to cancel.")

        # 취소 플래그 설정 및 서버에 인터럽트 전송
        ACTIVE_JOB["cancelled"] = True
        ok = client.interrupt()
        if not ok:
            raise HTTPException(status_code=500, detail="Failed to send interrupt to ComfyUI.")

        # UI에 'cancelling' 상태 브로드캐스트 (선택)
        await manager.broadcast_json({"status": "cancelling"})
        return {"message": "Cancel request sent."}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/v1/translate-prompt", tags=["Prompt Translation"])
async def translate_prompt_endpoint(text: str = Form(...)):
    if translator is None: raise HTTPException(status_code=503, detail="LLM model not loaded.")
    try:
        return {"translated_text": translator.translate_to_danbooru(text)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.websocket("/ws/status")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True: await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket)
    except Exception as e:
        print(f"💥 WebSocket error: {e}")
        manager.disconnect(websocket)

app.mount("/outputs", StaticFiles(directory="outputs"), name="outputs")
app.mount("/static", StaticFiles(directory="static"), name="static")
