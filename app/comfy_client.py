import websocket # 
import uuid
import json
import urllib.request
import urllib.parse
import asyncio


class ComfyUIClient:
    def __init__(self, server_address="127.0.0.1:8188", client_id=None, manager=None):
        """
        ComfyUI 서버와 통신하기 위한 클라이언트를 초기화합니다.

        Args:
            server_address (str): ComfyUI 서버 주소 (예: "127.0.0.1:8188")
            client_id (str, optional): 클라이언트를 식별하기 위한 고유 ID. Defaults to None.
                                    None이면 자동으로 생성됩니다.
            manager (ConnectionManager, optional): FastAPI의 웹소켓 연결 관리자.
        """
        self.server_address = server_address
        self.client_id = client_id if client_id else str(uuid.uuid4())
        self.manager = manager

    def queue_prompt(self, workflow_json_path, prompt_overrides):
        """
        워크플로우를 기반으로 ComfyUI 서버에 이미지 생성을 요청합니다. (버그 수정 및 requests 사용)
        """
        # 1. 워크플로우 JSON 파일 로드
        try:
            with open(workflow_json_path, 'r', encoding='utf-8') as f:
                prompt = json.load(f)
        except FileNotFoundError:
            print(f"❌ 에러: 워크플로우 파일을 찾을 수 없습니다! 경로: {workflow_json_path}")
            return {}
        except json.JSONDecodeError:
            print(f"❌ 에러: 워크플로우 파일이 유효한 JSON 형식이 아닙니다! 파일 내용을 확인해주세요.")
            return {}

        # 2. 프롬프트 오버라이드 적용 (⭐️⭐️⭐️ 버그 수정된 핵심 로직 ⭐️⭐️⭐️)
        for node_id, overrides in prompt_overrides.items():
            if node_id in prompt:
                # 'inputs' 딕셔너리 내부의 값들만 업데이트하여 기존 연결 정보를 보존합니다.
                if 'inputs' in prompt[node_id] and 'inputs' in overrides:
                        prompt[node_id]['inputs'].update(overrides['inputs'])
                else: # 'inputs'가 아닌 다른 최상위 키를 덮어쓰는 경우 (예: class_type)
                        prompt[node_id].update(overrides)
            else:
                print(f"⚠️ 경고: 워크플로우에 노드 ID '{node_id}'가 없습니다. 이 오버라이드는 무시됩니다.")
        
        # 3. client_id와 prompt 데이터를 API 형식에 맞게 구성
        data = {
            "prompt": prompt,
            "client_id": self.client_id
        }
        
        # 4. HTTP POST 요청 보내기 (requests 라이브러리 사용)
        url = f"http://{self.server_address}/prompt"
        try:
            # requests 라이브러리를 사용하여 POST 요청을 보냅니다.
            import requests
            response = requests.post(url, json=data)
            response.raise_for_status() # 2xx 상태 코드가 아니면 에러를 발생시킴
            return response.json()
        except ImportError:
            print("❌ 에러: 'requests' 라이브러리가 설치되지 않았습니다. 'pip install requests'를 실행해주세요.")
            return {}
        except requests.exceptions.RequestException as e:
            print(f"❌ 에러: ComfyUI 서버에 요청을 보내는 중 문제가 발생했습니다.")
            print(f"    - URL: {url}")
            print(f"    - 에러 내용: {e}")
            # 서버가 받은 데이터가 궁금할 경우 아래 주석을 해제하여 디버깅할 수 있습니다.
            # print("\n--- 전송된 데이터 (JSON) ---")
            # print(json.dumps(data, indent=2))
            # print("--------------------------\n")
            return {}
        
    # 기존 get_images 메서드를 아래 코드로 완전히 교체해주세요.
    def get_images(self, prompt_id):
        """
        웹소켓을 통해 이미지 생성 진행 상황을 수신하고,
        ConnectionManager를 통해 연결된 모든 클라이언트에게 진행률을 브로드캐스팅합니다.
        """
        ws_url = f"ws://{self.server_address}/ws?clientId={self.client_id}"

        ws = websocket.create_connection(ws_url)
        try:
            while True:
                opcode, data = ws.recv_data()

                if opcode == 1:
                    message = json.loads(data.decode('utf-8'))

                    if message['type'] == 'executing':
                        node_data = message['data']
                        if node_data['node'] is None and node_data['prompt_id'] == prompt_id:
                            # 최종 완료 상태 브로드캐스팅
                            if self.manager:
                                asyncio.run(self.manager.broadcast_json({"progress": 100.0, "status": "complete"}))
                            print("\n✅ 작업 실행이 서버에서 완료되었습니다.")
                            break

                    if message['type'] == 'progress':
                        progress_data = message['data']
                        progress = (progress_data['value'] / progress_data['max']) * 100
                        print(f"⏳ 진행 중... {progress:.2f}%", end='\r', flush=True) # 터미널 로그는 유지

                        # ⭐️⭐️⭐️ 웹소켓 클라이언트에게 진행률 브로드캐스팅 ⭐️⭐️⭐️
                        if self.manager:
                            # 비동기 함수를 동기 코드에서 실행하기 위해 asyncio.run 사용
                            asyncio.run(self.manager.broadcast_json({"progress": progress, "status": "running"}))

                elif opcode == 2:
                    pass # Pong frame, 무시

        except websocket.WebSocketConnectionClosedException:
            print("웹소켓 연결이 정상적으로 닫혔습니다.")
        except Exception as e:
            print(f"메시지 수신 중 오류 발생: {e}")
            # 오류 브로드캐스트는 상위 레벨에서 일괄 처리합니다.
            raise
        finally:
            ws.close()

        # --- 아래 부분은 기존과 동일합니다 ---
        history = self.get_history(prompt_id).get(prompt_id, {})
        images_output = {}

        for node_id, node_output in history.get('outputs', {}).items():
            if 'images' in node_output:
                for image in node_output['images']:
                    image_data = self.get_image(image['filename'], image['subfolder'], image['type'])
                    if image_data:
                        images_output[image['filename']] = image_data

        return images_output

    def interrupt(self):
        """
        현재 client_id로 ComfyUI 서버에 인터럽트 요청을 보냅니다.
        실행 중인 작업이 있다면 즉시 중단됩니다.
        """
        url = f"http://{self.server_address}/interrupt"
        try:
            import requests
            response = requests.post(url, json={"client_id": self.client_id})
            response.raise_for_status()
            return True
        except ImportError:
            print("❌ 에러: 'requests' 라이브러리가 설치되지 않았습니다. 'pip install requests'를 실행해주세요.")
            return False
        except Exception as e:
            print(f"❌ 인터럽트 전송 실패: {e}")
            return False

    def get_history(self, prompt_id):
        """HTTP를 통해 특정 prompt_id의 히스토리를 가져옵니다."""
        with urllib.request.urlopen(f"http://{self.server_address}/history/{prompt_id}") as response:
            return json.loads(response.read())

    def get_image(self, filename, subfolder, folder_type):
        """HTTP를 통해 특정 이미지를 가져옵니다."""
        data = {"filename": filename, "subfolder": subfolder, "type": folder_type}
        url_values = urllib.parse.urlencode(data)
        with urllib.request.urlopen(f"http://{self.server_address}/view?{url_values}") as response:
            return response.read() 