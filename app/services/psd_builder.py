"""
SeeThrough PSD Builder
======================
ComfyUI See-through 노드가 출력한 레이어 PNG + metadata JSON을
서버사이드에서 Photoshop PSD 파일로 합성하는 모듈.

사용법:
    from .psd_builder import build_psd_from_seethrough
    psd_bytes = build_psd_from_seethrough(layers_json_path)
"""

import json
import os
from io import BytesIO
from typing import Optional

from PIL import Image
from psd_tools import PSDImage
from psd_tools.api.layers import PixelLayer
from psd_tools.constants import ChannelID, ColorMode, Compression

import numpy as np


def build_psd_from_seethrough(layers_json_path: str) -> bytes:
    """
    See-through metadata JSON을 읽고 레이어 PNG들을 합성하여 PSD 바이트를 반환.

    Parameters:
        layers_json_path: See-through SavePSD 노드가 생성한 *_layers.json 경로

    Returns:
        PSD 파일의 bytes
    """
    with open(layers_json_path, "r", encoding="utf-8") as f:
        meta = json.load(f)

    canvas_w = meta["width"]
    canvas_h = meta["height"]
    layers_info = meta["layers"]

    # depth_median 기준 내림차순 정렬 (뒤에 있는 것 = 아래 레이어)
    layers_info.sort(key=lambda l: l.get("depth_median", 0), reverse=True)

    # psd-tools로 빈 PSD 생성
    psd = PSDImage.new("RGBA", size=(canvas_w, canvas_h))

    for layer_info in layers_info:
        png_path = layer_info["filename"]
        if not os.path.exists(png_path):
            continue

        name = layer_info.get("name", "layer")
        left = layer_info.get("left", 0)
        top = layer_info.get("top", 0)

        # PNG 로드 (RGBA)
        img = Image.open(png_path).convert("RGBA")

        # PixelLayer 생성 후 PSD에 추가
        layer = PixelLayer.frompil(img, psd, name, compression=Compression.ZIP)
        layer._record.left = left
        layer._record.top = top
        layer._record.right = left + img.width
        layer._record.bottom = top + img.height

        psd.append(layer)

    # PSD를 메모리에 저장
    buf = BytesIO()
    psd.save(buf)
    return buf.getvalue()


def collect_seethrough_parts(layers_json_path: str) -> list[dict]:
    """
    See-through metadata JSON에서 파츠 정보를 수집.
    각 파츠의 name과 PNG bytes를 반환 (일시적 프리뷰용).

    Returns:
        [{"name": "face", "png_bytes": b"..."}, ...]
    """
    with open(layers_json_path, "r", encoding="utf-8") as f:
        meta = json.load(f)

    parts = []
    for layer_info in meta.get("layers", []):
        png_path = layer_info["filename"]
        if not os.path.exists(png_path):
            continue
        with open(png_path, "rb") as pf:
            png_bytes = pf.read()
        parts.append({
            "name": layer_info.get("name", "layer"),
            "png_bytes": png_bytes,
        })
    return parts


def cleanup_seethrough_output(layers_json_path: str) -> int:
    """
    See-through가 ComfyUI output 폴더에 생성한 파일들을 삭제.

    Returns:
        삭제된 파일 수
    """
    removed = 0
    try:
        with open(layers_json_path, "r", encoding="utf-8") as f:
            meta = json.load(f)
    except Exception:
        return 0

    files_to_remove = [layers_json_path]
    for layer_info in meta.get("layers", []):
        if layer_info.get("filename"):
            files_to_remove.append(layer_info["filename"])
        if layer_info.get("depth_filename"):
            files_to_remove.append(layer_info["depth_filename"])

    for fpath in files_to_remove:
        try:
            if os.path.exists(fpath):
                os.remove(fpath)
                removed += 1
        except Exception:
            pass

    return removed
