import time
import shutil
import sqlite3
import requests
from fastapi import APIRouter
from fastapi.responses import JSONResponse
from ..logging_utils import setup_logging
from ..config import SERVER_CONFIG, HEALTHZ_CONFIG, JOB_DB_PATH
import os


logger = setup_logging()
router = APIRouter(tags=["Health"])

OUTPUT_DIR = SERVER_CONFIG["output_dir"]
SERVER_ADDRESS = SERVER_CONFIG["server_address"]


@router.get("/healthz")
def healthz():
    results = {
        "comfyui": {"ok": False, "reason": None},
        "db": {"ok": False, "reason": None},
        "disk": {"ok": False, "reason": None},
        "llm": {"ok": False, "reason": None},
    }
    status_code = 200
    try:
        url = f"http://{SERVER_ADDRESS}/"
        resp = requests.get(url, timeout=(3.0, 5.0))
        results["comfyui"]["ok"] = (resp.status_code >= 200 and resp.status_code < 500)
        if not results["comfyui"]["ok"]:
            results["comfyui"]["reason"] = f"HTTP {resp.status_code}"
    except Exception as e:
        results["comfyui"]["reason"] = str(e)
        status_code = 503
    try:
        conn = sqlite3.connect(JOB_DB_PATH)
        conn.execute("CREATE TABLE IF NOT EXISTS __healthz (id INTEGER PRIMARY KEY AUTOINCREMENT, ts INTEGER)")
        conn.execute("INSERT INTO __healthz (ts) VALUES (?)", (int(time.time()),))
        conn.execute("DELETE FROM __healthz WHERE id IN (SELECT id FROM __healthz ORDER BY id DESC LIMIT 1 OFFSET 50)")
        conn.commit()
        conn.close()
        results["db"]["ok"] = True
    except Exception as e:
        results["db"]["reason"] = str(e)
        status_code = 503
    try:
        total, used, free = shutil.disk_usage(OUTPUT_DIR)
        free_mb = int(free / (1024 * 1024))
        min_mb = int(HEALTHZ_CONFIG.get("disk_min_free_mb", 512))
        results["disk"]["ok"] = (free_mb >= min_mb)
        if not results["disk"]["ok"]:
            results["disk"]["reason"] = f"free {free_mb}MB < min {min_mb}MB"
    except Exception as e:
        results["disk"]["reason"] = str(e)
        status_code = 503
    try:
        # Optional component: prompt translation (external Gemini API)
        api_key_present = bool(os.getenv("GOOGLE_AI_STUDIO_API_KEY") or os.getenv("GEMINI_API_KEY"))
        results["llm"]["ok"] = api_key_present
        if not api_key_present:
            results["llm"]["reason"] = "GOOGLE_AI_STUDIO_API_KEY not set"
    except Exception as e:
        results["llm"]["reason"] = str(e)
    overall_ok = results["comfyui"]["ok"] and results["db"]["ok"] and results["disk"]["ok"]
    payload = {"ok": overall_ok, "components": results}
    if not overall_ok and status_code == 200:
        status_code = 503
    return JSONResponse(content=payload, status_code=status_code)


