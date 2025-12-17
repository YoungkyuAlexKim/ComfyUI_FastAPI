import websocket # 
import uuid
import json
import urllib.request
import urllib.parse
import asyncio
from typing import Callable, Optional
import logging
from urllib.parse import urlparse

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

    def _normalize_server(self) -> tuple[str, str]:
        """
        Normalize server address from env/config.

        Accepts both:
          - "127.0.0.1:8188"
          - "http://127.0.0.1:8188" (or https)

        Returns: (http_scheme, hostport)
        """
        raw = str(self.server_address or "").strip()
        if "://" in raw:
            u = urlparse(raw)
            scheme = (u.scheme or "http").lower()
            hostport = (u.netloc or u.path or "").strip()
            if not hostport:
                hostport = "127.0.0.1:8188"
            if scheme not in ("http", "https"):
                scheme = "http"
            return (scheme, hostport)
        # No scheme; treat as host:port
        return ("http", raw or "127.0.0.1:8188")

    def _http_base(self) -> str:
        scheme, hostport = self._normalize_server()
        return f"{scheme}://{hostport}"

    def _ws_base(self) -> str:
        scheme, hostport = self._normalize_server()
        ws_scheme = "wss" if scheme == "https" else "ws"
        return f"{ws_scheme}://{hostport}"

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
        url = f"{self._http_base()}/prompt"
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
        url = f"{self._http_base()}/upload/image"
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
        ws_url = f"{self._ws_base()}/ws?clientId={self.client_id}"

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

        # --- 결과 이미지 선택 ---
        # ComfyUI history에는 "최종 결과"뿐 아니라 입력/중간 단계의 이미지도 outputs에 포함될 수 있습니다.
        # 예: LoadImage 출력(원본), 중간 프리뷰, 최종 Preview/SaveImage 결과 등.
        # 그래서 단순히 "첫 번째 이미지"를 쓰면 Img2Img에서 원본이 결과로 저장/표시되는 문제가 생길 수 있습니다.
        #
        # 해결: history의 prompt 그래프에서 각 node의 class_type을 함께 보고,
        # SaveImage/PreviewImage가 만든 이미지를 최우선으로 선택합니다.
        history = self.get_history(prompt_id).get(prompt_id, {}) or {}
        outputs = (history.get("outputs", {}) or {}) if isinstance(history, dict) else {}
        # history["prompt"] 는 ComfyUI 버전에 따라 형태가 다를 수 있습니다.
        # 흔한 형태:
        # - dict: { node_id: {class_type, inputs, ...}, ... }
        # - list: [queue_id, prompt_id, { node_id: {...}, ... }]
        prompt_field = history.get("prompt") if isinstance(history, dict) else None
        prompt_graph = {}
        try:
            if isinstance(prompt_field, dict):
                # Some variants wrap nodes under "nodes"
                if isinstance(prompt_field.get("nodes"), dict):
                    prompt_graph = prompt_field.get("nodes") or {}
                else:
                    prompt_graph = prompt_field
            elif isinstance(prompt_field, list):
                if len(prompt_field) >= 3 and isinstance(prompt_field[2], dict):
                    prompt_graph = prompt_field[2]
        except Exception:
            prompt_graph = {}

        candidates: list[tuple[int, int, int, dict]] = []

        def _node_num(node_id: str) -> int:
            try:
                return int(str(node_id))
            except Exception:
                return -1

        def _type_priority(folder_type: str) -> int:
            # /view?type=output|temp|input
            t = str(folder_type or "").lower()
            if t == "output":
                return 3
            if t == "temp":
                return 2
            if t == "input":
                return 1
            return 0

        def _class_priority(class_type: str) -> int:
            # 최종 결과를 만드는 노드 우선
            # - SaveImage/PreviewImage: 최종에 가까움
            # - VAEDecode: 디코딩된 최종 이미지(워크플로우에 Save/Preview가 없어도 여기서 선택 가능)
            # - LoadImage: 입력 원본이므로 최하위 (Img2Img에서 이것을 선택하면 "원본이 결과" 문제가 발생)
            ct = str(class_type or "")
            if ct == "SaveImage":
                return 100
            if ct == "PreviewImage":
                return 90
            if ct in ("VAEDecode", "VAEDecodeTiled", "VAEDecodeTAESD"):
                return 80
            if ct == "LoadImage":
                return 0
            return 50

        for node_id, node_output in outputs.items():
            if not isinstance(node_output, dict):
                continue
            imgs = node_output.get("images")
            if not isinstance(imgs, list) or not imgs:
                continue
            node_cfg = prompt_graph.get(str(node_id), {}) if isinstance(prompt_graph, dict) else {}
            class_type = node_cfg.get("class_type") if isinstance(node_cfg, dict) else None
            cpri = _class_priority(class_type)
            nid = _node_num(str(node_id))
            for img in imgs:
                if not isinstance(img, dict):
                    continue
                tpri = _type_priority(img.get("type"))
                candidates.append((cpri, tpri, nid, img))

        # Filter 1: output/temp 가 하나라도 있으면 input 타입은 제외(가능한 경우)
        try:
            has_non_input = any(t[1] >= 2 for t in candidates)  # temp(2) or output(3)
            if has_non_input:
                candidates = [t for t in candidates if t[1] >= 2]
        except Exception:
            pass

        # 우선순위: class > type(output/temp/input) > node_id(큰 것이 보통 더 마지막)
        candidates.sort(key=lambda t: (t[0], t[1], t[2]), reverse=True)

        images_output: dict[str, bytes] = {}
        for cpri, tpri, nid, img in candidates:
            try:
                filename = img.get("filename")
                subfolder = img.get("subfolder", "")
                folder_type = img.get("type", "")
                if not filename:
                    continue
                image_data = self.get_image(filename, subfolder, folder_type)
                if image_data:
                    images_output[str(filename)] = image_data
            except Exception:
                continue

        # (디버깅 힌트) 어떤 후보가 1순위였는지 + 상위 후보 몇 개를 로그
        try:
            if candidates:
                top = candidates[0]
                img = top[3]
                top_list = []
                try:
                    for it in candidates[:5]:
                        node_id = str(it[2])
                        node_cfg = prompt_graph.get(node_id, {}) if isinstance(prompt_graph, dict) else {}
                        ct = node_cfg.get("class_type") if isinstance(node_cfg, dict) else None
                        top_list.append({
                            "node_id": it[2],
                            "class_type": ct,
                            "type": (it[3] or {}).get("type"),
                            "subfolder": (it[3] or {}).get("subfolder"),
                            "filename": (it[3] or {}).get("filename"),
                            "class_priority": it[0],
                            "type_priority": it[1],
                        })
                except Exception:
                    top_list = []
                self._logger.info({
                    "event": "comfy_images_selected",
                    "prompt_id": prompt_id,
                    "selected_filename": img.get("filename"),
                    "selected_type": img.get("type"),
                    "selected_subfolder": img.get("subfolder"),
                    "selected_node_id": top[2],
                    "selected_class_priority": top[0],
                    "top_candidates": top_list,
                })
        except Exception:
            pass

        return images_output

    def interrupt(self):
        """
        현재 client_id로 ComfyUI 서버에 인터럽트 요청을 보냅니다.
        실행 중인 작업이 있다면 즉시 중단됩니다.
        """
        url = f"{self._http_base()}/interrupt"
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
        url = f"{self._http_base()}/history/{prompt_id}"
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
        url = f"{self._http_base()}/view"
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