import os
import re
from typing import Dict, List, Optional, Tuple

from ..character_store import REQUIRED_CHARACTER_REFERENCE_IMAGE_COUNT
from ..config import SERVER_CONFIG


_NAME_RE = re.compile(r"^[A-Za-z0-9가-힣_-]{1,32}$")
_IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".webp")
_THUMB_NAMES = ("thumb", "thumbnail", "avatar")


def _output_dir() -> str:
    out = SERVER_CONFIG.get("output_dir") if isinstance(SERVER_CONFIG, dict) else None
    out = str(out or "./outputs/")
    return out


def global_characters_base_dir() -> str:
    """
    Global characters folder (filesystem):

    outputs/global/characters/<name>/*.png|jpg|webp
    """
    return os.path.join(_output_dir(), "global", "characters")


def _build_web_path(abs_path: str) -> str:
    # OUTPUT_DIR is served at /outputs
    abs_outputs = os.path.abspath(_output_dir())
    abs_target = os.path.abspath(str(abs_path or ""))
    rel = os.path.relpath(abs_target, abs_outputs).replace("\\", "/")
    return f"/outputs/{rel}"


def _is_valid_name(name: str) -> bool:
    try:
        s = str(name or "").strip()
    except Exception:
        s = ""
    return bool(s and _NAME_RE.match(s))


def _try_parse_ref_index(filename: str) -> Optional[int]:
    """
    Prefer ref_01..ref_06 ordering when present.
    Accept common variants: ref01, ref-01, ref_1, REF_02.jpg
    """
    try:
        base = os.path.splitext(os.path.basename(filename or ""))[0]
        s = str(base or "").strip().lower()
    except Exception:
        return None
    if not s.startswith("ref"):
        return None
    m = re.search(r"(\d{1,2})", s)
    if not m:
        return None
    try:
        return int(m.group(1))
    except Exception:
        return None


def _list_image_files(dir_path: str) -> List[str]:
    files: List[str] = []
    try:
        for name in os.listdir(dir_path):
            try:
                p = os.path.join(dir_path, name)
                if not os.path.isfile(p):
                    continue
                low = name.lower()
                if not low.endswith(_IMAGE_EXTS):
                    continue
                files.append(p)
            except Exception:
                continue
    except Exception:
        return []

    def _sort_key(p: str) -> Tuple[int, int, str]:
        base = os.path.basename(p)
        idx = _try_parse_ref_index(base)
        # ref_01.. comes first (smaller rank), then name sort
        if idx is None:
            return (1, 999, base.lower())
        return (0, max(0, idx), base.lower())

    files.sort(key=_sort_key)
    return files


def _find_thumbnail_file(ch_dir: str) -> Optional[str]:
    """
    Thumbnail convention (optional):
    - thumb.png/webp/jpg/jpeg (recommended)
    - thumbnail.*
    - avatar.*
    """
    try:
        for stem in _THUMB_NAMES:
            for ext in _IMAGE_EXTS:
                cand = os.path.join(ch_dir, f"{stem}{ext}")
                if os.path.isfile(cand):
                    return cand
    except Exception:
        return None
    return None


def list_global_characters(*, include_invalid: bool = False) -> List[Dict]:
    """
    Returns a list of global characters found on disk.

    A character is "valid" when it has at least REQUIRED_CHARACTER_REFERENCE_IMAGE_COUNT images.
    Extra images are ignored (first N are used by deterministic ordering).
    """
    base = global_characters_base_dir()
    try:
        os.makedirs(base, exist_ok=True)
    except Exception:
        pass

    out: List[Dict] = []
    try:
        for entry in os.listdir(base):
            if not _is_valid_name(entry):
                continue
            ch_dir = os.path.join(base, entry)
            if not os.path.isdir(ch_dir):
                continue
            files = _list_image_files(ch_dir)
            ok = len(files) >= REQUIRED_CHARACTER_REFERENCE_IMAGE_COUNT
            if not ok and not include_invalid:
                continue
            thumb = _find_thumbnail_file(ch_dir)
            out.append(
                {
                    "name": entry,
                    "reference_image_paths": files[:REQUIRED_CHARACTER_REFERENCE_IMAGE_COUNT],
                    "reference_image_count": len(files),
                    "valid": ok,
                    "dir_path": ch_dir,
                    "thumbnail_path": thumb,
                    "thumbnail_url": _build_web_path(thumb) if thumb else None,
                }
            )
    except Exception:
        return []

    out.sort(key=lambda x: str(x.get("name") or "").lower())
    return out


def get_global_character(name: str) -> Optional[Dict]:
    if not _is_valid_name(name):
        return None
    items = list_global_characters(include_invalid=True)
    for it in items:
        if str(it.get("name") or "") == str(name or "").strip():
            if bool(it.get("valid")) and isinstance(it.get("reference_image_paths"), list):
                return it
            return None
    return None

