import os
import json
import hashlib
import logging
import shutil
import zipfile
from datetime import datetime, timezone
from io import BytesIO
from typing import Optional, List, Tuple
import uuid

try:
    from PIL import Image
except Exception:
    Image = None

from ..config import SERVER_CONFIG
from ..auth.user_management import require_principal_id
from .asset_runtime import get_asset_service
from .asset_service import atomic_write_bytes, atomic_write_json

# Reuse output directory from server config
OUTPUT_DIR = SERVER_CONFIG["output_dir"]
_FALLBACK_EVENTS: set[str] = set()


def _catalog_service(operation: str):
    service = get_asset_service()
    if service is not None:
        return service
    enabled = str(os.getenv("ASSET_CATALOG_FALLBACK_ENABLED", "true") or "true").strip().lower()
    if enabled not in {"1", "true", "yes", "on"}:
        raise RuntimeError(f"AssetService is required for media operation: {operation}")
    if operation not in _FALLBACK_EVENTS:
        _FALLBACK_EVENTS.add(operation)
        logging.getLogger("comfyui_app").warning(
            {
                "event": "asset_catalog_filesystem_fallback",
                "operation": operation,
            }
        )
    return None


# --- Paths and saving helpers ---

def _parse_grid_from_prompt(user_prompt: str) -> Optional[Tuple[int, int]]:
    """
    Returns (cols, rows) parsed from a line like 'GRID: 3x3' or 'GRID: 2x3'.
    """
    try:
        s = str(user_prompt or "")
    except Exception:
        s = ""
    if not s:
        return None
    for line in s.splitlines():
        try:
            t = line.strip()
        except Exception:
            continue
        if not t:
            continue
        if not t.upper().startswith("GRID:"):
            continue
        raw = t.split(":", 1)[1].strip() if ":" in t else ""
        raw = raw.lower().replace("×", "x")
        if "x" not in raw:
            continue
        a, b = raw.split("x", 1)
        try:
            cols = int(a.strip())
            rows = int(b.strip())
        except Exception:
            continue
        if cols > 0 and rows > 0:
            return cols, rows
    return None


def _detect_separator_segments(scores: list[float], threshold: float, min_width: int = 1) -> list[tuple[int, int]]:
    segs: list[tuple[int, int]] = []
    start = None
    for i, v in enumerate(scores):
        if v >= threshold:
            if start is None:
                start = i
        else:
            if start is not None:
                if i - start >= min_width:
                    segs.append((start, i))
                start = None
    if start is not None:
        if len(scores) - start >= min_width:
            segs.append((start, len(scores)))
    return segs


def _pick_internal_segments(
    segments: list[tuple[int, int]],
    total_len: int,
    expected_count: int,
    *,
    edge_margin: int,
    scores: list[float],
) -> tuple[list[tuple[int, int]], Optional[tuple[int, int]], Optional[tuple[int, int]]]:
    """
    Returns (internal_segments, left_edge_segment, right_edge_segment).
    Edge segments are optional and only selected if they touch near the boundaries.
    """
    if not segments:
        return ([], None, None)

    segs_sorted = sorted(segments, key=lambda x: (x[0], x[1]))

    left_edge = None
    if segs_sorted and segs_sorted[0][0] <= edge_margin:
        left_edge = segs_sorted[0]

    right_edge = None
    if segs_sorted and segs_sorted[-1][1] >= (total_len - edge_margin):
        right_edge = segs_sorted[-1]

    internal = []
    for s0, s1 in segs_sorted:
        if left_edge and (s0, s1) == left_edge:
            continue
        if right_edge and (s0, s1) == right_edge:
            continue
        internal.append((s0, s1))

    if expected_count <= 0:
        return ([], left_edge, right_edge)

    if len(internal) <= expected_count:
        return (internal, left_edge, right_edge)

    # Prefer segments whose centers are closest to ideal separator positions.
    # For cols=C, ideal internal separators are at i/C * total_len for i=1..C-1.
    ideal_positions = []
    try:
        step = total_len / float(expected_count + 1)
        for i in range(1, expected_count + 1):
            ideal_positions.append(step * i)
    except Exception:
        ideal_positions = []

    def seg_center(seg: tuple[int, int]) -> float:
        return (seg[0] + seg[1]) / 2.0

    def seg_width(seg: tuple[int, int]) -> int:
        try:
            return int(max(0, seg[1] - seg[0]))
        except Exception:
            return 0

    def seg_strength(seg: tuple[int, int]) -> float:
        try:
            return max(scores[seg[0] : seg[1]])
        except Exception:
            return 0.0

    def seg_mean(seg: tuple[int, int]) -> float:
        try:
            w = seg_width(seg)
            if w <= 0:
                return 0.0
            return sum(scores[seg[0] : seg[1]]) / float(w)
        except Exception:
            return 0.0

    def seg_quality(seg: tuple[int, int]) -> float:
        # Favor segments that are consistently "border-like" across their width.
        return (seg_strength(seg) + seg_mean(seg)) / 2.0

    selected: list[tuple[int, int]] = []
    remaining = internal[:]

    if ideal_positions:
        for pos in ideal_positions:
            if not remaining:
                break
            # Prefer: close to ideal position, strong+consistent, and not overly wide.
            best = min(
                remaining,
                key=lambda seg: (
                    abs(seg_center(seg) - pos),
                    -seg_quality(seg),
                    seg_width(seg),
                ),
            )
            selected.append(best)
            remaining = [s for s in remaining if s != best]
    else:
        # Fallback: select strongest segments.
        remaining.sort(key=lambda seg: (-seg_quality(seg), seg_width(seg), seg_center(seg)))
        selected = remaining[:expected_count]

    selected.sort(key=lambda seg: seg_center(seg))
    return (selected, left_edge, right_edge)


