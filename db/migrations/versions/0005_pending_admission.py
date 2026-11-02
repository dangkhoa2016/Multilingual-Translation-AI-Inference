"""Stable transaction locks for bounded pending workload admission.

Revision ID: 0005_pending_admission
Revises: 0004_run_metrics
"""
import sqlalchemy as sa
from alembic import op

revision = "0005_pending_admission"
down_revision = "0004_run_metrics"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("admission_locks",
                    sa.Column("scope", sa.String(16), primary_key=True),
                    sa.Column("name", sa.String(128), primary_key=True))


def downgrade():
    op.drop_table("admission_locks")
