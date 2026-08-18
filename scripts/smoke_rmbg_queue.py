"""Run two real RMBG jobs against an isolated app and verify local-lane serialization."""

from __future__ import annotations

from io import BytesIO
import json
import os
from pathlib import Path
import tempfile
import time
import uuid

from PIL import Image, ImageDraw


def _source_png_bytes() -> bytes:
    image = Image.new("RGB", (256, 256), "white")
    draw = ImageDraw.Draw(image)
    draw.ellipse((44, 28, 212, 196), fill=(40, 100, 210))
    draw.rectangle((82, 150, 174, 242), fill=(220, 70, 60))
    output = BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="lc-canvas-rmbg-queue-") as directory:
        root = Path(directory)
        output_root = root / "outputs"
        output_root.mkdir()
        os.environ.update(
            {
                "JOB_DB_PATH": str(root / "app_data.db"),
                "OUTPUT_DIR": str(output_root),
                "PRINCIPAL_COOKIE_SECRET": "rmbg-queue-smoke-" + ("x" * 48),
                "LOG_TO_FILE": "false",
                "MCP_ALLOWED_CLIENT_CIDRS": "",
                "ASSET_CATALOG_FALLBACK_ENABLED": "false",
            }
        )

        from fastapi.testclient import TestClient

        from app.main import app, generation_controls

        request_id = 0
        protocol_headers = {
            "Accept": "application/json, text/event-stream",
            "MCP-Protocol-Version": "2025-06-18",
        }

        def rpc(client: TestClient, method: str, params: dict) -> dict:
            nonlocal request_id
            request_id += 1
            response = client.post(
                "/mcp/",
                headers=protocol_headers,
                json={"jsonrpc": "2.0", "id": request_id, "method": method, "params": params},
            )
            response.raise_for_status()
            payload = response.json()
            if payload.get("error"):
                raise RuntimeError(json.dumps(payload["error"], ensure_ascii=False))
            return payload["result"]

        def call_tool(client: TestClient, name: str, arguments: dict) -> tuple[dict, dict]:
            result = rpc(client, "tools/call", {"name": name, "arguments": arguments})
            if result.get("isError"):
                raise RuntimeError(json.dumps(result, ensure_ascii=False))
            return result["structuredContent"], result

        with TestClient(app) as client:
            rpc(
                client,
                "initialize",
                {
                    "protocolVersion": "2025-06-18",
                    "capabilities": {},
                    "clientInfo": {"name": "rmbg-queue-smoke", "version": "1.0"},
                },
            )
            upload = client.post(
                "/api/v1/mcp/inputs/upload",
                files={
                    "file": (
                        "rmbg-queue-source.png",
                        _source_png_bytes(),
                        "image/png",
                    )
                },
            )
            upload.raise_for_status()
            image_id = upload.json()["asset_id"]

            plans = []
            for _ in range(2):
                plan, _ = call_tool(
                    client,
                    "plan_generation",
                    {
                        "capability": "remove_background",
                        "reference_image_ids": [image_id],
                        "options": {"mask_blur": 0, "mask_offset": 0},
                        "selection_mode": "clarify",
                    },
                )
                if plan.get("ready_to_generate") is not True:
                    raise RuntimeError(json.dumps(plan, ensure_ascii=False))
                plans.append(plan)

            submissions = []
            for plan in plans:
                arguments = dict(plan["tool_arguments"])
                arguments.update(
                    {
                        "plan_id": plan["plan_id"],
                        "idempotency_key": f"rmbg-queue-{uuid.uuid4().hex}",
                    }
                )
                submitted, _ = call_tool(client, "remove_background", arguments)
                submissions.append(submitted)

            immediate = []
            for submission in submissions:
                status, _ = call_tool(
                    client, "get_generation_job", {"job_id": submission["job_id"]}
                )
                immediate.append(status["status"])

            completed = []
            for submission in submissions:
                deadline = time.monotonic() + 60
                while True:
                    status, _ = call_tool(
                        client, "get_generation_job", {"job_id": submission["job_id"]}
                    )
                    if status["status"] in {"complete", "error", "cancelled"}:
                        break
                    if time.monotonic() >= deadline:
                        raise TimeoutError(f"RMBG job timed out: {submission['job_id']}")
                    time.sleep(0.1)
                if status["status"] != "complete":
                    raise RuntimeError(json.dumps(status, ensure_ascii=False))
                completed.append(status)

            image_blocks = 0
            for submission in submissions:
                structured, raw = call_tool(
                    client, "get_generation_result", {"job_id": submission["job_id"]}
                )
                if not structured.get("ready"):
                    raise RuntimeError(json.dumps(structured, ensure_ascii=False))
                blocks = [block for block in raw.get("content", []) if block.get("type") == "image"]
                if not blocks:
                    raise RuntimeError("Completed RMBG result did not include MCP image content")
                preview = blocks[0]
                if preview.get("mimeType") != "image/webp":
                    raise RuntimeError("Completed RMBG result did not include the compact WEBP preview")
                if "user" not in ((preview.get("annotations") or {}).get("audience") or []):
                    raise RuntimeError("Completed RMBG preview was not annotated for the user")
                text_blocks = [block for block in raw.get("content", []) if block.get("type") == "text"]
                if not any("[Open image in LC AI Canvas](" in str(block.get("text") or "") for block in text_blocks):
                    raise RuntimeError("Completed RMBG result did not include the clickable image fallback")
                presentation = structured.get("presentation") or {}
                if presentation.get("required") is not True:
                    raise RuntimeError("Completed RMBG result did not require user-visible presentation")
                if presentation.get("preferred") != "download_then_native_image_viewer":
                    raise RuntimeError("Completed RMBG result did not include the native image presentation contract")
                if presentation.get("tool_result_visibility_is_user_visibility") is not False:
                    raise RuntimeError("Completed RMBG result incorrectly treated tool visibility as user visibility")
                if presentation.get("regenerate_for_preview") is not False:
                    raise RuntimeError("Completed RMBG result did not forbid regeneration for preview")
                image_blocks += len(blocks)

            first, second = completed
            serial = float(second["started_at"]) >= float(first["ended_at"])
            if not serial:
                raise RuntimeError("RMBG jobs overlapped on the local ComfyUI lane")

            report = generation_controls.cost_report(days=1, capability="remove_background")
            summary = report["summary"]
            if summary["actual_cost_record_count"] != 2 or summary["missing_actual_cost_count"] != 0:
                raise RuntimeError(json.dumps(summary, ensure_ascii=False))

            observation = {
                "ok": True,
                "submitted_statuses": [item["status"] for item in submissions],
                "immediate_statuses": immediate,
                "job_ids": [item["job_id"] for item in submissions],
                "durations_seconds": [
                    round(float(item["ended_at"]) - float(item["started_at"]), 3)
                    for item in completed
                ],
                "second_started_after_first_ended": serial,
                "gap_seconds": round(float(second["started_at"]) - float(first["ended_at"]), 3),
                "mcp_image_blocks": image_blocks,
                "provider_api_actual_cost_usd": summary["actual_cost_usd"],
                "actual_cost_record_count": summary["actual_cost_record_count"],
                "missing_actual_cost_count": summary["missing_actual_cost_count"],
                "temporary_outputs_removed_on_exit": True,
            }
            print(json.dumps(observation, ensure_ascii=False))


if __name__ == "__main__":
    main()
