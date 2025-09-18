from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect, Request, BackgroundTasks, Form
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from typing import Optional
import time
import os
import asyncio
import json

from .comfy_client import ComfyUIClient
from .config import SERVER_CONFIG, WORKFLOW_CONFIGS, get_prompt_overrides, get_default_values
from llm.prompt_translator import PromptTranslator # <-- 이 줄이 추가되었습니다!

try:
    translator = PromptTranslator(model_path="./models/gemma-3-4b-it-Q6_K.gguf")
except FileNotFoundError as e:
    print(f"경고: {e}. 프롬프트 번역 기능이 비활성화됩니다.")
    translator = None

templates = Jinja2Templates(directory="templates")
app = FastAPI(title="ComfyUI FastAPI Server", version="0.2.3 (Enhanced Validation)")

# --- API 요청 모델 (width, height를 선택적으로 변경) ---
class GenerateRequest(BaseModel):
    prompt: str
    negative_prompt: str = ""
    width: Optional[int] = None
    height: Optional[int] = None
    workflow_id: str
    seed: Optional[int] = None

WORKFLOW_DIR = "./workflows/"
OUTPUT_DIR = SERVER_CONFIG["output_dir"]
SERVER_ADDRESS = SERVER_CONFIG["server_address"]

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

@app.get("/", response_class=HTMLResponse, tags=["Page"])
async def read_root(request: Request):
    default_values = get_default_values()
    return templates.TemplateResponse("index.html", {
        "request": request,
        "default_prompt": default_values["prompt"],
        "default_negative_prompt": default_values["negative_prompt"],
        "default_width": default_values["width"],
        "default_height": default_values["height"]
    })

@app.get("/api/v1/workflows", tags=["Workflows"])
async def get_workflows():
    workflows = []
    for workflow_id in WORKFLOW_CONFIGS:
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
            "name": workflow_id.replace("_", " ").title(),
            "description": f"The main workflow for generating images.",
            "node_count": node_count
        })
    return {"workflows": workflows}

def _run_generation(request: GenerateRequest):
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        workflow_path = os.path.join(WORKFLOW_DIR, f"{request.workflow_id}.json")
        prompt_overrides = get_prompt_overrides(
            prompt=request.prompt,
            negative_prompt=request.negative_prompt,
            width=request.width,
            height=request.height,
            workflow_name=request.workflow_id,
            seed=request.seed
        )
        client = ComfyUIClient(SERVER_ADDRESS, manager=manager)
        prompt_id = client.queue_prompt(workflow_path, prompt_overrides).get('prompt_id')
        if not prompt_id: raise RuntimeError("Failed to get prompt_id.")
        images_data = client.get_images(prompt_id)
        if not images_data: raise RuntimeError("Failed to receive generated images.")

        filename = list(images_data.keys())[0]
        image_bytes = list(images_data.values())[0]
        os.makedirs(OUTPUT_DIR, exist_ok=True)
        save_filename = f"api_{int(time.time())}_{filename}"
        save_path = os.path.join(OUTPUT_DIR, save_filename)
        with open(save_path, "wb") as f: f.write(image_bytes)
        print(f"✅ Image saved to '{save_path}'")
        web_path = f"/outputs/{save_filename}"
        loop.run_until_complete(manager.broadcast_json({"status": "complete", "image_path": web_path}))
    except Exception as e:
        print(f"❌ Background task error: {e}")
        loop.run_until_complete(manager.broadcast_json({"error": str(e)}))
    finally:
        loop.close()

@app.post("/api/v1/generate", tags=["Image Generation"])
async def generate_image(request: GenerateRequest, background_tasks: BackgroundTasks):
    # --- 명시적인 서버 측 검증 로직 추가 ---
    if request.width is None or request.width <= 0:
        raise HTTPException(status_code=422, detail="A valid 'width' is required.")
    if request.height is None or request.height <= 0:
        raise HTTPException(status_code=422, detail="A valid 'height' is required.")

    background_tasks.add_task(_run_generation, request)
    return {"message": "Image generation request received."}

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

