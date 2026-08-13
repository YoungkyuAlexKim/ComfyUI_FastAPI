import os
import time
import json
from typing import Callable, List, Optional

from ..logging_utils import setup_logging
from ..comfy_client import ComfyUIClient
from ..config import SERVER_CONFIG, WORKFLOW_CONFIGS, get_prompt_overrides, COMFY_INPUT_DIR, COMFY_OUTPUT_DIR, JOB_DB_PATH, get_workflow_default_prompt
from .media_store import (
    _locate_input_png_path,
    _save_image_and_meta,
    _save_game_ui_group,
    _save_audio_and_meta,
    _master_audio_file,
    _build_web_path,
)


logger = setup_logging()

WORKFLOW_DIR = "./workflows/"
SERVER_ADDRESS = SERVER_CONFIG["server_address"]


def _wait_for_input_visibility(filename: str, timeout_sec: float = 1.5, poll_ms: int = 50) -> bool:
    try:
        if not isinstance(COMFY_INPUT_DIR, str) or not COMFY_INPUT_DIR or not isinstance(filename, str) or not filename:
            return True
        import time as _t
        import os as _os
        target = _os.path.join(COMFY_INPUT_DIR, filename)
        deadline = _t.time() + max(0.05, timeout_sec)
        while _t.time() < deadline:
            if _os.path.exists(target):
                return True
            _t.sleep(max(0.01, poll_ms / 1000.0))
        return _os.path.exists(target)
    except Exception:
        return True


def _maybe_downscale_img2img_input_for_comfy(png_bytes: bytes, max_side: int = 1536) -> tuple[bytes, Optional[dict]]:
    """
    Downscale an img2img input image before uploading to ComfyUI.

    Policy:
    - Keep aspect ratio
    - Only downscale when max(width, height) > max_side
    - Do not modify stored originals; this function only returns bytes for upload

    Returns: (output_png_bytes, meta_or_none)
    """
    if not isinstance(png_bytes, (bytes, bytearray)) or not png_bytes:
        return png_bytes, None
    try:
        max_side_int = int(max_side)
    except Exception:
        max_side_int = 1536
    if max_side_int <= 0:
        return png_bytes, None

    try:
        from io import BytesIO
        from PIL import Image
    except Exception:
        return png_bytes, None
    try:
        from PIL import ImageOps
    except Exception:
        ImageOps = None

    def _resample_lanczos():
        try:
            # Pillow >= 9.1
            return Image.Resampling.LANCZOS
        except Exception:
            try:
                return Image.LANCZOS
            except Exception:
                return Image.BICUBIC

    try:
        with Image.open(BytesIO(png_bytes)) as im0:
            im = im0
            # Best-effort: stabilize orientation for images with EXIF (mostly JPGs, but harmless here).
            try:
                if ImageOps is not None:
                    im = ImageOps.exif_transpose(im)
            except Exception:
                pass

            try:
                w0, h0 = im.size
            except Exception:
                return png_bytes, None

            resized = False
            w1, h1 = w0, h0
            if isinstance(w0, int) and isinstance(h0, int) and w0 > 0 and h0 > 0 and max(w0, h0) > max_side_int:
                if w0 >= h0:
                    w1 = max_side_int
                    h1 = max(1, int(round(h0 * (max_side_int / float(w0)))))
                else:
                    h1 = max_side_int
                    w1 = max(1, int(round(w0 * (max_side_int / float(h0)))))
                try:
                    im = im.resize((w1, h1), resample=_resample_lanczos())
                    resized = True
                except Exception:
                    # If resize fails, fall back to original bytes
                    return png_bytes, None

            meta = {
                "policy": "max_side_1536_keep_aspect",
                "max_side": max_side_int,
                "resized": bool(resized),
                "original": {"width": int(w0), "height": int(h0)},
                "output": {"width": int(w1), "height": int(h1)},
            }
            if not resized:
                return png_bytes, meta

            # Preserve alpha when present for the resized output.
            try:
                has_alpha = (
                    im.mode in ("RGBA", "LA")
                    or (im.mode == "P" and "transparency" in (im.info or {}))
                )
            except Exception:
                has_alpha = False
            im = im.convert("RGBA" if has_alpha else "RGB")

            out = BytesIO()
            im.save(out, format="PNG")
            out_bytes = out.getvalue()
            return out_bytes, meta
    except Exception:
        return png_bytes, None


def _split_comfy_path(name: str) -> tuple[str, str]:
    """
    ComfyUI sometimes returns names that include a subfolder (e.g. 'foo/bar.png').
    Returns (filename, subfolder).
    """
    try:
        s = str(name or "").replace("\\", "/").strip()
    except Exception:
        s = ""
    if not s:
        return ("", "")
    if "/" not in s:
        return (s, "")
    parts = [p for p in s.split("/") if p]
    if not parts:
        return ("", "")
    if len(parts) == 1:
        return (parts[0], "")
    return (parts[-1], "/".join(parts[:-1]))


