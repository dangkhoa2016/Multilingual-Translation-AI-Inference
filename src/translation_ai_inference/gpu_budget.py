"""Opt-in *estimated* USD admission budget, not actual Modal billing.

A reservation is an operator-chosen fixed proxy amount per model run.  The
counter lives transactionally in PostgreSQL alongside job admission; it cannot
measure actual GPU time, cold starts, CPU, storage or other Modal costs.
Use a Modal Workspace Budget for authoritative workspace spending limits.
"""
from decimal import ROUND_CEILING, Decimal, InvalidOperation

from .quotas import consume_quota

MICROUSD = Decimal("1000000")
MAX_MICROUSD = 2_000_000_000  # usage_windows.used is an integer; guard overflow.


def usd_to_microusd(raw: str, *, variable: str) -> int:
    """Validate positive finite USD strings; always round reservations upward."""
    try:
        value = Decimal(raw)
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"{variable} must be positive finite USD") from exc
    if not value.is_finite() or value <= 0:
        raise ValueError(f"{variable} must be positive finite USD")
    count = int((value * MICROUSD).to_integral_value(rounding=ROUND_CEILING))
    if not (1 <= count <= MAX_MICROUSD):
        raise ValueError(f"{variable} is outside supported range")
    return count


def configured_estimate(raw_per_run: str | None, raw_day: str | None) -> tuple[int, int]:
    """Both values required, or both absent (disabled). Never infer a USD cost."""
    if raw_per_run is None and raw_day is None:
        return 0, 0
    if raw_per_run is None or raw_day is None:
        raise ValueError("Both estimated GPU USD budget variables must be configured together")
    per_run = usd_to_microusd(raw_per_run, variable="TRANSLATION_ESTIMATED_GPU_USD_PER_RUN")
    day = usd_to_microusd(raw_day, variable="TRANSLATION_MAX_ESTIMATED_GPU_USD_PER_DAY")
    if per_run > day:
        raise ValueError("Estimated GPU per-run reservation exceeds daily limit")
    return per_run, day


def reserve_estimated_gpu_budget(session, *, owner: str, model_count: int,
                                 microusd_per_run: int,
                                 daily_microusd_limit: int) -> None:
    """Atomic UTC-day transaction; same idempotency semantics as job quotas."""
    if microusd_per_run == daily_microusd_limit == 0:
        return
    if (model_count < 1 or microusd_per_run <= 0 or daily_microusd_limit <= 0
            or daily_microusd_limit > MAX_MICROUSD):
        raise ValueError("Invalid estimated GPU admission settings")
    required = model_count * microusd_per_run
    if required > MAX_MICROUSD:
        # Raise QuotaExceeded in the same way as other atomic quotas.
        from .quotas import QuotaExceeded
        raise QuotaExceeded("estimated-gpu-usd-per-day", 86400)
    consume_quota(
        session, owner=owner, scope="estimated-gpu-usd-per-day",
        amount=required, limit=daily_microusd_limit,
        window_seconds=86400,
    )
