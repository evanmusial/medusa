def load_database(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", "sqlite+pysqlite:///:memory:")
    monkeypatch.setenv("MEDUSA_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("MEDUSA_LOCAL_STORAGE_DIR", str(tmp_path / "data" / "originals"))
    from app.config import get_settings

    get_settings.cache_clear()
    from app import database

    return database


def test_init_db_uses_alembic_for_postgres(monkeypatch, tmp_path):
    database = load_database(monkeypatch, tmp_path)

    calls: list[str] = []
    monkeypatch.setattr(database, "is_postgres", lambda: True)
    monkeypatch.setattr(database, "run_migrations", lambda: calls.append("migrations"))
    monkeypatch.setattr(database, "create_schema_from_metadata", lambda: calls.append("metadata"))

    database.init_db()

    assert calls == ["migrations"]


def test_init_db_uses_metadata_for_sqlite(monkeypatch, tmp_path):
    database = load_database(monkeypatch, tmp_path)

    calls: list[str] = []
    monkeypatch.setattr(database, "is_postgres", lambda: False)
    monkeypatch.setattr(database, "run_migrations", lambda: calls.append("migrations"))
    monkeypatch.setattr(database, "create_schema_from_metadata", lambda: calls.append("metadata"))

    database.init_db()

    assert calls == ["metadata"]
