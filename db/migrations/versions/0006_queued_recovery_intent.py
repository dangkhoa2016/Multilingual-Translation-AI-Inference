"""Persist dispatch intent so recovery never upgrades old mock jobs to GPU.

Revision ID: 0006_queued_recovery_intent
Revises: 0005_pending_admission

Existing jobs receive NULL: their original mode is unknown, and automatic
recovery must fail closed rather than guessing a paid execution mode.
"""
import sqlalchemy as sa
from alembic import op

revision = "0006_queued_recovery_intent"
down_revision = "0005_pending_admission"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("jobs", sa.Column("dispatch_mode", sa.String(length=24), nullable=True))


def downgrade():
    op.drop_column("jobs", "dispatch_mode")
