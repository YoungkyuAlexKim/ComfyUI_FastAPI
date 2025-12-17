import base64
import os
import secrets
from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from ..auth.user_management import _get_anon_id_from_request
from ..feed_store import FeedStore
from ..logging_utils import setup_logging
from ..services.feed_media_store import publish_to_feed, move_post_assets_to_trash
from ..services.media_store import _locate_image_meta_path, _locate_input_png_path


logger = setup_logging()
router = APIRouter(tags=["Feed"])


def _admin_auth_enabled() -> bool:
    user = os.getenv("ADMIN_USER")
    pw = os.getenv("ADMIN_PASSWORD")
    return bool(user) and bool(pw)


def _is_admin_request(request: Request) -> bool:
    if not _admin_auth_enabled():
        return False
    try:
        auth = request.headers.get("Authorization") or ""
        if not auth.lower().startswith("basic "):
            return False
        raw = auth.split(" ", 1)[1].strip()
        decoded = base64.b64decode(raw).decode("utf-8", errors="ignore")
        if ":" not in decoded:
            return False
        username, password = decoded.split(":", 1)
        expected_user = os.getenv("ADMIN_USER", "")
        expected_pw = os.getenv("ADMIN_PASSWORD", "")
        return secrets.compare_digest(username or "", expected_user) and secrets.compare_digest(password or "", expected_pw)
    except Exception:
        return False


def _mask_owner(owner_id: str) -> str:
    try:
        s = str(owner_id or "")
        if s.startswith("anon-"):
            s = s[len("anon-") :]
        tail = s[-4:] if len(s) >= 4 else s
        return f"익명-{tail or 'user'}"
    except Exception:
        return "익명"


def _sanitize_author_name(name: Optional[str]) -> Optional[str]:
    if not isinstance(name, str):
        return None
    n = " ".join(name.replace("\n", " ").replace("\r", " ").split()).strip()
    if not n:
        return None
    return n[:20]


class FeedPublishRequest(BaseModel):
    image_id: str
    author_name: Optional[str] = None


class FeedReactionRequest(BaseModel):
    reaction: str


