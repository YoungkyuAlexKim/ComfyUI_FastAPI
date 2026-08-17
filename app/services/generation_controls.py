"""Operational admission controls and audit storage for generation requests."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import ipaddress
import json
import math
import os
import sqlite3
from contextlib import contextmanager
import time
import uuid
from typing import Any, Mapping
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


DEFAULT_POLICY: dict[str, Any] = {
    "generation_enabled": True,
    "mcp_enabled": True,
    "daily_request_limit": 0,
    "daily_cost_limit_usd": 0.0,
    "cost_confirmation_threshold_usd": 0.0,
    "confirmation_required_capabilities": [],
    "capability_enabled": {},
    "cost_estimates_usd": {},
}


class GenerationPolicyError(RuntimeError):
    def __init__(self, code: str, message: str, *, status_code: int, details: dict[str, Any] | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.details = details or {}

    def api_detail(self) -> dict[str, Any]:
        return {"code": self.code, "message": self.message, **self.details}


@dataclass(frozen=True)
class AdmissionResult:
    control_request_id: str | None
    estimated_cost_usd: float | None
    duplicate_job_id: str | None = None
    duplicate_status: str | None = None

    @property
    def is_duplicate(self) -> bool:
        return bool(self.duplicate_job_id)


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)) or default)
    except (TypeError, ValueError):
        return default


def _env_float(name: str, default: float) -> float:
    try:
        value = float(os.getenv(name, str(default)) or default)
        return value if math.isfinite(value) else default
    except (TypeError, ValueError):
        return default


def _nonnegative_float(value: Any) -> float:
    parsed = float(value or 0)
    if not math.isfinite(parsed):
        raise ValueError("Generation policy values must be finite numbers")
    return max(0.0, parsed)


def _masked_client_ip(value: Any) -> str:
    raw = str(value or "").strip()
    if not raw or raw == "unknown":
        return "(unknown)"
    try:
        address = ipaddress.ip_address(raw)
    except ValueError:
        return raw[:8] + ("…" if len(raw) > 8 else "")
    if address.version == 4:
        parts = raw.split(".")
        return ".".join(parts[:3] + ["x"])
    parts = address.exploded.split(":")
    return ":".join(parts[:3]) + ":…"


class GenerationControlService:
    """Owns policy, atomic daily-limit admission, idempotency, and audit events."""

    def __init__(self, db_path: str, *, timezone_name: str | None = None):
        self.db_path = db_path
        self.timezone_name = timezone_name or os.getenv("GENERATION_CONTROL_TIMEZONE", "Asia/Seoul")
        try:
            self.timezone = ZoneInfo(self.timezone_name)
        except ZoneInfoNotFoundError:
            # Windows Python installations often have no system IANA database.
            # Korea has used a fixed UTC+09:00 offset since 1988, so preserve
            # the intended company day boundary without adding a dependency.
            if self.timezone_name == "Asia/Seoul":
                self.timezone = timezone(timedelta(hours=9), name="Asia/Seoul")
            else:
                self.timezone_name = "UTC"
                self.timezone = timezone.utc
        directory = os.path.dirname(os.path.abspath(db_path))
        if directory:
            os.makedirs(directory, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path, timeout=10.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout=5000")
        return connection

    @contextmanager
    def _managed_connection(self):
        connection = self._connect()
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _init_db(self) -> None:
        with self._managed_connection() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS generation_control_settings (
                    key TEXT PRIMARY KEY,
                    value_json TEXT NOT NULL,
                    updated_at REAL NOT NULL
                );

                CREATE TABLE IF NOT EXISTS generation_control_requests (
                    id TEXT PRIMARY KEY,
                    source TEXT NOT NULL,
                    principal_id TEXT NOT NULL,
                    idempotency_key TEXT NOT NULL,
                    job_id TEXT,
                    day_key TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    status TEXT NOT NULL,
                    client_ip TEXT,
                    capability TEXT NOT NULL,
                    capability_variant TEXT,
                    workflow_id TEXT,
                    provider TEXT,
                    model TEXT,
                    cost_confirmed INTEGER NOT NULL DEFAULT 0,
                    estimated_cost_usd REAL NOT NULL DEFAULT 0,
                    estimated_cost_known INTEGER NOT NULL DEFAULT 0,
                    actual_cost_usd REAL,
                    UNIQUE(source, principal_id, idempotency_key)
                );

                CREATE INDEX IF NOT EXISTS idx_generation_control_requests_day
                    ON generation_control_requests(day_key, status);
                CREATE INDEX IF NOT EXISTS idx_generation_control_requests_job
                    ON generation_control_requests(job_id);
                CREATE INDEX IF NOT EXISTS idx_generation_control_requests_created
                    ON generation_control_requests(created_at, status);
                CREATE INDEX IF NOT EXISTS idx_generation_control_requests_client
                    ON generation_control_requests(client_ip, created_at);

                CREATE TABLE IF NOT EXISTS generation_control_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at REAL NOT NULL,
                    event_type TEXT NOT NULL,
                    decision TEXT,
                    reason_code TEXT,
                    request_id TEXT,
                    job_id TEXT,
                    source TEXT,
                    principal_id TEXT,
                    client_ip TEXT,
                    capability TEXT,
                    workflow_id TEXT,
                    provider TEXT,
                    model TEXT,
                    estimated_cost_usd REAL,
                    actual_cost_usd REAL,
                    details_json TEXT
                );

                CREATE INDEX IF NOT EXISTS idx_generation_control_events_created
                    ON generation_control_events(created_at DESC);
                """
            )
            request_columns = {
                str(row["name"])
                for row in connection.execute("PRAGMA table_info(generation_control_requests)").fetchall()
            }
            if "estimated_cost_known" not in request_columns:
                connection.execute(
                    "ALTER TABLE generation_control_requests "
                    "ADD COLUMN estimated_cost_known INTEGER NOT NULL DEFAULT 0"
                )
            # Legacy non-zero estimates came from an explicit policy match.
            connection.execute(
                """
                UPDATE generation_control_requests
                SET estimated_cost_known = 1
                WHERE estimated_cost_known = 0 AND estimated_cost_usd > 0
                """
            )
            # A completed local ComfyUI workflow has a known external provider
            # API cost of zero.  Record that as an actual value so operations
            # does not misclassify local completions as missing provider cost.
            # GPU, electricity, and infrastructure cost remain out of scope.
            connection.execute(
                """
                UPDATE generation_control_requests
                SET actual_cost_usd = 0
                WHERE status = 'complete'
                  AND actual_cost_usd IS NULL
                  AND LOWER(TRIM(COALESCE(provider, ''))) = 'comfyui'
                """
            )

    def _environment_policy(self) -> dict[str, Any]:
        policy = dict(DEFAULT_POLICY)
        policy.update(
            {
                "generation_enabled": _env_bool("GENERATION_ENABLED", True),
                "mcp_enabled": _env_bool("MCP_GENERATION_ENABLED", True),
                "daily_request_limit": max(0, _env_int("GENERATION_DAILY_REQUEST_LIMIT", 0)),
                "daily_cost_limit_usd": max(0.0, _env_float("GENERATION_DAILY_COST_LIMIT_USD", 0.0)),
                "cost_confirmation_threshold_usd": max(
                    0.0, _env_float("GENERATION_COST_CONFIRMATION_THRESHOLD_USD", 0.0)
                ),
            }
        )
        try:
            estimates = json.loads(os.getenv("GENERATION_COST_ESTIMATES_JSON", "{}") or "{}")
            if isinstance(estimates, dict):
                policy["cost_estimates_usd"] = estimates
        except (TypeError, ValueError, json.JSONDecodeError):
            pass
        return policy

    def get_policy(self) -> dict[str, Any]:
        environment_policy = self._environment_policy()
        policy = dict(environment_policy)
        with self._managed_connection() as connection:
            rows = connection.execute("SELECT key, value_json FROM generation_control_settings").fetchall()
        for row in rows:
            if row["key"] not in DEFAULT_POLICY:
                continue
            try:
                policy[row["key"]] = json.loads(row["value_json"])
            except (TypeError, ValueError, json.JSONDecodeError):
                continue
        normalized = self._normalize_policy(policy)
        # Environment kill switches are hard stops and cannot be re-enabled
        # accidentally by a previously persisted admin setting.
        normalized["generation_enabled"] = bool(
            normalized["generation_enabled"] and environment_policy["generation_enabled"]
        )
        normalized["mcp_enabled"] = bool(normalized["mcp_enabled"] and environment_policy["mcp_enabled"])
        return normalized

    def update_policy(self, changes: Mapping[str, Any]) -> dict[str, Any]:
        unknown = set(changes) - set(DEFAULT_POLICY)
        if unknown:
            raise ValueError(f"Unknown generation policy fields: {sorted(unknown)}")
        merged = self.get_policy()
        merged.update(dict(changes))
        normalized = self._normalize_policy(merged)
        now = time.time()
        with self._managed_connection() as connection:
            for key in changes:
                connection.execute(
                    """
                    INSERT INTO generation_control_settings (key, value_json, updated_at)
                    VALUES (?, ?, ?)
                    ON CONFLICT(key) DO UPDATE SET
                        value_json=excluded.value_json,
                        updated_at=excluded.updated_at
                    """,
                    (key, json.dumps(normalized[key], ensure_ascii=False), now),
                )
            self._event(
                connection,
                event_type="policy_updated",
                decision="updated",
                details={"fields": sorted(changes)},
            )
        return self.get_policy()

    def _normalize_policy(self, policy: Mapping[str, Any]) -> dict[str, Any]:
        normalized = dict(DEFAULT_POLICY)
        normalized.update(dict(policy))
        normalized["generation_enabled"] = bool(normalized["generation_enabled"])
        normalized["mcp_enabled"] = bool(normalized["mcp_enabled"])
        normalized["daily_request_limit"] = max(0, int(normalized["daily_request_limit"] or 0))
        normalized["daily_cost_limit_usd"] = _nonnegative_float(normalized["daily_cost_limit_usd"])
        normalized["cost_confirmation_threshold_usd"] = _nonnegative_float(
            normalized["cost_confirmation_threshold_usd"]
        )
        required = normalized.get("confirmation_required_capabilities")
        normalized["confirmation_required_capabilities"] = sorted(
            {str(value).strip() for value in required or [] if str(value).strip()}
        )
        capability_enabled = normalized.get("capability_enabled")
        normalized["capability_enabled"] = {
            str(key).strip(): bool(value)
            for key, value in (capability_enabled.items() if isinstance(capability_enabled, dict) else [])
            if str(key).strip()
        }
        estimates = normalized.get("cost_estimates_usd")
        clean_estimates: dict[str, float] = {}
        for key, value in (estimates.items() if isinstance(estimates, dict) else []):
            try:
                clean_estimates[str(key).strip()] = _nonnegative_float(value)
            except (TypeError, ValueError):
                continue
        normalized["cost_estimates_usd"] = clean_estimates
        return normalized

    def _day_key(self, timestamp: float | None = None) -> str:
        return datetime.fromtimestamp(timestamp or time.time(), tz=self.timezone).date().isoformat()

    def estimate_cost(
        self,
        payload: Mapping[str, Any],
        policy: Mapping[str, Any] | None = None,
    ) -> float | None:
        provider = str(payload.get("resolved_provider") or "").strip().lower()
        if provider == "comfyui":
            # Local workflows consume GPU/infrastructure resources but do not
            # incur an external provider API charge.
            return 0.0
        active_policy = policy or self.get_policy()
        estimates = active_policy.get("cost_estimates_usd") or {}
        if not isinstance(estimates, dict):
            return None
        model = str(payload.get("resolved_model") or payload.get("image_model") or "").strip()
        size = str(payload.get("resolved_image_size") or payload.get("image_size") or "").strip().upper()
        quality = str(payload.get("resolved_image_quality") or payload.get("image_quality") or "").strip().lower()
        capability = str(payload.get("capability") or "").strip()
        candidates = [
            f"{model}|{size}|{quality}",
            f"{model}|{quality}",
            f"{model}|{size}",
            model,
            f"capability:{capability}",
        ]
        for key in candidates:
            if key and key in estimates:
                try:
                    return _nonnegative_float(estimates[key])
                except (TypeError, ValueError):
                    continue
        return None

    def admit(self, payload: Mapping[str, Any], *, cost_confirmed: bool = False) -> AdmissionResult:
        policy = self.get_policy()
        request_id = str(payload.get("request_id") or uuid.uuid4().hex)
        source = str(payload.get("request_source") or "unknown").strip().lower()
        principal_id = str(payload.get("principal_id") or "unknown").strip()
        idempotency_key = str(payload.get("idempotency_key") or request_id).strip()[:128]
        capability = str(payload.get("capability") or "unknown").strip()
        variant = str(payload.get("capability_variant") or "default").strip()
        workflow_id = str(payload.get("resolved_workflow_id") or payload.get("workflow_id") or "").strip()
        provider = str(payload.get("resolved_provider") or "").strip()
        model = str(payload.get("resolved_model") or "").strip()
        client_ip = str(payload.get("client_ip") or "unknown").strip()
        estimate = self.estimate_cost(payload, policy)
        day_key = self._day_key()
        now = time.time()

        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            duplicate = connection.execute(
                """
                SELECT id, job_id, status, estimated_cost_usd,
                       estimated_cost_known, updated_at
                FROM generation_control_requests
                WHERE source = ? AND principal_id = ? AND idempotency_key = ?
                """,
                (source, principal_id, idempotency_key),
            ).fetchone()
            retryable_duplicate = bool(
                duplicate
                and (
                    duplicate["status"] == "enqueue_failed"
                    or (
                        duplicate["status"] == "reserved"
                        and now - float(duplicate["updated_at"] or 0) > 120.0
                    )
                )
            )
            if retryable_duplicate:
                connection.execute(
                    "DELETE FROM generation_control_requests WHERE id = ?",
                    (duplicate["id"],),
                )
                self._event(
                    connection,
                    event_type="admission",
                    decision="retry",
                    reason_code="stale_or_failed_reservation",
                    request_id=duplicate["id"],
                    job_id=duplicate["job_id"],
                    payload=payload,
                )
                duplicate = None
            if duplicate:
                self._event(
                    connection,
                    event_type="admission",
                    decision="duplicate",
                    reason_code="idempotency_replay",
                    request_id=duplicate["id"],
                    job_id=duplicate["job_id"],
                    payload=payload,
                )
                connection.commit()
                if duplicate["job_id"]:
                    return AdmissionResult(
                        control_request_id=duplicate["id"],
                        estimated_cost_usd=(
                            float(duplicate["estimated_cost_usd"] or 0)
                            if bool(duplicate["estimated_cost_known"])
                            else None
                        ),
                        duplicate_job_id=duplicate["job_id"],
                        duplicate_status=duplicate["status"],
                    )
                raise GenerationPolicyError(
                    "idempotency_in_progress",
                    "같은 요청이 등록 중입니다. 잠시 후 다시 시도해 주세요.",
                    status_code=409,
                )

            rejection = self._policy_rejection(
                connection,
                policy=policy,
                source=source,
                capability=capability,
                day_key=day_key,
                estimate=estimate,
                cost_confirmed=cost_confirmed,
            )
            if rejection:
                self._event(
                    connection,
                    event_type="admission",
                    decision="rejected",
                    reason_code=rejection.code,
                    request_id=request_id,
                    payload=payload,
                    estimated_cost_usd=estimate,
                    details=rejection.details,
                )
                connection.commit()
                raise rejection

            connection.execute(
                """
                INSERT INTO generation_control_requests (
                    id, source, principal_id, idempotency_key, day_key,
                    created_at, updated_at, status, client_ip, capability,
                    capability_variant, workflow_id, provider, model,
                    cost_confirmed, estimated_cost_usd, estimated_cost_known
                ) VALUES (?, ?, ?, ?, ?, ?, ?, 'reserved', ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    request_id,
                    source,
                    principal_id,
                    idempotency_key,
                    day_key,
                    now,
                    now,
                    client_ip,
                    capability,
                    variant,
                    workflow_id,
                    provider,
                    model,
                    1 if cost_confirmed else 0,
                    float(estimate or 0),
                    1 if estimate is not None else 0,
                ),
            )
            self._event(
                connection,
                event_type="admission",
                decision="accepted",
                request_id=request_id,
                payload=payload,
                estimated_cost_usd=estimate,
            )
            connection.commit()
            return AdmissionResult(request_id, estimate)
        except Exception:
            if connection.in_transaction:
                connection.rollback()
            raise
        finally:
            connection.close()

    def _policy_rejection(
        self,
        connection: sqlite3.Connection,
        *,
        policy: Mapping[str, Any],
        source: str,
        capability: str,
        day_key: str,
        estimate: float | None,
        cost_confirmed: bool,
    ) -> GenerationPolicyError | None:
        if not policy.get("generation_enabled", True):
            return GenerationPolicyError(
                "generation_disabled", "현재 생성 기능이 운영자에 의해 중지되었습니다.", status_code=503
            )
        if source == "mcp" and not policy.get("mcp_enabled", True):
            return GenerationPolicyError(
                "mcp_disabled", "현재 MCP 생성 기능이 중지되었습니다.", status_code=503
            )
        if policy.get("capability_enabled", {}).get(capability) is False:
            return GenerationPolicyError(
                "capability_disabled", f"현재 {capability} 기능이 중지되었습니다.", status_code=503
            )

        active_statuses = ("reserved", "queued", "running", "complete", "error", "cancelled")
        placeholders = ",".join("?" for _ in active_statuses)
        usage = connection.execute(
            f"""
            SELECT COUNT(*) AS request_count,
                   COALESCE(SUM(COALESCE(actual_cost_usd, estimated_cost_usd, 0)), 0) AS cost_usd
            FROM generation_control_requests
            WHERE day_key = ? AND status IN ({placeholders})
            """,
            (day_key, *active_statuses),
        ).fetchone()
        request_count = int(usage["request_count"] or 0)
        cost_usd = float(usage["cost_usd"] or 0)

        daily_request_limit = int(policy.get("daily_request_limit") or 0)
        if daily_request_limit > 0 and request_count >= daily_request_limit:
            return GenerationPolicyError(
                "daily_request_limit_reached",
                "전사 일일 생성 한도에 도달했습니다.",
                status_code=429,
                details={"limit": daily_request_limit, "used": request_count, "day": day_key},
            )

        daily_cost_limit = float(policy.get("daily_cost_limit_usd") or 0)
        threshold = float(policy.get("cost_confirmation_threshold_usd") or 0)
        if estimate is None and (daily_cost_limit > 0 or threshold > 0):
            return GenerationPolicyError(
                "cost_estimate_unavailable",
                "비용 제한 또는 확인 정책에 필요한 사전 비용 추정값이 없습니다.",
                status_code=503,
                details={"capability": capability},
            )

        estimate_value = float(estimate or 0)
        if daily_cost_limit > 0 and cost_usd + estimate_value > daily_cost_limit:
            return GenerationPolicyError(
                "daily_cost_limit_reached",
                "전사 일일 생성 비용 한도에 도달했습니다.",
                status_code=429,
                details={
                    "limit_usd": daily_cost_limit,
                    "used_usd": round(cost_usd, 6),
                    "estimated_request_usd": round(estimate_value, 6),
                    "day": day_key,
                },
            )

        required_capabilities = set(policy.get("confirmation_required_capabilities") or [])
        confirmation_required = capability in required_capabilities or (
            threshold > 0 and estimate is not None and estimate >= threshold
        )
        if confirmation_required and not cost_confirmed:
            return GenerationPolicyError(
                "cost_confirmation_required",
                "이 생성 작업은 실행 전 비용 확인이 필요합니다.",
                status_code=409,
                details={
                    "estimated_cost_usd": round(estimate, 6) if estimate is not None else None,
                    "capability": capability,
                },
            )
        return None

    def sync_job(self, job: Any) -> None:
        payload = job.payload if isinstance(getattr(job, "payload", None), dict) else {}
        control_request_id = str(payload.get("control_request_id") or payload.get("request_id") or "").strip()
        if not control_request_id:
            return
        status = str(getattr(job, "status", "unknown") or "unknown")
        actual_cost = payload.get("actual_cost_usd")
        try:
            actual_cost_value = _nonnegative_float(actual_cost) if actual_cost is not None else None
        except (TypeError, ValueError):
            actual_cost_value = None
        now = time.time()
        with self._managed_connection() as connection:
            previous = connection.execute(
                "SELECT status, actual_cost_usd, provider "
                "FROM generation_control_requests WHERE id = ?",
                (control_request_id,),
            ).fetchone()
            if not previous:
                return
            provider = str(
                payload.get("resolved_provider")
                or payload.get("provider")
                or previous["provider"]
                or ""
            ).strip().lower()
            if status == "complete" and actual_cost_value is None and provider == "comfyui":
                actual_cost_value = 0.0
            connection.execute(
                """
                UPDATE generation_control_requests
                SET job_id = ?, status = ?, updated_at = ?,
                    actual_cost_usd = COALESCE(?, actual_cost_usd)
                WHERE id = ?
                """,
                (job.id, status, now, actual_cost_value, control_request_id),
            )
            if previous["status"] != status or (
                actual_cost_value is not None and previous["actual_cost_usd"] != actual_cost_value
            ):
                self._event(
                    connection,
                    event_type="job_status",
                    decision=status,
                    request_id=control_request_id,
                    job_id=job.id,
                    payload=payload,
                    actual_cost_usd=actual_cost_value,
                )

    def mark_enqueue_failed(self, control_request_id: str, reason: str) -> None:
        now = time.time()
        with self._managed_connection() as connection:
            connection.execute(
                "UPDATE generation_control_requests SET status = 'enqueue_failed', updated_at = ? WHERE id = ?",
                (now, control_request_id),
            )
            self._event(
                connection,
                event_type="job_status",
                decision="enqueue_failed",
                request_id=control_request_id,
                details={"reason": str(reason)[:500]},
            )

    def summary(self, day_key: str | None = None) -> dict[str, Any]:
        day = day_key or self._day_key()
        with self._managed_connection() as connection:
            row = connection.execute(
                """
                SELECT COUNT(*) AS total,
                       SUM(CASE WHEN status = 'complete' THEN 1 ELSE 0 END) AS complete,
                       SUM(CASE WHEN status = 'error' THEN 1 ELSE 0 END) AS error,
                       SUM(CASE WHEN status IN ('reserved', 'queued', 'running') THEN 1 ELSE 0 END) AS active,
                       COALESCE(SUM(estimated_cost_usd), 0) AS estimated_cost_usd,
                       COALESCE(SUM(actual_cost_usd), 0) AS actual_cost_usd,
                       SUM(CASE WHEN estimated_cost_known = 0 THEN 1 ELSE 0 END) AS unknown_estimate_count,
                       SUM(CASE WHEN status = 'complete' AND actual_cost_usd IS NULL THEN 1 ELSE 0 END)
                           AS missing_actual_cost_count
                FROM generation_control_requests
                WHERE day_key = ? AND status != 'enqueue_failed'
                """,
                (day,),
            ).fetchone()
            rejected = connection.execute(
                """
                SELECT COUNT(*) FROM generation_control_events
                WHERE decision = 'rejected'
                  AND created_at >= ? AND created_at < ?
                """,
                self._day_bounds(day),
            ).fetchone()[0]

            def grouped(column: str) -> list[dict[str, Any]]:
                if column not in {"source", "capability", "model"}:
                    raise ValueError("Unsupported summary group")
                rows = connection.execute(
                    f"""
                    SELECT COALESCE(NULLIF({column}, ''), '(unknown)') AS name,
                           COUNT(*) AS total,
                           COALESCE(SUM(estimated_cost_usd), 0) AS estimated_cost_usd,
                           COALESCE(SUM(actual_cost_usd), 0) AS actual_cost_usd,
                           SUM(CASE WHEN estimated_cost_known = 0 THEN 1 ELSE 0 END)
                               AS unknown_estimate_count,
                           SUM(CASE WHEN status = 'complete' AND actual_cost_usd IS NULL THEN 1 ELSE 0 END)
                               AS missing_actual_cost_count
                    FROM generation_control_requests
                    WHERE day_key = ? AND status != 'enqueue_failed'
                    GROUP BY name
                    ORDER BY total DESC, name ASC
                    """,
                    (day,),
                ).fetchall()
                return [
                    {
                        "name": group["name"],
                        "total": int(group["total"] or 0),
                        "estimated_cost_usd": round(float(group["estimated_cost_usd"] or 0), 6),
                        "actual_cost_usd": round(float(group["actual_cost_usd"] or 0), 6),
                        "unknown_estimate_count": int(group["unknown_estimate_count"] or 0),
                        "missing_actual_cost_count": int(group["missing_actual_cost_count"] or 0),
                    }
                    for group in rows
                ]

            by_source = grouped("source")
            by_capability = grouped("capability")
            by_model = grouped("model")
        policy = self.get_policy()
        return {
            "day": day,
            "timezone": self.timezone_name,
            "total": int(row["total"] or 0),
            "complete": int(row["complete"] or 0),
            "error": int(row["error"] or 0),
            "active": int(row["active"] or 0),
            "rejected": int(rejected or 0),
            "estimated_cost_usd": round(float(row["estimated_cost_usd"] or 0), 6),
            "actual_cost_usd": round(float(row["actual_cost_usd"] or 0), 6),
            "unknown_estimate_count": int(row["unknown_estimate_count"] or 0),
            "missing_actual_cost_count": int(row["missing_actual_cost_count"] or 0),
            "daily_request_limit": policy["daily_request_limit"],
            "daily_cost_limit_usd": policy["daily_cost_limit_usd"],
            "by_source": by_source,
            "by_capability": by_capability,
            "by_model": by_model,
        }

    def cost_report(
        self,
        *,
        days: int = 30,
        client_ip: str | None = None,
        capability: str | None = None,
        model: str | None = None,
        limit: int = 50,
    ) -> dict[str, Any]:
        bounded_days = max(1, min(365, int(days)))
        bounded_limit = max(1, min(500, int(limit)))
        cutoff = time.time() - (bounded_days * 86400.0)
        selected = {
            "client_ip": str(client_ip or "").strip(),
            "capability": str(capability or "").strip(),
            "model": str(model or "").strip(),
        }
        conditions = ["created_at >= ?", "status != 'enqueue_failed'"]
        params: list[Any] = [cutoff]
        for column in ("client_ip", "capability", "model"):
            value = selected[column]
            if value:
                conditions.append(f"{column} = ?")
                params.append(value)
        where_sql = " AND ".join(conditions)

        with self._managed_connection() as connection:
            summary = connection.execute(
                f"""
                SELECT COUNT(*) AS total,
                       SUM(CASE WHEN status = 'complete' THEN 1 ELSE 0 END) AS complete,
                       SUM(CASE WHEN status = 'error' THEN 1 ELSE 0 END) AS error,
                       COALESCE(SUM(actual_cost_usd), 0) AS actual_cost_usd,
                       COUNT(actual_cost_usd) AS actual_cost_record_count,
                       COALESCE(SUM(CASE WHEN estimated_cost_known = 1
                                         THEN estimated_cost_usd ELSE 0 END), 0) AS estimated_cost_usd,
                       SUM(CASE WHEN estimated_cost_known = 0 THEN 1 ELSE 0 END)
                           AS unknown_estimate_count,
                       SUM(CASE WHEN status = 'complete' AND actual_cost_usd IS NULL THEN 1 ELSE 0 END)
                           AS missing_actual_cost_count,
                       COALESCE(SUM(CASE WHEN actual_cost_usd IS NOT NULL AND estimated_cost_known = 1
                                         THEN estimated_cost_usd ELSE 0 END), 0)
                           AS comparable_estimated_cost_usd,
                       COALESCE(SUM(CASE WHEN actual_cost_usd IS NOT NULL AND estimated_cost_known = 1
                                         THEN actual_cost_usd ELSE 0 END), 0)
                           AS comparable_actual_cost_usd
                FROM generation_control_requests
                WHERE {where_sql}
                """,
                params,
            ).fetchone()

            def grouped(column: str) -> list[dict[str, Any]]:
                if column not in {"day_key", "capability", "model"}:
                    raise ValueError("Unsupported cost report group")
                order_sql = "name DESC" if column == "day_key" else "actual_cost_usd DESC, total DESC, name ASC"
                rows = connection.execute(
                    f"""
                    SELECT COALESCE(NULLIF({column}, ''), '(unknown)') AS name,
                           COUNT(*) AS total,
                           SUM(CASE WHEN status = 'complete' THEN 1 ELSE 0 END) AS complete,
                           COALESCE(SUM(actual_cost_usd), 0) AS actual_cost_usd,
                           COUNT(actual_cost_usd) AS actual_cost_record_count,
                           SUM(CASE WHEN estimated_cost_known = 0 THEN 1 ELSE 0 END)
                               AS unknown_estimate_count,
                           SUM(CASE WHEN status = 'complete' AND actual_cost_usd IS NULL THEN 1 ELSE 0 END)
                               AS missing_actual_cost_count
                    FROM generation_control_requests
                    WHERE {where_sql}
                    GROUP BY name
                    ORDER BY {order_sql}
                    LIMIT ?
                    """,
                    [*params, bounded_limit],
                ).fetchall()
                return [
                    {
                        "name": row["name"],
                        "total": int(row["total"] or 0),
                        "complete": int(row["complete"] or 0),
                        "actual_cost_usd": round(float(row["actual_cost_usd"] or 0), 6),
                        "actual_cost_record_count": int(row["actual_cost_record_count"] or 0),
                        "unknown_estimate_count": int(row["unknown_estimate_count"] or 0),
                        "missing_actual_cost_count": int(row["missing_actual_cost_count"] or 0),
                    }
                    for row in rows
                ]

            ip_rows = connection.execute(
                f"""
                SELECT COALESCE(NULLIF(client_ip, ''), '(unknown)') AS client_ip,
                       COUNT(DISTINCT COALESCE(NULLIF(principal_id, ''), '(unknown)')) AS principal_count,
                       COUNT(*) AS total,
                       SUM(CASE WHEN status = 'complete' THEN 1 ELSE 0 END) AS complete,
                       COALESCE(SUM(actual_cost_usd), 0) AS actual_cost_usd,
                       COUNT(actual_cost_usd) AS actual_cost_record_count,
                       SUM(CASE WHEN estimated_cost_known = 0 THEN 1 ELSE 0 END)
                           AS unknown_estimate_count,
                       SUM(CASE WHEN status = 'complete' AND actual_cost_usd IS NULL THEN 1 ELSE 0 END)
                           AS missing_actual_cost_count,
                       MAX(updated_at) AS last_seen_at
                FROM generation_control_requests
                WHERE {where_sql}
                GROUP BY client_ip
                ORDER BY actual_cost_usd DESC, total DESC, client_ip ASC
                LIMIT ?
                """,
                [*params, bounded_limit],
            ).fetchall()
            by_ip = [
                {
                    "client_ip": row["client_ip"],
                    "masked_client_ip": _masked_client_ip(row["client_ip"]),
                    "principal_count": int(row["principal_count"] or 0),
                    "total": int(row["total"] or 0),
                    "complete": int(row["complete"] or 0),
                    "actual_cost_usd": round(float(row["actual_cost_usd"] or 0), 6),
                    "actual_cost_record_count": int(row["actual_cost_record_count"] or 0),
                    "unknown_estimate_count": int(row["unknown_estimate_count"] or 0),
                    "missing_actual_cost_count": int(row["missing_actual_cost_count"] or 0),
                    "last_seen_at": float(row["last_seen_at"] or 0),
                }
                for row in ip_rows
            ]

            available_ip_rows = connection.execute(
                """
                SELECT COALESCE(NULLIF(client_ip, ''), '(unknown)') AS client_ip,
                       COUNT(DISTINCT COALESCE(NULLIF(principal_id, ''), '(unknown)')) AS principal_count
                FROM generation_control_requests
                WHERE created_at >= ? AND status != 'enqueue_failed'
                GROUP BY client_ip
                ORDER BY client_ip ASC
                """,
                (cutoff,),
            ).fetchall()

            def distinct_values(column: str) -> list[str]:
                if column not in {"capability", "model"}:
                    raise ValueError("Unsupported cost filter")
                rows = connection.execute(
                    f"""
                    SELECT DISTINCT {column} AS value
                    FROM generation_control_requests
                    WHERE created_at >= ? AND status != 'enqueue_failed'
                      AND {column} IS NOT NULL AND {column} != ''
                    ORDER BY value ASC
                    """,
                    (cutoff,),
                ).fetchall()
                return [str(row["value"]) for row in rows]

            daily = grouped("day_key")
            by_capability = grouped("capability")
            by_model = grouped("model")
            available_capabilities = distinct_values("capability")
            available_models = distinct_values("model")

        return {
            "days_requested": bounded_days,
            "timezone": self.timezone_name,
            "filters": selected,
            "available_filters": {
                "client_ips": [
                    {
                        "value": row["client_ip"],
                        "label": _masked_client_ip(row["client_ip"]),
                        "principal_count": int(row["principal_count"] or 0),
                    }
                    for row in available_ip_rows
                ],
                "capabilities": available_capabilities,
                "models": available_models,
            },
            "summary": {
                "total": int(summary["total"] or 0),
                "complete": int(summary["complete"] or 0),
                "error": int(summary["error"] or 0),
                "actual_cost_usd": round(float(summary["actual_cost_usd"] or 0), 6),
                "actual_cost_record_count": int(summary["actual_cost_record_count"] or 0),
                "estimated_cost_usd": round(float(summary["estimated_cost_usd"] or 0), 6),
                "known_estimate_count": int(summary["total"] or 0)
                - int(summary["unknown_estimate_count"] or 0),
                "unknown_estimate_count": int(summary["unknown_estimate_count"] or 0),
                "missing_actual_cost_count": int(summary["missing_actual_cost_count"] or 0),
                "comparable_estimated_cost_usd": round(
                    float(summary["comparable_estimated_cost_usd"] or 0), 6
                ),
                "comparable_actual_cost_usd": round(
                    float(summary["comparable_actual_cost_usd"] or 0), 6
                ),
            },
            "daily": daily,
            "by_ip": by_ip,
            "by_capability": by_capability,
            "by_model": by_model,
        }

    def _day_bounds(self, day_key: str) -> tuple[float, float]:
        start = datetime.strptime(day_key, "%Y-%m-%d").replace(tzinfo=self.timezone)
        end = start + timedelta(days=1)
        return (start.timestamp(), end.timestamp())

    def recent_events(self, limit: int = 100) -> list[dict[str, Any]]:
        bounded_limit = max(1, min(1000, int(limit)))
        with self._managed_connection() as connection:
            rows = connection.execute(
                """
                SELECT * FROM generation_control_events
                ORDER BY created_at DESC LIMIT ?
                """,
                (bounded_limit,),
            ).fetchall()
        events = []
        for row in rows:
            item = dict(row)
            try:
                item["details"] = json.loads(item.pop("details_json") or "{}")
            except (TypeError, ValueError, json.JSONDecodeError):
                item["details"] = {}
            events.append(item)
        return events

    def _event(
        self,
        connection: sqlite3.Connection,
        *,
        event_type: str,
        decision: str | None = None,
        reason_code: str | None = None,
        request_id: str | None = None,
        job_id: str | None = None,
        payload: Mapping[str, Any] | None = None,
        estimated_cost_usd: float | None = None,
        actual_cost_usd: float | None = None,
        details: Mapping[str, Any] | None = None,
    ) -> None:
        data = payload or {}
        connection.execute(
            """
            INSERT INTO generation_control_events (
                created_at, event_type, decision, reason_code, request_id, job_id,
                source, principal_id, client_ip, capability, workflow_id,
                provider, model, estimated_cost_usd, actual_cost_usd, details_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                time.time(),
                event_type,
                decision,
                reason_code,
                request_id,
                job_id,
                data.get("request_source"),
                data.get("principal_id"),
                data.get("client_ip"),
                data.get("capability"),
                data.get("resolved_workflow_id") or data.get("workflow_id"),
                data.get("resolved_provider"),
                data.get("resolved_model"),
                estimated_cost_usd,
                actual_cost_usd,
                json.dumps(dict(details or {}), ensure_ascii=False),
            ),
        )
