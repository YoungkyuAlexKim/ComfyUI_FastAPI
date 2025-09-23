from typing import Optional
import os
import logging
from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from ..config import SERVER_CONFIG
from ..services.media_store import (
    _gather_user_images,
    _gather_user_controls,
    _gather_user_inputs,
    _update_image_status,
    _update_control_status,
    _user_base_dir,
)
from pydantic import BaseModel

router = APIRouter()
logger = logging.getLogger("comfyui_app")

templates = Jinja2Templates(directory="templates")

OUTPUT_DIR = SERVER_CONFIG["output_dir"]


@router.get("/admin", response_class=HTMLResponse, tags=["Admin"])
async def admin_page(request: Request):
    return templates.TemplateResponse("admin.html", {"request": request})


def _list_user_ids() -> list[str]:
    users_root = os.path.join(OUTPUT_DIR, "users")
    if not os.path.isdir(users_root):
        return []
    entries: list[str] = []
    for name in os.listdir(users_root):
        full = os.path.join(users_root, name)
        if os.path.isdir(full):
            entries.append(name)
    return sorted(entries)


@router.get("/api/v1/admin/users", tags=["Admin"])
async def admin_users(page: int = 1, size: int = 50, q: Optional[str] = None):
    users = _list_user_ids()
    if q and isinstance(q, str):
        ql = q.lower()
        users = [u for u in users if ql in u.lower()]
    size = max(1, min(200, size))
    page = max(1, page)
    total = len(users)
    start = (page - 1) * size
    end = start + size
    slice_users = users[start:end]
    total_pages = (total + size - 1) // size
    return {"users": slice_users, "page": page, "size": size, "total": total, "total_pages": total_pages}


@router.get("/api/v1/admin/jobs", tags=["Admin"])
async def admin_jobs(request: Request, limit: int = 100):
    try:
        job_store = getattr(request.app.state, "job_store", None)
        job_manager = getattr(request.app.state, "job_manager", None)
        jobs = job_store.fetch_recent(limit=limit) if job_store else []
        if not jobs and job_manager:
            jobs = job_manager.list_jobs(limit=limit)
        if jobs and 'artifact_available' not in jobs[0]:
            def artifact_exists(web_path: str) -> bool:
                try:
                    if not isinstance(web_path, str) or not web_path:
                        return False
                    p = web_path
                    if p.startswith('/outputs/'):
                        rel = p[len('/outputs/') : ]
                    elif p.startswith('outputs/'):
                        rel = p[len('outputs/') : ]
                    else:
                        return False
                    fs_path = os.path.join(OUTPUT_DIR, rel)
                    return os.path.exists(fs_path)
                except Exception:
                    return False
            for j in jobs:
                res = j.get('result') if isinstance(j, dict) else None
                img = res.get('image_path') if isinstance(res, dict) else None
                j['artifact_available'] = artifact_exists(img)
        return {"jobs": jobs}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/v1/admin/jobs/metrics", tags=["Admin"])
async def admin_jobs_metrics(request: Request, limit: int = 100):
    try:
        job_manager = getattr(request.app.state, "job_manager", None)
        avg = job_manager.get_recent_averages(limit=limit) if job_manager else {"overall_avg_sec": None, "per_workflow_avg_sec": {}, "count": 0}
        return avg
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/v1/admin/jobs/sweep", tags=["Admin"])
async def admin_jobs_sweep(request: Request, limit: int = 200):
    try:
        limit = max(1, min(5000, int(limit)))
        job_store = getattr(request.app.state, "job_store", None)
        if not job_store:
            return {"updated": 0}
        jobs = job_store.fetch_recent(limit=limit)
        updated = 0
        for j in jobs:
            try:
                res = j.get('result') if isinstance(j, dict) else None
                img = res.get('image_path') if isinstance(res, dict) else None
                avail = False
                if isinstance(img, str) and img:
                    p = img
                    if p.startswith('/outputs/'):
                        rel = p[len('/outputs/'):] 
                    elif p.startswith('outputs/'):
                        rel = p[len('outputs/'):] 
                    else:
                        rel = None
                    if rel:
                        fs_path = os.path.join(OUTPUT_DIR, rel)
                        avail = os.path.exists(fs_path)
                j['artifact_available'] = avail
                job_store.upsert_job(j)
                updated += 1
            except Exception:
                continue
        return {"updated": updated}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/v1/admin/images", tags=["Admin"])
