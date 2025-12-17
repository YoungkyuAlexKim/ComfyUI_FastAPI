import json
import os
import shutil
import uuid
from datetime import datetime, timezone
from io import BytesIO
from typing import Optional, Tuple

try:
    from PIL import Image
except Exception:
    Image = None

from .media_store import OUTPUT_DIR, _build_web_path


def _feed_active_root() -> str:
    return os.path.join(OUTPUT_DIR, "feed")


def _feed_trash_root() -> str:
    return os.path.join(_feed_active_root(), "trash")


def _date_partition(dt: datetime) -> str:
    return dt.strftime("%Y/%m/%d")


def _ensure_dirs(base_dir: str) -> Tuple[str, str]:
    os.makedirs(base_dir, exist_ok=True)
    thumb_dir = os.path.join(base_dir, "thumb")
    os.makedirs(thumb_dir, exist_ok=True)
    return base_dir, thumb_dir


def _outputs_url_to_fs(path_or_url: Optional[str]) -> Optional[str]:
    if not isinstance(path_or_url, str) or not path_or_url:
        return None
    p = path_or_url
    if p.startswith("/outputs/"):
        rel = p[len("/outputs/") :]
    elif p.startswith("outputs/"):
        rel = p[len("outputs/") :]
    else:
        return None
    return os.path.join(OUTPUT_DIR, rel.replace("/", os.sep))


def _write_thumb_from_png(src_png_path: str, dest_thumb_dir: str, dest_base_name: str) -> Optional[str]:
    if Image is None:
        return None
    try:
        with open(src_png_path, "rb") as f:
            data = f.read()
        with Image.open(BytesIO(data)) as im:
            im = im.convert("RGB")
            im.thumbnail((384, 384))
            webp_path = os.path.join(dest_thumb_dir, f"{dest_base_name}.webp")
            jpg_path = os.path.join(dest_thumb_dir, f"{dest_base_name}.jpg")
            try:
                im.save(webp_path, format="WEBP", quality=80, method=6)
                return webp_path
            except Exception:
                im.save(jpg_path, format="JPEG", quality=80)
                return jpg_path
    except Exception:
        return None


def _copy_png_to_feed(
    src_png_path: str,
    dest_dir: str,
    dest_base_name: str,
) -> Tuple[str, Optional[str]]:
    _ensure_dirs(dest_dir)
    dest_png = os.path.join(dest_dir, f"{dest_base_name}.png")
    shutil.copy2(src_png_path, dest_png)

    thumb_dir = os.path.join(dest_dir, "thumb")
    os.makedirs(thumb_dir, exist_ok=True)
    thumb_fs = _write_thumb_from_png(dest_png, thumb_dir, dest_base_name)
    return dest_png, thumb_fs


def publish_to_feed(
    owner_id: str,
    author_name: Optional[str],
    prompt: str,
    workflow_id: Optional[str],
    seed: Optional[int],
    aspect_ratio: Optional[str],
    source_image_id: str,
    source_png_fs: str,
    input_source_image_id: Optional[str] = None,
    input_png_fs: Optional[str] = None,
) -> dict:
    now = datetime.now(timezone.utc)
    post_id = uuid.uuid4().hex
    rel_date = _date_partition(now)
    dest_dir = os.path.join(_feed_active_root(), rel_date.replace("/", os.sep))

    out_png_fs, out_thumb_fs = _copy_png_to_feed(source_png_fs, dest_dir, post_id)
    input_png_url = None
    input_thumb_url = None
    input_png_written_fs = None
    input_thumb_written_fs = None
    if input_png_fs and os.path.exists(input_png_fs):
        in_base = f"{post_id}_input"
        input_png_written_fs, input_thumb_written_fs = _copy_png_to_feed(input_png_fs, dest_dir, in_base)
        input_png_url = _build_web_path(input_png_written_fs)
        input_thumb_url = _build_web_path(input_thumb_written_fs) if input_thumb_written_fs else None

    out_png_url = _build_web_path(out_png_fs)
    out_thumb_url = _build_web_path(out_thumb_fs) if out_thumb_fs else None

    meta = {
        "post_id": post_id,
        "owner_id": owner_id,
        "author_name": author_name,
        "prompt": prompt,
        "workflow_id": workflow_id,
        "seed": seed,
        "aspect_ratio": aspect_ratio,
        "image_url": out_png_url,
        "thumb_url": out_thumb_url,
        "input_image_url": input_png_url,
        "input_thumb_url": input_thumb_url,
        "source_image_id": source_image_id,
        "input_source_image_id": input_source_image_id,
        "published_at": now.timestamp(),
        "status": "active",
    }

    meta_path = os.path.join(dest_dir, f"{post_id}.json")
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)

    return meta


