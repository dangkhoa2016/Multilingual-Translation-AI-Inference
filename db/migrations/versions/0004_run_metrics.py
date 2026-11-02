"""Optional per-attempt telemetry. Existing rows remain readable without backfill.

Revision ID: 0004_run_metrics
Revises: 0003_open_languages
"""
import sqlalchemy as sa
from alembic import op

revision = "0004_run_metrics"
down_revision = "0003_open_languages"
branch_labels = None
depends_on = None


def upgrade():
    # Earlier source revisions already declare the fields in the initial schema.
    # Older, actually deployed databases may lack them: add only when missing.
    if op.get_context().as_sql:
        if op.get_context().dialect.name != "postgresql":
            raise RuntimeError("Offline deployment migrations require PostgreSQL")
        # Safe for both historical schemas and fresh installs with these fields.
        op.execute("ALTER TABLE job_runs ADD COLUMN IF NOT EXISTS created_at TIMESTAMP WITH TIME ZONE")
        op.execute("ALTER TABLE job_runs ADD COLUMN IF NOT EXISTS metrics_json TEXT")
        return
    existing = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("job_runs")}
    if "created_at" not in existing:
        op.add_column("job_runs", sa.Column("created_at", sa.DateTime(timezone=True), nullable=True))
    if "metrics_json" not in existing:
        op.add_column("job_runs", sa.Column("metrics_json", sa.Text(), nullable=True))


def downgrade():
    # Non-destructive rollback: these nullable columns are part of the initial
    # migration for fresh installs. Retaining them also keeps legacy upgrades safe
    # if this Alembic revision is downgraded and upgraded again.
    pass