async def admin_images(user_id: str, page: int = 1, size: int = 24, include: str = "all", from_date: Optional[str] = None, to_date: Optional[str] = None):
    include_trash = True
    items = _gather_user_images(user_id, include_trash=include_trash)
    if include == "active":
        items = [it for it in items if it.get("status") == "active"]
    elif include == "trash":
        items = [it for it in items if it.get("status") != "active"]

    def parse_iso(s: str) -> Optional[float]:
        try:
            return datetime.fromisoformat(s.replace('Z','+00:00')).timestamp()
        except Exception:
            try:
                d = datetime.fromisoformat(s)
                return d.timestamp()
            except Exception:
                return None

    if from_date:
        ts = parse_iso(from_date)
        if ts is not None:
            items = [it for it in items if it.get("mtime", 0) >= ts]
    if to_date:
        ts = parse_iso(to_date)
        if ts is not None:
            items = [it for it in items if it.get("mtime", 0) <= ts]

    size = max(1, min(100, size))
    page = max(1, page)
    start = (page - 1) * size
    end = start + size
    total = len(items)
    slice_items = items[start:end]
    response_items = []
    from datetime import datetime, timezone  # local import to avoid heavy global deps
    for it in slice_items:
        response_items.append({
            "id": it["id"],
            "url": it["url"],
            "thumb_url": it.get("thumb_url"),
            "status": it.get("status"),
            "created_at": datetime.fromtimestamp(it["mtime"], tz=timezone.utc).isoformat(),
        })
    total_pages = (total + size - 1) // size
    return {
        "items": response_items,
        "page": page,
        "size": size,
        "total": total,
        "total_pages": total_pages
    }


@router.get("/api/v1/admin/controls", tags=["Admin"])
async def admin_controls(user_id: str, page: int = 1, size: int = 24, include: str = "all"):
    include_trash = True
    items = _gather_user_controls(user_id, include_trash=include_trash)
    if include == "active":
        items = [it for it in items if it.get("status") == "active"]
    elif include == "trash":
        items = [it for it in items if it.get("status") != "active"]

    size = max(1, min(100, size))
    page = max(1, page)
    start = (page - 1) * size
    end = start + size
    total = len(items)
    slice_items = items[start:end]
    response_items = []
    from datetime import datetime, timezone  # local import
    for it in slice_items:
        response_items.append({
            "id": it["id"],
            "url": it["url"],
            "thumb_url": it.get("thumb_url"),
            "status": it.get("status"),
            "created_at": datetime.fromtimestamp(it["mtime"], tz=timezone.utc).isoformat(),
        })
    total_pages = (total + size - 1) // size
    return {"items": response_items, "page": page, "size": size, "total": total, "total_pages": total_pages}


@router.get("/api/v1/admin/inputs", tags=["Admin"])
async def admin_inputs(user_id: str, page: int = 1, size: int = 24, include: str = "all"):
    include_trash = True
    items = _gather_user_inputs(user_id, include_trash=include_trash)
    if include == "active":
        items = [it for it in items if it.get("status") == "active"]
    elif include == "trash":
        items = [it for it in items if it.get("status") != "active"]

    size = max(1, min(100, size))
    page = max(1, page)
    start = (page - 1) * size
    end = start + size
    total = len(items)
    slice_items = items[start:end]
    response_items = []
    from datetime import datetime, timezone  # local import
    for it in slice_items:
        response_items.append({
            "id": it["id"],
            "url": it["url"],
            "thumb_url": it.get("thumb_url"),
            "status": it.get("status"),
            "created_at": datetime.fromtimestamp(it["mtime"], tz=timezone.utc).isoformat(),
        })
    total_pages = (total + size - 1) // size
    return {"items": response_items, "page": page, "size": size, "total": total, "total_pages": total_pages}


