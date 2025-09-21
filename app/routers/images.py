from datetime import datetime, timezone
from fastapi import APIRouter, HTTPException, Request
from ..logging_utils import setup_logging
from ..auth.user_management import _get_anon_id_from_request
from ..services.media_store import _gather_user_images, _update_image_status
from ..schemas.api_models import PaginatedImages


logger = setup_logging()
router = APIRouter(tags=["Images"])


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
    total_pages = (total + size_val - 1) // size_val
    return slice_items, {"page": page_val, "size": size_val, "total": total, "total_pages": total_pages}


@router.get("/api/v1/images", response_model=PaginatedImages)
async def list_images(page: int = 1, size: int = 24, request: Request = None):
    anon_id = _get_anon_id_from_request(request)
    logger.info({"event": "list_images", "owner_id": anon_id, "page": page, "size": size})
    items = _gather_user_images(anon_id, include_trash=False)
    slice_items, meta = _paginate(items, page, size)
    response_items = []
    for it in slice_items:
        response_items.append({
            "id": it["id"],
            "url": it["url"],
            "created_at": datetime.fromtimestamp(it["mtime"], tz=timezone.utc).isoformat(),
            "meta": it.get("meta"),
            "thumb_url": it.get("thumb_url"),
        })
    return {"items": response_items, **meta}


@router.post("/api/v1/images/{image_id}/delete")
async def user_soft_delete_image(image_id: str, request: Request):
    anon_id = _get_anon_id_from_request(request)
    logger.info({"event": "user_soft_delete", "owner_id": anon_id, "image_id": image_id})
    ok = _update_image_status(anon_id, image_id, "trash")
    if not ok:
        raise HTTPException(status_code=404, detail="Image not found")
    return {"ok": True}


