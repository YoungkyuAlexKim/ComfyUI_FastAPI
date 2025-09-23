from datetime import datetime, timezone
from io import BytesIO
import os
from fastapi import APIRouter, HTTPException, Request, UploadFile, File
from ..logging_utils import setup_logging
from ..auth.user_management import _get_anon_id_from_request
from ..services.media_store import (
    _gather_user_inputs,
    _save_input_image_and_meta,
    _update_input_status,
    _build_web_path,
)
from ..schemas.api_models import PaginatedControls as PaginatedInputs, UploadControlResponse as UploadInputResponse, OkResponse

try:
    from PIL import Image
except Exception:
    Image = None


logger = setup_logging()
router = APIRouter(tags=["Inputs"])


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


@router.get("/api/v1/inputs", response_model=PaginatedInputs)
async def user_list_inputs(page: int = 1, size: int = 24, request: Request = None):
    anon_id = _get_anon_id_from_request(request)
    items = _gather_user_inputs(anon_id, include_trash=False)
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


@router.post("/api/v1/inputs/upload", response_model=UploadInputResponse)
async def user_upload_input_image(request: Request, file: UploadFile = File(...)):
    anon_id = _get_anon_id_from_request(request)
    if not file or not isinstance(file.filename, str):
        raise HTTPException(status_code=400, detail="Invalid upload")
    name = os.path.basename(file.filename)
    if not name.lower().endswith((".png", ".jpg", ".jpeg", ".webp")):
        raise HTTPException(status_code=400, detail="Unsupported file type")
    # TODO: (optional) apply size caps similar to controls
    chunks: list[bytes] = []
    total = 0
    while True:
        piece = await file.read(1024 * 256)
        if not piece:
            break
        total += len(piece)
        chunks.append(piece)
    data = b"".join(chunks)
    png_bytes = data
    if not name.lower().endswith(".png") and Image is not None:
        try:
            with Image.open(BytesIO(data)) as im:
                im = im.convert("RGB")
                out = BytesIO()
                im.save(out, format="PNG")
                png_bytes = out.getvalue()
        except Exception:
            raise HTTPException(status_code=400, detail="Failed to decode image")
    path, meta = _save_input_image_and_meta(anon_id, png_bytes, name)
    web_url = _build_web_path(path)
    return {"ok": True, "id": os.path.splitext(os.path.basename(path))[0], "url": web_url}


@router.post("/api/v1/inputs/{image_id}/delete", response_model=OkResponse)
async def user_soft_delete_input(image_id: str, request: Request):
    anon_id = _get_anon_id_from_request(request)
    ok = _update_input_status(anon_id, image_id, "trash")
    if not ok:
        raise HTTPException(status_code=404, detail="Input not found")
    return {"ok": True}


@router.post("/api/v1/inputs/{image_id}/restore", response_model=OkResponse)
async def user_restore_input(image_id: str, request: Request):
    anon_id = _get_anon_id_from_request(request)
    ok = _update_input_status(anon_id, image_id, "active")
    if not ok:
        raise HTTPException(status_code=404, detail="Input not found")
    return {"ok": True}


