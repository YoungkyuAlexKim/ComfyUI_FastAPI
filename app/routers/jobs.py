from fastapi import APIRouter, Request


router = APIRouter(tags=["Jobs"])


def _compute_recent_averages_from_rows(rows: list[dict]) -> dict:
    """
    Compute rolling average durations overall and per workflow_id from job dict rows.
    Expected keys: status, started_at, ended_at, result(optional), payload(optional).
    """
    completed: list[dict] = []
    for j in rows:
        try:
            if not isinstance(j, dict):
                continue
            if j.get("status") != "complete":
                continue
            sa = j.get("started_at")
            ea = j.get("ended_at")
            if not isinstance(sa, (int, float)) or not isinstance(ea, (int, float)):
                continue
            completed.append(j)
        except Exception:
            continue

    if not completed:
        return {"overall_avg_sec": None, "per_workflow_avg_sec": {}, "count": 0}

    durations: list[float] = []
    per: dict[str, list[float]] = {}
    for j in completed:
        try:
            sa = float(j["started_at"])
            ea = float(j["ended_at"])
            d = max(0.0, ea - sa)
            durations.append(d)
            wf = None
            payload = j.get("payload")
            if isinstance(payload, dict):
                wf = payload.get("workflow_id")
            if isinstance(wf, str) and wf:
                per.setdefault(wf, []).append(d)
        except Exception:
            continue

    overall = (sum(durations) / len(durations)) if durations else None
    per_avg = {wf: (sum(vals) / len(vals)) for wf, vals in per.items() if vals}
    return {"overall_avg_sec": overall, "per_workflow_avg_sec": per_avg, "count": len(durations)}


@router.get("/api/v1/jobs/metrics")
async def jobs_metrics(request: Request, limit: int = 50):
    """
    Public-safe endpoint for frontend ETA estimates.
    Returns only aggregate timing stats; no user ids, no job ids, no file paths.
    """
    limit = max(1, min(500, int(limit)))
    job_store = getattr(request.app.state, "job_store", None)
    job_manager = getattr(request.app.state, "job_manager", None)

    # Prefer persisted jobs if available
    if job_store is not None:
        try:
            rows = job_store.fetch_recent(limit=limit) or []
            # job_store rows don't include payload; best-effort overall avg only
            # For compatibility, we still return the same schema.
            # If payload isn't present, per_workflow_avg_sec will be empty.
            return _compute_recent_averages_from_rows(rows)
        except Exception:
            pass

    # Fallback to in-memory job manager
    if job_manager is not None:
        try:
            return job_manager.get_recent_averages(limit=limit)
        except Exception:
            pass

    return {"overall_avg_sec": None, "per_workflow_avg_sec": {}, "count": 0}


