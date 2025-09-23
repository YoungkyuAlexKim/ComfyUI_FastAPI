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

    # Apply multi-control overrides
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
                start_pct = float(defaults.get("start_percent", 0.0))
                end_pct = float(defaults.get("end_percent", 0.33))
                for mc in multi_controls:
                    slot = mc.get("slot")
                    mapping = slots_cfg.get(slot) if isinstance(slots_cfg, dict) else None
                    if not mapping:
                        continue
                    apply_node = mapping.get("apply_node")
                    image_node = mapping.get("image_node")
                    strength = float(mc.get("strength", 1.0))
                    image_filename = mc.get("image_filename")
                    if apply_node:
                        prompt_overrides[apply_node] = {
                            "inputs": {
                                "strength": strength,
                                "start_percent": start_pct,
                                "end_percent": end_pct,
                            }
                        }
                    if image_node and image_filename:
                        prompt_overrides[image_node] = {"inputs": {"image": image_filename}}
    except Exception:
        pass

    # Gate: if control enabled, ensure image override present
    try:
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
            if not (has_single or has_override or has_multi):
                logger.info({
                    "event": "controlnet_gate_failed",
                    "owner_id": job.owner_id,
                    "job_id": job.id,
                    "reason": "no image override present",
                    "control_enabled": True,
                    "image_node": image_node,
                    "overrides_keys": list(prompt_overrides.keys()) if isinstance(prompt_overrides, dict) else None,
                })
                raise RuntimeError("ControlNet image not prepared. Please re-select the control image and try again.")
    except Exception:
        pass

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
                            stored = client.upload_image_to_input(f"{img_id}_{job.id}.png", data, "image/png")
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
                if uploaded_input_filename:
                    try:
                        candidate = os.path.join(COMFY_INPUT_DIR, uploaded_input_filename)
                        if os.path.exists(candidate):
                            os.remove(candidate)
                    except Exception:
                        pass
                if uploaded_image_input_filename:
                    try:
                        candidate2 = os.path.join(COMFY_INPUT_DIR, uploaded_image_input_filename)
                        if os.path.exists(candidate2):
                            os.remove(candidate2)
                    except Exception:
                        pass
                try:
                    for fname in list(uploaded_multi_filenames):
                        if not fname:
                            continue
                        try:
                            candidate = os.path.join(COMFY_INPUT_DIR, fname)
                            if os.path.exists(candidate):
                                os.remove(candidate)
                        except Exception:
                            continue
                except Exception:
                    pass
        except Exception:
            pass


