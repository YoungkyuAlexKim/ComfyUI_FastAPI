"""Game UI asset-sheet prompting and deterministic post-processing.

The image model returns one square 2x2 sheet.  This module turns that sheet
into four independently downloadable PNG assets without making another model
call.  It intentionally contains no storage or provider code so the image
processing can be tested in isolation.
"""

from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
from statistics import median
from typing import Dict, List, Tuple

from PIL import Image, ImageChops


GAME_UI_WORKFLOW_ID = "GameUI_Elements"
GAME_UI_BACKGROUND_MODES = {"transparent", "opaque"}
GAME_UI_TARGET_SIZES = (32, 64, 128, 256)


@dataclass(frozen=True)
class GameUiOptions:
    background_mode: str

    @property
    def transparent(self) -> bool:
        return self.background_mode == "transparent"


@dataclass(frozen=True)
class ProcessedGameUiAsset:
    index: int
    master_png: bytes
    master_width: int
    master_height: int
    size_pngs: Dict[str, bytes]
    size_dimensions: Dict[str, Tuple[int, int]]


def normalize_game_ui_options(background_mode: object) -> GameUiOptions:
    normalized_background = str(background_mode or "transparent").strip().lower()
    if normalized_background not in GAME_UI_BACKGROUND_MODES:
        normalized_background = "transparent"

    return GameUiOptions(normalized_background)


def build_game_ui_generation_prompt(
    user_prompt: str,
    options: GameUiOptions,
    *,
    reference_count: int = 0,
) -> str:
    request_text = str(user_prompt or "").strip()
    if not request_text:
        raise RuntimeError("만들고 싶은 게임 UI 에셋을 설명해 주세요.")

    reference_rules = (
        "REFERENCE IMAGES: Use the attached images as visual style, material, palette, and shape-language "
        "references. Do not copy their screenshot layout, HUD, text, logos, characters, or unrelated content. "
        "Apply only the visual qualities relevant to the user request."
        if reference_count > 0
        else
        "REFERENCE IMAGES: None are attached. Infer a coherent production-ready visual language entirely "
        "from the user request."
    )
    if options.transparent:
        background_rules = (
            "CHROMA MATTE: Fill every pixel behind and inside open areas of the asset with one perfectly flat, "
            "uniform pure chroma green (#00FF00). Use no gradient, texture, floor, horizon, shadow, ambient glow, "
            "or green spill on that matte. Keep the foreground distinct from the exact matte color."
        )
    else:
        background_rules = (
            "OPAQUE OUTPUT: Give every cell a restrained, consistent backing treatment that belongs to the "
            "requested UI style. Keep the asset clearly separated from it."
        )
    return "\n".join(
        [
            "TASK: Produce four usable alternative game UI elements for one request.",
            f"USER REQUEST: {request_text}",
            reference_rules,
            "INTERPRETATION: The user request is authoritative. Infer the requested element, purpose, shape, aspect ratio, "
            "filled or open areas, and visual hierarchy directly from that request. Do not force it into a predefined "
            "icon, button, frame, badge, or panel category.",
            "VARIATION: The four cells are alternatives for the same request, not a set of four different items. "
            "Keep one coherent art direction while varying silhouette, ornament, proportions, and detail treatment.",
            "SHEET FORMAT: Output exactly one square image containing exactly four equal cells in a strict 2 columns "
            "by 2 rows layout. Reading order is top-left, top-right, bottom-left, bottom-right.",
            "CELL SAFETY: Put exactly one complete asset in each cell. Center it, keep it fully inside its own quadrant, "
            "and leave at least 8 percent safe margin. Nothing may cross the vertical or horizontal center line.",
            "SEAMS: Cells must meet edge-to-edge with zero border, zero gutter, zero padding, and no visible divider lines.",
            background_rules,
            "PROPORTIONS: Preserve the natural proportions explicitly or implicitly requested by the user, including "
            "square, circular, wide, tall, asymmetric, or freeform elements. Do not stretch every element to fill its cell.",
            "PRODUCTION RULES: One isolated, complete, reusable element per cell; orthographic front-facing presentation, "
            "crisp controlled edges, consistent lighting, no mockup, no perspective scene, no hands, no device screen, "
            "no inventory grid, and no full HUD.",
            "TEXT RULES: Do not invent words, letters, numbers, captions, labels, logos, signatures, or watermarks. "
            "Include text only when the user explicitly requests it.",
            "OUTPUT: Return only the finished 2x2 sheet as one image.",
        ]
    )


def _resample_lanczos():
    try:
        return Image.Resampling.LANCZOS
    except AttributeError:  # Pillow < 9.1
        return Image.LANCZOS


def _encode_png(image: Image.Image) -> bytes:
    out = BytesIO()
    image.save(out, format="PNG", optimize=True)
    return out.getvalue()


