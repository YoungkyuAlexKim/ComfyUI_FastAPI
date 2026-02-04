from io import BytesIO
from typing import List, Optional, Tuple

try:
    from PIL import Image
except Exception:
    Image = None


def _center_crop_to_square(im: "Image.Image") -> "Image.Image":
    w, h = im.size
    side = min(w, h)
    left = int((w - side) / 2)
    top = int((h - side) / 2)
    return im.crop((left, top, left + side, top + side))


def build_character_reference_sheet(
    image_bytes_list: List[bytes],
    *,
    cols: int = 3,
    rows: int = 2,
    tile_size: int = 512,
    background_rgb: Tuple[int, int, int] = (18, 18, 18),
) -> Optional[bytes]:
    """
    Build a single PNG "reference sheet" (montage) from multiple reference images.

    - No gutters/borders (edge-to-edge tiles)
    - Slight cropping is acceptable (center-crop to square) to maximize identity consistency
    - If fewer than cols*rows images are provided, the last image is repeated to fill the grid
    """
    if Image is None:
        return None
    if cols <= 0 or rows <= 0:
        return None
    if tile_size < 64:
        tile_size = 64

    raw = list(image_bytes_list or [])
    raw = [b for b in raw if isinstance(b, (bytes, bytearray)) and len(b) > 0]
    if not raw:
        return None

    tiles: List["Image.Image"] = []
    for b in raw[: cols * rows]:
        try:
            with Image.open(BytesIO(b)) as im0:
                im = im0.convert("RGB")
                im = _center_crop_to_square(im)
                im = im.resize((tile_size, tile_size), resample=Image.LANCZOS)
                tiles.append(im)
        except Exception:
            continue

    if not tiles:
        return None

    # Fill missing slots by repeating the last tile
    need = cols * rows
    while len(tiles) < need:
        try:
            tiles.append(tiles[-1].copy())
        except Exception:
            break

    sheet_w = cols * tile_size
    sheet_h = rows * tile_size
    base = Image.new("RGB", (sheet_w, sheet_h), color=background_rgb)

    idx = 0
    for r in range(rows):
        for c in range(cols):
            if idx >= len(tiles):
                break
            base.paste(tiles[idx], (c * tile_size, r * tile_size))
            idx += 1

    buf = BytesIO()
    base.save(buf, format="PNG", optimize=True)
    return buf.getvalue()

