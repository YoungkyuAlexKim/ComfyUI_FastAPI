import os
import json
import hashlib
from datetime import datetime, timezone
from io import BytesIO
from typing import Optional, List, Tuple
import uuid

try:
    from PIL import Image
except Exception:
    Image = None

from ..config import SERVER_CONFIG

# Reuse output directory from server config
OUTPUT_DIR = SERVER_CONFIG["output_dir"]


# --- Paths and saving helpers ---

def _user_base_dir(anon_id: str) -> str:
    return os.path.join(OUTPUT_DIR, "users", anon_id)


def _date_partition_path(base_dir: str, dt: datetime) -> str:
    return os.path.join(base_dir, dt.strftime("%Y"), dt.strftime("%m"), dt.strftime("%d"))


def _build_web_path(abs_path: str) -> str:
    # Assumes OUTPUT_DIR is served at /outputs
    abs_outputs = os.path.abspath(OUTPUT_DIR)
    abs_target = os.path.abspath(abs_path)
    rel = os.path.relpath(abs_target, abs_outputs).replace("\\", "/")
    return f"/outputs/{rel}"


def _save_image_and_meta(anon_id: str, image_bytes: bytes, req, original_filename: str) -> Tuple[str, str]:
    now = datetime.now(timezone.utc)
    user_dir = _user_base_dir(anon_id)
    dated_dir = _date_partition_path(user_dir, now)
    os.makedirs(dated_dir, exist_ok=True)

    image_id = uuid.uuid4().hex
    image_filename = f"{image_id}.png"
    image_path = os.path.join(dated_dir, image_filename)

    with open(image_path, "wb") as f:
        f.write(image_bytes)

    # Thumbnail (webp preferred; fallback to jpg)
    thumb_rel_dir = os.path.join(dated_dir, "thumb")
    os.makedirs(thumb_rel_dir, exist_ok=True)
    thumb_webp_path = os.path.join(thumb_rel_dir, f"{image_id}.webp")
    thumb_jpg_path = os.path.join(thumb_rel_dir, f"{image_id}.jpg")
    thumb_path_written = None
    if Image is not None:
        try:
            with Image.open(BytesIO(image_bytes)) as im:
                im = im.convert("RGB")
                # Resize keeping aspect ratio: short side 384px
                max_side = 384
                im.thumbnail((max_side, max_side))
                try:
                    im.save(thumb_webp_path, format="WEBP", quality=80, method=6)
                    thumb_path_written = thumb_webp_path
                except Exception:
                    im.save(thumb_jpg_path, format="JPEG", quality=80)
                    thumb_path_written = thumb_jpg_path
        except Exception:
            thumb_path_written = None

    # Sidecar metadata
    sha256 = hashlib.sha256(image_bytes).hexdigest()
    meta = {
        "id": image_id,
        "owner": anon_id,
        "workflow_id": getattr(req, "workflow_id", None),
        "aspect_ratio": getattr(req, "aspect_ratio", None),
        "seed": getattr(req, "seed", None),
        "prompt": getattr(req, "user_prompt", None),
        # Img2Img: 입력 이미지(보관함) id를 기록해두면, 이후 공유/재현에 도움이 됩니다.
        "input_image_id": getattr(req, "input_image_id", None),
        "original_filename": original_filename,
        "mime": "image/png",
        "bytes": len(image_bytes),
        "sha256": sha256,
        "created_at": now.isoformat(),
        "status": "active",
        "thumb": _build_web_path(thumb_path_written) if thumb_path_written else None,
        "tags": [],
    }
    meta_path = os.path.join(dated_dir, f"{image_id}.json")
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)

    return image_path, meta_path


def _control_base_dir(anon_id: str) -> str:
    return os.path.join(_user_base_dir(anon_id), "controls")


def _input_base_dir(anon_id: str) -> str:
    return os.path.join(_user_base_dir(anon_id), "inputs")


def _locate_input_png_path(anon_id: str, image_id: str) -> Optional[str]:
    base = _input_base_dir(anon_id)
    if not os.path.isdir(base):
        return None
    target = f"{image_id}.png"
    for root, _, files in os.walk(base):
        if target in files:
            return os.path.join(root, target)
    return None


