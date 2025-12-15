import os
import time
from typing import Callable, List, Optional

from ..logging_utils import setup_logging
from ..comfy_client import ComfyUIClient
from ..config import SERVER_CONFIG, WORKFLOW_CONFIGS, get_prompt_overrides, COMFY_INPUT_DIR
from .media_store import (
    _locate_control_png_path,
    _save_image_and_meta,
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
            self.control_enabled = d.get("control_enabled")
            self.control_image_id = d.get("control_image_id")
            self.controls = d.get("controls")
            # Include optional image-to-image fields
            self.input_image_id = d.get("input_image_id")
            self.input_image_filename = d.get("input_image_filename")

    request = _Req(req_dict)
    try:
        logger.info({
            "event": "gen_request",
            "job_id": job.id,
            "owner_id": job.owner_id,
            "workflow_id": getattr(request, "workflow_id", None),
            "input_image_id": getattr(request, "input_image_id", None),
            "input_image_filename": getattr(request, "input_image_filename", None),
        })
    except Exception:
        pass
    workflow_path = os.path.join(WORKFLOW_DIR, f"{request.workflow_id}.json")
    control = None
    multi_controls: List[dict] = []
    uploaded_multi_filenames: List[str] = []
    uploaded_input_filename: Optional[str] = None  # control single
    uploaded_image_input_filename: Optional[str] = None  # image_input single
    uploaded_image_input_requested_name: Optional[str] = None

    # Prepare ControlNet overrides if enabled
    try:
        if getattr(request, "control_enabled", None):
            wf_cfg = WORKFLOW_CONFIGS.get(request.workflow_id, {}) if isinstance(WORKFLOW_CONFIGS, dict) else {}
            slots_cfg = wf_cfg.get("control_slots") if isinstance(wf_cfg, dict) else None
            provided_controls = []
            try:
                if isinstance(req_dict.get("controls"), list):
                    provided_controls = [c for c in req_dict["controls"] if isinstance(c, dict) and c.get("slot") and c.get("image_id")]
            except Exception:
                provided_controls = []

            if slots_cfg and provided_controls:
                anon_id = job.owner_id
                client_tmp = ComfyUIClient(SERVER_ADDRESS)
                for item in provided_controls:
                    slot = str(item.get("slot"))
                    image_id = str(item.get("image_id"))
                    if slot not in slots_cfg:
                        continue
                    local_png = _locate_control_png_path(anon_id, image_id)
                    if not local_png or not os.path.exists(local_png):
                        continue
                    try:
                        with open(local_png, "rb") as f:
                            data = f.read()
                        stored = None
                        for _attempt in range(3):
                            try:
                                stored = client_tmp.upload_image_to_input(f"{image_id}_{job.id}.png", data, "image/png")
                                if isinstance(stored, str) and stored:
                                    break
                            except Exception:
                                time.sleep(0.15)
                        if isinstance(stored, str) and stored:
                            try:
                                _ = _wait_for_input_visibility(stored, timeout_sec=1.5, poll_ms=50)
                            except Exception:
                                pass
                            multi_controls.append({
                                "slot": slot,
                                "image_filename": stored,
                                "strength": 1.0,
                            })
                            try:
                                uploaded_multi_filenames.append(stored)
                            except Exception:
                                pass
                            try:
                                time.sleep(0.1)
                            except Exception:
                                pass
                        else:
                            logger.info({"event": "controlnet_upload_failed_multi", "job_id": job.id, "owner_id": job.owner_id, "slot": slot, "error": "upload returned empty"})
                    except Exception as e:
                        logger.info({"event": "controlnet_upload_failed_multi", "job_id": job.id, "owner_id": job.owner_id, "slot": slot, "error": str(e)})
                control = None
            else:
                control = {"strength": 0.0}
                if isinstance(request.control_image_id, str) and len(request.control_image_id) > 0:
                    anon_id = job.owner_id
                    local_png = _locate_control_png_path(anon_id, request.control_image_id)
                    if local_png and os.path.exists(local_png):
                        try:
                            with open(local_png, "rb") as f:
                                data = f.read()
                            client_tmp = ComfyUIClient(SERVER_ADDRESS)
                            stored = None
                            for _attempt in range(3):
                                try:
                                    stored = client_tmp.upload_image_to_input(f"{request.control_image_id}_{job.id}.png", data, "image/png")
                                    if isinstance(stored, str) and stored:
                                        break
                                except Exception:
                                    time.sleep(0.15)
                            if isinstance(stored, str) and stored:
                                try:
                                    _ = _wait_for_input_visibility(stored, timeout_sec=1.5, poll_ms=50)
                                except Exception:
                                    pass
                                uploaded_input_filename = stored
                                control = {"strength": 1.0, "image_filename": stored}
                                try:
                                    time.sleep(0.1)
                                except Exception:
                                    pass
                            else:
                                logger.info({"event": "controlnet_upload_failed", "job_id": job.id, "owner_id": job.owner_id, "error": "upload returned empty"})
                        except Exception as e:
                            logger.info({"event": "controlnet_upload_failed", "job_id": job.id, "owner_id": job.owner_id, "error": str(e)})
                            pass
        else:
            control = {"strength": 0.0}
    except Exception:
        control = None

    prompt_overrides = get_prompt_overrides(
        user_prompt=getattr(request, "user_prompt", ""),
        aspect_ratio=getattr(request, "aspect_ratio", "square"),
        workflow_name=getattr(request, "workflow_id", "BasicWorkFlow_PixelArt"),
        seed=getattr(request, "seed", None),
        control=control,
    )

    # --- Optional: LoRA per-slot strengths override ---
    try:
        loras_req = req_dict.get("loras") if isinstance(req_dict, dict) else None
        if isinstance(loras_req, list) and loras_req:
            wf_cfg = WORKFLOW_CONFIGS.get(request.workflow_id, {}) if isinstance(WORKFLOW_CONFIGS, dict) else {}
            lora_map = wf_cfg.get("loras") if isinstance(wf_cfg, dict) else None
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

    # Diagnostics: final control application intent
    try:
        cn_cfg = WORKFLOW_CONFIGS.get(request.workflow_id, {}).get("controlnet")
        apply_node = cn_cfg.get("apply_node") if isinstance(cn_cfg, dict) else None
        image_node = cn_cfg.get("image_node") if isinstance(cn_cfg, dict) else None
        logger.info({
            "event": "controlnet_final_overrides",
            "owner_id": job.owner_id,
            "job_id": job.id,
            "control_enabled": bool(getattr(request, "control_enabled", False)),
            "control_image_id": getattr(request, "control_image_id", None),
            "single_image": (control or {}).get("image_filename") if isinstance(control, dict) else None,
            "multi_count": len(multi_controls),
            "apply_node_inputs": (prompt_overrides.get(apply_node, {}) if apply_node else {}),
            "image_node_inputs": (prompt_overrides.get(image_node, {}) if image_node else {}),
        })
    except Exception:
        pass

    # Apply multi-control overrides (with per-slot params)
    try:
        if multi_controls:
            wf_cfg = WORKFLOW_CONFIGS.get(request.workflow_id, {}) if isinstance(WORKFLOW_CONFIGS, dict) else {}
            slots_cfg = wf_cfg.get("control_slots") if isinstance(wf_cfg, dict) else None
            defaults = {}
            try:
                defaults = wf_cfg.get("controlnet", {}).get("defaults", {}) or {}
            except Exception:
                defaults = {}
            if slots_cfg and isinstance(prompt_overrides, dict):
                for mc in multi_controls:
                    slot = mc.get("slot")
                    mapping = slots_cfg.get(slot) if isinstance(slots_cfg, dict) else None
                    if not mapping:
                        continue
                    apply_node = mapping.get("apply_node")
                    image_node = mapping.get("image_node")
                    image_filename = mc.get("image_filename")
                    # Per-slot UI defaults (optional)
                    ui_cfg = (mapping.get("ui") if isinstance(mapping, dict) else {}) or {}
                    def _d(key, fallback):
                        try:
                            return float(((ui_cfg.get(key) or {}).get("default")))
                        except Exception:
                            return float(fallback)
                    start_def = _d("start_percent", defaults.get("start_percent", 0.0))
                    end_def = _d("end_percent", defaults.get("end_percent", 0.33))
                    strength_def = _d("strength", defaults.get("strength", 0.0))
                    # If request.controls contains this slot, use its params
                    req_strength = None
                    req_start = None
                    req_end = None
                    try:
                        if isinstance(req_dict.get("controls"), list):
                            for it in req_dict["controls"]:
                                if isinstance(it, dict) and it.get("slot") == slot:
                                    if "strength" in it and isinstance(it["strength"], (int, float)):
                                        req_strength = float(it["strength"]) 
                                    if "start_percent" in it and isinstance(it["start_percent"], (int, float)):
                                        req_start = float(it["start_percent"]) 
                                    if "end_percent" in it and isinstance(it["end_percent"], (int, float)):
                                        req_end = float(it["end_percent"]) 
                                    break
                    except Exception:
                        pass
                    # Clamp and compose, force strength=0 if no image_filename
                    def _clamp(v, lo, hi, default_v):
                        try:
                            x = float(v) if v is not None else float(default_v)
                            return max(float(lo), min(float(hi), x))
                        except Exception:
                            return float(default_v)
                    # Resolve ranges
                    def _range_of(key, fallback_min, fallback_max):
                        try:
                            cfg = ui_cfg.get(key) or {}
                            lo = float(cfg.get("min", fallback_min))
                            hi = float(cfg.get("max", fallback_max))
                            return (lo, hi)
                        except Exception:
                            return (fallback_min, fallback_max)
                    s_lo, s_hi = _range_of("strength", 0.0, 1.5)
                    p_lo, p_hi = _range_of("start_percent", 0.0, 1.0)
                    e_lo, e_hi = _range_of("end_percent", 0.0, 1.0)
                    strength_val = _clamp(req_strength, s_lo, s_hi, strength_def)
                    start_val = _clamp(req_start, p_lo, p_hi, start_def)
                    end_val = _clamp(req_end, e_lo, e_hi, end_def)
                    if not image_filename:
                        strength_val = 0.0
                    # Ensure start <= end
                    if start_val > end_val:
                        start_val, end_val = end_val, start_val
                    if apply_node:
                        prompt_overrides[apply_node] = {
                            "inputs": {
                                "strength": strength_val,
                                "start_percent": start_val,
                                "end_percent": end_val,
                            }
                        }
                    if image_node and image_filename:
                        prompt_overrides[image_node] = {"inputs": {"image": image_filename}}
    except Exception:
        pass

    # Gate: if control enabled, ensure image override present (strict)
    if getattr(request, "control_enabled", False):
        wf_cfg = WORKFLOW_CONFIGS.get(request.workflow_id, {}) if isinstance(WORKFLOW_CONFIGS, dict) else {}
        cn_cfg = wf_cfg.get("controlnet") if isinstance(wf_cfg, dict) else None
        image_node = cn_cfg.get("image_node") if isinstance(cn_cfg, dict) else None
        has_single = bool(isinstance(control, dict) and control.get("image_filename"))
        has_override = bool(
            image_node and isinstance(prompt_overrides, dict) and image_node in prompt_overrides and
            isinstance(prompt_overrides[image_node], dict) and isinstance(prompt_overrides[image_node].get("inputs"), dict) and
            prompt_overrides[image_node]["inputs"].get("image")
        )
        has_multi = bool(multi_controls)
        # Relaxed gating: if enabled but no image, we keep strength at 0 and proceed

    # Debug logging for ControlNet application
    try:
        cn_cfg = WORKFLOW_CONFIGS.get(request.workflow_id, {}).get("controlnet")
        apply_node = cn_cfg.get("apply_node") if isinstance(cn_cfg, dict) else None
        image_node = cn_cfg.get("image_node") if isinstance(cn_cfg, dict) else None
        logger.info({
            "event": "controlnet_overrides",
            "owner_id": job.owner_id,
            "job_id": job.id,
            "control_enabled": bool(getattr(request, "control_enabled", False)),
            "control_image_id": getattr(request, "control_image_id", None),
            "uploaded_input_filename": uploaded_input_filename,
            "apply_node_inputs": (prompt_overrides.get(apply_node, {}) if apply_node else {}),
            "image_node_inputs": (prompt_overrides.get(image_node, {}) if image_node else {}),
        })
    except Exception:
        pass

    client = ComfyUIClient(SERVER_ADDRESS)
    # Allow cancellation from job manager via provided setter
    try:
        set_cancel_handle(client.interrupt)
    except Exception:
        pass

    try:
        # --- Optional: image-to-image workflow handling ---
        wf_cfg = WORKFLOW_CONFIGS.get(request.workflow_id, {}) if isinstance(WORKFLOW_CONFIGS, dict) else {}
        io_cfg = wf_cfg.get("image_input") if isinstance(wf_cfg, dict) else None
        # image_input: { image_node: str (node_id), input_field: str (default 'image') }
        # Support: request.input_image_id (user gallery/controls saved PNG) or request.input_image_filename (already uploaded to Comfy)
        if io_cfg and isinstance(io_cfg, dict):
            image_node = io_cfg.get("image_node")
            input_field = io_cfg.get("input_field", "image")
            image_filename = None
            resolve_source = None
            # If request has input_image_filename already uploaded to Comfy input, use it
            try:
                image_filename = getattr(request, "input_image_filename", None)
            except Exception:
                image_filename = None
            if image_filename:
                resolve_source = "preuploaded"
            # Else, if request.input_image_id refers to user input/gallery/control PNG, upload it
            if not image_filename:
                try:
                    img_id = getattr(request, "input_image_id", None)
                except Exception:
                    img_id = None
                if isinstance(img_id, str) and img_id:
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
                    # 3) controls
                    if not local_png:
                        local_png = _locate_control_png_path(job.owner_id, img_id)
                        if local_png:
                            resolve_source = "controls"
                    try:
                        logger.info({
                            "event": "image_input_resolved",
                            "job_id": job.id,
                            "owner_id": job.owner_id,
                            "input_image_id": img_id,
                            "local_png": local_png,
                            "source": resolve_source,
                        })
                    except Exception:
                        pass
                    if local_png and os.path.exists(local_png):
                        try:
                            with open(local_png, "rb") as f:
                                data = f.read()
                            req_name = f"{img_id}_{job.id}.png"
                            uploaded_image_input_requested_name = req_name
                            stored = client.upload_image_to_input(req_name, data, "image/png")
                            if isinstance(stored, str) and stored:
                                try:
                                    _ = _wait_for_input_visibility(stored, timeout_sec=1.5, poll_ms=50)
                                except Exception:
                                    pass
                                image_filename = stored
                                uploaded_image_input_filename = stored
                                try:
                                    logger.info({
                                        "event": "image_input_uploaded",
                                        "job_id": job.id,
                                        "owner_id": job.owner_id,
                                        "stored": stored,
                                        "source": resolve_source,
                                    })
                                except Exception:
                                    pass
                                try:
                                    time.sleep(0.1)
                                except Exception:
                                    pass
                        except Exception as e:
                            try:
                                logger.info({"event": "image_input_upload_failed", "job_id": job.id, "owner_id": job.owner_id, "error": str(e)})
                            except Exception:
                                pass
                    else:
                        # As a fallback, if id looks like a filename already in Comfy input, pass-through
                        try:
                            if (not local_png) and ("/" not in img_id) and ("\\" not in img_id) and img_id.lower().endswith('.png'):
                                image_filename = img_id
                                resolve_source = "filename_passthrough"
                        except Exception:
                            pass
            # Hard gate: when image input is configured, an image must be resolved
            if not image_filename:
                try:
                    logger.info({
                        "event": "image_input_gate_error",
                        "job_id": job.id,
                        "owner_id": job.owner_id,
                        "workflow_id": getattr(request, "workflow_id", None),
                        "reason": "missing_input_image",
                    })
                except Exception:
                    pass
                raise RuntimeError("입력 이미지가 준비되지 않았습니다. 입력 이미지를 선택/업로드 후 다시 시도해 주세요.")

            if image_node and image_filename:
                prompt_overrides[image_node] = {"inputs": {input_field: image_filename}}
                try:
                    logger.info({
                        "event": "image_input_override_set",
                        "job_id": job.id,
                        "owner_id": job.owner_id,
                        "image_node": image_node,
                        "input_field": input_field,
                        "image_filename": image_filename,
                    })
                except Exception:
                    pass

        # Merge additional prompt into target text node if configured (e.g., node 63 for ILXL)
        try:
            wf_cfg2 = WORKFLOW_CONFIGS.get(request.workflow_id, {}) if isinstance(WORKFLOW_CONFIGS, dict) else {}
            ui_cfg = wf_cfg2.get("ui") if isinstance(wf_cfg2, dict) else None
            target_node = ui_cfg.get("additionalPromptTargetNode") if isinstance(ui_cfg, dict) else None
            if target_node and isinstance(target_node, str) and len(target_node) > 0:
                base_text = ""
                try:
                    base_text = wf_cfg2.get("style_prompt", "") or ""
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
                prompt_overrides[target_node] = {"inputs": {"text": merged_text}}
        except Exception:
            pass

        resp = client.queue_prompt(workflow_path, prompt_overrides)
        prompt_id = resp.get('prompt_id') if isinstance(resp, dict) else None
        if not prompt_id:
            raise RuntimeError("Failed to get prompt_id.")

        def on_progress(p: float):
            progress_cb(p)

        images_data = client.get_images(prompt_id, on_progress=on_progress)
        if not images_data:
            raise RuntimeError("Failed to receive generated images.")

        filename = list(images_data.keys())[0]
        image_bytes = list(images_data.values())[0]
        saved_image_path, _ = _save_image_and_meta(job.owner_id, image_bytes, request, filename)
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

                if uploaded_input_filename:
                    _try_delete(uploaded_input_filename, "control_single")
                if uploaded_image_input_filename:
                    _try_delete(uploaded_image_input_filename, "img2img_single")
                if uploaded_image_input_requested_name:
                    _try_delete(uploaded_image_input_requested_name, "img2img_single_requested")
                try:
                    for fname in list(uploaded_multi_filenames):
                        if not fname:
                            continue
                        _try_delete(fname, "control_multi")
                except Exception:
                    pass

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


