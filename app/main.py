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
    return templates.TemplateResponse("index.html", {
        "request": request,
        "default_user_prompt": "",  # 워크플로우별로 설정되므로 빈 값
        "default_style_prompt": default_values.get("style_prompt", ""),
        "default_negative_prompt": default_values.get("negative_prompt", ""),
        "default_recommended_prompt": default_values.get("recommended_prompt", ""),
        "workflows_sizes_json": json.dumps(default_values.get("workflows_sizes", {})), # ✨ 사이즈 정보 추가
        "workflow_default_prompts_json": json.dumps(default_values.get("workflow_default_prompts", {})) # 워크플로우별 기본 프롬프트
    })

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

def _run_generation(request: GenerateRequest):
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
        os.makedirs(OUTPUT_DIR, exist_ok=True)
        save_filename = f"api_{int(time.time())}_{filename}"
        save_path = os.path.join(OUTPUT_DIR, save_filename)
        with open(save_path, "wb") as f: f.write(image_bytes)
        print(f"✅ Image saved to '{save_path}'")
        web_path = f"/outputs/{save_filename}"
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
async def generate_image(request: GenerateRequest, background_tasks: BackgroundTasks):
    # ✨ width, height 유효성 검사 로직 제거
    background_tasks.add_task(_run_generation, request)
    return {"message": "Image generation request received."}

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
