"""Create the initial translation job persistence schema.

Revision ID: 0001_translation_jobs
Revises:
"""
import sqlalchemy as sa
from alembic import op

revision = "0001_translation_jobs"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "jobs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("request_owner", sa.String(128), nullable=False),
        sa.Column("idempotency_key", sa.String(200)),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("source_language", sa.String(8), nullable=False),
        sa.Column("target_language", sa.String(8), nullable=False),
        sa.Column("input_text", sa.Text(), nullable=False),
        sa.Column("options_json", sa.Text(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("request_owner", "idempotency_key", name="uq_jobs_owner_idempotency"),
    )
    op.create_index("ix_jobs_status", "jobs", ["status"])
    op.create_table(
        "job_runs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("job_id", sa.String(36), sa.ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("model_key", sa.String(64), nullable=False),
        sa.Column("attempt_no", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("claim_token", sa.String(36)),
        sa.Column("created_at", sa.DateTime(timezone=True)),
        sa.Column("metrics_json", sa.Text()),
        sa.Column("modal_call_id", sa.String(128)),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("error_code", sa.String(64)),
        sa.UniqueConstraint("job_id", "model_key", "attempt_no", name="uq_job_runs_attempt"),
    )
    op.create_index("ix_job_runs_job_id", "job_runs", ["job_id"])
    op.create_index("ix_job_runs_model_key", "job_runs", ["model_key"])
    op.create_index("ix_job_runs_status", "job_runs", ["status"])
    op.create_table(
        "translation_results",
        sa.Column("run_id", sa.String(36), sa.ForeignKey("job_runs.id", ondelete="CASCADE"),
                  primary_key=True),
        sa.Column("translation_text", sa.Text(), nullable=False),
        sa.Column("is_mock_result", sa.Boolean(), nullable=False),
        sa.Column("input_tokens", sa.Integer()),
        sa.Column("output_tokens", sa.Integer()),
    )


def downgrade():
    op.drop_table("translation_results")
    op.drop_index("ix_job_runs_status", table_name="job_runs")
    op.drop_index("ix_job_runs_model_key", table_name="job_runs")
    op.drop_index("ix_job_runs_job_id", table_name="job_runs")
    op.drop_table("job_runs")
    op.drop_index("ix_jobs_status", table_name="jobs")
    op.drop_table("jobs")
