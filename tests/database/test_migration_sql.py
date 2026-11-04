"""The PostgreSQL deployment migration chain can be reviewed without a live DB."""
import os
import subprocess
import sys
from pathlib import Path


def test_postgresql_offline_migration_exports_sql_without_connecting():
    root = Path(__file__).resolve().parents[2]
    env = {**os.environ,
           "TRANSLATION_INFERENCE_MIGRATION_DATABASE_URL": "postgresql+psycopg://offline:offline@invalid.example/review"}
    result = subprocess.run([sys.executable, "-m", "alembic", "-c", "db/alembic.ini",
                             "upgrade", "head", "--sql"], cwd=root, env=env,
                            text=True, capture_output=True, timeout=30)
    assert result.returncode == 0, result.stderr
    assert "CREATE TABLE jobs" in result.stdout
    assert "ALTER TABLE job_runs ADD COLUMN IF NOT EXISTS created_at" in result.stdout
    assert "ALTER TABLE job_runs ADD COLUMN IF NOT EXISTS metrics_json" in result.stdout
