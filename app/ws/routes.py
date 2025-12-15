from fastapi import APIRouter, WebSocket
from ..logging_utils import setup_logging
from ..auth.user_management import _get_anon_id_from_ws
from ..beta_access import beta_enabled, is_request_authed
from .manager import manager


logger = setup_logging()
router = APIRouter()


@router.websocket("/ws/status")
async def websocket_status(websocket: WebSocket):
    # Beta gate: WebSocket must also be authenticated when BETA_PASSWORD is set.
    if beta_enabled():
        try:
            if not is_request_authed(websocket.cookies):
                await websocket.close(code=4401)
                return
        except Exception:
            try:
                await websocket.close(code=4401)
            except Exception:
                pass
            return
    qp = websocket.query_params
    user_id = qp.get("anon_id") or _get_anon_id_from_ws(websocket)
    logger.info({"event": "ws_connect", "owner_id": user_id})
    await manager.connect(websocket, user_id)
    try:
        while True:
            await websocket.receive_text()
    except Exception as e:
        # Distinguish normal disconnects if needed by checking type
        try:
            from fastapi import WebSocketDisconnect  # local import to avoid unused if not triggered
        except Exception:
            WebSocketDisconnect = Exception
        if isinstance(e, WebSocketDisconnect):
            logger.info({"event": "ws_disconnect", "owner_id": user_id})
        else:
            logger.error({"event": "ws_error", "owner_id": user_id, "error": str(e)})
    finally:
        manager.disconnect(websocket, user_id)


