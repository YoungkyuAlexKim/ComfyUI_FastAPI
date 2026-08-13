"""Operational readiness checks for browser principal identity migration."""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import json
import os
from pathlib import Path
from typing import Any

from .asset_admin import _principal_secret_bytes, _verify_backup


_IDENTITY_EVENT = "principal_identity_cookie_issued"


def _parse_timestamp(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _scan_identity_logs(log_dir: str | Path) -> dict[str, Any]:
    root = Path(log_dir).resolve()
    counts: Counter[str] = Counter()
    first_log_timestamp: datetime | None = None
    last_log_timestamp: datetime | None = None
    last_legacy_timestamp: datetime | None = None
    parsed_records = 0
    files = 0
    seen_identity_events: set[tuple[object, ...]] = set()
    if root.is_dir():
        for path in sorted(root.glob("*.log*")):
            if not path.is_file():
                continue
            files += 1
            try:
                lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
            except OSError:
                continue
            for line in lines:
                try:
                    record = json.loads(line)
                except (json.JSONDecodeError, TypeError):
                    continue
                if not isinstance(record, dict):
                    continue
                stamp = _parse_timestamp(record.get("ts"))
                if stamp is not None:
                    parsed_records += 1
                    if first_log_timestamp is None or stamp < first_log_timestamp:
                        first_log_timestamp = stamp
                    if last_log_timestamp is None or stamp > last_log_timestamp:
                        last_log_timestamp = stamp
                if record.get("event") != _IDENTITY_EVENT:
                    continue
                source = str(record.get("identity_source") or "unknown")
                fingerprint = (
                    record.get("ts"),
                    source,
                    record.get("principal_hash"),
                )
                if fingerprint in seen_identity_events:
                    continue
                seen_identity_events.add(fingerprint)
                counts[source] += 1
                if source == "legacy_cookie" and stamp is not None:
                    if last_legacy_timestamp is None or stamp > last_legacy_timestamp:
                        last_legacy_timestamp = stamp
    return {
        "directory": str(root),
        "files": files,
        "parsed_records": parsed_records,
        "first_log_timestamp": first_log_timestamp,
        "last_log_timestamp": last_log_timestamp,
        "last_legacy_timestamp": last_legacy_timestamp,
        "identity_sources": dict(sorted(counts.items())),
        "identity_events": sum(counts.values()),
    }


def principal_readiness(
    *,
    log_dir: str | Path = "logs",
    observation_days: int = 14,
    quiet_days: int = 7,
    backup: str | Path | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Evaluate evidence for a compat -> enforced transition without changing it."""

    observation_days = max(1, int(observation_days))
    quiet_days = max(1, min(int(quiet_days), observation_days))
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    scanned = _scan_identity_logs(log_dir)
    first = scanned.pop("first_log_timestamp")
    last = scanned.pop("last_log_timestamp")
    last_legacy = scanned.pop("last_legacy_timestamp")
    coverage_days = max(0.0, (current - first).total_seconds() / 86400) if first else 0.0
    if last_legacy is not None:
        legacy_quiet_for_days = max(0.0, (current - last_legacy).total_seconds() / 86400)
    else:
        legacy_quiet_for_days = coverage_days

    secret_valid = False
    secret_source = None
    secret_error = None
    try:
        secret_bytes, secret_source = _principal_secret_bytes()
        secret_valid = len(secret_bytes) >= 32
    except Exception as exc:
        secret_error = str(exc)

    backup_verified = False
    backup_error = None
    backup_path = None
    if backup is not None:
        backup_path = str(Path(backup).resolve())
        try:
            backup_verified = bool(_verify_backup(backup_path).get("ok"))
        except Exception as exc:
            backup_error = str(exc)

    mode = str(os.getenv("PRINCIPAL_IDENTITY_MODE", "compat") or "compat").strip().lower()
    legacy_header_enabled = str(os.getenv("ALLOW_LEGACY_ANON_HEADER", "false") or "false").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    log_coverage_ready = coverage_days >= observation_days
    legacy_quiet_ready = legacy_quiet_for_days >= quiet_days
    technical_ready = secret_valid and not legacy_header_enabled and mode in {"compat", "enforced"}
    ready = technical_ready and log_coverage_ready and legacy_quiet_ready and backup_verified

    blockers: list[str] = []
    if not secret_valid:
        blockers.append("principal_cookie_secret_invalid")
    if legacy_header_enabled:
        blockers.append("legacy_anon_header_enabled")
    if not log_coverage_ready:
        blockers.append("observation_window_incomplete")
    if not legacy_quiet_ready:
        blockers.append("recent_legacy_cookie_upgrade")
    if not backup_verified:
        blockers.append("verified_complete_backup_required")

    return {
        "ok": True,
        "mode": mode,
        "checked_at": current.isoformat(),
        "policy": {"observation_days": observation_days, "quiet_days": quiet_days},
        "secret": {
            "valid": secret_valid,
            "source": secret_source,
            "error": secret_error,
        },
        "legacy_header_enabled": legacy_header_enabled,
        "logs": {
            **scanned,
            "first_timestamp": first.isoformat() if first else None,
            "last_timestamp": last.isoformat() if last else None,
            "last_legacy_timestamp": last_legacy.isoformat() if last_legacy else None,
            "coverage_days": round(coverage_days, 3),
            "legacy_quiet_for_days": round(legacy_quiet_for_days, 3),
        },
        "backup": {
            "path": backup_path,
            "verified": backup_verified,
            "error": backup_error,
        },
        "technical_ready": technical_ready,
        "ready_for_enforced": ready,
        "blockers": blockers,
        "operator_review_required": True,
        "note": (
            "Log evidence covers active clients only; review support/user activity before changing mode."
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Browser principal migration operations")
    sub = parser.add_subparsers(dest="command", required=True)
    readiness = sub.add_parser("readiness", help="Assess compat -> enforced transition evidence")
    readiness.add_argument("--log-dir", default="logs")
    readiness.add_argument("--observation-days", type=int, default=14)
    readiness.add_argument("--quiet-days", type=int, default=7)
    readiness.add_argument("--backup")
    readiness.add_argument("--require-ready", action="store_true")
    args = parser.parse_args()

    result = principal_readiness(
        log_dir=args.log_dir,
        observation_days=args.observation_days,
        quiet_days=args.quiet_days,
        backup=args.backup,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if args.require_ready and not result["ready_for_enforced"]:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