def _detect_matte_color(image: Image.Image) -> Tuple[int, int, int]:
    """Estimate the generated matte using sparse samples from all four edges."""
    rgb = image.convert("RGB")
    width, height = rgb.size
    if width < 2 or height < 2:
        return (0, 255, 0)
    step_x = max(1, width // 48)
    step_y = max(1, height // 48)
    samples = []
    for x in range(0, width, step_x):
        samples.append(rgb.getpixel((x, 0)))
        samples.append(rgb.getpixel((x, height - 1)))
    for y in range(0, height, step_y):
        samples.append(rgb.getpixel((0, y)))
        samples.append(rgb.getpixel((width - 1, y)))
    if not samples:
        return (0, 255, 0)
    return tuple(int(median([pixel[channel] for pixel in samples])) for channel in range(3))


def remove_chroma_matte(
    image: Image.Image,
    *,
    cutoff: int = 18,
    softness: int = 26,
) -> Image.Image:
    """Convert a nearly uniform generated matte to alpha and reduce edge spill.

    Only colors close to the detected edge matte become transparent.  This is
    deliberately conservative so ordinary greens inside an icon stay opaque.
    """
    rgb = image.convert("RGB")
    key = _detect_matte_color(rgb)
    key_image = Image.new("RGB", rgb.size, key)
    difference = ImageChops.difference(rgb, key_image)
    r_diff, g_diff, b_diff = difference.split()
    distance = ImageChops.lighter(ImageChops.lighter(r_diff, g_diff), b_diff)
    cutoff = max(0, min(254, int(cutoff)))
    softness = max(1, int(softness))

    def alpha_for_distance(value: int) -> int:
        if value <= cutoff:
            return 0
        if value >= cutoff + softness:
            return 255
        return int(round(255.0 * (value - cutoff) / softness))

    alpha = distance.point(alpha_for_distance)

    # Despill only partially transparent pixels. Opaque foreground colors,
    # including intentionally green icon details, remain untouched.
    red, green, blue = rgb.split()
    red_blue_max = ImageChops.lighter(red, blue)
    green_limit = ImageChops.add(red_blue_max, Image.new("L", rgb.size, 28), scale=1.0, offset=0)
    cleaned_green = ImageChops.darker(green, green_limit)
    partial_mask = alpha.point(lambda value: 255 - value if 0 < value < 255 else 0)
    green = Image.composite(cleaned_green, green, partial_mask)

    return Image.merge("RGBA", (red, green, blue, alpha))


def split_sheet_2x2(sheet_bytes: bytes) -> List[Image.Image]:
    if not isinstance(sheet_bytes, (bytes, bytearray)) or not sheet_bytes:
        raise RuntimeError("생성된 UI 시트 이미지가 비어 있습니다.")
    try:
        with Image.open(BytesIO(sheet_bytes)) as source:
            image = source.convert("RGB")
    except Exception as exc:
        raise RuntimeError("생성된 UI 시트 이미지를 읽을 수 없습니다.") from exc

    width, height = image.size
    if width < 4 or height < 4:
        raise RuntimeError("생성된 UI 시트의 해상도가 너무 작습니다.")
    x_mid = width // 2
    y_mid = height // 2
    boxes = (
        (0, 0, x_mid, y_mid),
        (x_mid, 0, width, y_mid),
        (0, y_mid, x_mid, height),
        (x_mid, y_mid, width, height),
    )
    return [image.crop(box) for box in boxes]


def _natural_asset_canvas(image: Image.Image, *, transparent: bool) -> Image.Image:
    if not transparent:
        return image.convert("RGB")

    rgba = image.convert("RGBA")
    alpha_for_bounds = rgba.getchannel("A").point(lambda value: 255 if value >= 12 else 0)
    bbox = alpha_for_bounds.getbbox()
    if not bbox:
        return rgba
    cropped = rgba.crop(bbox)
    padding = max(2, int(round(max(cropped.size) * 0.06)))
    canvas = Image.new(
        "RGBA",
        (cropped.width + padding * 2, cropped.height + padding * 2),
        (0, 0, 0, 0),
    )
    canvas.alpha_composite(cropped, (padding, padding))
    if max(canvas.size) > 1024:
        canvas.thumbnail((1024, 1024), _resample_lanczos())
    return canvas


def _resize_long_edge(image: Image.Image, target_size: int) -> Image.Image:
    width, height = image.size
    longest = max(width, height, 1)
    scale = float(target_size) / float(longest)
    out_width = max(1, int(round(width * scale)))
    out_height = max(1, int(round(height * scale)))
    return image.resize((out_width, out_height), _resample_lanczos())


def process_game_ui_sheet(
    sheet_bytes: bytes,
    options: GameUiOptions,
) -> List[ProcessedGameUiAsset]:
    tiles = split_sheet_2x2(sheet_bytes)
    processed: List[ProcessedGameUiAsset] = []

    for index, tile in enumerate(tiles, start=1):
        prepared = remove_chroma_matte(tile) if options.transparent else tile.convert("RGB")
        master = _natural_asset_canvas(prepared, transparent=options.transparent)
        master_width, master_height = master.size
        size_pngs: Dict[str, bytes] = {}
        size_dimensions: Dict[str, Tuple[int, int]] = {}
        for base_size in GAME_UI_TARGET_SIZES:
            resized = _resize_long_edge(master, base_size)
            out_width, out_height = resized.size
            key = str(base_size)
            size_pngs[key] = _encode_png(resized)
            size_dimensions[key] = (out_width, out_height)

        processed.append(
            ProcessedGameUiAsset(
                index=index,
                master_png=_encode_png(master),
                master_width=master_width,
                master_height=master_height,
                size_pngs=size_pngs,
                size_dimensions=size_dimensions,
            )
        )
    return processed
