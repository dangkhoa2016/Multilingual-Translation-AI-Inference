"""CPU-only production safeguard inspection: no GPU allocation and no retries.

Read PostgreSQL job-state aggregates, inspect Modal *workspace* billing, and
print structured warnings without exposing bearer tokens, DB passwords,
translation text, individual user IDs or job IDs.

  set -a; source .env; set +a
  PYTHONPATH=src python scripts/operations/check_safeguards.py --profile YOUR_MODAL_PROFILE

Optional read-only alert thresholds:
  --alert-metered-usd 10 --alert-billed-usd 5

Optional explicitly destructive-in-scope *state* reconciliation (never retry):
  --apply-reconcile

Exit code 2 indicates a threshold alert; 1 indicates a monitoring failure.
Amounts from 'modal billing summary' are WORKSPACE-wide and may lag;
operator-chosen estimated job reservation counters are not actual bills.
"""
import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path

from multilingual_translation_ai_inference.database import make_engine, make_session_factory
from multilingual_translation_ai_inference.operations import collect_operations_snapshot
from multilingual_translation_ai_inference.repository import JobRepository

ROOT = Path(__file__).resolve().parents[2]


def billing_summary(*, profile: str | None, modal_bin: str | None = None) -> dict:
    binary = modal_bin or str(ROOT / ".venv" / "bin" / "modal")
    args = [binary, "billing", "summary", "--for", "this month", "--json"]
    if profile:
        args.extend(["--profile", profile])
    result = subprocess.run(args, capture_output=True, text=True,
                            timeout=60, check=False)
    if result.returncode:
        # CLI stderr might contain infrastructure internals; do not print.
        raise RuntimeError("Modal workspace billing CLI was unavailable")
    try:
        raw = json.loads(result.stdout)
        amount = {}
        for key in ("metered_cost", "billed_cost"):
            value = Decimal(str(raw[key]))
            if not value.is_finite() or value < 0:
                raise ValueError(f"Unexpected billing field {key}")
            amount[key + "_usd"] = str(value)
        return {
            "scope": "entire_modal_workspace",
            "period": "current_month",
            **amount,
        }
    except (KeyError, TypeError, ValueError, InvalidOperation) as exc:
        raise RuntimeError("Modal returned an unsupported billing schema") from exc


def make_alerts(snapshot: dict, billing: dict | None, *,
                metered_limit: Decimal | None, billed_limit: Decimal | None,
                alert_uncertain_count: int = 1) -> list[str]:
    alerts = []
    counts = snapshot["total_runs_by_state"]
    uncertain_count = counts.get("dispatch_uncertain", 0) + counts.get("execution_uncertain", 0)
    if uncertain_count >= alert_uncertain_count:
        alerts.append("uncertain_runs_require_operator_investigation")
    if snapshot["stale_dispatching_count"] or snapshot["stale_running_count"]:
        alerts.append("stale_running_or_dispatching_runs_detected")
    if billing is not None:
        if (metered_limit is not None
                and Decimal(billing["metered_cost_usd"]) >= metered_limit):
            alerts.append("workspace_metered_usd_alert_threshold")
        if (billed_limit is not None
                and Decimal(billing["billed_cost_usd"]) >= billed_limit):
            alerts.append("workspace_billed_usd_alert_threshold")
    return alerts


def positive_usd_argument(raw: str) -> Decimal:
    try:
        result = Decimal(raw)
    except InvalidOperation as exc:
        raise argparse.ArgumentTypeError("USD threshold must be numeric") from exc
    if not result.is_finite() or result <= 0:
        raise argparse.ArgumentTypeError("USD threshold must be positive and finite")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", default=os.environ.get("TRANSLATION_MODAL_PROFILE"))
    parser.add_argument("--skip-billing", action="store_true",
                        help="Do not call Modal CLI; inspect PostgreSQL only")
    parser.add_argument("--alert-metered-usd", type=positive_usd_argument)
    parser.add_argument("--alert-billed-usd", type=positive_usd_argument)
    parser.add_argument("--alert-uncertain-count", type=int, default=1)
    parser.add_argument("--dispatch-age-seconds", type=int, default=300)
    parser.add_argument("--running-age-seconds", type=int, default=900)
    parser.add_argument("--apply-reconcile", action="store_true",
                        help="Explicitly mark stale runs uncertain; NEVER retry or spawn GPU")
    parser.add_argument("--output", type=Path, help="Save redacted aggregate JSON")
    args = parser.parse_args()
    if args.alert_uncertain_count < 1:
        parser.error("--alert-uncertain-count must be positive")
    if min(args.dispatch_age_seconds, args.running_age_seconds) < 1:
        parser.error("Stale age thresholds must be positive")
    url = os.environ.get("TRANSLATION_INFERENCE_DATABASE_URL")
    if not url:
        raise RuntimeError("TRANSLATION_INFERENCE_DATABASE_URL is required")
    engine = make_engine(url)
    try:
        repo = JobRepository(make_session_factory(engine))
        snapshot = collect_operations_snapshot(
            repo, dispatch_age_seconds=args.dispatch_age_seconds,
            running_age_seconds=args.running_age_seconds,
        )
        if args.apply_reconcile:
            snapshot["explicit_reconciliation_transitions"] = repo.reconcile_stale(
                dispatch_age_seconds=args.dispatch_age_seconds,
                running_age_seconds=args.running_age_seconds,
            )
            snapshot["post_reconciliation"] = collect_operations_snapshot(
                repo, dispatch_age_seconds=args.dispatch_age_seconds,
                running_age_seconds=args.running_age_seconds,
            )
    finally:
        engine.dispose()
    billing = None if args.skip_billing else billing_summary(profile=args.profile)
    alerts = make_alerts(
        snapshot, billing, metered_limit=args.alert_metered_usd,
        billed_limit=args.alert_billed_usd,
        alert_uncertain_count=args.alert_uncertain_count,
    )
    report = {
        "checked_at_utc": datetime.now(timezone.utc).isoformat(),
        "kind": "cpu_only_workspace_billing_and_postgresql_safety_snapshot",
        "read_only": not args.apply_reconcile,
        "database": snapshot,
        "modal_billing": billing,
        "alerts": alerts,
        "note": "Workspace spending only; estimated reservations not actual cost. "
                "No GPU allocated, no job retries, no translated content logged.",
    }
    output = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(output + "\n", encoding="utf-8")
        print("Aggregate safety report written:", args.output)
    else:
        print(output)
    return 2 if alerts else 0


if __name__ == "__main__":
    sys.exit(main())
