import os

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse

from ..auth.user_management import _get_anon_id_from_request
from ..services.asset_runtime import get_asset_service


router = APIRouter(prefix="/api/v1/assets", tags=["Assets"])


def _owned_active_asset(request: Request, asset_id: str) -> tuple[dict, object]:
    owner_id = _get_anon_id_from_request(request)
    service = get_asset_service(required=True)
    asset = service.get(owner_id, asset_id)
    if not asset or asset.get("status") != "active":
        raise HTTPException(status_code=404, detail="Asset not found")
    return asset, service


@router.get("/{asset_id}/content")
async def asset_content(asset_id: str, request: Request):
    asset, service = _owned_active_asset(request, asset_id)
    path = service.resolve_storage_path(asset.get("storage_path"))
    if not path or not os.path.isfile(path):
        raise HTTPException(status_code=404, detail="Asset file not found")
    response = FileResponse(path, media_type=asset.get("mime_type") or "application/octet-stream")
    response.headers["Cache-Control"] = "private, max-age=300"
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response

@router.get("/{asset_id}/thumbnail")
async def asset_thumbnail(asset_id: str, request: Request):
    asset, service = _owned_active_asset(request, asset_id)
    path = service.resolve_storage_path(asset.get("thumbnail_path"))
    if not path or not os.path.isfile(path):
        raise HTTPException(status_code=404, detail="Asset thumbnail not found")
    extension = os.path.splitext(path)[1].lower()
    media_type = "image/webp" if extension == ".webp" else "image/jpeg"
    response = FileResponse(path, media_type=media_type)
    response.headers["Cache-Control"] = "private, max-age=300"
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response
