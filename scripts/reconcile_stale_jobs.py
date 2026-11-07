"""Operator-only P2 maintenance. Never retries, spawns or terminates a worker.

Load TRANSLATION_INFERENCE_DATABASE_URL from .env before running.
Without --apply this script is read-only.
"""
import argparse
import os

from translation_ai_inference.database import make_engine, make_session_factory
from translation_ai_inference.repository import JobRepository


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dispatch-age-seconds", type=int, default=300)
    parser.add_argument("--running-age-seconds", type=int, default=900)
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    if not os.environ.get("TRANSLATION_INFERENCE_DATABASE_URL"):
        raise SystemExit("TRANSLATION_INFERENCE_DATABASE_URL is required")
    engine = make_engine(os.environ["TRANSLATION_INFERENCE_DATABASE_URL"])
    try:
        repo = JobRepository(make_session_factory(engine))
        preview = repo.stale_counts(
            dispatch_age_seconds=args.dispatch_age_seconds,
            running_age_seconds=args.running_age_seconds,
        )
        print("stale dispatching:", preview["dispatching"],
              "; stale running:", preview["running"])
        if args.apply:
            changed = repo.reconcile_stale(
                dispatch_age_seconds=args.dispatch_age_seconds,
                running_age_seconds=args.running_age_seconds,
                limit=args.limit,
            )
            print("marked uncertain (never retried):", changed)
        else:
            print("DRY RUN: no database modifications; pass --apply to mark uncertain")
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