def run_generation_processor(job, progress_cb: Callable[[float], None], set_cancel_handle: Callable[[Callable[[], bool]], None]):
    """Heavyweight generation processor extracted from main.

    - Uses set_cancel_handle to register ComfyUI interrupt back with JobManager.
    - Mutates job.result with { "image_path": "/outputs/..." } upon success.
    """
    req_dict = job.payload
    # GenerateRequest shape is validated earlier; keep dynamic access for decoupling
    class _Req:
        def __init__(self, d):
            self.user_prompt = d.get("user_prompt")
            self.aspect_ratio = d.get("aspect_ratio")
            self.workflow_id = d.get("workflow_id")
            self.seed = d.get("seed")
            self.image_size = d.get("image_size")
            self.image_model = d.get("image_model")
            self.image_quality = d.get("image_quality")
            # RMBG2 optional params
            self.rmbg_mask_blur = d.get("rmbg_mask_blur")
            self.rmbg_mask_offset = d.get("rmbg_mask_offset")
            # Include optional image-to-image fields
            self.input_image_id = d.get("input_image_id")
            self.input_image_ids = d.get("input_image_ids")
            self.input_image_filename = d.get("input_image_filename")
            # ACE-Step (music/audio) fields
            self.lyrics = d.get("lyrics")
            self.bpm = d.get("bpm")
            self.duration = d.get("duration")
            self.steps = d.get("steps")
            self.keyscale = d.get("keyscale")
            self.timesignature = d.get("timesignature")
            self.language = d.get("language")
            # SeeThrough fields
            self.seethrough_resolution = d.get("seethrough_resolution")
            # Game UI element maker fields
            self.game_ui_background_mode = d.get("game_ui_background_mode")

    request = _Req(req_dict)
    # Ensure we always have a concrete seed so users can reproduce results later,
    # even when the UI leaves seed empty ("random").
    try:
        if getattr(request, "seed", None) is None:
            request.seed = int(time.time() * 1000) % 1000000000000000
            try:
                if isinstance(req_dict, dict):
                    req_dict["seed"] = request.seed
            except Exception:
                pass
    except Exception:
        pass

    # Optional safety: if user_prompt is empty, fall back to the workflow default prompt (when defined).
    # This is important for tool workflows that allow "optional" user text on the frontend.
    try:
        raw_up = str(getattr(request, "user_prompt", "") or "")
    except Exception:
        raw_up = ""
    if not raw_up.strip():
        try:
            wf_id = str(getattr(request, "workflow_id", "") or "").strip()
        except Exception:
            wf_id = ""
        if wf_id:
            try:
                default_up = str(get_workflow_default_prompt(wf_id) or "")
            except Exception:
                default_up = ""
            if default_up.strip():
                try:
                    request.user_prompt = default_up
                except Exception:
                    pass
                try:
                    if isinstance(req_dict, dict):
                        req_dict["user_prompt"] = default_up
                except Exception:
                    pass

    try:
        logger.info({
            "event": "gen_request",
            "job_id": job.id,
            "owner_id": job.owner_id,
            "request_id": req_dict.get("request_id") if isinstance(req_dict, dict) else None,
            "request_source": req_dict.get("request_source") if isinstance(req_dict, dict) else None,
            "client_ip": req_dict.get("client_ip") if isinstance(req_dict, dict) else None,
            "capability": req_dict.get("capability") if isinstance(req_dict, dict) else None,
            "capability_variant": req_dict.get("capability_variant") if isinstance(req_dict, dict) else None,
            "workflow_id": getattr(request, "workflow_id", None),
            "input_image_id": getattr(request, "input_image_id", None),
            "input_image_filename": getattr(request, "input_image_filename", None),
        })
    except Exception:
        pass

    # --- Provider routing (OpenRouter vs ComfyUI) ---
    wf_cfg = WORKFLOW_CONFIGS.get(request.workflow_id, {}) if isinstance(WORKFLOW_CONFIGS, dict) else {}
    provider = (wf_cfg.get("provider", "comfyui") if isinstance(wf_cfg, dict) else "comfyui") or "comfyui"
    provider = str(provider).strip().lower()
    if provider == "openrouter":
        import threading

        cancel_event = threading.Event()

        def _cancel_openrouter() -> bool:
            try:
                cancel_event.set()
            except Exception:
                pass
            return True

        try:
            set_cancel_handle(_cancel_openrouter)
        except Exception:
            pass

        # Fake progress milestones (best-effort)
        progress_cb(5)
        if cancel_event.is_set():
            raise RuntimeError("생성이 취소되었습니다.")

        openrouter_cfg = wf_cfg.get("openrouter") if isinstance(wf_cfg, dict) else None
        model = None
        mode = None
        try:
            if isinstance(openrouter_cfg, dict):
                model = openrouter_cfg.get("model")
                mode = openrouter_cfg.get("mode")
        except Exception:
            model = None
            mode = None

        mode_norm = str(mode or "").strip().lower()
        is_txt2img = mode_norm in ("text-to-image", "text_to_image", "txt2img", "")
        is_img2img = mode_norm in ("image-edit", "image_edit", "img2img")

        progress_cb(20)
        if cancel_event.is_set():
            raise RuntimeError("생성이 취소되었습니다.")

        from .openrouter_client import (
            OpenRouterUpstreamError,
            build_image_prompt,
            generate_image,
            gpt_image_timeout_seconds,
            image_model_max_references,
            resolve_image_model_options,
        )

        def _record_openrouter_provider_error(e: OpenRouterUpstreamError, *, context: str) -> None:
            try:
                job.result["provider_error"] = {
                    "provider": "openrouter",
                    "kind": getattr(e, "kind", None),
                    "http_status": getattr(e, "http_status", None),
                    "upstream_code": getattr(e, "upstream_code", None),
                    "retry_after": getattr(e, "retry_after", None),
                    "context": str(context or ""),
                }
            except Exception:
                pass
            try:
                logger.warning(
                    {
                        "event": "openrouter_user_facing_error",
                        "job_id": job.id,
                        "owner_id": job.owner_id,
                        "workflow_id": getattr(request, "workflow_id", None),
                        "context": str(context or ""),
                        "kind": getattr(e, "kind", None),
                        "http_status": getattr(e, "http_status", None),
                        "upstream_code": getattr(e, "upstream_code", None),
                        "message": str(getattr(e, "public_message", str(e))),
                    }
                )
            except Exception:
                pass

        def _load_input_png_bytes(anon_id: str, image_id: str, ordinal: int) -> bytes:
            # 1) inputs 저장소
            local_png = None
            resolve_source = None
            try:
                from .media_store import _locate_input_png_path

                local_png = _locate_input_png_path(anon_id, image_id)
                if local_png:
                    resolve_source = "inputs"
            except Exception:
                local_png = None

            # 2) generated images (gallery)
            try:
                from .media_store import _locate_image_meta_path

                meta_path = _locate_image_meta_path(anon_id, image_id)
                if meta_path and os.path.exists(meta_path):
                    base_dir = os.path.dirname(meta_path)
                    cand = os.path.join(base_dir, f"{image_id}.png")
                    if os.path.exists(cand):
                        local_png = cand
                        resolve_source = "images"
            except Exception:
                pass

            # 3) legacy controls store removed (no longer supported)

            try:
                logger.info(
                    {
                        "event": "openrouter_image_input_resolved",
                        "job_id": job.id,
                        "owner_id": anon_id,
                        "input_image_id": image_id,
                        "ordinal": ordinal,
                        "local_png": local_png,
                        "source": resolve_source,
                    }
                )
            except Exception:
                pass

            if not local_png or not os.path.exists(local_png):
                raise RuntimeError(f"{ordinal}번째 입력 이미지를 찾지 못했습니다. 다시 업로드한 뒤 선택해 주세요.")

            try:
                with open(local_png, "rb") as f:
                    return f.read()
            except Exception:
                raise RuntimeError(f"{ordinal}번째 입력 이미지를 불러오지 못했습니다. 잠시 후 다시 시도해 주세요.")

        def _load_local_file_bytes(abs_path: str, ordinal: int) -> bytes:
            try:
                p = str(abs_path or "").strip()
            except Exception:
                p = ""
            if not p or not os.path.exists(p):
                raise RuntimeError(f"{ordinal}번째 레퍼런스 파일을 찾지 못했습니다. 공용 캐릭터 폴더 구성을 확인해 주세요.")
            try:
                with open(p, "rb") as f:
                    return f.read()
            except Exception:
                raise RuntimeError(f"{ordinal}번째 레퍼런스 파일을 불러오지 못했습니다. 잠시 후 다시 시도해 주세요.")

        def _load_image_file_as_png_bytes(path_like: str, ordinal: int) -> bytes:
            """
            Load an image from disk and return PNG bytes.
            - Accepts absolute path or repo-root-relative path
            - Best-effort EXIF transpose
            """
            try:
                raw = str(path_like or "").strip()
            except Exception:
                raw = ""
            if not raw:
                raise RuntimeError(f"{ordinal}번째 숨김 레퍼런스 이미지 경로가 비어 있습니다.")

            abs_path = raw
            try:
                if not os.path.isabs(abs_path):
                    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
                    abs_path = os.path.join(repo_root, raw.replace("/", os.sep))
            except Exception:
                abs_path = raw

            if not abs_path or not os.path.exists(abs_path):
                raise RuntimeError(
                    "숨김 레퍼런스 이미지를 찾지 못했습니다. "
                    f"파일을 준비해 주세요: {raw}"
                )
            try:
                from io import BytesIO
                from PIL import Image
            except Exception:
                # Pillow should be installed, but keep a clear message if not.
                raise RuntimeError("서버에서 이미지 처리(Pillow) 기능이 준비되지 않았습니다.")
            try:
                from PIL import ImageOps
            except Exception:
                ImageOps = None

            try:
                with Image.open(abs_path) as im0:
                    im = im0
                    try:
                        if ImageOps is not None:
                            im = ImageOps.exif_transpose(im)
                    except Exception:
                        pass
                    try:
                        has_alpha = (
                            im.mode in ("RGBA", "LA")
                            or (im.mode == "P" and "transparency" in (im.info or {}))
                        )
                    except Exception:
                        has_alpha = False
                    im = im.convert("RGBA" if has_alpha else "RGB")
                    out = BytesIO()
                    im.save(out, format="PNG")
                    return out.getvalue()
            except RuntimeError:
                raise
            except Exception:
                raise RuntimeError(f"{ordinal}번째 숨김 레퍼런스 이미지를 읽지 못했습니다. 파일 형식을 확인해 주세요.")

        # --- Character mentions (@Name) => attach reference sheets (txt2img only) ---
        ref_sheet_bytes_list: list[bytes] | None = None
        mention_names: list[str] = []
        try:
            raw_user_prompt = str(getattr(request, "user_prompt", "") or "")
        except Exception:
            raw_user_prompt = ""

        # Gate: mentions are a feature only for the base NanoBanana txt2img workflow.
        mentions_enabled = False
        try:
            ui_cfg = wf_cfg.get("ui") if isinstance(wf_cfg, dict) else None
            mentions_enabled = bool(isinstance(ui_cfg, dict) and ui_cfg.get("characterMentions") is True)
        except Exception:
            mentions_enabled = False

        if mentions_enabled and is_txt2img and "@" in raw_user_prompt:
            import re

            seen = set()
            for m in re.finditer(r"@([A-Za-z0-9가-힣_-]{1,32})", raw_user_prompt):
                nm = (m.group(1) or "").strip()
                if not nm or nm in seen:
                    continue
                seen.add(nm)
                mention_names.append(nm)

            if mention_names:
                # Safety: avoid too many reference sheets (cost + token/image limit)
                if len(mention_names) > 4:
                    raise RuntimeError("캐릭터는 한 번에 최대 4명(@이름 4개)까지 사용할 수 있어요.")

                from ..character_store import CharacterStore
                from .character_refs import build_character_reference_sheet
                from .global_character_store import get_global_character

                store = CharacterStore(JOB_DB_PATH)
                out_sheets: list[bytes] = []
                for i, nm in enumerate(mention_names):
                    source = "personal"
                    refs: list[str] = []
                    ref_paths: list[str] = []

                    ch = None
                    try:
                        ch = store.get_by_name(job.owner_id, nm)
                    except Exception:
                        ch = None
                    if ch and (ch.get("status") in (None, "", "active")):
                        refs = ch.get("reference_image_ids") if isinstance(ch, dict) else None
                        refs = refs if isinstance(refs, list) else []
                    else:
                        ch = None

                    if not ch:
                        gch = None
                        try:
                            gch = get_global_character(nm)
                        except Exception:
                            gch = None
                        if gch and isinstance(gch.get("reference_image_paths"), list):
                            source = "global"
                            ref_paths = [str(x or "").strip() for x in (gch.get("reference_image_paths") or [])]
                            ref_paths = [x for x in ref_paths if x]

                    # Validate reference count
                    if source == "personal":
                        if len(refs) != 6:
                            if ch:
                                raise RuntimeError(f"@{nm} 캐릭터 레퍼런스가 올바르지 않습니다. (레퍼런스 6장 필요)")
                            raise RuntimeError(
                                f"@{nm} 캐릭터가 등록되어 있지 않습니다. 먼저 '캐릭터 등록/관리'에서 추가해 주세요."
                            )
                    else:
                        if len(ref_paths) != 6:
                            raise RuntimeError(
                                f"@{nm} 공용 캐릭터 레퍼런스가 올바르지 않습니다. (공용 폴더에 이미지 6장 필요)"
                            )

                    ref_bytes_list: list[bytes] = []
                    if source == "personal":
                        for j, rid in enumerate(refs):
                            if cancel_event.is_set():
                                raise RuntimeError("생성이 취소되었습니다.")
                            ref_bytes_list.append(_load_input_png_bytes(job.owner_id, str(rid), (i * 6) + j + 1))
                    else:
                        for j, p in enumerate(ref_paths):
                            if cancel_event.is_set():
                                raise RuntimeError("생성이 취소되었습니다.")
                            ref_bytes_list.append(_load_local_file_bytes(p, (i * 6) + j + 1))

                    sheet = build_character_reference_sheet(ref_bytes_list, cols=3, rows=2, tile_size=512)
                    if not sheet:
                        raise RuntimeError(f"@{nm} 캐릭터 레퍼런스 시트를 만들지 못했습니다. 다른 레퍼런스 이미지로 다시 등록해 주세요.")
                    out_sheets.append(sheet)

                ref_sheet_bytes_list = out_sheets

                # Replace '@Name' tokens so the model sees clean text, and add explicit mapping.
                prompt_for_model = raw_user_prompt
                for nm in mention_names:
                    try:
                        prompt_for_model = prompt_for_model.replace(f"@{nm}", nm)
                    except Exception:
                        pass
                ref_lines = "\n".join([f"{idx+1}) {nm}" for idx, nm in enumerate(mention_names)])
                augmented = (
                    "REFERENCE_SHEETS_ORDER:\n"
                    f"{ref_lines}\n\n"
                    "USER_PROMPT:\n"
                    f"{prompt_for_model}\n\n"
                    "RULES_CHECKLIST:\n"
                    "- Maintain the art style and key features of each character from its reference sheet.\n"
                    "- Keep identity consistent (face, hair, outfit, colors).\n"
                )
                try:
                    request.user_prompt = augmented
                except Exception:
                    pass
                try:
                    request.character_mentions = mention_names
                except Exception:
                    pass

        # --- Hidden reference images (tool workflows): auto-switch to image-edit even on txt2img ---
        hidden_ref_bytes_list: list[bytes] | None = None
        try:
            hidden_paths = wf_cfg.get("openrouter_hidden_reference_images") if isinstance(wf_cfg, dict) else None
        except Exception:
            hidden_paths = None
        try:
            if is_txt2img and (not ref_sheet_bytes_list) and isinstance(hidden_paths, list) and hidden_paths:
                out_hidden: list[bytes] = []
                for i, p in enumerate(hidden_paths[:4]):  # safety cap
                    if cancel_event.is_set():
                        raise RuntimeError("생성이 취소되었습니다.")
                    out_hidden.append(_load_image_file_as_png_bytes(str(p or ""), i + 1))
                if out_hidden:
                    hidden_ref_bytes_list = out_hidden
                    try:
                        request.openrouter_hidden_reference_images = [str(x or "") for x in hidden_paths[:4]]
                    except Exception:
                        pass
        except RuntimeError:
            raise
        except Exception:
            hidden_ref_bytes_list = None

        # --- Game UI element maker: optional references + server-owned prompt contract ---
        game_ui_options = None
        game_ui_reference_bytes_list: list[bytes] | None = None
        is_game_ui = str(getattr(request, "workflow_id", "") or "") == "GameUI_Elements"
        if is_game_ui:
            from .game_ui_assets import build_game_ui_generation_prompt, normalize_game_ui_options

            game_ui_options = normalize_game_ui_options(getattr(request, "game_ui_background_mode", None))
            request.game_ui_background_mode = game_ui_options.background_mode
            original_prompt = str(getattr(request, "user_prompt", "") or "").strip()
            request.game_ui_original_prompt = original_prompt

            ids: list[str] = []
            seen_ids = set()
            raw_ids = getattr(request, "input_image_ids", None)
            if isinstance(raw_ids, list):
                for raw_id in raw_ids:
                    image_id = str(raw_id or "").strip()
                    if image_id and image_id not in seen_ids:
                        seen_ids.add(image_id)
                        ids.append(image_id)
            if not ids:
                single_id = str(getattr(request, "input_image_id", "") or "").strip()
                if single_id:
                    ids = [single_id]
            ids = ids[:3]
            if ids:
                game_ui_reference_bytes_list = [
                    _load_input_png_bytes(job.owner_id, image_id, index + 1)
                    for index, image_id in enumerate(ids)
                ]
                request.input_image_ids = ids
                request.input_image_id = ids[0]

            request.user_prompt = build_game_ui_generation_prompt(
                original_prompt,
                game_ui_options,
                reference_count=len(game_ui_reference_bytes_list or []),
            )

        final_prompt = build_image_prompt(request, wf_cfg)

        progress_cb(45)
        if cancel_event.is_set():
            raise RuntimeError("생성이 취소되었습니다.")

        chosen_model, req_size, req_quality = resolve_image_model_options(
            requested_model=getattr(request, "image_model", None),
            requested_resolution=(
                getattr(request, "image_size", None)
                or ((openrouter_cfg or {}).get("default_resolution") if isinstance(openrouter_cfg, dict) else None)
            ),
            requested_quality=getattr(request, "image_quality", None),
            default_model=str(model or "").strip(),
            allowed_models=(openrouter_cfg or {}).get("allowed_models") if isinstance(openrouter_cfg, dict) else None,
            default_quality=(openrouter_cfg or {}).get("default_quality") if isinstance(openrouter_cfg, dict) else None,
        )
        try:
            request.image_size = req_size
            request.image_model = chosen_model
            request.image_quality = req_quality
            if isinstance(req_dict, dict):
                # Keep the persisted Job payload aligned with what the provider
                # actually received, rather than only the initially requested values.
                req_dict["resolved_provider"] = "openrouter"
                req_dict["resolved_model"] = chosen_model
                req_dict["resolved_image_size"] = req_size
                req_dict["resolved_image_quality"] = req_quality
        except Exception:
            pass

        def _record_provider_usage(usage: dict) -> None:
            if not isinstance(req_dict, dict) or not isinstance(usage, dict):
                return
            # Store the provider's reported amount; do not infer actual spend
            # from a stale hard-coded price table.
            try:
                cost = max(0.0, float(usage.get("cost")))
            except (TypeError, ValueError):
                cost = None
            if cost is not None:
                try:
                    previous = float(req_dict.get("actual_cost_usd") or 0)
                except (TypeError, ValueError):
                    previous = 0.0
                req_dict["actual_cost_usd"] = round(previous + cost, 8)
            # Usage is persisted for later operations analysis. It is bounded
            # to JSON-compatible scalar/dict/list data by a round trip.
            try:
                req_dict["provider_usage"] = json.loads(json.dumps(usage))
            except (TypeError, ValueError):
                pass

        image_timeout = (5.0, gpt_image_timeout_seconds()) if chosen_model == "openai/gpt-image-2" else (5.0, 90.0)

        if is_txt2img:
            # Map UI aspect ratio -> OpenRouter image aspect_ratio
            ar = str(getattr(request, "aspect_ratio", "") or "").strip().lower()
            output_aspect = "1:1"
            if ar == "landscape":
                output_aspect = "16:9"
            elif ar == "portrait":
                output_aspect = "9:16"
            else:
                output_aspect = "1:1"

            if ref_sheet_bytes_list or hidden_ref_bytes_list or game_ui_reference_bytes_list:
                # Auto-switch to image-edit when we have any attached reference images.
                # IMPORTANT: do not mix "hidden refs" with character mention sheets; it would break sheet ordering.
                if ref_sheet_bytes_list:
                    images_for_edit = ref_sheet_bytes_list
                elif hidden_ref_bytes_list:
                    images_for_edit = hidden_ref_bytes_list
                else:
                    images_for_edit = game_ui_reference_bytes_list
                try:
                    image_bytes = generate_image(
                        model=chosen_model,
                        prompt=final_prompt,
                        images=images_for_edit,
                        aspect_ratio=output_aspect,
                        resolution=req_size,
                        quality=req_quality,
                        timeout=image_timeout,
                        usage_callback=_record_provider_usage,
                    )
                except OpenRouterUpstreamError as e:
                    _record_openrouter_provider_error(e, context="imgedit_auto")
                    raise RuntimeError(getattr(e, "public_message", str(e)))
            else:
                try:
                    image_bytes = generate_image(
                        model=chosen_model,
                        prompt=final_prompt,
                        aspect_ratio=output_aspect,
                        resolution=req_size,
                        quality=req_quality,
                        timeout=image_timeout,
                        usage_callback=_record_provider_usage,
                    )
                except OpenRouterUpstreamError as e:
                    _record_openrouter_provider_error(e, context="txt2img")
                    raise RuntimeError(getattr(e, "public_message", str(e)))
        elif is_img2img:
            # Phase C: 멀티 입력 이미지 편집(img2img)
            # 규칙: input_image_ids가 비어있지 않으면 우선 사용, 없으면 input_image_id 사용
            # 제한: 최대 14장
            def _normalize_ids(v) -> list[str]:
                out: list[str] = []
                seen = set()
                if not isinstance(v, list):
                    return out
                for x in v:
                    try:
                        s = str(x or "").strip()
                    except Exception:
                        s = ""
                    if not s:
                        continue
                    if s in seen:
                        continue
                    seen.add(s)
                    out.append(s)
                return out

            ids: list[str] = []
            try:
                ids = _normalize_ids(getattr(request, "input_image_ids", None))
            except Exception:
                ids = []

            if not ids:
                img_id = None
                try:
                    img_id = getattr(request, "input_image_id", None)
                except Exception:
                    img_id = None
                if isinstance(img_id, str) and img_id.strip():
                    ids = [img_id.strip()]

            # Clamp to the selected provider model's advertised reference limit.
            ids = ids[:image_model_max_references(chosen_model)]

            if not ids:
                raise RuntimeError("편집할 입력 이미지가 없습니다. 먼저 이미지를 1장 이상 업로드/선택한 뒤 다시 시도해 주세요.")

            # Backward-compat: always keep input_image_id as the first item
            try:
                request.input_image_ids = ids
            except Exception:
                pass
            try:
                request.input_image_id = ids[0]
            except Exception:
                pass

            input_png_bytes_list: list[bytes] = []
            for i, image_id in enumerate(ids):
                if cancel_event.is_set():
                    raise RuntimeError("생성이 취소되었습니다.")
                input_png_bytes_list.append(_load_input_png_bytes(job.owner_id, image_id, i + 1))

            # 출력 비율 옵션:
            # - "auto": 입력 비율 유지(기본/권장) => aspectRatio 생략
            # - square/landscape/portrait => OpenRouter aspect_ratio로 전달
            ar = str(getattr(request, "aspect_ratio", "") or "").strip().lower()
            output_aspect = None
            if ar and ar != "auto":
                if ar == "landscape":
                    output_aspect = "16:9"
                elif ar == "portrait":
                    output_aspect = "9:16"
                else:
                    output_aspect = "1:1"

            # GPT Image 2 requires an explicit size for the selected 1K/2K tier.
            # When the edit UI is on Auto, infer the closest supported orientation
            # from the first input image instead of silently forcing a square.
            if chosen_model == "openai/gpt-image-2" and output_aspect is None and input_png_bytes_list:
                try:
                    from io import BytesIO
                    from PIL import Image

                    with Image.open(BytesIO(input_png_bytes_list[0])) as source_image:
                        width, height = source_image.size
                    ratio = (float(width) / float(height)) if height else 1.0
                    if ratio > 1.15:
                        output_aspect = "16:9"
                    elif ratio < (1.0 / 1.15):
                        output_aspect = "9:16"
                    else:
                        output_aspect = "1:1"
                except Exception:
                    output_aspect = "1:1"

            try:
                image_bytes = generate_image(
                    model=chosen_model,
                    prompt=final_prompt,
                    images=input_png_bytes_list,
                    aspect_ratio=output_aspect,
                    resolution=req_size,
                    quality=req_quality,
                    timeout=image_timeout,
                    usage_callback=_record_provider_usage,
                )
            except OpenRouterUpstreamError as e:
                _record_openrouter_provider_error(e, context="imgedit_user")
                raise RuntimeError(getattr(e, "public_message", str(e)))
        else:
            raise RuntimeError("이 AI 이미지 워크플로우의 모드 설정이 올바르지 않습니다. 서버 워크플로우 설정을 확인해 주세요.")

        progress_cb(85)
        if cancel_event.is_set():
            raise RuntimeError("생성이 취소되었습니다.")

        progress_cb(90)
        if is_game_ui and game_ui_options is not None:
            from .game_ui_assets import process_game_ui_sheet

            processed_assets = process_game_ui_sheet(image_bytes, game_ui_options)
            web_path, asset_group = _save_game_ui_group(
                job.owner_id,
                image_bytes,
                processed_assets,
                request,
                f"openrouter:{chosen_model or 'image'}",
            )
            job.result["image_path"] = web_path
            job.result["asset_group"] = asset_group
        else:
            saved_image_path, _ = _save_image_and_meta(job.owner_id, image_bytes, request, f"openrouter:{chosen_model or 'image'}")
            web_path = _build_web_path(saved_image_path)
            job.result["image_path"] = web_path
        progress_cb(100)
        return

    # --- ComfyUI workflow selection (supports wrapper -> variant mapping) ---
    ui_workflow_id = getattr(request, "workflow_id", None)
    ui_workflow_id = str(ui_workflow_id or "").strip()
    wf_cfg_ui = WORKFLOW_CONFIGS.get(ui_workflow_id, {}) if isinstance(WORKFLOW_CONFIGS, dict) else {}

    effective_workflow_id = ui_workflow_id
    wf_cfg_effective = wf_cfg_ui
    try:
        variants = wf_cfg_ui.get("comfy_variants_by_input_count") if isinstance(wf_cfg_ui, dict) else None
    except Exception:
        variants = None
    try:
        if isinstance(variants, dict) and variants:
            # Count selected input images (multi preferred; legacy single fallback)
            ids: list[str] = []
            try:
                raw_ids = getattr(request, "input_image_ids", None)
                if isinstance(raw_ids, list):
                    for x in raw_ids:
                        try:
                            s = str(x or "").strip()
                        except Exception:
                            s = ""
                        if s:
                            ids.append(s)
            except Exception:
                ids = []
            if not ids:
                try:
                    one = getattr(request, "input_image_id", None)
                except Exception:
                    one = None
                if isinstance(one, str) and one.strip():
                    ids = [one.strip()]

            # Also treat a preuploaded Comfy input filename as a single image selection.
            if not ids:
                try:
                    pre = getattr(request, "input_image_filename", None)
                except Exception:
                    pre = None
                if isinstance(pre, str) and pre.strip():
                    ids = ["__preuploaded__"]

            # This feature is intended for 1 vs 2 images. Clamp: 0/1/2.
            n = len(ids)
            count_key = 2 if n >= 2 else (1 if n == 1 else 0)
            cand = variants.get(count_key)
            if not cand:
                cand = variants.get(str(count_key))
            if isinstance(cand, str) and cand.strip():
                effective_workflow_id = cand.strip()
                wf_cfg_effective = WORKFLOW_CONFIGS.get(effective_workflow_id, wf_cfg_ui) if isinstance(WORKFLOW_CONFIGS, dict) else wf_cfg_ui
                try:
                    request.comfy_effective_workflow_id = effective_workflow_id
                except Exception:
                    pass
    except Exception:
        # Fail-safe: ignore variant selection errors
        effective_workflow_id = ui_workflow_id
        wf_cfg_effective = wf_cfg_ui

    workflow_path = os.path.join(WORKFLOW_DIR, f"{effective_workflow_id}.json")
    # Some workflows rely on a hidden reference image already present in ComfyUI's input directory.
    # Example: a fixed LoadImage node used as a style/character reference (user does not upload it).
    # If that file is missing, ComfyUI will fail with a confusing error. We preflight-check and
    # return a user-friendly message instead.
    try:
        required_inputs = wf_cfg_effective.get("required_comfy_inputs") if isinstance(wf_cfg_effective, dict) else None
        if isinstance(required_inputs, list) and required_inputs:
            if not isinstance(COMFY_INPUT_DIR, str) or not COMFY_INPUT_DIR:
                raise RuntimeError(
                    "이 워크플로우는 서버의 ComfyUI input 폴더에 미리 준비된 레퍼런스 이미지가 필요합니다. "
                    "하지만 서버 설정(COMFY_INPUT_DIR)이 비어있어 파일 존재 여부를 확인할 수 없습니다. "
                    "서버 .env에 COMFY_INPUT_DIR을 설정해 주세요."
                )
            missing: List[str] = []
            for name in required_inputs:
                try:
                    if not isinstance(name, str) or not name.strip():
                        continue
                    cand = os.path.join(COMFY_INPUT_DIR, name.strip())
                    if not os.path.exists(cand):
                        missing.append(name.strip())
                except Exception:
                    continue
            if missing:
                raise RuntimeError(
                    "이 워크플로우는 숨겨진 레퍼런스 이미지를 사용합니다. "
                    f"ComfyUI input 폴더(`COMFY_INPUT_DIR`)에 다음 파일을 넣어주세요: {', '.join(missing)}"
                )
    except RuntimeError:
        raise
    except Exception:
        # Fail-safe: do not block generation due to preflight-check errors.
        pass
    # Track any uploaded/temporary images in ComfyUI input for cleanup.
    uploaded_image_input_filenames: list[str] = []
    uploaded_image_input_requested_names: list[str] = []

    prompt_overrides = get_prompt_overrides(
        user_prompt=getattr(request, "user_prompt", ""),
        aspect_ratio=getattr(request, "aspect_ratio", "square"),
        workflow_name=effective_workflow_id or getattr(request, "workflow_id", "NanoBanana"),
        seed=getattr(request, "seed", None),
    )

    # --- Optional: RMBG2 parameter overrides (mask_blur / mask_offset) ---
    try:
        rmbg_cfg = wf_cfg_effective.get("rmbg") if isinstance(wf_cfg_effective, dict) else None
        rmbg_node = None
        try:
            rmbg_node = (rmbg_cfg or {}).get("node") if isinstance(rmbg_cfg, dict) else None
        except Exception:
            rmbg_node = None
        if not rmbg_node and effective_workflow_id == "RMBG2":
            rmbg_node = "11"

        def _clamp_int(v, lo, hi):
            try:
                x = int(v)
                return max(int(lo), min(int(hi), x))
            except Exception:
                return None

        mb = _clamp_int(getattr(request, "rmbg_mask_blur", None), 0, 256)
        mo = _clamp_int(getattr(request, "rmbg_mask_offset", None), -256, 256)
        if rmbg_node and (mb is not None or mo is not None):
            node_over = prompt_overrides.get(rmbg_node, {"inputs": {}})
            if "inputs" not in node_over or not isinstance(node_over["inputs"], dict):
                node_over["inputs"] = {}
            if mb is not None:
                node_over["inputs"]["mask_blur"] = mb
            if mo is not None:
                node_over["inputs"]["mask_offset"] = mo
            prompt_overrides[rmbg_node] = node_over
            try:
                logger.info({
                    "event": "rmbg_params_override",
                    "job_id": job.id,
                    "owner_id": job.owner_id,
                    "workflow_id": getattr(request, "workflow_id", None),
                    "effective_workflow_id": effective_workflow_id,
                    "node": rmbg_node,
                    "mask_blur": mb,
                    "mask_offset": mo,
                })
            except Exception:
                pass
    except Exception:
        pass

    # --- Optional: LoRA per-slot strengths override ---
    try:
        loras_req = req_dict.get("loras") if isinstance(req_dict, dict) else None
        if isinstance(loras_req, list) and loras_req:
            lora_map = wf_cfg_effective.get("loras") if isinstance(wf_cfg_effective, dict) else None
            if isinstance(lora_map, dict):
                for item in loras_req:
                    if not isinstance(item, dict):
                        continue
                    slot = item.get("slot")
                    if not slot or slot not in lora_map:
                        continue
                    meta = lora_map[slot] or {}
                    node = meta.get("node")
                    unet_key = meta.get("unet_input", "strength_model")
                    clip_key = meta.get("clip_input", "strength_clip")
                    name_key = meta.get("name_input", "lora_name")
                    if not node:
                        continue
                    node_over = prompt_overrides.get(node, {"inputs": {}})
                    if "inputs" not in node_over or not isinstance(node_over["inputs"], dict):
                        node_over["inputs"] = {}
                    # Single value => apply to both UNet/CLIP
                    if "value" in item and isinstance(item["value"], (int, float)):
                        val = float(item["value"])
                        node_over["inputs"][unet_key] = val
                        node_over["inputs"][clip_key] = val
                    else:
                        # Backward-compat: accept separate unet/clip
                        if "unet" in item and isinstance(item["unet"], (int, float)):
                            node_over["inputs"][unet_key] = float(item["unet"]) 
                        if "clip" in item and isinstance(item["clip"], (int, float)):
                            node_over["inputs"][clip_key] = float(item["clip"]) 
                    if isinstance(item.get("name"), str) and item.get("name"):
                        node_over["inputs"][name_key] = item["name"]
                    prompt_overrides[node] = node_over
    except Exception:
        pass

    client = ComfyUIClient(SERVER_ADDRESS)
    # Allow cancellation from job manager via provided setter
    try:
        set_cancel_handle(client.interrupt)
    except Exception:
        pass

    try:
        # --- Optional: image-to-image workflow handling (single or multi input) ---
        io_cfg_single = wf_cfg_effective.get("image_input") if isinstance(wf_cfg_effective, dict) else None
        io_cfg_multi = wf_cfg_effective.get("image_inputs") if isinstance(wf_cfg_effective, dict) else None

        # Normalize to a list of mappings:
        # - image_input: { image_node, input_field }
        # - image_inputs: [ { image_node, input_field, ordinal } ... ]
        io_mappings: list[dict] = []
        if isinstance(io_cfg_multi, list) and io_cfg_multi:
            io_mappings = [x for x in io_cfg_multi if isinstance(x, dict)]
        elif isinstance(io_cfg_single, dict) and io_cfg_single:
            io_mappings = [dict(io_cfg_single, ordinal=1)]

        # Support: request.input_image_ids (preferred) or request.input_image_id (legacy single)
        input_ids: list[str] = []
        try:
            raw_ids = getattr(request, "input_image_ids", None)
            if isinstance(raw_ids, list):
                for x in raw_ids:
                    try:
                        s = str(x or "").strip()
                    except Exception:
                        s = ""
                    if s:
                        input_ids.append(s)
        except Exception:
            input_ids = []
        if not input_ids:
            try:
                one = getattr(request, "input_image_id", None)
            except Exception:
                one = None
            if isinstance(one, str) and one.strip():
                input_ids = [one.strip()]

        downscale_meta_items: list[dict] = []

        def _resolve_and_upload_to_comfy_input(img_id: str, ordinal: int) -> Optional[str]:
            """
            Resolve an input image id to a ComfyUI input filename.
            - Prefer local inputs/gallery PNG by id and upload it.
            - Fallback: treat 'xxx.png' as a filename already in Comfy input.
            - If source is already in Comfy input, optionally downscale by re-uploading a temp job file.
            Returns the Comfy input filename (stored) or None.
            """
            image_filename = None
            resolve_source = None

            # 0) If request has an explicit preuploaded filename, only apply it for the first image.
            if ordinal == 1:
                try:
                    pre = getattr(request, "input_image_filename", None)
                except Exception:
                    pre = None
                if isinstance(pre, str) and pre.strip():
                    image_filename = pre.strip()
                    resolve_source = "preuploaded"

            # 1) Resolve by stored PNG id and upload to Comfy input
            if not image_filename:
                local_png = None
                # 1) inputs store
                try:
                    from .media_store import _locate_input_png_path

                    local_png = _locate_input_png_path(job.owner_id, img_id)
                    if local_png:
                        resolve_source = "inputs"
                except Exception:
                    local_png = None
                # 2) generated images (gallery)
                try:
                    from .media_store import _locate_image_meta_path

                    meta_path = _locate_image_meta_path(job.owner_id, img_id)
                    if meta_path and os.path.exists(meta_path):
                        base_dir = os.path.dirname(meta_path)
                        cand = os.path.join(base_dir, f"{img_id}.png")
                        if os.path.exists(cand):
                            local_png = cand
                            resolve_source = "images"
                except Exception:
                    pass

                try:
                    logger.info(
                        {
                            "event": "image_input_resolved",
                            "job_id": job.id,
                            "owner_id": job.owner_id,
                            "input_image_id": img_id,
                            "ordinal": ordinal,
                            "local_png": local_png,
                            "source": resolve_source,
                        }
                    )
                except Exception:
                    pass

                if local_png and os.path.exists(local_png):
                    try:
                        with open(local_png, "rb") as f:
                            data = f.read()
                        data_for_upload = data
                        downscale_meta = None
                        try:
                            data_for_upload, downscale_meta = _maybe_downscale_img2img_input_for_comfy(data, max_side=1536)
                        except Exception:
                            data_for_upload = data
                            downscale_meta = None
                        try:
                            if isinstance(downscale_meta, dict):
                                downscale_meta["ordinal"] = int(ordinal)
                                downscale_meta["source"] = resolve_source
                                downscale_meta_items.append(downscale_meta)
                        except Exception:
                            pass

                        req_name = f"{img_id}_{job.id}_{ordinal}.png"
                        uploaded_image_input_requested_names.append(req_name)
                        stored = client.upload_image_to_input(req_name, data_for_upload, "image/png")
                        if isinstance(stored, str) and stored:
                            try:
                                _ = _wait_for_input_visibility(stored, timeout_sec=1.5, poll_ms=50)
                            except Exception:
                                pass
                            image_filename = stored
                            uploaded_image_input_filenames.append(stored)
                            try:
                                logger.info(
                                    {
                                        "event": "image_input_uploaded",
                                        "job_id": job.id,
                                        "owner_id": job.owner_id,
                                        "ordinal": ordinal,
                                        "stored": stored,
                                        "source": resolve_source,
                                        "downscale": downscale_meta,
                                    }
                                )
                            except Exception:
                                pass
                            try:
                                time.sleep(0.1)
                            except Exception:
                                pass
                    except Exception as e:
                        try:
                            logger.info(
                                {
                                    "event": "image_input_upload_failed",
                                    "job_id": job.id,
                                    "owner_id": job.owner_id,
                                    "ordinal": ordinal,
                                    "error": str(e),
                                }
                            )
                        except Exception:
                            pass
                else:
                    # Fallback: if id looks like a filename already in Comfy input, pass-through
                    try:
                        if (not local_png) and ("/" not in img_id) and ("\\" not in img_id) and img_id.lower().endswith(".png"):
                            image_filename = img_id
                            resolve_source = "filename_passthrough"
                    except Exception:
                        pass

            # 2) If the image is already in ComfyUI input (preuploaded / filename passthrough),
            # we can still downscale it by loading bytes, resizing in memory, and re-uploading
            # a temporary PNG for this job only.
            try:
                if image_filename and resolve_source in ("preuploaded", "filename_passthrough"):
                    orig_name = str(image_filename)
                    raw_bytes = None

                    # 1) Try local filesystem when COMFY_INPUT_DIR is configured (best for performance).
                    try:
                        fn, sub = _split_comfy_path(orig_name)
                        if isinstance(COMFY_INPUT_DIR, str) and COMFY_INPUT_DIR and fn:
                            cand = os.path.join(COMFY_INPUT_DIR, sub, fn) if sub else os.path.join(COMFY_INPUT_DIR, fn)
                            if os.path.exists(cand):
                                with open(cand, "rb") as f:
                                    raw_bytes = f.read()
                    except Exception:
                        raw_bytes = None

                    # 2) Fallback: fetch from ComfyUI over HTTP (/view?type=input)
                    try:
                        if raw_bytes is None:
                            fn, sub = _split_comfy_path(orig_name)
                            if fn:
                                raw_bytes = client.get_image(fn, sub or "", "input")
                    except Exception:
                        raw_bytes = None

                    if raw_bytes:
                        ds_bytes = raw_bytes
                        ds_meta = None
                        try:
                            ds_bytes, ds_meta = _maybe_downscale_img2img_input_for_comfy(raw_bytes, max_side=1536)
                        except Exception:
                            ds_bytes = raw_bytes
                            ds_meta = None

                        # Record meta even if no resize happened (helps debugging).
                        try:
                            if isinstance(ds_meta, dict):
                                ds_meta["source"] = resolve_source
                                ds_meta["input_filename"] = orig_name
                                ds_meta["ordinal"] = int(ordinal)
                                downscale_meta_items.append(ds_meta)
                        except Exception:
                            pass

                        # Only upload a temporary file when a resize actually happened.
                        try:
                            resized_flag = bool(isinstance(ds_meta, dict) and ds_meta.get("resized") is True)
                        except Exception:
                            resized_flag = False

                        if resized_flag:
                            base = ""
                            try:
                                base = os.path.splitext(os.path.basename(orig_name.replace("\\", "/")))[0]
                            except Exception:
                                base = "input"
                            if not base:
                                base = "input"
                            req_name = f"{base}_{job.id}_ds1536_{ordinal}.png"
                            uploaded_image_input_requested_names.append(req_name)
                            stored = client.upload_image_to_input(req_name, ds_bytes, "image/png")
                            if isinstance(stored, str) and stored:
                                try:
                                    _ = _wait_for_input_visibility(stored, timeout_sec=1.5, poll_ms=50)
                                except Exception:
                                    pass
                                image_filename = stored
                                uploaded_image_input_filenames.append(stored)
                                try:
                                    logger.info(
                                        {
                                            "event": "image_input_preuploaded_downscaled",
                                            "job_id": job.id,
                                            "owner_id": job.owner_id,
                                            "ordinal": ordinal,
                                            "original": orig_name,
                                            "stored": stored,
                                            "downscale": ds_meta,
                                        }
                                    )
                                except Exception:
                                    pass
            except Exception:
                pass

            return image_filename

        if io_mappings:
            # Hard gate: when image input is configured, required image ids must exist.
            if not input_ids:
                try:
                    logger.info(
                        {
                            "event": "image_input_gate_error",
                            "job_id": job.id,
                            "owner_id": job.owner_id,
                            "workflow_id": getattr(request, "workflow_id", None),
                            "reason": "missing_input_image",
                        }
                    )
                except Exception:
                    pass
                raise RuntimeError("입력 이미지가 준비되지 않았습니다. 입력 이미지를 선택/업로드 후 다시 시도해 주세요.")

            # Resolve and apply overrides for each mapping
            for m in io_mappings:
                image_node = m.get("image_node")
                input_field = m.get("input_field", "image")
                try:
                    ordinal = int(m.get("ordinal", 1))
                except Exception:
                    ordinal = 1
                if ordinal < 1:
                    ordinal = 1

                if len(input_ids) < ordinal:
                    raise RuntimeError(
                        f"이 워크플로우는 입력 이미지가 {ordinal}장 필요합니다. "
                        "입력 이미지를 더 선택해 주세요."
                    )

                img_id = input_ids[ordinal - 1]
                image_filename = _resolve_and_upload_to_comfy_input(img_id, ordinal=ordinal)
                if not image_filename:
                    raise RuntimeError(
                        f"{ordinal}번째 입력 이미지가 준비되지 않았습니다. "
                        "입력 이미지를 다시 선택/업로드 후 다시 시도해 주세요."
                    )

                if image_node and image_filename:
                    prompt_overrides.setdefault(str(image_node), {"inputs": {}})
                    prompt_overrides[str(image_node)]["inputs"][str(input_field)] = image_filename
                    try:
                        logger.info(
                            {
                                "event": "image_input_override_set",
                                "job_id": job.id,
                                "owner_id": job.owner_id,
                                "ordinal": ordinal,
                                "image_node": image_node,
                                "input_field": input_field,
                                "image_filename": image_filename,
                            }
                        )
                    except Exception:
                        pass

            # Persist downscale meta (single dict for single-image, list for multi)
            try:
                if downscale_meta_items:
                    if len(io_mappings) <= 1 and len(downscale_meta_items) == 1:
                        request.comfy_img2img_input_downscale = downscale_meta_items[0]
                    else:
                        request.comfy_img2img_input_downscale = downscale_meta_items
            except Exception:
                pass

        # Merge additional prompt into target text node if configured (e.g., node 63 for ILXL)
        try:
            ui_cfg = wf_cfg_effective.get("ui") if isinstance(wf_cfg_effective, dict) else None
            target_node = ui_cfg.get("additionalPromptTargetNode") if isinstance(ui_cfg, dict) else None
            if target_node and isinstance(target_node, str) and len(target_node) > 0:
                base_text = ""
                try:
                    base_text = wf_cfg_effective.get("style_prompt", "") or ""
                except Exception:
                    base_text = ""
                add_text = getattr(request, "user_prompt", "") or ""
                def _split(s: str) -> list[str]:
                    return [t.strip() for t in s.split(',') if isinstance(t, str) and t.strip()]
                merged: list[str] = []
                seen = set()
                for t in _split(base_text) + _split(add_text):
                    tl = t.lower()
                    if tl in seen:
                        continue
                    seen.add(tl)
                    merged.append(t)
                merged_text = ", ".join(merged)
                prompt_overrides.setdefault(str(target_node), {"inputs": {}})
                prompt_overrides[str(target_node)]["inputs"]["text"] = merged_text
        except Exception:
            pass

        # --- ACE-Step (music/audio) parameter injection ---
        try:
            if wf_cfg_effective.get("audio_workflow"):
                ap = wf_cfg_effective.get("audio_params") or {}
                rd = req_dict if isinstance(req_dict, dict) else {}

                # Lyrics
                lyrics_val = rd.get("lyrics") or ""
                lyrics_node = ap.get("lyrics_node")
                lyrics_key = ap.get("lyrics_key", "lyrics")
                if lyrics_node:
                    prompt_overrides.setdefault(str(lyrics_node), {"inputs": {}})
                    prompt_overrides[str(lyrics_node)]["inputs"][str(lyrics_key)] = str(lyrics_val)

                # BPM
                bpm_val = rd.get("bpm")
                bpm_node = ap.get("bpm_node")
                bpm_key = ap.get("bpm_key", "bpm")
                if bpm_node and bpm_val is not None:
                    prompt_overrides.setdefault(str(bpm_node), {"inputs": {}})
                    prompt_overrides[str(bpm_node)]["inputs"][str(bpm_key)] = int(bpm_val)

                # Duration (inject into both TextEncode and LatentAudio nodes)
                dur_val = rd.get("duration")
                if dur_val is not None:
                    dur_val = int(dur_val)
                    for nk, kk in [
                        ("duration_node_encode", "duration_key_encode"),
                        ("duration_node_latent", "duration_key_latent"),
                    ]:
                        dn = ap.get(nk)
                        dk = ap.get(kk)
                        if dn and dk:
                            prompt_overrides.setdefault(str(dn), {"inputs": {}})
                            prompt_overrides[str(dn)]["inputs"][str(dk)] = dur_val

                # Time signature
                ts_val = rd.get("timesignature")
                ts_node = ap.get("timesignature_node")
                ts_key = ap.get("timesignature_key", "timesignature")
                if ts_node and ts_val is not None:
                    prompt_overrides.setdefault(str(ts_node), {"inputs": {}})
                    prompt_overrides[str(ts_node)]["inputs"][str(ts_key)] = str(ts_val)

                # Language
                lang_val = rd.get("language")
                lang_node = ap.get("language_node")
                lang_key = ap.get("language_key", "language")
                if lang_node and lang_val is not None:
                    prompt_overrides.setdefault(str(lang_node), {"inputs": {}})
                    prompt_overrides[str(lang_node)]["inputs"][str(lang_key)] = str(lang_val)

                # Key/Scale
                ks_val = rd.get("keyscale")
                ks_node = ap.get("keyscale_node")
                ks_key = ap.get("keyscale_key", "keyscale")
                if ks_node and ks_val is not None:
                    prompt_overrides.setdefault(str(ks_node), {"inputs": {}})
                    prompt_overrides[str(ks_node)]["inputs"][str(ks_key)] = str(ks_val)

                # Fixed params (cfg_scale, temperature, etc. — not user-facing)
                fixed = wf_cfg_effective.get("audio_fixed_params") or {}
                for fnode, fparams in fixed.items():
                    if isinstance(fparams, dict):
                        prompt_overrides.setdefault(str(fnode), {"inputs": {}})
                        for fk, fv in fparams.items():
                            prompt_overrides[str(fnode)]["inputs"][str(fk)] = fv

                # Extra seed nodes (e.g. KSampler) + steps override
                extra_seeds = wf_cfg_effective.get("extra_seed_nodes") or []
                for es in extra_seeds:
                    if isinstance(es, dict):
                        es_node = es.get("node")
                        es_key = es.get("key", "seed")
                        if es_node and hasattr(request, "seed") and request.seed is not None:
                            prompt_overrides.setdefault(str(es_node), {"inputs": {}})
                            prompt_overrides[str(es_node)]["inputs"][str(es_key)] = request.seed

                # Steps override on KSampler (node 3)
                steps_val = rd.get("steps")
                if steps_val is not None:
                    steps_val = max(1, min(100, int(steps_val)))
                    prompt_overrides.setdefault("3", {"inputs": {}})
                    prompt_overrides["3"]["inputs"]["steps"] = steps_val
        except Exception:
            pass

        # --- SeeThrough parameter injection ---
        is_seethrough = bool(wf_cfg_effective.get("seethrough_workflow"))
        if is_seethrough:
            try:
                rd = req_dict if isinstance(req_dict, dict) else {}
                # Resolution → node 24 (SeeThrough_GenerateLayers)
                res_val = rd.get("seethrough_resolution")
                if res_val is not None:
                    res_val = max(768, min(1472, int(res_val)))
                    prompt_overrides.setdefault("24", {"inputs": {}})
                    prompt_overrides["24"]["inputs"]["resolution"] = res_val
                # Seed → node 23 (GenerateDepth) + node 24 (GenerateLayers)
                # See-through 노드는 seed 최대값이 4294967295 (32비트)
                seed_val = getattr(request, "seed", None)
                if seed_val is not None:
                    seed_val = int(seed_val) % 4294967295
                    for sn in ("23", "24"):
                        prompt_overrides.setdefault(sn, {"inputs": {}})
                        prompt_overrides[sn]["inputs"]["seed"] = seed_val
                # filename_prefix → node 21 (SeeThrough_SavePSD): job ID를 포함시켜 파일 식별
                seethrough_prefix = f"seethrough_{job.id}"
                if COMFY_OUTPUT_DIR:
                    import os as _os
                    seethrough_out_dir = _os.path.join(COMFY_OUTPUT_DIR, "seethrough")
                    _os.makedirs(seethrough_out_dir, exist_ok=True)
                    seethrough_prefix = _os.path.join(seethrough_out_dir, f"st_{job.id}")
                prompt_overrides.setdefault("21", {"inputs": {}})
                prompt_overrides["21"]["inputs"]["filename_prefix"] = seethrough_prefix
            except Exception:
                pass

        resp = client.queue_prompt(workflow_path, prompt_overrides)
        prompt_id = resp.get('prompt_id') if isinstance(resp, dict) else None
        if not prompt_id:
            raise RuntimeError("Failed to get prompt_id.")

        def on_progress(p: float):
            progress_cb(p)

        images_data = client.get_images(prompt_id, on_progress=on_progress)

        # --- SeeThrough 전용 후처리 ---
        if is_seethrough:
            from .psd_builder import build_psd_from_seethrough, collect_seethrough_parts, cleanup_seethrough_output
            import glob as _glob

            # seethrough_psd_info.log 또는 job ID로 layers.json 찾기
            layers_json_path = None
            search_dirs = []
            if COMFY_OUTPUT_DIR:
                search_dirs.append(os.path.join(COMFY_OUTPUT_DIR, "seethrough"))
                search_dirs.append(COMFY_OUTPUT_DIR)
            # fallback: ComfyUI 기본 output 디렉토리
            search_dirs.append(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "..", ".."))

            for sd in search_dirs:
                pattern = os.path.join(sd, f"**/*{job.id}*_layers.json")
                matches = _glob.glob(pattern, recursive=True)
                if matches:
                    layers_json_path = matches[0]
                    break

            # fallback: seethrough_psd_info.log
            if not layers_json_path and COMFY_OUTPUT_DIR:
                log_path = os.path.join(COMFY_OUTPUT_DIR, "seethrough_psd_info.log")
                if os.path.exists(log_path):
                    with open(log_path, "r") as lf:
                        info_name = lf.read().strip()
                    # info_name could be absolute or relative
                    if os.path.isabs(info_name) and os.path.exists(info_name):
                        layers_json_path = info_name
                    else:
                        candidate = os.path.join(COMFY_OUTPUT_DIR, info_name)
                        if os.path.exists(candidate):
                            layers_json_path = candidate

            if not layers_json_path:
                raise RuntimeError("SeeThrough 레이어 데이터를 찾을 수 없습니다.")

            # 1) PSD 빌드
            psd_bytes = build_psd_from_seethrough(layers_json_path)

            # 2) PSD를 서비스 outputs에 저장
            from datetime import datetime, timezone
            now = datetime.now(timezone.utc)
            user_dir = os.path.join(SERVER_CONFIG["output_dir"], job.owner_id)
            dated_dir = os.path.join(user_dir, now.strftime("%Y-%m-%d"))
            os.makedirs(dated_dir, exist_ok=True)

            import uuid as _uuid
            psd_id = _uuid.uuid4().hex
            psd_filename = f"{psd_id}.psd"
            psd_path = os.path.join(dated_dir, psd_filename)
            with open(psd_path, "wb") as pf:
                pf.write(psd_bytes)
            psd_web_path = _build_web_path(psd_path)

            # 3) 파츠 프리뷰 수집 (base64 — 디스크 저장 없이 WebSocket으로만 전달)
            import base64 as _b64
            parts = collect_seethrough_parts(layers_json_path)
            parts_info = []
            for part in parts:
                b64 = _b64.b64encode(part["png_bytes"]).decode("ascii")
                parts_info.append({
                    "name": part["name"],
                    "data_url": f"data:image/png;base64,{b64}",
                })

            # 4) 프리뷰 이미지 (base64 — 디스크 저장 없음)
            preview_data_url = None
            if images_data:
                preview_bytes = list(images_data.values())[0]
                b64_preview = _b64.b64encode(preview_bytes).decode("ascii")
                preview_data_url = f"data:image/png;base64,{b64_preview}"

            # 5) job.result에 결과 설정
            job.result["is_seethrough"] = True
            job.result["psd_path"] = psd_web_path
            job.result["psd_size_bytes"] = len(psd_bytes)
            job.result["parts"] = parts_info
            if preview_data_url:
                job.result["preview_data_url"] = preview_data_url

            # 6) ComfyUI output 정리
            try:
                cleanup_seethrough_output(layers_json_path)
            except Exception:
                pass

            try:
                logger.info({
                    "event": "seethrough_complete",
                    "job_id": job.id,
                    "psd_path": psd_web_path,
                    "psd_size": len(psd_bytes),
                    "layers_count": len(parts_info),
                })
            except Exception:
                pass

        elif not images_data:
            is_audio = bool(wf_cfg_effective.get("audio_workflow"))
            raise RuntimeError("Failed to receive generated audio." if is_audio else "Failed to receive generated images.")

        else:
            filename = list(images_data.keys())[0]
            file_bytes = list(images_data.values())[0]

            # For audio workflows, save via audio store (date-partitioned + metadata JSON)
            is_audio_wf = bool(wf_cfg_effective.get("audio_workflow"))
            if is_audio_wf:
                audio_path, _ = _save_audio_and_meta(job.owner_id, file_bytes, request, filename)
                # Auto-mastering (EQ + Compressor + Limiter) — overwrites in-place
                try:
                    _master_audio_file(audio_path)
                except Exception:
                    pass
                web_path = _build_web_path(audio_path)
                job.result["audio_path"] = web_path
                job.result["is_audio"] = True
            else:
                saved_image_path, _ = _save_image_and_meta(job.owner_id, file_bytes, request, filename)
                web_path = _build_web_path(saved_image_path)
                job.result["image_path"] = web_path
    finally:
        # Best-effort cleanup of any uploaded inputs in ComfyUI input directory (single and multi)
        try:
            if isinstance(COMFY_INPUT_DIR, str) and COMFY_INPUT_DIR:
                def _try_delete(name: str, kind: str):
                    if not isinstance(name, str) or not name:
                        return
                    # ComfyUI가 반환하는 name이 경로를 포함하는 경우가 드물게 있어, 두 가지 후보를 시도합니다.
                    candidates = []
                    try:
                        candidates.append(os.path.join(COMFY_INPUT_DIR, name))
                    except Exception:
                        pass
                    try:
                        base = os.path.basename(name.replace("\\", "/"))
                        if base and base != name:
                            candidates.append(os.path.join(COMFY_INPUT_DIR, base))
                    except Exception:
                        pass

                    for cand in candidates:
                        if not cand:
                            continue
                        ok = False
                        last_err = None
                        # Windows에서는 ComfyUI가 파일 핸들을 잠깐 잡고 있는 경우가 있어 재시도합니다.
                        for _ in range(25):
                            try:
                                if os.path.exists(cand):
                                    os.remove(cand)
                                ok = True
                                break
                            except Exception as e:
                                last_err = str(e)
                                try:
                                    time.sleep(0.2)
                                except Exception:
                                    pass
                        try:
                            logger.info({
                                "event": "comfy_input_cleanup",
                                "kind": kind,
                                "name": name,
                                "candidate": cand,
                                "ok": ok,
                                "error": last_err,
                            })
                        except Exception:
                            pass
                        if ok:
                            break

                for n in uploaded_image_input_filenames:
                    _try_delete(n, "img2img_input")
                for n in uploaded_image_input_requested_names:
                    _try_delete(n, "img2img_input_requested")

                # 마지막 안전장치:
                # ComfyUI가 업로드 파일명에 (1) 같은 접미사를 붙이거나, 반환값 파싱이 어긋나는 경우가 있습니다.
                # 우리 쪽 업로드 파일명에는 job.id(uuid hex)가 포함되므로, input 폴더에서 job.id가 들어간 파일을
                # 추가로 찾아 정리합니다.
                try:
                    jid = getattr(job, "id", None)
                    if isinstance(jid, str) and jid:
                        removed = 0
                        for name in os.listdir(COMFY_INPUT_DIR):
                            try:
                                if not isinstance(name, str) or not name:
                                    continue
                                low = name.lower()
                                if (jid.lower() in low) and (low.endswith(".png") or low.endswith(".webp") or low.endswith(".jpg") or low.endswith(".jpeg")):
                                    _try_delete(name, "sweep_by_job_id")
                                    removed += 1
                            except Exception:
                                continue
                        try:
                            logger.info({"event": "comfy_input_cleanup_sweep_done", "job_id": jid, "removed_candidates": removed})
                        except Exception:
                            pass
                except Exception:
                    pass
        except Exception:
            pass


