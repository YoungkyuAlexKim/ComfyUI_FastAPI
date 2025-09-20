import asyncio
from fastapi import WebSocket
from ..logging_utils import setup_logging


logger = setup_logging()


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
        except Exception as e:
            logger.debug({"event": "ws_send_from_worker_failed", "owner_id": user_id, "error": str(e)})


# Singleton instance to be imported across the app
manager = ConnectionManager()


