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
    if wf_id not in ("NanoBanana_StoryboardCutboard", "NanoBanana_WhatsNextVariations"):
        return image_bytes, None

    cols_rows = None
    try:
        up = getattr(req, "user_prompt", "") or ""
    except Exception:
        up = ""

    if wf_id == "NanoBanana_WhatsNextVariations":
        cols_rows = (2, 2)
    else:
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

    post_meta = None
    try:
        image_bytes, post_meta = _maybe_postprocess_grid_image(image_bytes, req)
    except Exception:
        post_meta = None

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
        "thumb": _build_web_path(thumb_path_written) if thumb_path_written else None,
        "tags": [],
    }
    if post_meta:
        meta["postprocess"] = post_meta
    meta_path = os.path.join(dated_dir, f"{image_id}.json")
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)

    return image_path, meta_path

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
