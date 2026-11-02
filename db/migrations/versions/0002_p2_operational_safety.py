"""Track dispatch claims and durable submission quotas.

Revision ID: 0002_p2_safety
Revises: 0001_translation_jobs
"""
import sqlalchemy as sa
from alembic import op

revision = "0002_p2_safety"
down_revision = "0001_translation_jobs"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("job_runs", sa.Column("dispatch_claimed_at", sa.DateTime(timezone=True)))
    op.create_table(
        "usage_windows",
        sa.Column("request_owner", sa.String(128), primary_key=True),
        sa.Column("scope", sa.String(32), primary_key=True),
        sa.Column("bucket_start", sa.BigInteger(), primary_key=True),
        sa.Column("used", sa.Integer(), nullable=False),
    )


def downgrade():
    op.drop_table("usage_windows")
    op.drop_column("job_runs", "dispatch_claimed_at")