def _save_input_image_and_meta(anon_id: str, image_bytes: bytes, original_filename: str) -> Tuple[str, str]:
    now = datetime.now(timezone.utc)
    base_dir = _input_base_dir(anon_id)
    dated_dir = _date_partition_path(base_dir, now)
    os.makedirs(dated_dir, exist_ok=True)

    input_id = uuid.uuid4().hex
    filename = f"{input_id}.png"
    image_path = os.path.join(dated_dir, filename)

    with open(image_path, "wb") as f:
        f.write(image_bytes)

    # Thumbnail
    thumb_rel_dir = os.path.join(dated_dir, "thumb")
    os.makedirs(thumb_rel_dir, exist_ok=True)
    thumb_webp_path = os.path.join(thumb_rel_dir, f"{input_id}.webp")
    thumb_jpg_path = os.path.join(thumb_rel_dir, f"{input_id}.jpg")
    thumb_path_written = None
    if Image is not None:
        try:
            with Image.open(BytesIO(image_bytes)) as im:
                im = im.convert("RGB")
                max_side = 384
                im.thumbnail((max_side, max_side))
                try:
                    im.save(thumb_webp_path, format="WEBP", quality=80, method=6)
                    thumb_path_written = thumb_webp_path
                except Exception:
                    im.save(thumb_jpg_path, format="JPEG", quality=80)
                    thumb_path_written = thumb_jpg_path
        except Exception:
            thumb_path_written = None

    sha256 = hashlib.sha256(image_bytes).hexdigest()
    meta = {
        "id": input_id,
        "owner": anon_id,
        "kind": "input",
        "original_filename": original_filename,
        "mime": "image/png",
        "bytes": len(image_bytes),
        "sha256": sha256,
        "created_at": now.isoformat(),
        "status": "active",
        "thumb": _build_web_path(thumb_path_written) if thumb_path_written else None,
        "tags": [],
    }
    meta_path = os.path.join(dated_dir, f"{input_id}.json")
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)

    return image_path, meta_path


def _gather_user_inputs(anon_id: str, include_trash: bool = False) -> List[dict]:
    base = _input_base_dir(anon_id)
    if not os.path.isdir(base):
        return []
    items: List[dict] = []
    for root, _, files in os.walk(base):
        for name in files:
            if not name.lower().endswith(".png"):
                continue
            png_path = os.path.join(root, name)
            try:
                stat = os.stat(png_path)
                created = stat.st_mtime
                image_id = os.path.splitext(name)[0]
                meta_path = os.path.join(root, f"{image_id}.json")
                meta = None
                if os.path.exists(meta_path):
                    try:
                        with open(meta_path, "r", encoding="utf-8") as f:
                            meta = json.load(f)
                    except Exception:
                        meta = None
                status = None
                if meta and isinstance(meta, dict):
                    status = meta.get("status")
                if not include_trash and status and status != "active":
                    continue
                thumb_url = None
                if meta and isinstance(meta, dict):
                    thumb_url = meta.get("thumb")
                else:
                    t_webp = os.path.join(root, "thumb", f"{image_id}.webp")
                    t_jpg = os.path.join(root, "thumb", f"{image_id}.jpg")
                    if os.path.exists(t_webp):
                        thumb_url = _build_web_path(t_webp)
                    elif os.path.exists(t_jpg):
                        thumb_url = _build_web_path(t_jpg)

                items.append({
                    "id": image_id,
                    "url": _build_web_path(png_path),
                    "thumb_url": thumb_url,
                    "meta": meta,
                    "status": status or "active",
                    "mtime": created,
                })
            except Exception:
                continue
    items.sort(key=lambda x: x["mtime"], reverse=True)
    return items


def _locate_input_meta_path(anon_id: str, image_id: str) -> Optional[str]:
    base = _input_base_dir(anon_id)
    if not os.path.isdir(base):
        return None
    target = f"{image_id}.json"
    for root, _, files in os.walk(base):
        if target in files:
            return os.path.join(root, target)
    return None


