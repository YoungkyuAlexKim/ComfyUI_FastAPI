from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect, Request, BackgroundTasks, Form
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field
import time
import os
import asyncio
import json
import glob

# Phase 1에서 우리가 만든 ComfyUIClient를 가져옵니다.
from .comfy_client import ComfyUIClient
from .config import SERVER_CONFIG, WORKFLOW_CONFIGS, get_prompt_overrides, get_default_prompts_for_html, get_api_examples

# Gemma 프롬프트 번역기 모듈을 가져옵니다.
from llm.prompt_translator import PromptTranslator

# --- LLM 번역기 인스턴스 생성 ---
try:
    translator = PromptTranslator(model_path="./models/gemma-3-4b-it-Q6_K.gguf")
except FileNotFoundError as e:
    print(f"경고: {e}. 프롬프트 번역 기능이 비활성화됩니다.")
    translator = None

templates = Jinja2Templates(directory="templates")

# --- FastAPI 앱 설정 ---
app = FastAPI(
    title="ComfyUI FastAPI Server",
    description="FastAPI를 사용하여 ComfyUI 워크플로우를 실행하는 API 서버입니다.",
    version="0.1.0",
)

# --- API 요청/응답 모델 정의 ---
api_examples = get_api_examples() # 함수를 호출하여 예제값을 가져옵니다.

class GenerateRequest(BaseModel):
    """이미지 생성 요청 시 Body에 포함될 데이터 모델"""
    prompt_a: str = Field(..., description="긍정 프롬프트 A (예: 캐릭터, 행동 서술)", example=api_examples.get("prompt_a"))
    prompt_b: str = Field(..., description="긍정 프롬프트 B (예: 스타일, 화풍 서술)", example=api_examples.get("prompt_b"))
    negative_prompt: str = Field("", description="부정 프롬프트 텍스트", example=api_examples.get("negative_prompt"))
    workflow_id: str = Field("basic_workflow", description="사용할 워크플로우 ID", example="basic_workflow")

# --- 서버 설정 (config.py에서 가져옴) ---
WORKFLOW_DIR = "./workflows/"
OUTPUT_DIR = SERVER_CONFIG["output_dir"]
SERVER_ADDRESS = SERVER_CONFIG["server_address"]

