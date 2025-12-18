from datetime import datetime, timezone
from io import BytesIO
import os
from fastapi import APIRouter, HTTPException, Request, UploadFile, File
from ..config import UPLOAD_CONFIG
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

_ALLOWED_INPUT_EXTS = (".png", ".jpg", ".jpeg", ".webp")
_ALLOWED_INPUT_CT = ("image/png", "image/jpeg", "image/webp")


def _infer_ext(filename: str | None, content_type: str | None) -> str | None:
    """
    Some browsers/devices may provide odd filenames without extensions (e.g. 'blob').
    Infer an allowed extension from filename or content-type.
    """
    name = (filename or "").strip()
    lower = name.lower()
    for ext in _ALLOWED_INPUT_EXTS:
        if lower.endswith(ext):
            return ext
    ct = (content_type or "").split(";")[0].strip().lower()
    if ct == "image/png":
        return ".png"
    if ct == "image/jpeg":
        return ".jpg"
    if ct == "image/webp":
        return ".webp"
    return None



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
    safe_name = os.path.basename(file.filename)
    ext = _infer_ext(safe_name, getattr(file, "content_type", None))
    if not ext:
        raise HTTPException(status_code=400, detail="지원하지 않는 파일 형식입니다. PNG/JPG/WEBP만 업로드할 수 있어요.")
    if not safe_name.lower().endswith(ext):
        # Normalize to a stable extension so later logic can decide conversion correctly.
        safe_name = f"upload{ext}"
    # Enforce inputs size cap
    chunks: list[bytes] = []
    total = 0
    max_bytes = int(UPLOAD_CONFIG.get("inputs_max_bytes", 10 * 1024 * 1024))
    max_mb = max_bytes / (1024 * 1024)
    while True:
        piece = await file.read(1024 * 256)
        if not piece:
            break
        total += len(piece)
        if total > max_bytes:
            raise HTTPException(status_code=413, detail=f"입력 이미지가 너무 큽니다. 최대 {max_mb:.1f}MB 까지 허용됩니다.")
        chunks.append(piece)
    data = b"".join(chunks)
    png_bytes = data
    if ext != ".png":
        if Image is None:
            raise HTTPException(status_code=400, detail="서버에서 이미지 변환 기능이 준비되지 않았습니다. PNG로 변환 후 업로드해 주세요.")
        try:
            with Image.open(BytesIO(data)) as im:
                im = im.convert("RGB")
                out = BytesIO()
                im.save(out, format="PNG")
                png_bytes = out.getvalue()
        except Exception:
            raise HTTPException(status_code=400, detail="이미지를 읽을 수 없습니다. 파일이 손상되었거나 지원하지 않는 형식일 수 있어요.")
    # Post-conversion safety cap
    if len(png_bytes) > max_bytes:
        raise HTTPException(status_code=413, detail=f"입력 이미지가 너무 큽니다. 최대 {max_mb:.1f}MB 까지 허용됩니다.")
    path, meta = _save_input_image_and_meta(anon_id, png_bytes, safe_name)
    web_url = _build_web_path(path)
    return {"ok": True, "id": os.path.splitext(os.path.basename(path))[0], "url": web_url}


@router.post("/api/v1/inputs/copy", response_model=UploadInputResponse)
async def user_copy_to_inputs(request: Request):
    anon_id = _get_anon_id_from_request(request)
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")
    source = str(body.get("source") or "").strip().lower()
    image_id = str(body.get("id") or "").strip()
    if source not in ("generated", "controls"):
        raise HTTPException(status_code=400, detail="Unsupported source")
    if not image_id:
        raise HTTPException(status_code=400, detail="Missing id")

    # Locate source PNG path
    try:
        if source == "generated":
            from ..services.media_store import _locate_image_meta_path
            meta_path = _locate_image_meta_path(anon_id, image_id)
            if not meta_path:
                raise HTTPException(status_code=404, detail="Source image not found")
            base_dir = os.path.dirname(meta_path)
            png_path = os.path.join(base_dir, f"{image_id}.png")
            if not os.path.exists(png_path):
                raise HTTPException(status_code=404, detail="Source PNG not found")
        else:
            from ..services.media_store import _locate_control_png_path
            png_path = _locate_control_png_path(anon_id, image_id)
            if not png_path or not os.path.exists(png_path):
                raise HTTPException(status_code=404, detail="Source PNG not found")
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=500, detail="Failed to locate source image")

    # Enforce inputs size limit on copy as well
    try:
        max_bytes = int(UPLOAD_CONFIG.get("inputs_max_bytes", 10 * 1024 * 1024))
        max_mb = max_bytes / (1024 * 1024)
        size = os.path.getsize(png_path)
        if size > max_bytes:
            raise HTTPException(status_code=413, detail=f"원본 이미지가 입력 크기 제한을 초과합니다. 최대 {max_mb:.1f}MB 까지 허용됩니다.")
    except HTTPException:
        raise
    except Exception:
        pass

    # Read and save via inputs pipeline to generate proper meta/thumb
    try:
        with open(png_path, "rb") as f:
            data = f.read()
    except Exception:
        raise HTTPException(status_code=500, detail="Failed to read source image")

    try:
        path, meta = _save_input_image_and_meta(anon_id, data, os.path.basename(png_path))
        web_url = _build_web_path(path)
        return {"ok": True, "id": os.path.splitext(os.path.basename(path))[0], "url": web_url}
    except Exception:
        raise HTTPException(status_code=500, detail="Failed to save input image")


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


