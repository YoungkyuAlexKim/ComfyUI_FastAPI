from datetime import datetime, timezone
from fastapi import APIRouter, HTTPException, Request
from ..logging_utils import setup_logging
from ..auth.user_management import _get_anon_id_from_request
from ..services.media_store import _gather_user_audio, _update_audio_status
from ..schemas.api_models import PaginatedImages  # reuse same paginated model


logger = setup_logging()
router = APIRouter(tags=["Audio"])


def _paginate(items: list, page: int, size: int):
    try:
        size_val = int(size)
    except Exception:
        size_val = 24
    try:
        page_val = int(page)
    except Exception:
        page_val = 1
    size_val = max(1, min(100, size_val))
    page_val = max(1, page_val)
    total = len(items)
    start = (page_val - 1) * size_val
    end = start + size_val
    slice_items = items[start:end]
    total_pages = max(1, (total + size_val - 1) // size_val)
    return slice_items, {"page": page_val, "size": size_val, "total": total, "total_pages": total_pages}


@router.get("/api/v1/audio")
async def list_audio(page: int = 1, size: int = 24, request: Request = None):
    anon_id = _get_anon_id_from_request(request)
    logger.info({"event": "list_audio", "owner_id": anon_id, "page": page, "size": size})
    page_val = max(1, int(page))
    size_val = max(1, min(100, int(size)))
    asset_service = getattr(request.app.state, "asset_service", None)
    if asset_service is not None:
        total = asset_service.count_media(anon_id, "audio")
        slice_items = asset_service.list_media(
            anon_id, "audio", limit=size_val, offset=(page_val - 1) * size_val
        )
        meta = {
            "page": page_val,
            "size": size_val,
            "total": total,
            "total_pages": max(1, (total + size_val - 1) // size_val),
        }
    else:
        items = _gather_user_audio(anon_id, include_trash=False)
        slice_items, meta = _paginate(items, page_val, size_val)
    response_items = []
    for it in slice_items:
        response_items.append({
            "id": it["id"],
            "url": it["url"],
            "created_at": datetime.fromtimestamp(it["mtime"], tz=timezone.utc).isoformat(),
            "meta": it.get("meta"),
            "thumb_url": None,
        })
    return {"items": response_items, **meta}


@router.post("/api/v1/audio/{audio_id}/delete")
async def user_soft_delete_audio(audio_id: str, request: Request):
    anon_id = _get_anon_id_from_request(request)
    logger.info({"event": "user_soft_delete_audio", "owner_id": anon_id, "audio_id": audio_id})
    ok = _update_audio_status(anon_id, audio_id, "trash")
    if not ok:
        raise HTTPException(status_code=404, detail="Audio not found")
    return {"ok": True}
