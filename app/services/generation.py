import os
import time
import json
from typing import Callable

from ..logging_utils import setup_logging
from ..config import WORKFLOW_CONFIGS, get_workflow_default_prompt
from .media_store import (
    _save_image_and_meta,
    _save_game_ui_group,
    _build_web_path,
)


logger = setup_logging()


def run_generation_processor(job, progress_cb: Callable[[float], None], set_cancel_handle: Callable[[Callable[[], bool]], None]):
    """Heavyweight generation processor extracted from main.

    - Uses set_cancel_handle to register provider cancellation back with JobManager.
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
            # Include optional image-to-image fields
            self.input_image_id = d.get("input_image_id")
            self.input_image_ids = d.get("input_image_ids")
            self.input_image_filename = d.get("input_image_filename")
            # Game UI element maker fields
            self.game_ui_background_mode = d.get("game_ui_background_mode")
            self.game_ui_grid = d.get("game_ui_grid")

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

    # --- Provider routing ---
    wf_cfg = WORKFLOW_CONFIGS.get(request.workflow_id, {}) if isinstance(WORKFLOW_CONFIGS, dict) else {}
    provider = (wf_cfg.get("provider", "") if isinstance(wf_cfg, dict) else "") or ""
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

        # --- Hidden reference images (tool workflows): auto-switch to image-edit even on txt2img ---
        hidden_ref_bytes_list: list[bytes] | None = None
        try:
            hidden_paths = wf_cfg.get("openrouter_hidden_reference_images") if isinstance(wf_cfg, dict) else None
        except Exception:
            hidden_paths = None
        try:
            if is_txt2img and isinstance(hidden_paths, list) and hidden_paths:
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

            game_ui_options = normalize_game_ui_options(
                getattr(request, "game_ui_background_mode", None),
                getattr(request, "game_ui_grid", None),
            )
            request.game_ui_background_mode = game_ui_options.background_mode
            request.game_ui_grid = game_ui_options.grid
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

            if hidden_ref_bytes_list or game_ui_reference_bytes_list:
                # Auto-switch to image-edit when we have any attached reference images.
                if hidden_ref_bytes_list:
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
                source_job_id=job.id,
            )
            job.result["image_path"] = web_path
            job.result["asset_group"] = asset_group
        else:
            saved_image_path, _ = _save_image_and_meta(
                job.owner_id,
                image_bytes,
                request,
                f"openrouter:{chosen_model or 'image'}",
                source_job_id=job.id,
            )
            web_path = _build_web_path(saved_image_path)
            job.result["image_path"] = web_path
        progress_cb(100)
        return

    raise RuntimeError(
        f"지원하지 않는 워크플로우 provider입니다: {provider or 'unknown'}. "
        "현재는 OpenRouter 워크플로우만 실행할 수 있습니다."
    )