class AdminControlUpdateRequest(BaseModel):
    user_id: str


@router.post("/api/v1/admin/controls/{image_id}/delete", tags=["Admin"])
async def admin_control_soft_delete(image_id: str, req: AdminControlUpdateRequest):
    ok = _update_control_status(req.user_id, image_id, "trash")
    if not ok:
        raise HTTPException(status_code=404, detail="Control not found")
    return {"ok": True}


@router.post("/api/v1/admin/controls/{image_id}/restore", tags=["Admin"])
async def admin_control_restore(image_id: str, req: AdminControlUpdateRequest):
    ok = _update_control_status(req.user_id, image_id, "active")
    if not ok:
        raise HTTPException(status_code=404, detail="Control not found")
    return {"ok": True}


@router.post("/api/v1/admin/purge-controls", tags=["Admin"])
async def admin_purge_controls(req: AdminControlUpdateRequest):
    base = _user_base_dir(req.user_id)
    base = os.path.join(base, "controls")
    if not os.path.isdir(base):
        return {"deleted": 0}
    deleted = 0
    for root, _, files in os.walk(base):
        for name in files:
            if not name.endswith('.json'):
                continue
            meta_path = os.path.join(root, name)
            try:
                import json
                with open(meta_path, 'r', encoding='utf-8') as f:
                    meta = json.load(f)
                if meta.get('status') == 'active':
                    continue
                image_id = os.path.splitext(name)[0]
                png_path = os.path.join(root, f"{image_id}.png")
                t_webp = os.path.join(root, 'thumb', f"{image_id}.webp")
                t_jpg = os.path.join(root, 'thumb', f"{image_id}.jpg")
                for p in [png_path, t_webp, t_jpg, meta_path]:
                    try:
                        if os.path.exists(p):
                            os.remove(p)
                    except Exception:
                        pass
                deleted += 1
            except Exception:
                continue
    return {"deleted": deleted}


class AdminUpdateRequest(BaseModel):
    user_id: str


@router.post("/api/v1/admin/images/{image_id}/delete", tags=["Admin"])
async def admin_soft_delete(image_id: str, req: AdminUpdateRequest):
    ok = _update_image_status(req.user_id, image_id, "trash")
    if not ok:
        raise HTTPException(status_code=404, detail="Image not found")
    return {"ok": True}


@router.post("/api/v1/admin/images/{image_id}/restore", tags=["Admin"])
async def admin_restore(image_id: str, req: AdminUpdateRequest):
    ok = _update_image_status(req.user_id, image_id, "active")
    if not ok:
        raise HTTPException(status_code=404, detail="Image not found")
    return {"ok": True}


@router.post("/api/v1/admin/purge-trash", tags=["Admin"])
async def admin_purge_trash(req: AdminUpdateRequest):
    base = _user_base_dir(req.user_id)
    if not os.path.isdir(base):
        return {"deleted": 0}
    deleted = 0
    for root, _, files in os.walk(base):
        for name in files:
            if not name.endswith('.json'):
                continue
            meta_path = os.path.join(root, name)
            try:
                import json
                with open(meta_path, 'r', encoding='utf-8') as f:
                    meta = json.load(f)
                if meta.get('status') == 'active':
                    continue
                image_id = os.path.splitext(name)[0]
                png_path = os.path.join(root, f"{image_id}.png")
                t_webp = os.path.join(root, 'thumb', f"{image_id}.webp")
                t_jpg = os.path.join(root, 'thumb', f"{image_id}.jpg")
                for p in [png_path, t_webp, t_jpg, meta_path]:
                    try:
                        if os.path.exists(p):
                            os.remove(p)
                    except Exception:
                        pass
                deleted += 1
            except Exception:
                continue
    return {"deleted": deleted}
