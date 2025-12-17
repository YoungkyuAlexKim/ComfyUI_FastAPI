from fastapi import APIRouter, HTTPException, Request, Depends

from ..feed_store import FeedStore
from ..logging_utils import setup_logging
from ..services.feed_media_store import (
    move_post_assets_to_trash,
    restore_post_assets_from_trash,
    purge_post_assets_from_trash,
)
from .admin import require_admin


logger = setup_logging()
router = APIRouter(tags=["Admin"], dependencies=[Depends(require_admin)])


def _active_url_to_trash_url(url: str | None) -> str | None:
    if not isinstance(url, str) or not url:
        return None
    if url.startswith("/outputs/feed/"):
        return url.replace("/outputs/feed/", "/outputs/feed/trash/", 1)
    return url


@router.get("/api/v1/admin/feed")
async def admin_feed_list(request: Request, include: str = "all", page: int = 1, size: int = 48):
    store: FeedStore = getattr(request.app.state, "feed_store", None)
    if store is None:
        raise HTTPException(status_code=500, detail="Feed store not available")
    data = store.list_posts(include=include, page=page, size=size)

    items = []
    for it in data.get("items", []):
        display_image_url = it.get("image_url")
        display_thumb_url = it.get("thumb_url")
        display_input_image_url = it.get("input_image_url")
        display_input_thumb_url = it.get("input_thumb_url")
        if it.get("status") == "trash":
            display_image_url = _active_url_to_trash_url(display_image_url)
            display_thumb_url = _active_url_to_trash_url(display_thumb_url)
            display_input_image_url = _active_url_to_trash_url(display_input_image_url)
            display_input_thumb_url = _active_url_to_trash_url(display_input_thumb_url)

        items.append(
            {
                **it,
                "display_image_url": display_image_url,
                "display_thumb_url": display_thumb_url,
                "display_input_image_url": display_input_image_url,
                "display_input_thumb_url": display_input_thumb_url,
            }
        )

    return {**data, "items": items}


@router.post("/api/v1/admin/feed/{post_id}/delete")
async def admin_feed_delete(post_id: str, request: Request):
    store: FeedStore = getattr(request.app.state, "feed_store", None)
    if store is None:
        raise HTTPException(status_code=500, detail="Feed store not available")
    post = store.get_post(post_id)
    if not post:
        raise HTTPException(status_code=404, detail="Post not found")
    if post.get("status") != "active":
        raise HTTPException(status_code=400, detail="Post is not active")
    try:
        move_post_assets_to_trash(
            active_image_url=post.get("image_url"),
            active_thumb_url=post.get("thumb_url"),
            input_image_url=post.get("input_image_url"),
            input_thumb_url=post.get("input_thumb_url"),
        )
        store.update_status(post_id, "trash")
        return {"ok": True}
    except Exception as e:
        logger.error({"event": "admin_feed_delete_failed", "post_id": post_id, "error": str(e)})
        raise HTTPException(status_code=500, detail="Failed to delete")


@router.post("/api/v1/admin/feed/{post_id}/restore")
async def admin_feed_restore(post_id: str, request: Request):
    store: FeedStore = getattr(request.app.state, "feed_store", None)
    if store is None:
        raise HTTPException(status_code=500, detail="Feed store not available")
    post = store.get_post(post_id)
    if not post:
        raise HTTPException(status_code=404, detail="Post not found")
    if post.get("status") != "trash":
        raise HTTPException(status_code=400, detail="Post is not in trash")
    try:
        restore_post_assets_from_trash(
            active_image_url=post.get("image_url"),
            active_thumb_url=post.get("thumb_url"),
            input_image_url=post.get("input_image_url"),
            input_thumb_url=post.get("input_thumb_url"),
        )
        store.update_status(post_id, "active")
        return {"ok": True}
    except Exception as e:
        logger.error({"event": "admin_feed_restore_failed", "post_id": post_id, "error": str(e)})
        raise HTTPException(status_code=500, detail="Failed to restore")


@router.post("/api/v1/admin/feed/{post_id}/purge")
async def admin_feed_purge(post_id: str, request: Request):
    store: FeedStore = getattr(request.app.state, "feed_store", None)
    if store is None:
        raise HTTPException(status_code=500, detail="Feed store not available")
    post = store.get_post(post_id)
    if not post:
        raise HTTPException(status_code=404, detail="Post not found")
    if post.get("status") != "trash":
        raise HTTPException(status_code=400, detail="Post is not in trash")
    try:
        purge_post_assets_from_trash(
            active_image_url=post.get("image_url"),
            active_thumb_url=post.get("thumb_url"),
            input_image_url=post.get("input_image_url"),
            input_thumb_url=post.get("input_thumb_url"),
        )
        store.delete_post_and_likes(post_id)
        return {"ok": True}
    except Exception as e:
        logger.error({"event": "admin_feed_purge_failed", "post_id": post_id, "error": str(e)})
        raise HTTPException(status_code=500, detail="Failed to purge")