# --- 웹소켓 연결 관리자 ---
class ConnectionManager:
    def __init__(self):
        self.active_connections: list[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        self.active_connections.remove(websocket)

    async def broadcast_json(self, data: dict):
        for connection in self.active_connections:
            await connection.send_json(data)

manager = ConnectionManager()

@app.get("/", response_class=HTMLResponse, tags=["Page"])
async def read_root(request: Request):
    """
    웹 UI를 위한 메인 페이지(index.html)를 렌더링합니다.
    """
    default_prompts = get_default_prompts_for_html()
    return templates.TemplateResponse("index.html", {
        "request": request,
        "default_prompt_a": default_prompts["prompt_a"],
        "default_prompt_b": default_prompts["prompt_b"],
        "default_negative_prompt": default_prompts["negative_prompt"]
    })

@app.get("/api/v1/default-prompts", tags=["Configuration"])
async def get_default_prompts():
    """
    HTML 템플릿에서 사용할 기본 프롬프트 값을 반환합니다.
    """
    return get_default_prompts_for_html()

@app.get("/api/v1/workflows", tags=["Workflows"])
async def get_workflows():
    """
    사용 가능한 워크플로우 목록을 반환합니다.
    """
    workflows = []
    workflow_dir = "./workflows/"

    # config.py에 정의된 워크플로우 목록을 기준으로 정보를 조합합니다.
    for workflow_id, config in WORKFLOW_CONFIGS.items():
        json_file_path = os.path.join(workflow_dir, f"{workflow_id}.json")
        node_count = 0

        try:
            # 실제 파일이 있는지 확인하고 노드 수를 계산합니다.
            if os.path.exists(json_file_path):
                with open(json_file_path, 'r', encoding='utf-8') as f:
                    workflow_data = json.load(f)
                    node_count = len(workflow_data) if isinstance(workflow_data, dict) else 0

            workflow_info = {
                "id": workflow_id,
                "name": workflow_id.replace("_", " ").title(),
                "file_path": json_file_path,
                "description": f"{workflow_id} 워크플로우",
                "node_count": node_count
            }
            workflows.append(workflow_info)
        except Exception as e:
            print(f"워크플로우 파일 처리 중 오류: {json_file_path} - {e}")

    return {"workflows": workflows, "total": len(workflows)}

# --- 백그라운드 작업 함수 ---
def _run_generation(request: GenerateRequest, prompt_overrides: dict):
    """실제 이미지 생성을 수행하는 내부 함수 (백그라운드에서 실행됨)"""
    try:
        # 선택된 워크플로우 파일 경로 결정
        workflow_path = os.path.join(WORKFLOW_DIR, f"{request.workflow_id}.json")

        # 워크플로우 파일 존재 확인
        if not os.path.exists(workflow_path):
            print(f"❌ 워크플로우 파일을 찾을 수 없습니다: {workflow_path}")
            asyncio.run(manager.broadcast_json({"error": f"Workflow '{request.workflow_id}' not found."}))
            return

        # ConnectionManager를 ComfyUIClient에 전달합니다.
        client = ComfyUIClient(SERVER_ADDRESS, manager=manager)

        print(f"🚀 백그라운드에서 이미지 생성을 시작합니다... (워크플로우: {request.workflow_id})")
        prompt_id = client.queue_prompt(workflow_path, prompt_overrides).get('prompt_id')

        if not prompt_id:
            print("❌ 이미지 생성 요청에 실패했습니다 (prompt_id를 받지 못함).")
            # asyncio.run()은 이미 실행 중인 이벤트 루프에서 호출할 수 없으므로,
            # 새 루프를 만들어 실행하거나 get_running_loop().run_in_executor() 등을 사용해야 합니다.
            # 여기서는 간단하게 새 스레드에서 실행되므로 .run()을 유지합니다.
            asyncio.run(manager.broadcast_json({"error": "Failed to get prompt_id."}))
            return

        images_data = client.get_images(prompt_id)

        if not images_data:
            print("❌ 생성된 이미지를 수신하지 못했습니다.")
            asyncio.run(manager.broadcast_json({"error": "Failed to receive generated images."}))
            return

        # ⭐️⭐️⭐️ 수정된 부분 시작 ⭐️⭐️⭐️

        # 생성된 파일의 순수한 이름 (예: ComfyUI_..._.png)
        filename = list(images_data.keys())[0]
        image_bytes = list(images_data.values())[0]

        os.makedirs(OUTPUT_DIR, exist_ok=True)
        
        # 실제 디스크에 저장될 전체 경로
        save_path = os.path.join(OUTPUT_DIR, f"api_{int(time.time())}_{filename}")
        
        with open(save_path, "wb") as f:
            f.write(image_bytes)
        
        print(f"✅ 작업 완료! 이미지를 '{save_path}'에 저장했습니다.")

        # 웹 브라우저가 접근할 URL 경로 (예: outputs/api_..._.png)
        # StaticFiles로 마운트한 경로('outputs')와 실제 파일 이름을 조합하여 만듭니다.
        web_accessible_path = f"outputs/api_{int(time.time())}_{filename}"

        # ⭐️⭐️⭐️ 수정된 부분 끝 ⭐️⭐️⭐️
        
        asyncio.run(manager.broadcast_json({
            "status": "complete",
            "message": f"Image saved to {save_path}",
            "image_path": web_accessible_path.replace("\\", "/") # 윈도우 경로 문자를 웹 경로 문자로 변경
        }))

    except Exception as e:
        print(f"❌ 백그라운드 작업 중 에러 발생: {e}")
        asyncio.run(manager.broadcast_json({"error": str(e)}))

# --- API 엔드포인트 정의 ---
@app.post("/api/v1/generate", tags=["Image Generation"])
async def generate_image(request: GenerateRequest, background_tasks: BackgroundTasks):
    """
    이미지 생성 요청을 접수하고, 실제 생성 작업은 백그라운드에서 실행합니다.
    """
    prompt_overrides = get_prompt_overrides(
        prompt_a=request.prompt_a,
        prompt_b=request.prompt_b,
        negative_prompt=request.negative_prompt,
        workflow_name=request.workflow_id
    )
    
    # 실제 이미지 생성 함수를 백그라운드 작업으로 추가
    background_tasks.add_task(_run_generation, request, prompt_overrides)
    
    # 사용자에게는 즉시 응답 반환
    return {"message": "이미지 생성 요청이 성공적으로 접수되었습니다. 잠시 후 결과가 표시됩니다."}

# --- API 엔드포인트 정의 ---
@app.post("/api/v1/translate-prompt", tags=["Prompt Translation"])
async def translate_prompt_endpoint(text: str = Form(...)):
    """
    주어진 자연어 텍스트를 Danbooru 태그로 변환합니다.
    """
    if translator is None:
        raise HTTPException(
            status_code=503, 
            detail="LLM 모델이 로드되지 않아 번역 기능을 사용할 수 없습니다."
        )

    try:
        translated_tags = translator.translate_to_danbooru(text)
        return {"translated_text": translated_tags}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# --- 웹소켓 엔드포인트 정의 ---
@app.websocket("/ws/status")
async def websocket_endpoint(websocket: WebSocket):
    """
    웹소켓 연결을 처리하고, ConnectionManager를 통해 관리합니다.
    """
    await manager.connect(websocket)
    print(f"✅ 클라이언트 연결됨: {websocket.client}")
    try:
        # 연결 유지를 위해 계속 대기
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket)
        print(f"❌ 클라이언트 연결 끊어짐: {websocket.client}")
    except Exception as e:
        manager.disconnect(websocket)
        print(f"💥 웹소켓 오류 발생: {e}")

# --- 정적 파일 서빙 설정 추가 ---
# 생성된 이미지를 웹 브라우저에서 바로 볼 수 있도록 /outputs 경로를 서빙합니다.
from fastapi.staticfiles import StaticFiles
app.mount("/outputs", StaticFiles(directory="outputs"), name="outputs")

# CSS, JS, 이미지 등의 정적 파일들을 서빙합니다.
app.mount("/static", StaticFiles(directory="static"), name="static")