def _active_fs_to_trash_fs(active_fs: str) -> Optional[str]:
    if not isinstance(active_fs, str) or not active_fs:
        return None
    try:
        rel = os.path.relpath(os.path.abspath(active_fs), os.path.abspath(OUTPUT_DIR))
        rel = rel.replace("\\", "/")
        if not rel.startswith("feed/"):
            return None
        rel_under_feed = rel[len("feed/") :]
        return os.path.join(OUTPUT_DIR, "feed", "trash", rel_under_feed.replace("/", os.sep))
    except Exception:
        return None


def _trash_fs_to_active_fs(trash_fs: str) -> Optional[str]:
    if not isinstance(trash_fs, str) or not trash_fs:
        return None
    try:
        rel = os.path.relpath(os.path.abspath(trash_fs), os.path.abspath(OUTPUT_DIR))
        rel = rel.replace("\\", "/")
        if not rel.startswith("feed/trash/"):
            return None
        rel_under = rel[len("feed/trash/") :]
        return os.path.join(OUTPUT_DIR, "feed", rel_under.replace("/", os.sep))
    except Exception:
        return None


def move_post_assets_to_trash(active_image_url: str, active_thumb_url: Optional[str], input_image_url: Optional[str], input_thumb_url: Optional[str]) -> None:
    for url in [active_image_url, active_thumb_url, input_image_url, input_thumb_url]:
        fs = _outputs_url_to_fs(url)
        if not fs or not os.path.exists(fs):
            continue
        trash_fs = _active_fs_to_trash_fs(fs)
        if not trash_fs:
            continue
        os.makedirs(os.path.dirname(trash_fs), exist_ok=True)
        shutil.move(fs, trash_fs)

    # Move meta json (derived from image url)
    meta_fs = _outputs_url_to_fs(active_image_url)
    if meta_fs:
        meta_fs = os.path.splitext(meta_fs)[0] + ".json"
        if os.path.exists(meta_fs):
            trash_meta = _active_fs_to_trash_fs(meta_fs)
            if trash_meta:
                os.makedirs(os.path.dirname(trash_meta), exist_ok=True)
                shutil.move(meta_fs, trash_meta)


def restore_post_assets_from_trash(active_image_url: str, active_thumb_url: Optional[str], input_image_url: Optional[str], input_thumb_url: Optional[str]) -> None:
    for url in [active_image_url, active_thumb_url, input_image_url, input_thumb_url]:
        active_fs = _outputs_url_to_fs(url)
        if not active_fs:
            continue
        trash_fs = _active_fs_to_trash_fs(active_fs)
        if not trash_fs or not os.path.exists(trash_fs):
            continue
        os.makedirs(os.path.dirname(active_fs), exist_ok=True)
        shutil.move(trash_fs, active_fs)

    # Restore meta json
    active_meta_fs = _outputs_url_to_fs(active_image_url)
    if active_meta_fs:
        active_meta_fs = os.path.splitext(active_meta_fs)[0] + ".json"
        trash_meta = _active_fs_to_trash_fs(active_meta_fs)
        if trash_meta and os.path.exists(trash_meta):
            os.makedirs(os.path.dirname(active_meta_fs), exist_ok=True)
            shutil.move(trash_meta, active_meta_fs)


def purge_post_assets_from_trash(active_image_url: str, active_thumb_url: Optional[str], input_image_url: Optional[str], input_thumb_url: Optional[str]) -> None:
    # Purge from trash side using active urls as canonical key
    for url in [active_image_url, active_thumb_url, input_image_url, input_thumb_url]:
        active_fs = _outputs_url_to_fs(url)
        if not active_fs:
            continue
        trash_fs = _active_fs_to_trash_fs(active_fs)
        if trash_fs and os.path.exists(trash_fs):
            try:
                os.remove(trash_fs)
            except Exception:
                pass

    # Purge meta json
    active_meta_fs = _outputs_url_to_fs(active_image_url)
    if active_meta_fs:
        active_meta_fs = os.path.splitext(active_meta_fs)[0] + ".json"
        trash_meta = _active_fs_to_trash_fs(active_meta_fs)
        if trash_meta and os.path.exists(trash_meta):
            try:
                os.remove(trash_meta)
            except Exception:
                pass


