"""Read-only aggregate operations snapshot with no request text, tokens or job IDs.

Designed for CPU-only operator checks against the existing PostgreSQL database.
Never spawns GPU, modifies job state or logs personally identifying content.
"""
from datetime import timedelta

from sqlalchemy import func, select

from .admission import ACTIVE_RUN_STATES
from .database import Job, JobRun, TranslationResult, UsageWindow, utcnow
from .model_registry import MODEL_REGISTRY


def collect_operations_snapshot(repository, *, last_hours: int = 24,
                                dispatch_age_seconds: int = 300,
                                running_age_seconds: int = 900) -> dict:
    if not 1 <= last_hours <= 720:
        raise ValueError("last_hours must be between 1 and 720")
    cutoff = utcnow() - timedelta(hours=last_hours)
    with repository.session_factory() as session:
        pending_jobs = session.scalar(select(func.count(func.distinct(JobRun.job_id))).where(
            JobRun.status.in_(ACTIVE_RUN_STATES)))
        pending_models = {}
        for model, count in session.execute(select(JobRun.model_key, func.count(JobRun.id)).where(
            JobRun.status.in_(ACTIVE_RUN_STATES)).group_by(JobRun.model_key)):
            label = model if model in MODEL_REGISTRY else "unknown_model"
            pending_models[label] = pending_models.get(label, 0) + count
        all_statuses = dict(session.execute(
            select(JobRun.status, func.count(JobRun.id)).group_by(JobRun.status)
        ).all())
        recent_statuses = dict(session.execute(
            select(JobRun.status, func.count(JobRun.id))
            .join(Job, JobRun.job_id == Job.id)
            .where(Job.created_at >= cutoff)
            .group_by(JobRun.status)
        ).all())
        recent_errors = dict(session.execute(
            select(JobRun.error_code, func.count(JobRun.id))
            .join(Job, JobRun.job_id == Job.id)
            .where(Job.created_at >= cutoff,
                   JobRun.error_code.is_not(None))
            .group_by(JobRun.error_code)
        ).all())
        real_completed = session.scalar(
            select(func.count(TranslationResult.run_id))
            .join(TranslationResult.run)
            .join(Job, JobRun.job_id == Job.id)
            .where(Job.created_at >= cutoff,
                   TranslationResult.is_mock_result.is_(False))
        )
        utc_bucket = int(utcnow().timestamp()) // 86400 * 86400
        estimated_reservations = list(session.execute(
            select(UsageWindow.request_owner, UsageWindow.used).where(
                UsageWindow.scope == "estimated-gpu-usd-per-day",
                UsageWindow.bucket_start == utc_bucket,
            )
        ))
    stale = repository.stale_counts(
        dispatch_age_seconds=dispatch_age_seconds,
        running_age_seconds=running_age_seconds,
    )
    return {
        "window_hours": last_hours,
        "pending_jobs_count": int(pending_jobs or 0),
        "pending_runs_by_model": pending_models,
        "total_runs_by_state": all_statuses,
        "recent_runs_by_state": recent_statuses,
        "recent_error_codes": recent_errors,
        "recent_real_results_count": int(real_completed or 0),
        "stale_dispatching_count": int(stale["dispatching"]),
        "stale_running_count": int(stale["running"]),
        "estimated_gpu_usd_reserved_today": (
            round(sum(int(used) for _owner, used in estimated_reservations) / 1_000_000, 6)
        ),
        "estimated_reservation_configured_owners": len(estimated_reservations),
    }
