from typing import Optional
import os
import logging
import secrets
from fastapi import APIRouter, Request, HTTPException, Depends
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from fastapi.security import HTTPBasic, HTTPBasicCredentials

from ..config import SERVER_CONFIG, WORKFLOW_CONFIGS
from ..services.media_store import (
    _gather_user_images,
    _gather_user_inputs,
    _gather_user_audio,
    _update_image_status,
    _update_audio_status,
    _user_base_dir,
)
from pydantic import BaseModel

security = HTTPBasic()


def _admin_auth_enabled() -> bool:
    user = os.getenv("ADMIN_USER")
    pw = os.getenv("ADMIN_PASSWORD")
    return bool(user) and bool(pw)


def require_admin(credentials: HTTPBasicCredentials = Depends(security)) -> bool:
    """
    Protect admin endpoints with HTTP Basic auth.

    - Enabled when both ADMIN_USER and ADMIN_PASSWORD are set.
    - If not configured, admin routes remain open (for local/dev convenience),
      but you SHOULD set these in production/beta.
    """
    if not _admin_auth_enabled():
        return True
    expected_user = os.getenv("ADMIN_USER", "")
    expected_pw = os.getenv("ADMIN_PASSWORD", "")
    ok = secrets.compare_digest(credentials.username or "", expected_user) and secrets.compare_digest(
        credentials.password or "", expected_pw
    )
    if not ok:
        raise HTTPException(status_code=401, detail="Unauthorized", headers={"WWW-Authenticate": "Basic"})
    return True


router = APIRouter(dependencies=[Depends(require_admin)])
logger = logging.getLogger("comfyui_app")

templates = Jinja2Templates(directory="templates")

OUTPUT_DIR = SERVER_CONFIG["output_dir"]


class GenerationPolicyUpdate(BaseModel):
    generation_enabled: Optional[bool] = None
    mcp_enabled: Optional[bool] = None
    daily_request_limit: Optional[int] = None
    daily_cost_limit_usd: Optional[float] = None
    cost_confirmation_threshold_usd: Optional[float] = None
    confirmation_required_capabilities: Optional[list[str]] = None
    capability_enabled: Optional[dict[str, bool]] = None
    cost_estimates_usd: Optional[dict[str, float]] = None


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


def _purge_user_trash_images(user_id: str) -> int:
    """
    Permanently delete all trashed items (images + audio) for a given user.

    - A trashed item is defined as: meta JSON exists and meta.status != "active".
    - Deletes: <id>.png/.mp3/.wav/etc, thumb/<id>.webp, thumb/<id>.jpg, <id>.json
    """
    base = _user_base_dir(user_id)
    if not os.path.isdir(base):
        return 0
    deleted = 0
    _media_exts = (".png", ".mp3", ".wav", ".flac", ".ogg", ".m4a")
    for root, _, files in os.walk(base):
        for name in files:
            if not name.endswith(".json"):
                continue
            meta_path = os.path.join(root, name)
            try:
                import json

                with open(meta_path, "r", encoding="utf-8") as f:
                    meta = json.load(f)
                if meta.get("status") == "active":
                    continue
                item_id = os.path.splitext(name)[0]
                # Delete all possible media files for this item
                candidates = [meta_path]
                for ext in _media_exts:
                    candidates.append(os.path.join(root, f"{item_id}{ext}"))
                candidates.append(os.path.join(root, "thumb", f"{item_id}.webp"))
                candidates.append(os.path.join(root, "thumb", f"{item_id}.jpg"))
                for p in candidates:
                    try:
                        if os.path.exists(p):
                            os.remove(p)
                    except Exception:
                        pass
                deleted += 1
            except Exception:
                continue
    return deleted


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


def _generation_controls(request: Request):
    controls = getattr(request.app.state, "generation_controls", None)
    if controls is None:
        raise HTTPException(status_code=503, detail="Generation controls are not initialized")
    return controls


@router.get("/api/v1/admin/generation-controls/policy", tags=["Admin"])
async def admin_generation_policy(request: Request):
    controls = _generation_controls(request)
    return {"policy": controls.get_policy(), "timezone": controls.timezone_name}


@router.put("/api/v1/admin/generation-controls/policy", tags=["Admin"])
async def admin_update_generation_policy(request: Request, body: GenerationPolicyUpdate):
    controls = _generation_controls(request)
    changes = body.model_dump(exclude_unset=True, exclude_none=True)
    try:
        return {"ok": True, "policy": controls.update_policy(changes)}
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/api/v1/admin/generation-controls/summary", tags=["Admin"])
async def admin_generation_summary(request: Request, day: Optional[str] = None):
    controls = _generation_controls(request)
    try:
        return controls.summary(day)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid day: {exc}")


