from datetime import datetime, timezone
import os
from fastapi import APIRouter, HTTPException, Request, UploadFile, File
from ..logging_utils import setup_logging
from ..auth.user_management import _get_anon_id_from_request
from ..auth.mcp_identity import (
    mcp_client_ip_allowed,
    parse_allowed_mcp_networks,
    principal_for_mcp_ip,
)
from ..services.media_store import (
    _gather_user_inputs,
    _update_input_status,
    _build_web_path,
)
from ..services.input_assets import InputAssetError, input_max_bytes, register_input_image
from ..services.generation_commands import resolve_client_ip
from ..services.principal_links import browser_asset_owner_ids
from ..schemas.api_models import PaginatedImages as PaginatedInputs, UploadMediaResponse as UploadInputResponse, OkResponse

logger = setup_logging()
router = APIRouter(tags=["Inputs"])


async def _read_bounded_upload(file: UploadFile) -> bytes:
    if not file or not isinstance(file.filename, str):
        raise HTTPException(status_code=400, detail="Invalid upload")
    chunks: list[bytes] = []
    total = 0
    max_bytes = input_max_bytes()
    max_mb = max_bytes / (1024 * 1024)
    while True:
        piece = await file.read(1024 * 256)
        if not piece:
            break
        total += len(piece)
        if total > max_bytes:
            raise HTTPException(
                status_code=413,
                detail=f"입력 이미지가 너무 큽니다. 최대 {max_mb:.1f}MB 까지 허용됩니다.",
            )
        chunks.append(piece)
    return b"".join(chunks)


def _mcp_upload_owner(request: Request) -> tuple[str, str, str]:
    peer_ip = getattr(getattr(request, "client", None), "host", None)
    client_ip, source = resolve_client_ip(
        peer_ip,
        request.headers.get("x-forwarded-for"),
        os.getenv("TRUSTED_PROXY_CIDRS"),
    )
    try:
        parse_allowed_mcp_networks(os.getenv("MCP_ALLOWED_CLIENT_CIDRS"))
    except ValueError as exc:
        raise HTTPException(status_code=503, detail="mcp_client_cidr_policy_invalid") from exc
    if not mcp_client_ip_allowed(client_ip, os.getenv("MCP_ALLOWED_CLIENT_CIDRS")):
        raise HTTPException(status_code=403, detail="mcp_client_ip_not_allowed")
    return principal_for_mcp_ip(client_ip), client_ip, source



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
    page_val = max(1, int(page))
    size_val = max(1, min(100, int(size)))
    asset_service = getattr(request.app.state, "asset_service", None)
    if asset_service is not None:
        total = asset_service.count_media(anon_id, "input")
        slice_items = asset_service.list_media(
            anon_id, "input", limit=size_val, offset=(page_val - 1) * size_val
        )
        meta = {
            "page": page_val,
            "size": size_val,
            "total": total,
            "total_pages": (total + size_val - 1) // size_val,
        }
    else:
        items = _gather_user_inputs(anon_id, include_trash=False)
        slice_items, meta = _paginate(items, page_val, size_val)
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
    data = await _read_bounded_upload(file)
    try:
        service = request.app.state.asset_service
        row, _ = register_input_image(
            service,
            anon_id,
            data,
            filename=file.filename,
            content_type=getattr(file, "content_type", None),
            deduplicate=False,
        )
    except InputAssetError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc
    path = service.resolve_storage_path(row.get("storage_path"))
    if not path:
        raise HTTPException(status_code=500, detail="Failed to resolve saved input image")
    return {"ok": True, "id": row["asset_id"], "url": _build_web_path(path)}


@router.post("/api/v1/mcp/inputs/upload")
async def mcp_upload_input_image(request: Request, file: UploadFile = File(...)):
    """Register a multipart image under the caller's MCP IP workspace."""

    owner_id, client_ip, client_ip_source = _mcp_upload_owner(request)
    data = await _read_bounded_upload(file)
    try:
        service = request.app.state.asset_service
        row, duplicate = register_input_image(
            service,
            owner_id,
            data,
            filename=file.filename,
            content_type=getattr(file, "content_type", None),
            deduplicate=True,
        )
    except InputAssetError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc
    return {
        "ok": True,
        "asset_id": row["asset_id"],
        "kind": "input",
        "duplicate": duplicate,
        "mime_type": row.get("mime_type") or "image/png",
        "byte_size": row.get("byte_size"),
        "client_ip": client_ip,
        "client_ip_source": client_ip_source,
        "next_action": "Use asset_id in reference_image_ids for plan_generation.",
    }


@router.post("/api/v1/inputs/copy", response_model=UploadInputResponse)
async def user_copy_to_inputs(request: Request):
    anon_id = _get_anon_id_from_request(request)
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")
    source = str(body.get("source") or "").strip().lower()
    image_id = str(body.get("id") or "").strip()
    if source not in ("generated",):
        raise HTTPException(status_code=400, detail="Unsupported source")
    if not image_id:
        raise HTTPException(status_code=400, detail="Missing id")

    # Resolve the browser-owned image or an explicitly linked MCP image. The
    # copy is written under the browser principal, so subsequent web edits do
    # not mutate or depend on the original MCP workspace.
    try:
        service = request.app.state.asset_service
        row = service.get_for_owners(
            browser_asset_owner_ids(request, anon_id),
            image_id,
            kind="image",
            active_only=True,
        )
        if not row:
            raise HTTPException(status_code=404, detail="Source image not found")
        png_path = service.resolve_storage_path(row.get("storage_path"))
        if not png_path or not os.path.isfile(png_path):
            raise HTTPException(status_code=404, detail="Source PNG not found")
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=500, detail="Failed to locate source image")

    # Enforce inputs size limit on copy as well
    try:
        max_bytes = input_max_bytes()
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
        row, _ = register_input_image(
            service,
            anon_id,
            data,
            filename=os.path.basename(png_path),
            content_type="image/png",
            deduplicate=False,
        )
        path = service.resolve_storage_path(row.get("storage_path"))
        if not path:
            raise RuntimeError("Saved input path is unavailable")
        return {
            "ok": True,
            "id": row["asset_id"],
            "url": f"/outputs/{str(row['storage_path']).replace(os.sep, '/')}",
        }
    except InputAssetError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc
    except Exception as exc:
        logger.exception({"event": "copy_input_save_failed", "owner_id": anon_id, "image_id": image_id, "error": str(exc)})
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


