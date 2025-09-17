from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect, Request, BackgroundTasks
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

templates = Jinja2Templates(directory="templates")

# --- FastAPI 앱 설정 ---
app = FastAPI(
    title="ComfyUI FastAPI Server",
    description="FastAPI를 사용하여 ComfyUI 워크플로우를 실행하는 API 서버입니다.",
    version="0.1.0",
)

# --- API 요청/응답 모델 정의 ---
# API 예제값들을 가져옵니다
api_examples = get_api_examples()

class GenerateRequest(BaseModel):
    """이미지 생성 요청 시 Body에 포함될 데이터 모델"""
    prompt_a: str = Field(..., description="긍정 프롬프트 A (예: 캐릭터, 행동 서술)", example=api_examples["prompt_a"])
    prompt_b: str = Field(..., description="긍정 프롬프트 B (예: 스타일, 화풍 서술)", example=api_examples["prompt_b"])
    negative_prompt: str = Field("", description="부정 프롬프트 텍스트", example=api_examples["negative_prompt"])
    seed: int = Field(None, description="랜덤 시드 값 (빈 값이면 자동 랜덤 생성)", example=12345)
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
    설정된 워크플로우 목록을 반환합니다.
    """
    workflow_dir = "./workflows/"
    workflows = []

    if os.path.exists(workflow_dir):
        # 설정된 워크플로우들만 처리
        for workflow_name in WORKFLOW_CONFIGS.keys():
            json_file = os.path.join(workflow_dir, f"{workflow_name}.json")

            if os.path.exists(json_file):
                try:
                    with open(json_file, 'r', encoding='utf-8') as f:
                        workflow_data = json.load(f)

                    # 워크플로우 메타데이터 추출
                    workflow_info = {
                        "id": workflow_name,
                        "name": workflow_name.replace("_", " ").title(),
                        "file_path": json_file,
                        "description": f"{workflow_name} 워크플로우",
                        "node_count": len(workflow_data) if isinstance(workflow_data, dict) else 0,
                        "configured": True  # 설정된 워크플로우임을 표시
                    }

                    workflows.append(workflow_info)
                except Exception as e:
                    print(f"워크플로우 파일 로드 중 오류: {json_file} - {e}")
            else:
                print(f"⚠️ 설정된 워크플로우 파일이 존재하지 않습니다: {json_file}")

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