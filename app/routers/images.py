from datetime import datetime, timezone
from fastapi import APIRouter, HTTPException, Request
from ..logging_utils import setup_logging
from ..auth.user_management import _get_anon_id_from_request
from ..services.media_store import _gather_user_images, _update_image_status
from ..schemas.api_models import PaginatedImages
from ..services.principal_links import browser_asset_owner_ids, linked_mcp_owner_ids


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


def _paginate_preserving_groups(items: list, page: int, size: int):
    """Legacy-catalog fallback for the opt-in group-preserving gallery view."""

    page_val = max(1, int(page))
    size_val = max(1, min(100, int(size)))
    blocks: list[list[dict]] = []
    blocks_by_key: dict[str, list[dict]] = {}
    for item in items:
        metadata = item.get("meta") if isinstance(item.get("meta"), dict) else {}
        group_id = str(metadata.get("game_ui_group_id") or "").strip()
        key = f"group:{group_id}" if group_id else f"asset:{item.get('id')}"
        block = blocks_by_key.get(key)
        if block is None:
            block = []
            blocks_by_key[key] = block
            blocks.append(block)
        block.append(item)

    pages: list[list[list[dict]]] = []
    current: list[list[dict]] = []
    current_weight = 0
    for block in blocks:
        weight = max(1, len(block))
        if current and current_weight + weight > size_val:
            pages.append(current)
            current = []
            current_weight = 0
        current.append(block)
        current_weight += weight
    if current:
        pages.append(current)

    selected_blocks = pages[page_val - 1] if page_val <= len(pages) else []
    selected_items = [item for block in selected_blocks for item in block]
    return selected_items, {
        "page": page_val,
        "size": size_val,
        "total": len(items),
        "total_pages": len(pages),
    }


@router.get("/api/v1/images", response_model=PaginatedImages)
async def list_images(
    page: int = 1,
    size: int = 24,
    preserve_groups: bool = False,
    request: Request = None,
):
    anon_id = _get_anon_id_from_request(request)
    logger.info({"event": "list_images", "owner_id": anon_id, "page": page, "size": size})
    page_val = max(1, int(page))
    size_val = max(1, min(100, int(size)))
    asset_service = getattr(request.app.state, "asset_service", None)
    if asset_service is not None:
        owner_ids = [anon_id, *linked_mcp_owner_ids(request, anon_id)]
        if preserve_groups:
            slice_items, meta = asset_service.list_media_group_preserving_page_for_owners(
                owner_ids, "image", page=page_val, size=size_val
            )
        else:
            total = asset_service.count_media_for_owners(owner_ids, "image")
            slice_items = asset_service.list_media_for_owners(
                owner_ids, "image", limit=size_val, offset=(page_val - 1) * size_val
            )
            meta = {
                "page": page_val,
                "size": size_val,
                "total": total,
                "total_pages": (total + size_val - 1) // size_val,
            }
    else:
        items = _gather_user_images(anon_id, include_trash=False)
        if preserve_groups:
            slice_items, meta = _paginate_preserving_groups(items, page_val, size_val)
        else:
            slice_items, meta = _paginate(items, page_val, size_val)
    response_items = []
    for it in slice_items:
        response_items.append({
            "id": it["id"],
            "url": it["url"],
            "created_at": datetime.fromtimestamp(it["mtime"], tz=timezone.utc).isoformat(),
            "meta": it.get("meta"),
            "thumb_url": it.get("thumb_url"),
            "linked_from_mcp": it.get("owner_id") != anon_id,
        })
    return {"items": response_items, **meta}


@router.post("/api/v1/images/{image_id}/delete")
async def user_soft_delete_image(image_id: str, request: Request):
    actor_owner_id = _get_anon_id_from_request(request)
    ok, asset_owner_id = _update_browser_manageable_image_status(request, image_id, "trash")
    logger.info({
        "event": "user_soft_delete",
        "owner_id": actor_owner_id,
        "asset_owner_id": asset_owner_id,
        "linked_from_mcp": bool(asset_owner_id and asset_owner_id != actor_owner_id),
        "image_id": image_id,
        "ok": ok,
    })
    if not ok:
        raise HTTPException(status_code=404, detail="Image not found")
    return {"ok": True}


@router.post("/api/v1/images/{image_id}/restore")
async def user_restore_image(image_id: str, request: Request):
    actor_owner_id = _get_anon_id_from_request(request)
    ok, asset_owner_id = _update_browser_manageable_image_status(request, image_id, "active")
    logger.info({
        "event": "user_restore_image",
        "owner_id": actor_owner_id,
        "asset_owner_id": asset_owner_id,
        "linked_from_mcp": bool(asset_owner_id and asset_owner_id != actor_owner_id),
        "image_id": image_id,
        "ok": ok,
    })
    if not ok:
        raise HTTPException(status_code=404, detail="Image not found")
    return {"ok": True}


def _update_browser_manageable_image_status(
    request: Request,
    image_id: str,
    status: str,
) -> tuple[bool, str | None]:
    """Update a browser-owned or explicitly linked MCP image without transferring ownership."""

    actor_owner_id = _get_anon_id_from_request(request)
    asset_service = getattr(request.app.state, "asset_service", None)
    if asset_service is None:
        return _update_image_status(actor_owner_id, image_id, status), actor_owner_id

    row = asset_service.get_for_owners(
        browser_asset_owner_ids(request, actor_owner_id),
        image_id,
        kind="image",
    )
    if not row:
        return False, None
    asset_owner_id = str(row["owner_id"])
    return asset_service.update_status(asset_owner_id, image_id, status, kind="image"), asset_owner_id


def _update_game_ui_group_status(request: Request, group_id: str, status: str) -> tuple[bool, str | None]:
    asset_service = getattr(request.app.state, "asset_service", None)
    if asset_service is None:
        raise HTTPException(status_code=503, detail="Asset catalog is not initialized")
    actor_owner_id = _get_anon_id_from_request(request)
    for asset_owner_id in browser_asset_owner_ids(request, actor_owner_id):
        if asset_service.get_group(asset_owner_id, group_id):
            return asset_service.update_group_status(asset_owner_id, group_id, status), asset_owner_id
    return False, None


@router.post("/api/v1/game-ui-groups/{group_id}/delete")
async def user_soft_delete_game_ui_group(group_id: str, request: Request):
    actor_owner_id = _get_anon_id_from_request(request)
    ok, asset_owner_id = _update_game_ui_group_status(request, group_id, "trash")
    logger.info({
        "event": "user_soft_delete_game_ui_group",
        "owner_id": actor_owner_id,
        "asset_owner_id": asset_owner_id,
        "linked_from_mcp": bool(asset_owner_id and asset_owner_id != actor_owner_id),
        "group_id": group_id,
        "ok": ok,
    })
    if not ok:
        raise HTTPException(status_code=404, detail="Game UI group not found")
    return {"ok": True, "scope": "group", "group_id": group_id}


@router.post("/api/v1/game-ui-groups/{group_id}/restore")
async def user_restore_game_ui_group(group_id: str, request: Request):
    actor_owner_id = _get_anon_id_from_request(request)
    ok, asset_owner_id = _update_game_ui_group_status(request, group_id, "active")
    logger.info({
        "event": "user_restore_game_ui_group",
        "owner_id": actor_owner_id,
        "asset_owner_id": asset_owner_id,
        "linked_from_mcp": bool(asset_owner_id and asset_owner_id != actor_owner_id),
        "group_id": group_id,
        "ok": ok,
    })
    if not ok:
        raise HTTPException(status_code=404, detail="Game UI group not found")
    return {"ok": True, "scope": "group", "group_id": group_id}