def _update_input_status(anon_id: str, image_id: str, status: str) -> bool:
    meta_path = _locate_input_meta_path(anon_id, image_id)
    if not meta_path:
        return False
    try:
        with open(meta_path, "r", encoding="utf-8") as f:
            meta = json.load(f)
        meta["status"] = status
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump(meta, f, ensure_ascii=False, indent=2)
        return True
    except Exception:
        return False

def _save_control_image_and_meta(anon_id: str, image_bytes: bytes, original_filename: str) -> Tuple[str, str]:
    now = datetime.now(timezone.utc)
    base_dir = _control_base_dir(anon_id)
    dated_dir = _date_partition_path(base_dir, now)
    os.makedirs(dated_dir, exist_ok=True)

    control_id = uuid.uuid4().hex
    filename = f"{control_id}.png"
    image_path = os.path.join(dated_dir, filename)

    with open(image_path, "wb") as f:
        f.write(image_bytes)

    # Thumbnail
    thumb_rel_dir = os.path.join(dated_dir, "thumb")
    os.makedirs(thumb_rel_dir, exist_ok=True)
    thumb_webp_path = os.path.join(thumb_rel_dir, f"{control_id}.webp")
    thumb_jpg_path = os.path.join(thumb_rel_dir, f"{control_id}.jpg")
    thumb_path_written = None
    if Image is not None:
        try:
            with Image.open(BytesIO(image_bytes)) as im:
                im = im.convert("RGB")
                max_side = 384
                im.thumbnail((max_side, max_side))
                try:
                    im.save(thumb_webp_path, format="WEBP", quality=80, method=6)
                    thumb_path_written = thumb_webp_path
                except Exception:
                    im.save(thumb_jpg_path, format="JPEG", quality=80)
                    thumb_path_written = thumb_jpg_path
        except Exception:
            thumb_path_written = None

    sha256 = hashlib.sha256(image_bytes).hexdigest()
    meta = {
        "id": control_id,
        "owner": anon_id,
        "workflow_id": None,
        "kind": "control",
        "original_filename": original_filename,
        "mime": "image/png",
        "bytes": len(image_bytes),
        "sha256": sha256,
        "created_at": now.isoformat(),
        "status": "active",
        "thumb": _build_web_path(thumb_path_written) if thumb_path_written else None,
        "tags": [],
    }
    meta_path = os.path.join(dated_dir, f"{control_id}.json")
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)

    return image_path, meta_path


def _gather_user_controls(anon_id: str, include_trash: bool = False) -> List[dict]:
    base = _control_base_dir(anon_id)
    if not os.path.isdir(base):
        return []
    items: List[dict] = []
    for root, _, files in os.walk(base):
        for name in files:
            if not name.lower().endswith(".png"):
                continue
            png_path = os.path.join(root, name)
            try:
                stat = os.stat(png_path)
                created = stat.st_mtime
                image_id = os.path.splitext(name)[0]
                meta_path = os.path.join(root, f"{image_id}.json")
                meta = None
                if os.path.exists(meta_path):
                    try:
                        with open(meta_path, "r", encoding="utf-8") as f:
                            meta = json.load(f)
                    except Exception:
                        meta = None
                status = None
                if meta and isinstance(meta, dict):
                    status = meta.get("status")
                if not include_trash and status and status != "active":
                    continue
                thumb_url = None
                if meta and isinstance(meta, dict):
                    thumb_url = meta.get("thumb")
                else:
                    t_webp = os.path.join(root, "thumb", f"{image_id}.webp")
                    t_jpg = os.path.join(root, "thumb", f"{image_id}.jpg")
                    if os.path.exists(t_webp):
                        thumb_url = _build_web_path(t_webp)
                    elif os.path.exists(t_jpg):
                        thumb_url = _build_web_path(t_jpg)

                items.append({
                    "id": image_id,
                    "url": _build_web_path(png_path),
                    "thumb_url": thumb_url,
                    "meta": meta,
                    "status": status or "active",
                    "mtime": created,
                })
            except Exception:
                continue
    items.sort(key=lambda x: x["mtime"], reverse=True)
    return items


