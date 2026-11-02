"""Widen job language labels for arbitrary language names and tags.

Revision ID: 0003_open_languages
Revises: 0002_p2_safety
"""
import sqlalchemy as sa
from alembic import op

revision = "0003_open_languages"
down_revision = "0002_p2_safety"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("jobs") as batch:
        batch.alter_column("source_language", existing_type=sa.String(8),
                           type_=sa.String(64), existing_nullable=False)
        batch.alter_column("target_language", existing_type=sa.String(8),
                           type_=sa.String(64), existing_nullable=False)


def downgrade():
    # Values exceeding 8 characters must be handled before downgrading.
    with op.batch_alter_table("jobs") as batch:
        batch.alter_column("source_language", existing_type=sa.String(64),
                           type_=sa.String(8), existing_nullable=False)
        batch.alter_column("target_language", existing_type=sa.String(64),
                           type_=sa.String(8), existing_nullable=False)
