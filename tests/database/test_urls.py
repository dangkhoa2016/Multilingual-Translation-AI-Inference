"""PostgreSQL provider URLs must use the installed psycopg v3 driver."""

from multilingual_translation_ai_inference.database import make_engine, normalize_postgresql_url


def test_provider_postgresql_scheme_selects_psycopg_v3():
    source = "postgresql://user:password@db.example.org:5432/translation?sslmode=require"
    converted = normalize_postgresql_url(source)
    assert converted.startswith("postgresql+psycopg://")
    assert converted.endswith("/translation?sslmode=require")
    engine = make_engine(source)
    assert engine.dialect.driver == "psycopg"
    engine.dispose()


def test_explicit_psycopg_and_sqlite_are_unchanged():
    assert normalize_postgresql_url("postgresql+psycopg://user:pass@host/db") == "postgresql+psycopg://user:pass@host/db"
    assert normalize_postgresql_url("sqlite+pysqlite:///test.sqlite3") == "sqlite+pysqlite:///test.sqlite3"


def test_open_language_migration_widens_existing_columns(tmp_path, monkeypatch):
    from pathlib import Path

    from alembic import command
    from alembic.config import Config
    from sqlalchemy import create_engine, inspect

    root = Path(__file__).resolve().parents[2]
    database_url = f"sqlite:///{tmp_path / 'upgrade.sqlite3'}"
    monkeypatch.setenv("TRANSLATION_INFERENCE_MIGRATION_DATABASE_URL", database_url)
    cfg = Config(str(root / "db/alembic.ini"))
    cfg.set_main_option("script_location", str(root / "db/migrations"))
    command.upgrade(cfg, "0002_p2_safety")
    engine = create_engine(database_url)
    before = {col["name"]: col for col in inspect(engine).get_columns("jobs")}
    assert before["source_language"]["type"].length == 8
    assert before["target_language"]["type"].length == 8
    engine.dispose()
    command.upgrade(cfg, "head")
    engine = create_engine(database_url)
    after = {col["name"]: col for col in inspect(engine).get_columns("jobs")}
    assert after["source_language"]["type"].length == 64
    assert after["target_language"]["type"].length == 64
    engine.dispose()
