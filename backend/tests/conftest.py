import os

import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("DEMO_MODE", "false")
os.environ.setdefault("JWT_SECRET", "test-secret")
os.environ.setdefault("HASH_ITERATIONS", "1000")
os.environ.setdefault("LLM_PROVIDER", "mock")
os.environ.setdefault("AUTO_CREATE_SCHEMA", "true")
os.environ.setdefault("ENVIRONMENT", "local")
os.environ.setdefault("HUMAN_REVIEW_EXPOSURE_THRESHOLD", "1000000")


@pytest.fixture
def database(tmp_path, monkeypatch):
    from app.core.config import get_settings
    from app.core.database import init_schema, reset_engine_cache

    monkeypatch.setenv("DATABASE_URL", "sqlite:///" + (tmp_path / "api.db").as_posix())
    monkeypatch.setenv("DEMO_MODE", "false")
    monkeypatch.setenv("JWT_SECRET", "test-secret")
    monkeypatch.setenv("HASH_ITERATIONS", "1000")
    monkeypatch.setenv("LOCAL_STORAGE_PATH", str(tmp_path / "edi"))
    monkeypatch.setenv("INGEST_ROOT", str(tmp_path / "inbox"))
    monkeypatch.setenv("LLM_PROVIDER", "mock")
    monkeypatch.setenv("HUMAN_REVIEW_EXPOSURE_THRESHOLD", "1000000")
    get_settings.cache_clear()
    reset_engine_cache()
    init_schema()
    yield
    reset_engine_cache()
    get_settings.cache_clear()


@pytest.fixture
def client(database):
    from app.main import create_app

    app = create_app()
    with TestClient(app) as test_client:
        yield test_client
