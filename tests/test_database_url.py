"""PostgreSQL provider URLs must use the installed psycopg v3 driver."""

from translation_ai_inference.database import make_engine, normalize_postgresql_url


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
