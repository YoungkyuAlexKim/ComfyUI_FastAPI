import threading
import time
import uuid
from collections import deque, defaultdict
from typing import Any, Callable, Deque, Dict, Optional
import logging
from .config import PROGRESS_LOG_CONFIG


JobStatus = str  # queued | running | complete | error | cancelled


class Job:
    def __init__(self, owner_id: str, job_type: str, payload: Dict[str, Any]):
        self.id: str = uuid.uuid4().hex
        self.owner_id: str = owner_id
        self.type: str = job_type  # e.g., "generate", "translate"
        self.payload: Dict[str, Any] = payload
        self.status: JobStatus = "queued"
        self.progress: float = 0.0
        self.created_at: float = time.time()
        self.started_at: Optional[float] = None
        self.ended_at: Optional[float] = None
        self.error_message: Optional[str] = None
        # Arbitrary results (e.g., image_path)
        self.result: Dict[str, Any] = {}


class JobManager:
    def __init__(self):
        self._lock = threading.RLock()
        self._jobs: Dict[str, Job] = {}
        self._user_queues: Dict[str, Deque[str]] = defaultdict(deque)
        self._users_rr: Deque[str] = deque()
        self._stop_event = threading.Event()
        self._worker_thread: Optional[threading.Thread] = None

        # Injected processing callbacks per job type
        # signature: (job: Job, progress_cb: Callable[[float], None]) -> None
        self._processors: Dict[str, Callable[[Job, Callable[[float], None]], None]] = {}

        # Active job context (single worker for now)
        self._active_job_id: Optional[str] = None
        # Comfy client cancel handle: Callable[[], bool]
        self._active_cancel_handle: Optional[Callable[[], bool]] = None
        # Cancel requests for running jobs
        self._cancel_requests: set[str] = set()

        # Optional event sink for external notifications
        # signature: (owner_id: str, event: Dict[str, Any]) -> None
        self._notify: Optional[Callable[[str, Dict[str, Any]], None]] = None
        # Job timeout seconds (None to disable)
        self.job_timeout_seconds: Optional[float] = 180.0
        self._logger = logging.getLogger("comfyui_app")
        # Backpressure configs
        self.max_per_user_queue: int = 5
        self.max_per_user_concurrent: int = 1
        self._running_by_user: Dict[str, int] = defaultdict(int)

    # ---- Registration ----
    def register_processor(self, job_type: str, processor: Callable[[Job, Callable[[float], None]], None]):
        self._processors[job_type] = processor

    def set_notifier(self, notify: Callable[[str, Dict[str, Any]], None]):
        self._notify = notify

    # ---- Enqueue / Status / Cancel ----
    def enqueue(self, owner_id: str, job_type: str, payload: Dict[str, Any]) -> Job:
        job = Job(owner_id=owner_id, job_type=job_type, payload=payload)
        with self._lock:
            # Enforce per-user queue limit
            q = self._user_queues[owner_id]
            if len(q) >= self.max_per_user_queue:
                raise RuntimeError("Queue limit reached for user")
            self._jobs[job.id] = job
            was_empty = (len(q) == 0)
            q.append(job.id)
            if was_empty and owner_id not in self._users_rr:
                self._users_rr.append(owner_id)
        if self._notify:
            self._notify(owner_id, {"status": "queued", "job_id": job.id})
        return job

    def get(self, job_id: str) -> Optional[Job]:
        with self._lock:
            return self._jobs.get(job_id)

    def get_position(self, job_id: str) -> Optional[int]:
        with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                return None
            q = self._user_queues.get(job.owner_id)
            if not q:
                return 0
            try:
                idx = list(q).index(job_id)
                return idx
            except ValueError:
                # Not in queue; if running/completed return 0
                return 0

    def list_jobs(self, limit: int = 100) -> list[dict]:
        with self._lock:
            jobs = list(self._jobs.values())
        jobs.sort(key=lambda j: j.created_at, reverse=True)
        return [self._to_public(j) for j in jobs[:limit]]

    def cancel(self, job_id: str) -> bool:
        with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                return False
            if job.status == "queued":
                # Remove from its user queue
                q = self._user_queues.get(job.owner_id)
                if q and job_id in q:
                    try:
                        q.remove(job_id)
                    except ValueError:
                        pass
                job.status = "cancelled"
                job.ended_at = time.time()
                if self._notify:
                    self._notify(job.owner_id, {"status": "cancelled", "job_id": job.id})
                return True
            if job.status == "running":
                # Try active cancel handle
                cancel = self._active_cancel_handle
                # Mark desire to cancel; processor should honor
                if cancel:
                    try:
                        cancel()
                    except Exception:
                        pass
                self._cancel_requests.add(job_id)
                # Actual status will flip when processor acknowledges
                return True
            return False

    # ---- Worker Loop ----
    def start(self):
        if self._worker_thread and self._worker_thread.is_alive():
            return
        self._stop_event.clear()
        self._worker_thread = threading.Thread(target=self._run_loop, name="JobWorker", daemon=True)
        self._worker_thread.start()

    def stop(self):
        self._stop_event.set()
        if self._worker_thread:
            self._worker_thread.join(timeout=2)

    def _run_loop(self):
        while not self._stop_event.is_set():
            job = self._next_job_round_robin()
            if not job:
                time.sleep(0.05)
                continue
            processor = self._processors.get(job.type)
            if not processor:
                self._mark_error(job, "No processor for job type")
                continue

            # Throttled/stepped progress logger state
            _last_logged_pct = -1.0
            _last_logged_ts = 0.0

            def progress_cb(p: float):
                nonlocal _last_logged_pct, _last_logged_ts
                with self._lock:
                    job.progress = max(0.0, min(100.0, float(p)))
                if self._notify:
                    self._notify(job.owner_id, {"status": "running", "job_id": job.id, "progress": job.progress})
                # Step/interval gating for logs
                try:
                    step = int(PROGRESS_LOG_CONFIG.get("step_percent", 10) or 0)
                    min_ms = int(PROGRESS_LOG_CONFIG.get("min_interval_ms", 500))
                except Exception:
                    step = 10
                    min_ms = 500
                now = time.time()
                should_log = True
                if step > 0:
                    # Only log when crossing multiples of 'step'
                    rounded = int(round(job.progress))
                    if rounded % max(1, step) != 0 and rounded != 100:
                        should_log = False
                    # Avoid duplicate logs at the same step
                    if should_log and _last_logged_pct == rounded:
                        should_log = False
                    if should_log:
                        _last_logged_pct = rounded
                # Interval throttle
                if should_log and min_ms > 0 and (now - _last_logged_ts) * 1000.0 < min_ms:
                    should_log = False
                if should_log:
                    _last_logged_ts = now
                    payload = {"event": "job_progress", "job_id": job.id, "owner_id": job.owner_id, "progress": round(job.progress, 2)}
                    try:
                        level = (PROGRESS_LOG_CONFIG.get("level") or "info").lower()
                    except Exception:
                        level = "info"
                    if level == "debug":
                        self._logger.debug(payload)
                    else:
                        self._logger.info(payload)

            with self._lock:
                self._active_job_id = job.id
                job.status = "running"
                job.started_at = time.time()
            if self._notify:
                self._notify(job.owner_id, {"status": "running", "job_id": job.id, "progress": 0.0})
            try:
                self._logger.info({"event": "job_start", "job_id": job.id, "owner_id": job.owner_id, "type": job.type})
            except Exception:
                pass

            # The processor may set a cancel handle via set_active_cancel_handle
            self._active_cancel_handle = None
            # Timeout watchdog
            timeout_timer = None
            if isinstance(self.job_timeout_seconds, (int, float)) and self.job_timeout_seconds and self.job_timeout_seconds > 0:
                def _timeout_job():
                    try:
                        with self._lock:
                            still_active = (self._active_job_id == job.id and job.status == "running")
                            if still_active:
                                self._cancel_requests.add(job.id)
                                cancel = self._active_cancel_handle
                            else:
                                cancel = None
                        if cancel:
                            try:
                                cancel()
                            except Exception:
                                pass
                        # Let normal error/cancel flow handle final state via _mark_error
                        if self._notify:
                            self._notify(job.owner_id, {"status": "cancelling", "job_id": job.id})
                    except Exception:
                        pass
                timeout_timer = threading.Timer(self.job_timeout_seconds, _timeout_job)
                timeout_timer.daemon = True
                timeout_timer.start()
            try:
                start_ts = time.time()
                processor(job, progress_cb)
                # If processor completes without exception
                with self._lock:
                    if job.status != "cancelled":
                        job.status = "complete"
                        job.progress = 100.0
                        job.ended_at = time.time()
                if self._notify:
                    payload = {"status": "complete", "job_id": job.id}
                    payload.update(job.result or {})
                    self._notify(job.owner_id, payload)
                try:
                    self._logger.info({"event": "job_complete", "job_id": job.id, "owner_id": job.owner_id})
                except Exception:
                    pass
            except Exception as e:
                self._mark_error(job, str(e))
            finally:
                if timeout_timer is not None:
                    try:
                        timeout_timer.cancel()
                    except Exception:
                        pass
                with self._lock:
                    self._active_job_id = None
                    self._active_cancel_handle = None
                    self._cancel_requests.discard(job.id)
                    try:
                        self._logger.info({"event": "job_end", "job_id": job.id, "owner_id": job.owner_id, "status": job.status})
                    except Exception:
                        pass
                    # Decrement running per-user counter
                    try:
                        if job.owner_id in self._running_by_user and self._running_by_user[job.owner_id] > 0:
                            self._running_by_user[job.owner_id] -= 1
                    except Exception:
                        pass

    def set_active_cancel_handle(self, handle: Optional[Callable[[], bool]]):
        with self._lock:
            self._active_cancel_handle = handle

    # ---- Helpers ----
    def _next_job_round_robin(self) -> Optional[Job]:
        with self._lock:
            if not self._users_rr:
                return None
            # Rotate users until a queue with items is found
            for _ in range(len(self._users_rr)):
                user_id = self._users_rr[0]
                q = self._user_queues.get(user_id)
                running = self._running_by_user.get(user_id, 0)
                if q and len(q) > 0 and running < self.max_per_user_concurrent:
                    job_id = q.popleft()
                    self._running_by_user[user_id] = running + 1
                    # If queue now empty, still keep user in RR to preserve order for future jobs
                    return self._jobs.get(job_id)
                # Rotate
                self._users_rr.rotate(-1)
            return None

    def _mark_error(self, job: Job, message: str):
        with self._lock:
            # If a cancel was requested, prefer cancelled state
            if job.id in self._cancel_requests:
                job.status = "cancelled"
                # Provide a friendly cancellation message for UI instead of a generic fetch failure
                message = "생성이 취소되었습니다."
            else:
                job.status = "error"
            job.error_message = message
            job.ended_at = time.time()
        if self._notify:
            status = "cancelled" if job.id in self._cancel_requests else "error"
            self._notify(job.owner_id, {"status": status, "job_id": job.id, "error": message})
        try:
            self._logger.info({"event": "job_error", "job_id": job.id, "owner_id": job.owner_id, "status": job.status, "error": message})
        except Exception:
            pass

    def _to_public(self, j: Job) -> Dict[str, Any]:
        return {
            "id": j.id,
            "owner_id": j.owner_id,
            "type": j.type,
            "status": j.status,
            "progress": j.progress,
            "created_at": j.created_at,
            "started_at": j.started_at,
            "ended_at": j.ended_at,
            "error": j.error_message,
            "result": j.result,
        }

    # External visibility helpers
    def is_cancel_requested(self, job_id: str) -> bool:
        with self._lock:
            return job_id in self._cancel_requests

    def get_active_for_owner(self, owner_id: str) -> Optional[Job]:
        with self._lock:
            if self._active_job_id is None:
                return None
            j = self._jobs.get(self._active_job_id)
            if j and j.owner_id == owner_id and j.status == "running":
                return j
            return None

    def get_recent_averages(self, limit: int = 100) -> Dict[str, Any]:
        """Compute rolling average durations overall and per workflow_id for last N completed jobs.
        Returns dict: { 'overall_avg_sec': float|None, 'per_workflow_avg_sec': {wf: float}, 'count': int }
        """
        with self._lock:
            jobs = list(self._jobs.values())
        # Sort by ended_at desc and take last N completed
        completed = [j for j in jobs if j.status == "complete" and j.started_at and j.ended_at]
        completed.sort(key=lambda j: j.ended_at or 0, reverse=True)
        window = completed[: max(0, limit)]
        if not window:
            return {"overall_avg_sec": None, "per_workflow_avg_sec": {}, "count": 0}
        # Overall
        durations = [(j.ended_at - j.started_at) for j in window if j.started_at and j.ended_at]
        overall = (sum(durations) / len(durations)) if durations else None
        # Per workflow: payload may include workflow_id
        per: Dict[str, list[float]] = {}
        for j in window:
            try:
                wf = None
                if isinstance(j.payload, dict):
                    wf = j.payload.get("workflow_id")
                if (j.started_at and j.ended_at and wf):
                    per.setdefault(wf, []).append(j.ended_at - j.started_at)
            except Exception:
                continue
        per_avg = {wf: (sum(vals) / len(vals)) for wf, vals in per.items() if vals}
        return {"overall_avg_sec": overall, "per_workflow_avg_sec": per_avg, "count": len(durations)}