@router.get("/api/v1/admin/generation-controls/events", tags=["Admin"])
async def admin_generation_events(request: Request, limit: int = 100):
    controls = _generation_controls(request)
    return {"events": controls.recent_events(limit)}


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


@router.get("/api/v1/admin/audio", tags=["Admin"])
async def admin_audio(user_id: str, page: int = 1, size: int = 24, include: str = "all"):
    include_trash = True
    items = _gather_user_audio(user_id, include_trash=include_trash)
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
    from datetime import datetime, timezone
    for it in slice_items:
        response_items.append({
            "id": it["id"],
            "url": it["url"],
            "status": it.get("status"),
            "meta": it.get("meta"),
            "created_at": datetime.fromtimestamp(it["mtime"], tz=timezone.utc).isoformat(),
        })
    total_pages = max(1, (total + size - 1) // size)
    return {"items": response_items, "page": page, "size": size, "total": total, "total_pages": total_pages}


class AdminControlUpdateRequest(BaseModel):
    user_id: str


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


@router.post("/api/v1/admin/audio/{audio_id}/delete", tags=["Admin"])
async def admin_soft_delete_audio(audio_id: str, req: AdminUpdateRequest):
    ok = _update_audio_status(req.user_id, audio_id, "trash")
    if not ok:
        raise HTTPException(status_code=404, detail="Audio not found")
    return {"ok": True}


@router.post("/api/v1/admin/audio/{audio_id}/restore", tags=["Admin"])
async def admin_restore_audio(audio_id: str, req: AdminUpdateRequest):
    ok = _update_audio_status(req.user_id, audio_id, "active")
    if not ok:
        raise HTTPException(status_code=404, detail="Audio not found")
    return {"ok": True}


@router.post("/api/v1/admin/purge-trash", tags=["Admin"])
async def admin_purge_trash(req: AdminUpdateRequest):
    deleted = _purge_user_trash_images(req.user_id)
    return {"deleted": deleted}


@router.post("/api/v1/admin/purge-trash-all", tags=["Admin"])
async def admin_purge_trash_all():
    """
    Permanently delete all trashed images across ALL users.
    Intended for ops/admin housekeeping.
    """
    users = _list_user_ids()
    total_deleted = 0
    users_with_deletions = 0
    per_user: dict[str, int] = {}
    for u in users:
        try:
            n = _purge_user_trash_images(u)
            if n > 0:
                per_user[u] = n
                total_deleted += n
                users_with_deletions += 1
        except Exception:
            continue
    return {
        "deleted": total_deleted,
        "users_scanned": len(users),
        "users_with_deletions": users_with_deletions,
        "per_user": per_user,
    }


@router.get("/api/v1/admin/usage", tags=["Admin"])
async def admin_usage(request: Request, days: int = 30):
    """
    Simple ops analytics:
    - Daily total generate calls
    - Daily top workflows
    - Overall top workflows for the selected window

    Notes:
    - Grouping uses server-local day boundary (SQLite 'localtime').
    - Older rows (before workflow_id/payload was stored) may appear as "(unknown)".
    """
    try:
        days_i = int(days)
    except Exception:
        days_i = 30
    days_i = max(1, min(365, days_i))

    job_store = getattr(request.app.state, "job_store", None)
    db_path = getattr(job_store, "db_path", None) if job_store else None
    if not isinstance(db_path, str) or not db_path:
        return {"days": [], "top_workflows": [], "total": 0, "days_requested": days_i}

    import sqlite3
    import time as _t

    cutoff = float(_t.time()) - (days_i * 86400.0)

    def wf_label(wf_id: str | None) -> str:
        try:
            s = str(wf_id or "").strip()
        except Exception:
            s = ""
        if not s:
            return "(unknown)"
        try:
            cfg = WORKFLOW_CONFIGS.get(s) if isinstance(WORKFLOW_CONFIGS, dict) else None
            dn = (cfg or {}).get("display_name") if isinstance(cfg, dict) else None
            return str(dn or s)
        except Exception:
            return s

    with sqlite3.connect(db_path) as con:
        # Daily totals
        q_daily = """
        SELECT
          strftime('%Y-%m-%d', created_at, 'unixepoch', 'localtime') AS day,
          COUNT(*) AS total,
          COUNT(DISTINCT owner_id) AS users,
          SUM(CASE WHEN status = 'complete' THEN 1 ELSE 0 END) AS complete,
          SUM(CASE WHEN status = 'error' THEN 1 ELSE 0 END) AS error,
          SUM(CASE WHEN status = 'cancelled' THEN 1 ELSE 0 END) AS cancelled,
          SUM(CASE WHEN json_extract(result_json, '$.provider_error.kind') IN ('nanobanana_quota_exhausted', 'openrouter_credits_exhausted') THEN 1 ELSE 0 END) AS nanobanana_quota_exhausted,
          SUM(CASE WHEN json_extract(result_json, '$.provider_error.kind') IN ('nanobanana_rate_limited', 'openrouter_rate_limited') THEN 1 ELSE 0 END) AS nanobanana_rate_limited
        FROM jobs
        WHERE type = 'generate' AND created_at IS NOT NULL AND created_at >= ?
        GROUP BY day
        ORDER BY day DESC
        """
        q_daily_fallback = """
        SELECT
          strftime('%Y-%m-%d', created_at, 'unixepoch', 'localtime') AS day,
          COUNT(*) AS total,
          COUNT(DISTINCT owner_id) AS users,
          SUM(CASE WHEN status = 'complete' THEN 1 ELSE 0 END) AS complete,
          SUM(CASE WHEN status = 'error' THEN 1 ELSE 0 END) AS error,
          SUM(CASE WHEN status = 'cancelled' THEN 1 ELSE 0 END) AS cancelled,
          0 AS nanobanana_quota_exhausted,
          0 AS nanobanana_rate_limited
        FROM jobs
        WHERE type = 'generate' AND created_at IS NOT NULL AND created_at >= ?
        GROUP BY day
        ORDER BY day DESC
        """
        try:
            cur = con.execute(q_daily, (cutoff,))
        except Exception:
            # Some environments may not have SQLite JSON1 enabled; keep endpoint functional.
            cur = con.execute(q_daily_fallback, (cutoff,))
        daily_rows = cur.fetchall() or []

        # Per-day, per-workflow counts
        cur2 = con.execute(
            """
            SELECT
              strftime('%Y-%m-%d', created_at, 'unixepoch', 'localtime') AS day,
              COALESCE(workflow_id, '(unknown)') AS workflow_id,
              COUNT(*) AS cnt
            FROM jobs
            WHERE type = 'generate' AND created_at IS NOT NULL AND created_at >= ?
            GROUP BY day, workflow_id
            ORDER BY day DESC, cnt DESC
            """,
            (cutoff,),
        )
        wf_rows = cur2.fetchall() or []

        # Overall top workflows
        cur3 = con.execute(
            """
            SELECT
              COALESCE(workflow_id, '(unknown)') AS workflow_id,
              COUNT(*) AS cnt
            FROM jobs
            WHERE type = 'generate' AND created_at IS NOT NULL AND created_at >= ?
            GROUP BY workflow_id
            ORDER BY cnt DESC
            LIMIT 50
            """,
            (cutoff,),
        )
        top_rows = cur3.fetchall() or []

    by_day: dict[str, list[dict]] = {}
    for day, wf_id, cnt in wf_rows:
        d = str(day or "")
        if not d:
            continue
        by_day.setdefault(d, []).append(
            {"workflow_id": wf_id, "workflow_name": wf_label(wf_id), "count": int(cnt or 0)}
        )

    days_out: list[dict] = []
    total_all = 0
    nb_quota_exhausted_total = 0
    nb_rate_limited_total = 0
    for day, total, users, complete, error, cancelled, nb_quota_exhausted, nb_rate_limited in daily_rows:
        d = str(day or "")
        if not d:
            continue
        t = int(total or 0)
        total_all += t
        nb_q = int(nb_quota_exhausted or 0)
        nb_r = int(nb_rate_limited or 0)
        nb_quota_exhausted_total += nb_q
        nb_rate_limited_total += nb_r
        wf_list = by_day.get(d, [])
        top_wf = wf_list[0] if wf_list else None
        days_out.append(
            {
                "day": d,
                "total": t,
                "users": int(users or 0),
                "complete": int(complete or 0),
                "error": int(error or 0),
                "cancelled": int(cancelled or 0),
                # Nano Banana/OpenRouter credit and rate-limit errors (legacy field names retained for UI compatibility)
                "nanobanana_quota_exhausted": nb_q,
                "nanobanana_rate_limited": nb_r,
                "nanobanana_quota": nb_q + nb_r,
                "top_workflow": top_wf,
                # Keep a cap for UI readability, but provide enough detail for ranking.
                "workflows": wf_list[:50],
            }
        )

    top_out: list[dict] = []
    for wf_id, cnt in top_rows:
        top_out.append(
            {
                "workflow_id": wf_id,
                "workflow_name": wf_label(wf_id),
                "count": int(cnt or 0),
            }
        )

    return {
        "days_requested": days_i,
        "total": total_all,
        "nanobanana_quota_exhausted_total": nb_quota_exhausted_total,
        "nanobanana_rate_limited_total": nb_rate_limited_total,
        "nanobanana_quota_total": nb_quota_exhausted_total + nb_rate_limited_total,
        "days": days_out,
        "top_workflows": top_out,
    }
