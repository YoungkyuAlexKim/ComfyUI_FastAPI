"""Shared admission and enqueue path for every generation entry point."""

from __future__ import annotations

from dataclasses import dataclass

from .generation_commands import ResolvedGenerationCommand
from .generation_controls import GenerationControlService


@dataclass(frozen=True)
class GenerationSubmission:
    job_id: str
    status: str
    position: int
    estimated_cost_usd: float | None
    duplicate: bool = False


class GenerationSubmissionService:
    """Apply operational policy, idempotency, and queueing in one place."""

    def __init__(self, job_manager, controls: GenerationControlService):
        self.job_manager = job_manager
        self.controls = controls

    def submit(
        self,
        resolved: ResolvedGenerationCommand,
        *,
        cost_confirmed: bool = False,
    ) -> GenerationSubmission:
        admission = self.controls.admit(resolved.payload, cost_confirmed=cost_confirmed)
        if admission.is_duplicate:
            return GenerationSubmission(
                job_id=str(admission.duplicate_job_id),
                status="duplicate",
                position=self.job_manager.get_position(admission.duplicate_job_id) or 0,
                estimated_cost_usd=admission.estimated_cost_usd,
                duplicate=True,
            )

        resolved.payload["control_request_id"] = admission.control_request_id
        resolved.payload["estimated_cost_usd"] = admission.estimated_cost_usd
        resolved.payload["cost_confirmed"] = bool(cost_confirmed)
        try:
            job = self.job_manager.enqueue(
                resolved.command.context.principal_id,
                "generate",
                resolved.payload,
            )
        except Exception as exc:
            if admission.control_request_id:
                self.controls.mark_enqueue_failed(admission.control_request_id, str(exc))
            raise

        return GenerationSubmission(
            job_id=job.id,
            status="queued",
            position=self.job_manager.get_position(job.id) or 0,
            estimated_cost_usd=admission.estimated_cost_usd,
        )
