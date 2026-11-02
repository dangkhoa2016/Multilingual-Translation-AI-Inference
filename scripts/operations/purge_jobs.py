"""Retention maintenance for terminal jobs; dry run by default.

Deletes input text and result text with their terminal jobs, never pending,
running, or uncertain jobs. Does not reset daily quota counters.
"""
import argparse
import os

from multilingual_translation_ai_inference.database import make_engine, make_session_factory
from multilingual_translation_ai_inference.repository import JobRepository


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--retention-days", type=int, default=90)
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    if not os.environ.get("TRANSLATION_INFERENCE_DATABASE_URL"):
        raise SystemExit("TRANSLATION_INFERENCE_DATABASE_URL is required")
    engine = make_engine(os.environ["TRANSLATION_INFERENCE_DATABASE_URL"])
    try:
        repo = JobRepository(make_session_factory(engine))
        count = repo.purge_old_terminal_jobs(
            retention_days=args.retention_days, limit=args.limit, apply=args.apply,
        )
        print("deleted" if args.apply else "eligible (dry-run)", "terminal jobs:", count)
        if not args.apply:
            print("No deletion performed. Set --apply only after reviewing retention policy.")
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
