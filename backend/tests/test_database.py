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


def test_run_migrations_stamps_empty_postgres(monkeypatch, tmp_path):
    import sys
    import types

    database = load_database(monkeypatch, tmp_path)

    calls: list[tuple[str, object]] = []

    class FakeConnection:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return False

        def execute(self, statement):
            calls.append(("execute", str(statement)))
            return self

        def commit(self):
            calls.append(("commit", None))

    class FakeEngine:
        connection = FakeConnection()

        def connect(self):
            return self.connection

    fake_engine = FakeEngine()

    monkeypatch.setattr(database, "is_postgres", lambda: True)
    monkeypatch.setattr(database, "engine", fake_engine)
    monkeypatch.setattr(database, "_postgres_has_alembic_version", lambda conn: False)
    monkeypatch.setattr(database, "_postgres_has_application_tables", lambda conn: False)
    monkeypatch.setattr(
        database,
        "create_schema_from_metadata",
        lambda bind=None: calls.append(("metadata", bind is fake_engine.connection)),
    )

    def fake_stamp(config, revision):
        calls.append(("stamp", (revision, config.attributes.get("connection") is fake_engine.connection)))

    def fake_upgrade(config, revision):
        calls.append(("upgrade", revision))

    class FakeConfig:
        def __init__(self, filename):
            self.filename = filename
            self.attributes = {}
            self.main_options = {}

        def set_main_option(self, key, value):
            self.main_options[key] = value

    fake_command = types.SimpleNamespace(stamp=fake_stamp, upgrade=fake_upgrade)
    fake_alembic = types.ModuleType("alembic")
    fake_alembic.command = fake_command
    fake_config_module = types.ModuleType("alembic.config")
    fake_config_module.Config = FakeConfig
    monkeypatch.setitem(sys.modules, "alembic", fake_alembic)
    monkeypatch.setitem(sys.modules, "alembic.config", fake_config_module)

    database.run_migrations()

    assert ("metadata", True) in calls
    assert ("stamp", ("head", True)) in calls
    assert ("upgrade", "head") not in calls