def _remove_grid_borders_and_stitch(im: "Image.Image", cols: int, rows: int) -> Optional["Image.Image"]:
    """
    Attempts to detect gutters/borders between panels and re-stitch panels edge-to-edge.
    Returns a new image on success, or None if detection fails.
    """
    if cols <= 0 or rows <= 0:
        return None
    if cols == 1 and rows == 1:
        return None

    try:
        w, h = im.size
        if w < 32 or h < 32:
            return None
    except Exception:
        return None

    # Convert to grayscale for lightweight scoring.
    g = im.convert("L")
    pix = g.load()
    if pix is None:
        return None

    # Sample step (speed vs robustness)
    step_y = max(1, h // 240)
    step_x = max(1, w // 240)

    # Border/gutter pixels can be pure white/black, but sometimes slightly off-white.
    # We'll score both strict and softer thresholds and take the stronger signal.
    white_thr_strict = 245
    black_thr_strict = 15
    white_thr_soft = 235
    black_thr_soft = 20

    def col_score(x: int) -> float:
        total = 0
        ws = bs = 0
        ww = bw = 0
        for y in range(0, h, step_y):
            v = pix[x, y]
            total += 1
            if v >= white_thr_strict:
                ws += 1
            elif v <= black_thr_strict:
                bs += 1
            if v >= white_thr_soft:
                ww += 1
            elif v <= black_thr_soft:
                bw += 1
        if not total:
            return 0.0
        strict = max(ws / total, bs / total)
        soft = max(ww / total, bw / total)
        return max(strict, soft)

    def row_score(y: int) -> float:
        total = 0
        ws = bs = 0
        ww = bw = 0
        for x in range(0, w, step_x):
            v = pix[x, y]
            total += 1
            if v >= white_thr_strict:
                ws += 1
            elif v <= black_thr_strict:
                bs += 1
            if v >= white_thr_soft:
                ww += 1
            elif v <= black_thr_soft:
                bw += 1
        if not total:
            return 0.0
        strict = max(ws / total, bs / total)
        soft = max(ww / total, bw / total)
        return max(strict, soft)

    x_scores_raw = [col_score(x) for x in range(w)]
    y_scores_raw = [row_score(y) for y in range(h)]

    def _smooth_3(scores: list[float]) -> list[float]:
        if not scores:
            return []
        n = len(scores)
        if n <= 2:
            return scores[:]
        out = [scores[0]]
        for i in range(1, n - 1):
            out.append((scores[i - 1] + scores[i] + scores[i + 1]) / 3.0)
        out.append(scores[-1])
        return out

    x_scores = _smooth_3(x_scores_raw)
    y_scores = _smooth_3(y_scores_raw)

    exp_v = max(0, cols - 1)
    exp_h = max(0, rows - 1)

    # Be a bit more willing to treat edge stripes as "outer borders".
    edge_margin_x = max(8, int(w * 0.03))
    edge_margin_y = max(8, int(h * 0.03))

    # Try a few thresholds: start strict, then relax.
    x_internal = []
    x_left = None
    x_right = None
    for thr in (0.92, 0.88, 0.84, 0.80, 0.76):
        segs = _detect_separator_segments(x_scores, thr, min_width=1)
        x_internal, x_left, x_right = _pick_internal_segments(
            segs, w, exp_v, edge_margin=edge_margin_x, scores=x_scores
        )
        if len(x_internal) >= exp_v:
            break

    y_internal = []
    y_top = None
    y_bottom = None
    for thr in (0.92, 0.88, 0.84, 0.80, 0.76):
        segs = _detect_separator_segments(y_scores, thr, min_width=1)
        y_internal, y_top, y_bottom = _pick_internal_segments(
            segs, h, exp_h, edge_margin=edge_margin_y, scores=y_scores
        )
        if len(y_internal) >= exp_h:
            break

    if len(x_internal) < exp_v or len(y_internal) < exp_h:
        return None

    def _expand_segment(seg: Optional[tuple[int, int]], total_len: int, pad: int) -> Optional[tuple[int, int]]:
        if not seg:
            return None
        try:
            a, b = int(seg[0]), int(seg[1])
        except Exception:
            return seg
        a2 = max(0, a - max(0, int(pad)))
        b2 = min(int(total_len), b + max(0, int(pad)))
        if b2 <= a2:
            return seg
        return (a2, b2)

    def _expand_segments(segs: list[tuple[int, int]], total_len: int, pad: int) -> list[tuple[int, int]]:
        out: list[tuple[int, int]] = []
        for seg in segs:
            e = _expand_segment(seg, total_len, pad)
            if e:
                out.append(e)
        out.sort(key=lambda t: (t[0], t[1]))
        # Merge overlaps (defensive)
        merged: list[tuple[int, int]] = []
        for a, b in out:
            if not merged:
                merged.append((a, b))
                continue
            pa, pb = merged[-1]
            if a <= pb:
                merged[-1] = (pa, max(pb, b))
            else:
                merged.append((a, b))
        return merged

    # Remove a little extra around separators so 1~2px lines don't survive.
    sep_pad = 2
    x_internal = _expand_segments(x_internal, w, sep_pad)
    y_internal = _expand_segments(y_internal, h, sep_pad)
    x_left = _expand_segment(x_left, w, sep_pad)
    x_right = _expand_segment(x_right, w, sep_pad)
    y_top = _expand_segment(y_top, h, sep_pad)
    y_bottom = _expand_segment(y_bottom, h, sep_pad)

    # Compute panel bounds.
    left_bound = (x_left[1] if x_left else 0)
    right_bound = (x_right[0] if x_right else w)
    top_bound = (y_top[1] if y_top else 0)
    bottom_bound = (y_bottom[0] if y_bottom else h)

    # Clamp bounds
    left_bound = max(0, min(w - 1, left_bound))
    right_bound = max(left_bound + 1, min(w, right_bound))
    top_bound = max(0, min(h - 1, top_bound))
    bottom_bound = max(top_bound + 1, min(h, bottom_bound))

    # Add internal separators and build intervals.
    x_seps = [(s0, s1) for (s0, s1) in x_internal]
    y_seps = [(s0, s1) for (s0, s1) in y_internal]
    x_seps.sort(key=lambda t: (t[0], t[1]))
    y_seps.sort(key=lambda t: (t[0], t[1]))

    # Panel x intervals
    x_bounds = [left_bound]
    for s0, s1 in x_seps:
        x_bounds.append(max(left_bound, min(right_bound, s0)))
        x_bounds.append(max(left_bound, min(right_bound, s1)))
    x_bounds.append(right_bound)

    # Panel y intervals
    y_bounds = [top_bound]
    for s0, s1 in y_seps:
        y_bounds.append(max(top_bound, min(bottom_bound, s0)))
        y_bounds.append(max(top_bound, min(bottom_bound, s1)))
    y_bounds.append(bottom_bound)

    # Derive panel rectangles (skip separator spans)
    x_panels: list[tuple[int, int]] = []
    for i in range(0, len(x_bounds) - 1, 2):
        x0 = x_bounds[i]
        x1 = x_bounds[i + 1]
        if x1 > x0:
            x_panels.append((x0, x1))
    y_panels: list[tuple[int, int]] = []
    for i in range(0, len(y_bounds) - 1, 2):
        y0 = y_bounds[i]
        y1 = y_bounds[i + 1]
        if y1 > y0:
            y_panels.append((y0, y1))

    if len(x_panels) != cols or len(y_panels) != rows:
        return None

    # Trim a few pixels inward to remove thin stroke lines.
    # (Slight content loss is acceptable for these grid tools; border invisibility is the priority.)
    trim = 4
    x_panels = [(max(0, a + trim), max(0, b - trim)) for (a, b) in x_panels]
    y_panels = [(max(0, a + trim), max(0, b - trim)) for (a, b) in y_panels]
    if any(b <= a for (a, b) in x_panels) or any(b <= a for (a, b) in y_panels):
        return None

    # Stitch
    col_widths = [b - a for (a, b) in x_panels]
    row_heights = [b - a for (a, b) in y_panels]
    new_w = sum(col_widths)
    new_h = sum(row_heights)
    if new_w <= 0 or new_h <= 0:
        return None

    mode = "RGBA" if im.mode in ("RGBA", "LA") else "RGB"
    base = Image.new(mode, (new_w, new_h))

    y_off = 0
    for r in range(rows):
        x_off = 0
        for c in range(cols):
            x0, x1 = x_panels[c]
            y0, y1 = y_panels[r]
            tile = im.crop((x0, y0, x1, y1))
            base.paste(tile, (x_off, y_off))
            x_off += tile.size[0]
        y_off += (y_panels[r][1] - y_panels[r][0])

    # Final pass: shave any remaining thin outer border lines (1~2px).
    try:
        g2 = base.convert("L")
        pix2 = g2.load()
        if pix2 is None:
            return base

        def _edge_score_col(x: int) -> float:
            total = 0
            hit = 0
            for y in range(0, new_h, max(1, new_h // 240)):
                v = pix2[x, y]
                total += 1
                if v >= white_thr_soft or v <= black_thr_soft:
                    hit += 1
            return (hit / total) if total else 0.0

        def _edge_score_row(y: int) -> float:
            total = 0
            hit = 0
            for x in range(0, new_w, max(1, new_w // 240)):
                v = pix2[x, y]
                total += 1
                if v >= white_thr_soft or v <= black_thr_soft:
                    hit += 1
            return (hit / total) if total else 0.0

        edge_thr = 0.97
        max_shave = 16
        shave_l = shave_r = shave_t = shave_b = 0
        for i in range(min(max_shave, new_w // 8)):
            if _edge_score_col(i) >= edge_thr:
                shave_l = i + 1
            else:
                break
        for i in range(min(max_shave, new_w // 8)):
            x = new_w - 1 - i
            if _edge_score_col(x) >= edge_thr:
                shave_r = i + 1
            else:
                break
        for i in range(min(max_shave, new_h // 8)):
            if _edge_score_row(i) >= edge_thr:
                shave_t = i + 1
            else:
                break
        for i in range(min(max_shave, new_h // 8)):
            y = new_h - 1 - i
            if _edge_score_row(y) >= edge_thr:
                shave_b = i + 1
            else:
                break

        if shave_l or shave_r or shave_t or shave_b:
            x0 = max(0, shave_l)
            y0 = max(0, shave_t)
            x1 = max(x0 + 1, new_w - shave_r)
            y1 = max(y0 + 1, new_h - shave_b)
            if x1 > x0 and y1 > y0:
                base = base.crop((x0, y0, x1, y1))
    except Exception:
        pass

    return base


def _maybe_postprocess_grid_image(image_bytes: bytes, req) -> tuple[bytes, Optional[dict]]:
    """
    For specific grid workflows, attempt to remove gutters/borders and stitch panels edge-to-edge.
    Returns (processed_bytes, postprocess_meta_or_none).
    """
    if Image is None:
        return image_bytes, None

    wf_id = getattr(req, "workflow_id", None)
    wf_id = str(wf_id or "")
    if wf_id != "NanoBanana_StoryboardCutboard":
        return image_bytes, None

    cols_rows = None
    try:
        up = getattr(req, "user_prompt", "") or ""
    except Exception:
        up = ""

    cols_rows = _parse_grid_from_prompt(str(up))
    if not cols_rows:
        # Best-effort fallback: infer from CUTS line.
        try:
            cuts = None
            for line in str(up).splitlines():
                t = line.strip()
                if t.upper().startswith("CUTS:"):
                    cuts = t.split(":", 1)[1].strip()
                    break
            if cuts == "6":
                cols_rows = (3, 2)
            elif cuts == "9":
                cols_rows = (3, 3)
        except Exception:
            cols_rows = None
        if not cols_rows:
            cols_rows = (3, 3)

    cols, rows = cols_rows

    try:
        with Image.open(BytesIO(image_bytes)) as im0:
            im = im0.convert("RGBA" if im0.mode in ("RGBA", "LA") else "RGB")
            out = _remove_grid_borders_and_stitch(im, cols, rows)
            if out is None:
                return image_bytes, {
                    "grid_border_removed": False,
                    "reason": "separator_detection_failed",
                    "grid": f"{cols}x{rows}",
                }
            buf = BytesIO()
            out.save(buf, format="PNG")
            # Record key tuning knobs (helps future debugging).
            return buf.getvalue(), {
                "grid_border_removed": True,
                "grid": f"{cols}x{rows}",
                "tuning": {
                    "trim": 4,
                    "sep_pad": 2,
                    "edge_shave_max": 16,
                    "edge_shave_thr": 0.97,
                },
            }
    except Exception:
        return image_bytes, {"grid_border_removed": False, "reason": "exception"}

def _user_base_dir(anon_id: str) -> str:
    principal_id = require_principal_id(anon_id)
    users_root = os.path.realpath(os.path.join(OUTPUT_DIR, "users"))
    target = os.path.realpath(os.path.join(users_root, principal_id))
    if os.path.commonpath([users_root, target]) != users_root:
        raise ValueError("Principal storage path escaped the users root")
    return target


def _date_partition_path(base_dir: str, dt: datetime) -> str:
    return os.path.join(base_dir, dt.strftime("%Y"), dt.strftime("%m"), dt.strftime("%d"))


def _build_web_path(abs_path: str) -> str:
    # Assumes OUTPUT_DIR is served at /outputs
    abs_outputs = os.path.realpath(OUTPUT_DIR)
    abs_target = os.path.realpath(abs_path)
    if os.path.commonpath([abs_outputs, abs_target]) != abs_outputs:
        raise ValueError("Media path escaped the output root")
    rel = os.path.relpath(abs_target, abs_outputs).replace("\\", "/")
    return f"/outputs/{rel}"


def _save_image_and_meta(
    anon_id: str,
    image_bytes: bytes,
    req,
    original_filename: str,
    *,
    extra_meta: Optional[dict] = None,
    postprocess: bool = True,
    source_job_id: Optional[str] = None,
    image_id: Optional[str] = None,
    register_catalog: bool = True,
    created_at: Optional[datetime] = None,
) -> Tuple[str, str]:
    now = created_at or datetime.now(timezone.utc)
    user_dir = _user_base_dir(anon_id)
    dated_dir = _date_partition_path(user_dir, now)
    os.makedirs(dated_dir, exist_ok=True)

    image_id = str(image_id or uuid.uuid4().hex)
    if len(image_id) != 32 or any(character not in "0123456789abcdef" for character in image_id):
        raise ValueError("Internal image ID must be a lowercase UUID hex value")
    image_filename = f"{image_id}.png"
    image_path = os.path.join(dated_dir, image_filename)

    post_meta = None
    if postprocess:
        try:
            image_bytes, post_meta = _maybe_postprocess_grid_image(image_bytes, req)
        except Exception:
            post_meta = None

    atomic_write_bytes(image_path, image_bytes)

    # Thumbnail (webp preferred; fallback to jpg)
    thumb_rel_dir = os.path.join(dated_dir, "thumb")
    os.makedirs(thumb_rel_dir, exist_ok=True)
    thumb_webp_path = os.path.join(thumb_rel_dir, f"{image_id}.webp")
    thumb_jpg_path = os.path.join(thumb_rel_dir, f"{image_id}.jpg")
    thumb_path_written = None
    if Image is not None:
        try:
            with Image.open(BytesIO(image_bytes)) as im:
                # Preserve alpha for transparent outputs (e.g. background removal)
                try:
                    has_alpha = (
                        im.mode in ("RGBA", "LA")
                        or (im.mode == "P" and "transparency" in (im.info or {}))
                    )
                except Exception:
                    has_alpha = False
                if has_alpha:
                    im = im.convert("RGBA")
                else:
                    im = im.convert("RGB")
                # Resize keeping aspect ratio: short side 384px
                max_side = 384
                im.thumbnail((max_side, max_side))
                try:
                    # WEBP supports alpha; keep it when present so thumbnails don't get a black background.
                    if has_alpha:
                        im.save(thumb_webp_path, format="WEBP", quality=80, method=6, lossless=True)
                    else:
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
        "image_size": getattr(req, "image_size", None),
        "image_model": getattr(req, "image_model", None),
        "image_quality": getattr(req, "image_quality", None),
        "seed": getattr(req, "seed", None),
        "prompt": getattr(req, "user_prompt", None),
        # Optional: NanoBanana character mentions (@Name)
        "character_mentions": getattr(req, "character_mentions", None),
        # RMBG2 parameters (if any)
        "rmbg_mask_blur": getattr(req, "rmbg_mask_blur", None),
        "rmbg_mask_offset": getattr(req, "rmbg_mask_offset", None),
        # Img2Img: 입력 이미지(보관함) id를 기록해두면, 이후 공유/재현에 도움이 됩니다.
        "input_image_id": getattr(req, "input_image_id", None),
        # Forward-compatible: optional multi-input image ids
        "input_image_ids": getattr(req, "input_image_ids", None),
        # ComfyUI Img2Img: input downscale info (bytes are downscaled only for upload; original remains unchanged)
        "comfy_img2img_input_downscale": getattr(req, "comfy_img2img_input_downscale", None),
        "original_filename": original_filename,
        "mime": "image/png",
        "bytes": len(image_bytes),
        "sha256": sha256,
        "created_at": now.isoformat(),
        "status": "active",
        "source_job_id": source_job_id,
        "thumb": _build_web_path(thumb_path_written) if thumb_path_written else None,
        "tags": [],
    }
    if post_meta:
        meta["postprocess"] = post_meta
    if isinstance(extra_meta, dict):
        meta.update(extra_meta)
    meta_path = os.path.join(dated_dir, f"{image_id}.json")
    atomic_write_json(meta_path, meta)

    asset_service = _catalog_service("save_image") if register_catalog else None
    if register_catalog and asset_service is not None:
        asset_service.register(
            owner_id=anon_id,
            kind="image",
            media_path=image_path,
            metadata_path=meta_path,
            metadata=meta,
            source_job_id=source_job_id,
        )

    return image_path, meta_path


def _save_game_ui_group(
    anon_id: str,
    source_sheet_bytes: bytes,
    assets: list,
    req,
    original_filename: str,
    source_job_id: Optional[str] = None,
) -> Tuple[str, dict]:
    """Persist one source sheet, its gallery children, derivatives, and a ZIP."""
    from .game_ui_assets import normalize_game_ui_options, validate_processed_game_ui_assets

    options = normalize_game_ui_options(
        getattr(req, "game_ui_background_mode", None),
        getattr(req, "game_ui_grid", None),
    )
    assets = validate_processed_game_ui_assets(assets, options)
    expected_count = options.asset_count
    if not isinstance(source_sheet_bytes, (bytes, bytearray)) or not source_sheet_bytes:
        raise RuntimeError("게임 UI 원본 시트 데이터가 비어 있습니다.")

    now = datetime.now(timezone.utc)
    group_id = uuid.uuid4().hex
    user_dir = _user_base_dir(anon_id)
    dated_dir = _date_partition_path(user_dir, now)
    group_dir = os.path.join(dated_dir, "game_ui_groups", group_id)
    sheet_path = os.path.join(group_dir, "source_sheet.png")
    manifest_path = os.path.join(group_dir, "manifest.json")
    zip_path = os.path.join(group_dir, f"game_ui_{group_id}.zip")
    background_mode = options.background_mode
    transparent = options.transparent
    original_prompt = str(
        getattr(req, "game_ui_original_prompt", None)
        or getattr(req, "user_prompt", "")
        or ""
    )
    download_url = _build_web_path(zip_path)
    sheet_url = _build_web_path(sheet_path)

    items = []
    catalog_assets = []
    created_child_ids = []
    try:
        atomic_write_bytes(sheet_path, bytes(source_sheet_bytes))
        for asset in assets:
            cell_index = int(getattr(asset, "index", len(items) + 1))
            cell_dir = os.path.join(group_dir, f"cell_{cell_index:02d}")

            size_urls = {}
            for size_key, png_bytes in dict(getattr(asset, "size_pngs", {}) or {}).items():
                dimensions = dict(getattr(asset, "size_dimensions", {}) or {}).get(str(size_key), (0, 0))
                size_path = os.path.join(cell_dir, f"{size_key}.png")
                atomic_write_bytes(size_path, png_bytes)
                size_urls[str(size_key)] = {
                    "url": _build_web_path(size_path),
                    "width": int(dimensions[0]),
                    "height": int(dimensions[1]),
                }

            extra_meta = {
                "kind": "game_ui_asset",
                "prompt": original_prompt,
                "game_ui_group_id": group_id,
                "game_ui_cell_index": cell_index,
                "game_ui_cell_count": expected_count,
                "game_ui_grid": options.grid,
                "game_ui_background_mode": background_mode,
                "game_ui_has_alpha": transparent,
                "game_ui_export_size_policy": "long_edge",
                "game_ui_sheet_url": sheet_url,
                "game_ui_group_download_url": download_url,
                "game_ui_size_urls": size_urls,
                "game_ui_master_dimensions": {
                    "width": int(getattr(asset, "master_width", 0) or 0),
                    "height": int(getattr(asset, "master_height", 0) or 0),
                },
            }
            child_id = uuid.uuid4().hex
            created_child_ids.append(child_id)
            image_path, meta_path = _save_image_and_meta(
                anon_id,
                bytes(getattr(asset, "master_png")),
                req,
                original_filename,
                extra_meta=extra_meta,
                postprocess=False,
                source_job_id=source_job_id,
                image_id=child_id,
                register_catalog=False,
                created_at=now,
            )
            with open(meta_path, "r", encoding="utf-8") as f:
                item_meta = json.load(f)
            catalog_assets.append(
                {
                    "kind": "image",
                    "media_path": image_path,
                    "metadata_path": meta_path,
                    "metadata": item_meta,
                    "source_job_id": source_job_id,
                }
            )
            items.append(
                {
                    "id": str(item_meta.get("id") or child_id),
                    "index": cell_index,
                    "url": _build_web_path(image_path),
                    "thumb_url": item_meta.get("thumb"),
                    "size_urls": size_urls,
                    "width": int(getattr(asset, "master_width", 0) or 0),
                    "height": int(getattr(asset, "master_height", 0) or 0),
                }
            )

        group = {
            "id": group_id,
            "kind": "game_ui_group",
            "status": "active",
            "workflow_id": getattr(req, "workflow_id", None),
            "prompt": original_prompt,
            "background_mode": background_mode,
            "has_alpha": transparent,
            "export_size_policy": "long_edge",
            "grid": options.grid,
            "columns": options.grid_spec.columns,
            "rows": options.grid_spec.rows,
            "count": expected_count,
            "created_at": now.isoformat(),
            "sheet_url": sheet_url,
            "download_url": download_url,
            "items": items,
        }
        atomic_write_json(manifest_path, group)

        zip_buffer = BytesIO()
        with zipfile.ZipFile(zip_buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.write(sheet_path, arcname="source_sheet.png")
            archive.write(manifest_path, arcname="manifest.json")
            for item, asset in zip(items, assets):
                archive.writestr(f"masters/cell_{item['index']:02d}.png", bytes(getattr(asset, "master_png")))
                for size_key, png_bytes in dict(getattr(asset, "size_pngs", {}) or {}).items():
                    dimensions = dict(getattr(asset, "size_dimensions", {}) or {}).get(str(size_key), (0, 0))
                    archive.writestr(
                        f"sizes/{dimensions[0]}x{dimensions[1]}/cell_{item['index']:02d}.png",
                        png_bytes,
                    )
        atomic_write_bytes(zip_path, zip_buffer.getvalue())

        asset_service = _catalog_service("save_game_ui_group")
        if asset_service is not None:
            asset_service.register_asset_group_bundle(
                owner_id=anon_id,
                assets=catalog_assets,
                manifest_path=manifest_path,
                group_metadata=group,
            )

        return items[0]["url"], group
    except Exception:
        # Every path below contains a fresh UUID created for this operation.
        # Compensate only this failed group; never touch pre-existing assets.
        for child_id in created_child_ids:
            for path in (
                os.path.join(dated_dir, f"{child_id}.png"),
                os.path.join(dated_dir, f"{child_id}.json"),
                os.path.join(dated_dir, "thumb", f"{child_id}.webp"),
                os.path.join(dated_dir, "thumb", f"{child_id}.jpg"),
            ):
                try:
                    os.remove(path)
                except FileNotFoundError:
                    pass
                except OSError:
                    logging.getLogger("comfyui_app").exception(
                        {"event": "game_ui_compensation_file_failed", "path": path}
                    )
        try:
            shutil.rmtree(group_dir)
        except FileNotFoundError:
            pass
        except OSError:
            logging.getLogger("comfyui_app").exception(
                {"event": "game_ui_compensation_group_failed", "path": group_dir}
            )
        raise

def _input_base_dir(anon_id: str) -> str:
    return os.path.join(_user_base_dir(anon_id), "inputs")


def _locate_input_png_path(anon_id: str, image_id: str) -> Optional[str]:
    asset_service = _catalog_service("locate_input")
    if asset_service is not None:
        row = asset_service.get(anon_id, image_id)
        if row and row.get("kind") == "input":
            path = asset_service.resolve_storage_path(row.get("storage_path"))
            return path if path and os.path.isfile(path) else None
    base = _input_base_dir(anon_id)
    if not os.path.isdir(base):
        return None
    target = f"{image_id}.png"
    for root, _, files in os.walk(base):
        if target in files:
            return os.path.join(root, target)
    return None


def _save_input_image_and_meta(anon_id: str, image_bytes: bytes, original_filename: str) -> Tuple[str, str]:
    asset_service = _catalog_service("save_input")
    if asset_service is not None:
        row = asset_service.create_input_image(anon_id, image_bytes, original_filename)
        image_path = asset_service.resolve_storage_path(row.get("storage_path"))
        meta_path = asset_service.resolve_storage_path(row.get("metadata_path"))
        if not image_path or not meta_path:
            raise RuntimeError("Registered input asset paths are unavailable")
        return image_path, meta_path

    # Legacy standalone fallback used only when AssetService has not been wired.
    now = datetime.now(timezone.utc)
    base_dir = _input_base_dir(anon_id)
    dated_dir = _date_partition_path(base_dir, now)
    os.makedirs(dated_dir, exist_ok=True)

    input_id = uuid.uuid4().hex
    filename = f"{input_id}.png"
    image_path = os.path.join(dated_dir, filename)

    atomic_write_bytes(image_path, image_bytes)

    # Thumbnail
    thumb_rel_dir = os.path.join(dated_dir, "thumb")
    os.makedirs(thumb_rel_dir, exist_ok=True)
    thumb_webp_path = os.path.join(thumb_rel_dir, f"{input_id}.webp")
    thumb_jpg_path = os.path.join(thumb_rel_dir, f"{input_id}.jpg")
    thumb_path_written = None
    if Image is not None:
        try:
            with Image.open(BytesIO(image_bytes)) as im:
                try:
                    has_alpha = (
                        im.mode in ("RGBA", "LA")
                        or (im.mode == "P" and "transparency" in (im.info or {}))
                    )
                except Exception:
                    has_alpha = False
                if has_alpha:
                    im = im.convert("RGBA")
                else:
                    im = im.convert("RGB")
                max_side = 384
                im.thumbnail((max_side, max_side))
                try:
                    if has_alpha:
                        im.save(thumb_webp_path, format="WEBP", quality=80, method=6, lossless=True)
                    else:
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
    atomic_write_json(meta_path, meta)

    return image_path, meta_path


def _gather_user_inputs(anon_id: str, include_trash: bool = False) -> List[dict]:
    asset_service = _catalog_service("list_inputs")
    if asset_service is not None:
        return asset_service.list_media(anon_id, "input", include_trash=include_trash)
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
    asset_service = _catalog_service("locate_input_metadata")
    if asset_service is not None:
        return asset_service.locate_metadata(anon_id, image_id, kind="input")
    base = _input_base_dir(anon_id)
    if not os.path.isdir(base):
        return None
    target = f"{image_id}.json"
    for root, _, files in os.walk(base):
        if target in files:
            return os.path.join(root, target)
    return None


def _update_input_status(anon_id: str, image_id: str, status: str) -> bool:
    asset_service = _catalog_service("update_input_status")
    if asset_service is not None:
        return asset_service.update_status(anon_id, image_id, status, kind="input")
    meta_path = _locate_input_meta_path(anon_id, image_id)
    if not meta_path:
        return False
    try:
        with open(meta_path, "r", encoding="utf-8") as f:
            meta = json.load(f)
        meta["status"] = status
        atomic_write_json(meta_path, meta)
        return True
    except Exception:
        return False


def _gather_user_images(anon_id: str, include_trash: bool = False) -> List[dict]:
    asset_service = _catalog_service("list_images")
    if asset_service is not None:
        return asset_service.list_media(anon_id, "image", include_trash=include_trash)
    base = _user_base_dir(anon_id)
    if not os.path.isdir(base):
        return []
    items: List[dict] = []
    for root, _, files in os.walk(base):
        # Skip non-gallery source/derivative stores entirely.
        try:
            parts = os.path.normpath(root).split(os.sep)
            if "controls" in parts:
                continue
            if "inputs" in parts:
                continue
            if "game_ui_groups" in parts:
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


def _locate_image_meta_path(anon_id: str, image_id: str) -> Optional[str]:
    asset_service = _catalog_service("locate_image_metadata")
    if asset_service is not None:
        return asset_service.locate_metadata(anon_id, image_id, kind="image")
    base = _user_base_dir(anon_id)
    if not os.path.isdir(base):
        return None
    target = f"{image_id}.json"
    for root, _, files in os.walk(base):
        if target in files:
            return os.path.join(root, target)
    return None


def _update_image_status(anon_id: str, image_id: str, status: str) -> bool:
    asset_service = _catalog_service("update_image_status")
    if asset_service is not None:
        return asset_service.update_status(anon_id, image_id, status, kind="image")
    meta_path = _locate_image_meta_path(anon_id, image_id)
    if not meta_path:
        return False
    try:
        with open(meta_path, "r", encoding="utf-8") as f:
            meta = json.load(f)
        meta["status"] = status
        atomic_write_json(meta_path, meta)
        return True
    except Exception:
        return False


# ── Audio (ACE-Step) storage ──────────────────────────────────────────

def _audio_base_dir(anon_id: str) -> str:
    return os.path.join(_user_base_dir(anon_id), "audio")


def _save_audio_and_meta(
    anon_id: str,
    audio_bytes: bytes,
    req,
    original_filename: str,
    source_job_id: Optional[str] = None,
) -> Tuple[str, str]:
    """Save audio file + JSON sidecar, mirroring _save_image_and_meta structure."""
    now = datetime.now(timezone.utc)
    base = _audio_base_dir(anon_id)
    dated_dir = _date_partition_path(base, now)
    os.makedirs(dated_dir, exist_ok=True)

    audio_id = uuid.uuid4().hex
    # Determine extension from original filename
    ext = ".mp3"
    try:
        _, fext = os.path.splitext(original_filename)
        if fext:
            ext = fext.lower()
    except Exception:
        pass
    audio_filename = f"{audio_id}{ext}"
    audio_path = os.path.join(dated_dir, audio_filename)

    atomic_write_bytes(audio_path, audio_bytes)
    # Master before hashing/catalog registration so metadata always describes
    # the final artifact. A missing optional audio dependency is harmless.
    try:
        if _master_audio_file(audio_path):
            with open(audio_path, "rb") as mastered_file:
                audio_bytes = mastered_file.read()
    except Exception:
        pass

    # Build metadata
    import hashlib as _hl
    sha = ""
    try:
        sha = _hl.sha256(audio_bytes).hexdigest()
    except Exception:
        pass

    meta = {
        "id": audio_id,
        "owner": anon_id,
        "kind": "audio",
        "workflow_id": getattr(req, "workflow_id", None) if req else None,
        "prompt": getattr(req, "user_prompt", "") if req else "",
        "lyrics": getattr(req, "lyrics", "") if req else "",
        "bpm": getattr(req, "bpm", None) if req else None,
        "duration": getattr(req, "duration", None) if req else None,
        "keyscale": getattr(req, "keyscale", None) if req else None,
        "language": getattr(req, "language", None) if req else None,
        "seed": getattr(req, "seed", None) if req else None,
        "original_filename": original_filename,
        "mime": "audio/mpeg" if ext == ".mp3" else f"audio/{ext.lstrip('.')}",
        "bytes": len(audio_bytes),
        "sha256": sha,
        "created_at": now.isoformat(),
        "status": "active",
        "source_job_id": source_job_id,
        "tags": [],
    }

    meta_path = os.path.join(dated_dir, f"{audio_id}.json")
    atomic_write_json(meta_path, meta)

    asset_service = _catalog_service("save_audio")
    if asset_service is not None:
        asset_service.register(
            owner_id=anon_id,
            kind="audio",
            media_path=audio_path,
            metadata_path=meta_path,
            metadata=meta,
            source_job_id=source_job_id,
        )

    return audio_path, meta_path


def _gather_user_audio(anon_id: str, include_trash: bool = False) -> List[dict]:
    """List audio files for a user, newest first."""
    asset_service = _catalog_service("list_audio")
    if asset_service is not None:
        return asset_service.list_media(anon_id, "audio", include_trash=include_trash)
    base = _audio_base_dir(anon_id)
    if not os.path.isdir(base):
        return []
    items: List[dict] = []
    _audio_exts = (".mp3", ".wav", ".flac", ".ogg", ".m4a")
    for root, _, files in os.walk(base):
        for name in files:
            low = name.lower()
            if not any(low.endswith(e) for e in _audio_exts):
                continue
            audio_path = os.path.join(root, name)
            try:
                stat = os.stat(audio_path)
                created = stat.st_mtime
                audio_id = os.path.splitext(name)[0]
                meta_path = os.path.join(root, f"{audio_id}.json")
                meta = None
                if os.path.exists(meta_path):
                    try:
                        with open(meta_path, "r", encoding="utf-8") as f:
                            meta = json.load(f)
                    except Exception:
                        meta = None
                # Skip orphan files (no metadata JSON) — leftover from purge
                if not meta or not isinstance(meta, dict):
                    continue
                status = meta.get("status")
                if not include_trash and status and status != "active":
                    continue
                items.append({
                    "id": audio_id,
                    "url": _build_web_path(audio_path),
                    "meta": meta,
                    "status": status or "active",
                    "mtime": created,
                })
            except Exception:
                continue
    items.sort(key=lambda x: x["mtime"], reverse=True)
    return items


def _locate_audio_meta_path(anon_id: str, audio_id: str) -> Optional[str]:
    asset_service = _catalog_service("locate_audio_metadata")
    if asset_service is not None:
        return asset_service.locate_metadata(anon_id, audio_id, kind="audio")
    base = _audio_base_dir(anon_id)
    if not os.path.isdir(base):
        return None
    for root, _, files in os.walk(base):
        cand = f"{audio_id}.json"
        if cand in files:
            return os.path.join(root, cand)
    return None


def _master_audio_file(audio_path: str) -> bool:
    """Apply mastering chain (EQ + Compressor + Limiter) to an audio file in-place."""
    try:
        from pedalboard import Pedalboard, Compressor, HighShelfFilter, LowShelfFilter, Limiter, Gain
        from pedalboard.io import AudioFile
    except ImportError:
        return False
    try:
        # Read
        with AudioFile(audio_path) as f:
            audio = f.read(f.frames)
            sr = f.samplerate
            channels = audio.shape[0]

        # Mastering chain
        board = Pedalboard([
            HighShelfFilter(cutoff_frequency_hz=3500, gain_db=3.5, q=0.7),
            LowShelfFilter(cutoff_frequency_hz=200, gain_db=1.5, q=0.7),
            Compressor(threshold_db=-18, ratio=3.0, attack_ms=10, release_ms=150),
            Gain(gain_db=2.0),
            Limiter(threshold_db=-1.0, release_ms=100),
        ])

        result = board(audio, sr)

        # Write to a sibling temporary file, then atomically replace the
        # original so readers never observe a partially encoded artifact.
        base, extension = os.path.splitext(audio_path)
        temp_path = f"{base}.{uuid.uuid4().hex}.tmp{extension}"
        try:
            with AudioFile(temp_path, 'w', sr, channels, quality="V0") as f:
                f.write(result)
            os.replace(temp_path, audio_path)
        finally:
            try:
                if os.path.exists(temp_path):
                    os.remove(temp_path)
            except OSError:
                pass
        return True
    except Exception:
        return False


def _update_audio_status(anon_id: str, audio_id: str, status: str) -> bool:
    asset_service = _catalog_service("update_audio_status")
    if asset_service is not None:
        return asset_service.update_status(anon_id, audio_id, status, kind="audio")
    meta_path = _locate_audio_meta_path(anon_id, audio_id)
    if not meta_path:
        return False
    try:
        with open(meta_path, "r", encoding="utf-8") as f:
            meta = json.load(f)
        meta["status"] = status
        atomic_write_json(meta_path, meta)
        return True
    except Exception:
        return False
