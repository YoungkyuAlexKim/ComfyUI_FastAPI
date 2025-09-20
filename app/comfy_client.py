import websocket # 
import uuid
import json
import urllib.request
import urllib.parse
import asyncio
from typing import Callable, Optional
import logging

from .config import HTTP_TIMEOUTS, WS_TIMEOUTS


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
        self._logger = logging.getLogger("comfyui_app")

    def _http_timeouts(self) -> tuple[float, float]:
        try:
            return (
                float(HTTP_TIMEOUTS.get("comfy_http_connect", 3.0)),
                float(HTTP_TIMEOUTS.get("comfy_http_read", 10.0)),
            )
        except Exception:
            return (3.0, 10.0)

    def _ws_connect_timeout(self) -> float:
        try:
            return float(WS_TIMEOUTS.get("comfy_ws_connect", 5.0))
        except Exception:
            return 5.0

    def _ws_idle_timeout(self) -> float:
        try:
            return float(WS_TIMEOUTS.get("comfy_ws_idle", 120.0))
        except Exception:
            return 120.0

    def queue_prompt(self, workflow_json_path, prompt_overrides):
        """
        워크플로우를 기반으로 ComfyUI 서버에 이미지 생성을 요청합니다. (버그 수정 및 requests 사용)
        """
        # 1. 워크플로우 JSON 파일 로드
        try:
            with open(workflow_json_path, 'r', encoding='utf-8') as f:
                prompt = json.load(f)
        except FileNotFoundError:
            try:
                self._logger.error({"event": "workflow_json_missing", "path": workflow_json_path})
            except Exception:
                pass
            return {}
        except json.JSONDecodeError as e:
            try:
                self._logger.error({"event": "workflow_json_invalid", "path": workflow_json_path, "error": str(e)})
            except Exception:
                pass
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
                try:
                    self._logger.warning({"event": "override_missing_node", "node_id": node_id})
                except Exception:
                    pass
        
        # Note: 출력 노드(Preview/SaveImage)는 워크플로우에 직접 포함하는 정책으로 유지합니다.

        # 3. client_id와 prompt 데이터를 API 형식에 맞게 구성
        data = {
            "prompt": prompt,
            "client_id": self.client_id
        }
        
        # 4. HTTP POST 요청 보내기 (requests 라이브러리 사용)
        url = f"http://{self.server_address}/prompt"
        try:
            import requests
            timeout_tuple = self._http_timeouts()
            response = requests.post(url, json=data, timeout=timeout_tuple)
            response.raise_for_status() # 2xx 상태 코드가 아니면 에러를 발생시킴
            return response.json()
        except ImportError:
            try:
                self._logger.error({"event": "requests_missing"})
            except Exception:
                pass
            return {}
        except requests.exceptions.Timeout as e:
            try:
                self._logger.error({"event": "comfy_timeout", "stage": "queue_prompt", "url": url, "error": str(e)})
            except Exception:
                pass
            return {}
        except requests.exceptions.RequestException as e:
            try:
                self._logger.error({"event": "comfy_http_error", "stage": "queue_prompt", "url": url, "error": str(e)})
            except Exception:
                pass
            try:
                # If server responded with 4xx/5xx, include body for diagnostics
                if hasattr(e, 'response') and e.response is not None:
                    body = None
                    try:
                        body = e.response.text
                    except Exception:
                        body = None
                    if body:
                        try:
                            self._logger.error({"event": "comfy_http_error_body", "status_code": e.response.status_code, "body": body[:2048]})
                        except Exception:
                            pass
            except Exception:
                pass
            try:
                payload = {"event": "comfy_http_error", "stage": "queue_prompt", "url": url, "error": str(e)}
                try:
                    if hasattr(e, 'response') and e.response is not None:
                        payload["status_code"] = e.response.status_code
                        payload["body"] = e.response.text
                except Exception:
                    pass
                self._logger.error(payload)
            except Exception:
                pass
            return {}

    def upload_image_to_input(self, filename: str, data: bytes, mime: str = "image/png") -> Optional[str]:
        """Upload an image to ComfyUI input folder so LoadImage node can reference it.

        Returns the stored filename on success, otherwise None.
        """
        url = f"http://{self.server_address}/upload/image"
        try:
            import requests
            files = {"image": (filename, data, mime)}
            form = {"type": "input"}
            timeout_tuple = self._http_timeouts()
            resp = requests.post(url, files=files, data=form, timeout=timeout_tuple)
            resp.raise_for_status()
            try:
                j = resp.json()
                # Common response: {"name": "filename.png"}
                name = None
                if isinstance(j, dict):
                    name = j.get("name") or j.get("filename") or j.get("file")
                    if not name:
                        try:
                            names = j.get("names")
                            if isinstance(names, list) and names:
                                name = names[0]
                        except Exception:
                            pass
                return name or filename
            except Exception:
                return filename
        except Exception as e:
            try:
                self._logger.error({"event": "comfy_http_error", "stage": "upload_image", "url": url, "error": str(e)})
            except Exception:
                pass
            return None
        
    # 기존 get_images 메서드를 아래 코드로 완전히 교체해주세요.
    def get_images(self, prompt_id, on_progress: Optional[Callable[[float], None]] = None):
        """
        웹소켓을 통해 이미지 생성 진행 상황을 수신하고,
        콜백을 통해 진행률을 보고합니다.
        """
        ws_url = f"ws://{self.server_address}/ws?clientId={self.client_id}"

        ws = None
        try:
            ws = websocket.create_connection(ws_url, timeout=self._ws_connect_timeout())
            try:
                ws.settimeout(self._ws_idle_timeout())
            except Exception:
                pass
            while True:
                try:
                    opcode, data = ws.recv_data()
                except websocket.WebSocketTimeoutException as e:
                    try:
                        self._logger.error({"event": "comfy_timeout", "stage": "ws_idle", "url": ws_url, "error": str(e)})
                    except Exception:
                        pass
                    raise

                if opcode == 1:
                    message = json.loads(data.decode('utf-8'))

                    if message['type'] == 'executing':
                        node_data = message['data']
                        if node_data['node'] is None and node_data['prompt_id'] == prompt_id:
                            # 최종 완료
                            if on_progress:
                                try:
                                    on_progress(100.0)
                                except Exception:
                                    pass
                            try:
                                self._logger.info({"event": "comfy_ws_complete", "prompt_id": prompt_id})
                            except Exception:
                                pass
                            break

                    if message['type'] == 'progress':
                        progress_data = message['data']
                        progress = (progress_data['value'] / progress_data['max']) * 100
                        try:
                            self._logger.debug({"event": "comfy_progress", "progress": round(progress, 2)})
                        except Exception:
                            pass

                        # 진행률 콜백
                        if on_progress:
                            try:
                                on_progress(progress)
                            except Exception:
                                pass

                elif opcode == 2:
                    pass # Pong frame, 무시

        except websocket.WebSocketConnectionClosedException:
            try:
                self._logger.info({"event": "comfy_ws_closed"})
            except Exception:
                pass
        except Exception as e:
            try:
                self._logger.error({"event": "comfy_ws_exception", "error": str(e)})
            except Exception:
                pass
            try:
                self._logger.error({"event": "comfy_ws_error", "stage": "get_images", "url": ws_url, "error": str(e)})
            except Exception:
                pass
            # 오류 브로드캐스트는 상위 레벨에서 일괄 처리합니다.
            raise
        finally:
            if ws is not None:
                try:
                    ws.close()
                except Exception:
                    pass

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
            timeout_tuple = self._http_timeouts()
            response = requests.post(url, json={"client_id": self.client_id}, timeout=timeout_tuple)
            response.raise_for_status()
            return True
        except ImportError:
            try:
                self._logger.error({"event": "requests_missing"})
            except Exception:
                pass
            return False
        except requests.exceptions.Timeout as e:
            try:
                self._logger.error({"event": "comfy_timeout", "stage": "interrupt", "url": url, "error": str(e)})
            except Exception:
                pass
            return False
        except Exception as e:
            try:
                self._logger.error({"event": "interrupt_failed", "error": str(e)})
            except Exception:
                pass
            try:
                self._logger.error({"event": "comfy_http_error", "stage": "interrupt", "url": url, "error": str(e)})
            except Exception:
                pass
            return False

    def get_history(self, prompt_id):
        """HTTP를 통해 특정 prompt_id의 히스토리를 가져옵니다."""
        import requests
        url = f"http://{self.server_address}/history/{prompt_id}"
        try:
            timeout_tuple = self._http_timeouts()
            response = requests.get(url, timeout=timeout_tuple)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.Timeout as e:
            try:
                self._logger.error({"event": "comfy_timeout", "stage": "get_history", "url": url, "error": str(e)})
            except Exception:
                pass
            return {}
        except Exception as e:
            try:
                self._logger.error({"event": "comfy_http_error", "stage": "get_history", "url": url, "error": str(e)})
            except Exception:
                pass
            return {}

    def get_image(self, filename, subfolder, folder_type):
        """HTTP를 통해 특정 이미지를 가져옵니다."""
        import requests
        params = {"filename": filename, "subfolder": subfolder, "type": folder_type}
        url = f"http://{self.server_address}/view"
        try:
            timeout_tuple = self._http_timeouts()
            response = requests.get(url, params=params, timeout=timeout_tuple)
            response.raise_for_status()
            return response.content
        except requests.exceptions.Timeout as e:
            try:
                self._logger.error({"event": "comfy_timeout", "stage": "get_image", "url": url, "error": str(e)})
            except Exception:
                pass
            return None
        except Exception as e:
            try:
                self._logger.error({"event": "comfy_http_error", "stage": "get_image", "url": url, "error": str(e)})
            except Exception:
                pass
            return None 