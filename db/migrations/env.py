"""Versioned migrations. Use a direct PostgreSQL URL for migration operations."""
import os

from alembic import context
from sqlalchemy import create_engine, pool

from translation_ai_inference.database import Base, normalize_postgresql_url

config = context.config
target_metadata = Base.metadata


def get_database_url() -> str:
    url = os.environ.get("TRANSLATION_INFERENCE_MIGRATION_DATABASE_URL") or os.environ.get(
        "TRANSLATION_INFERENCE_DATABASE_URL")
    if not url:
        raise RuntimeError("Set TRANSLATION_INFERENCE_MIGRATION_DATABASE_URL (direct PostgreSQL URL)")
    return normalize_postgresql_url(url)


def run_migrations_offline() -> None:
    context.configure(url=get_database_url(), target_metadata=target_metadata,
                      literal_binds=True, dialect_opts={"paramstyle": "named"})
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    engine = create_engine(get_database_url(), poolclass=pool.NullPool)
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata,
                          compare_type=True)
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