@router.post("/api/v1/feed/publish")
async def feed_publish(req: FeedPublishRequest, request: Request):
    anon_id = _get_anon_id_from_request(request)
    image_id = (req.image_id or "").strip()
    if not image_id:
        raise HTTPException(status_code=400, detail="Missing image_id")

    meta_path = _locate_image_meta_path(anon_id, image_id)
    if not meta_path or not os.path.exists(meta_path):
        raise HTTPException(status_code=404, detail="Source image not found")

    try:
        import json

        with open(meta_path, "r", encoding="utf-8") as f:
            meta = json.load(f)
    except Exception:
        raise HTTPException(status_code=500, detail="Failed to read source meta")

    status = meta.get("status") if isinstance(meta, dict) else None
    if status and status != "active":
        raise HTTPException(status_code=400, detail="Source image is not active")
    if isinstance(meta, dict) and meta.get("kind") in ("control", "input"):
        raise HTTPException(status_code=400, detail="Unsupported source kind")

    base_dir = os.path.dirname(meta_path)
    src_png = os.path.join(base_dir, f"{image_id}.png")
    if not os.path.exists(src_png):
        raise HTTPException(status_code=404, detail="Source PNG not found")

    input_source_id = None
    input_png = None
    try:
        input_source_id = meta.get("input_image_id") if isinstance(meta, dict) else None
        if isinstance(input_source_id, str) and input_source_id:
            input_png = _locate_input_png_path(anon_id, input_source_id)
            if not input_png or not os.path.exists(input_png):
                input_png = None
    except Exception:
        input_source_id = None
        input_png = None

    author_name = _sanitize_author_name(req.author_name)

    try:
        feed_meta = publish_to_feed(
            owner_id=anon_id,
            author_name=author_name,
            prompt=(meta.get("prompt") if isinstance(meta, dict) else "") or "",
            workflow_id=(meta.get("workflow_id") if isinstance(meta, dict) else None),
            seed=(meta.get("seed") if isinstance(meta, dict) else None),
            aspect_ratio=(meta.get("aspect_ratio") if isinstance(meta, dict) else None),
            source_image_id=image_id,
            source_png_fs=src_png,
            input_source_image_id=input_source_id,
            input_png_fs=input_png,
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error({"event": "feed_publish_failed", "owner_id": anon_id, "image_id": image_id, "error": str(e)})
        raise HTTPException(status_code=500, detail="Failed to publish")

    store: FeedStore = getattr(request.app.state, "feed_store", None)
    if store is None:
        raise HTTPException(status_code=500, detail="Feed store not available")
    try:
        store.create_post(feed_meta)
    except Exception as e:
        logger.error({"event": "feed_db_insert_failed", "post_id": feed_meta.get("post_id"), "error": str(e)})
        raise HTTPException(status_code=500, detail="Failed to persist feed post")

    return {
        "ok": True,
        "post_id": feed_meta.get("post_id"),
        "image_url": feed_meta.get("image_url"),
        "thumb_url": feed_meta.get("thumb_url"),
        "input_image_url": feed_meta.get("input_image_url"),
        "input_thumb_url": feed_meta.get("input_thumb_url"),
    }


@router.get("/api/v1/feed")
async def feed_list(request: Request, page: int = 1, size: int = 24, sort: str = "newest"):
    anon_id = _get_anon_id_from_request(request)
    store: FeedStore = getattr(request.app.state, "feed_store", None)
    if store is None:
        raise HTTPException(status_code=500, detail="Feed store not available")
    sort_key = (sort or "newest").strip().lower()
    if sort_key not in ("newest", "oldest", "most_reactions"):
        raise HTTPException(status_code=400, detail="invalid_sort")
    data = store.list_posts(include="active", page=page, size=size, sort=sort_key)
    items_out = []
    for it in data.get("items", []):
        like = store.get_like_info(it["post_id"], anon_id)
        react = store.get_reaction_info(it["post_id"], anon_id)
        author_display = it.get("author_name") or _mask_owner(it.get("owner_id"))
        items_out.append(
            {
                "post_id": it["post_id"],
                "image_url": it["image_url"],
                "thumb_url": it.get("thumb_url"),
                "input_thumb_url": it.get("input_thumb_url"),
                "author_name": it.get("author_name"),
                "author_display": author_display,
                "workflow_id": it.get("workflow_id"),
                "published_at": it.get("published_at"),
                "like_count": like.get("like_count", 0),
                "liked_by_me": like.get("liked_by_me", False),
                "reactions": react.get("reactions"),
                "my_reaction": react.get("my_reaction"),
                "has_input": bool(it.get("input_image_url")),
            }
        )
    return {**data, "items": items_out}


@router.get("/api/v1/feed/{post_id}")
async def feed_detail(post_id: str, request: Request):
    anon_id = _get_anon_id_from_request(request)
    store: FeedStore = getattr(request.app.state, "feed_store", None)
    if store is None:
        raise HTTPException(status_code=500, detail="Feed store not available")
    post = store.get_post(post_id)
    if not post:
        raise HTTPException(status_code=404, detail="Post not found")
    if post.get("status") != "active":
        raise HTTPException(status_code=404, detail="Post not found")
    like = store.get_like_info(post_id, anon_id)
    react = store.get_reaction_info(post_id, anon_id)
    can_delete = (post.get("owner_id") == anon_id) or _is_admin_request(request)
    author_display = post.get("author_name") or _mask_owner(post.get("owner_id"))
    return {
        "post_id": post.get("post_id"),
        "image_url": post.get("image_url"),
        "thumb_url": post.get("thumb_url"),
        "input_image_url": post.get("input_image_url"),
        "input_thumb_url": post.get("input_thumb_url"),
        "author_name": post.get("author_name"),
        "author_display": author_display,
        "owner_id": post.get("owner_id"),
        "workflow_id": post.get("workflow_id"),
        "seed": post.get("seed"),
        "aspect_ratio": post.get("aspect_ratio"),
        "prompt": post.get("prompt"),
        "published_at": post.get("published_at"),
        "like_count": like.get("like_count", 0),
        "liked_by_me": like.get("liked_by_me", False),
        "reactions": react.get("reactions"),
        "my_reaction": react.get("my_reaction"),
        "can_delete": bool(can_delete),
    }


@router.post("/api/v1/feed/{post_id}/like")
async def feed_like_toggle(post_id: str, request: Request):
    anon_id = _get_anon_id_from_request(request)
    store: FeedStore = getattr(request.app.state, "feed_store", None)
    if store is None:
        raise HTTPException(status_code=500, detail="Feed store not available")
    post = store.get_post(post_id)
    if not post or post.get("status") != "active":
        raise HTTPException(status_code=404, detail="Post not found")
    return store.like_toggle(post_id, anon_id)


@router.post("/api/v1/feed/{post_id}/reaction")
async def feed_reaction_set(post_id: str, req: FeedReactionRequest, request: Request):
    anon_id = _get_anon_id_from_request(request)
    store: FeedStore = getattr(request.app.state, "feed_store", None)
    if store is None:
        raise HTTPException(status_code=500, detail="Feed store not available")
    post = store.get_post(post_id)
    if not post or post.get("status") != "active":
        raise HTTPException(status_code=404, detail="Post not found")
    try:
        return store.reaction_set(post_id, anon_id, req.reaction)
    except ValueError:
        raise HTTPException(status_code=400, detail="invalid_reaction")


@router.post("/api/v1/feed/{post_id}/delete")
async def feed_delete(post_id: str, request: Request):
    anon_id = _get_anon_id_from_request(request)
    store: FeedStore = getattr(request.app.state, "feed_store", None)
    if store is None:
        raise HTTPException(status_code=500, detail="Feed store not available")
    post = store.get_post(post_id)
    if not post:
        raise HTTPException(status_code=404, detail="Post not found")
    if post.get("status") != "active":
        raise HTTPException(status_code=400, detail="Post is not active")

    can_delete = (post.get("owner_id") == anon_id) or _is_admin_request(request)
    if not can_delete:
        raise HTTPException(status_code=403, detail="Forbidden")

    try:
        move_post_assets_to_trash(
            active_image_url=post.get("image_url"),
            active_thumb_url=post.get("thumb_url"),
            input_image_url=post.get("input_image_url"),
            input_thumb_url=post.get("input_thumb_url"),
        )
        store.update_status(post_id, "trash")
    except Exception as e:
        logger.error({"event": "feed_delete_failed", "post_id": post_id, "error": str(e)})
        raise HTTPException(status_code=500, detail="Failed to delete")

    return {"ok": True}