def _gather_user_images(anon_id: str, include_trash: bool = False) -> List[dict]:
    base = _user_base_dir(anon_id)
    if not os.path.isdir(base):
        return []
    items: List[dict] = []
    for root, _, files in os.walk(base):
        # Skip control images and inputs directories entirely
        try:
            parts = os.path.normpath(root).split(os.sep)
            if "controls" in parts:
                continue
            if "inputs" in parts:
                continue
        except Exception:
            pass
        for name in files:
            if not name.lower().endswith(".png"):
                continue
            png_path = os.path.join(root, name)
            try:
                stat = os.stat(png_path)
                created = stat.st_mtime
                image_id = os.path.splitext(name)[0]
                meta_path = os.path.join(root, f"{image_id}.json")
                meta = None
                if os.path.exists(meta_path):
                    try:
                        with open(meta_path, "r", encoding="utf-8") as f:
                            meta = json.load(f)
                    except Exception:
                        meta = None
                # Exclude control items based on meta.kind
                try:
                    if isinstance(meta, dict) and meta.get("kind") == "control":
                        continue
                except Exception:
                    pass
                status = None
                if meta and isinstance(meta, dict):
                    status = meta.get("status")
                # Skip trashed in normal listings
                if not include_trash and status and status != "active":
                    continue
                thumb_url = None
                if meta and isinstance(meta, dict):
                    thumb_url = meta.get("thumb")
                else:
                    # Try implied thumb path
                    t_webp = os.path.join(root, "thumb", f"{image_id}.webp")
                    t_jpg = os.path.join(root, "thumb", f"{image_id}.jpg")
                    if os.path.exists(t_webp):
                        thumb_url = _build_web_path(t_webp)
                    elif os.path.exists(t_jpg):
                        thumb_url = _build_web_path(t_jpg)

                items.append({
                    "id": image_id,
                    "url": _build_web_path(png_path),
                    "thumb_url": thumb_url,
                    "meta": meta,
                    "status": status or "active",
                    "mtime": created,
                })
            except Exception:
                continue
    # Sort by mtime desc (newest first)
    items.sort(key=lambda x: x["mtime"], reverse=True)
    return items


def _locate_control_meta_path(anon_id: str, image_id: str) -> Optional[str]:
    base = _control_base_dir(anon_id)
    if not os.path.isdir(base):
        return None
    target = f"{image_id}.json"
    for root, _, files in os.walk(base):
        if target in files:
            return os.path.join(root, target)
    return None


def _locate_control_png_path(anon_id: str, image_id: str) -> Optional[str]:
    base = _control_base_dir(anon_id)
    if not os.path.isdir(base):
        return None
    target = f"{image_id}.png"
    for root, _, files in os.walk(base):
        if target in files:
            return os.path.join(root, target)
    return None


def _update_control_status(anon_id: str, image_id: str, status: str) -> bool:
    meta_path = _locate_control_meta_path(anon_id, image_id)
    if not meta_path:
        return False
    try:
        with open(meta_path, "r", encoding="utf-8") as f:
            meta = json.load(f)
        meta["status"] = status
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump(meta, f, ensure_ascii=False, indent=2)
        return True
    except Exception:
        return False


def _locate_image_meta_path(anon_id: str, image_id: str) -> Optional[str]:
    base = _user_base_dir(anon_id)
    if not os.path.isdir(base):
        return None
    target = f"{image_id}.json"
    for root, _, files in os.walk(base):
        if target in files:
            return os.path.join(root, target)
    return None


def _update_image_status(anon_id: str, image_id: str, status: str) -> bool:
    meta_path = _locate_image_meta_path(anon_id, image_id)
    if not meta_path:
        return False
    try:
        with open(meta_path, "r", encoding="utf-8") as f:
            meta = json.load(f)
        meta["status"] = status
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump(meta, f, ensure_ascii=False, indent=2)
        return True
    except Exception:
        return False
