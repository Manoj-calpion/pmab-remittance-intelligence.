"""SQLAlchemy engine and session management."""

from collections.abc import Generator
from functools import lru_cache
from pathlib import Path

from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings


def _prepare_sqlite_url(url: str) -> str:
    if not url.startswith("sqlite:///"):
        return url
    if url == "sqlite:///:memory:" or url.startswith("sqlite:////"):
        return url
    raw_path = url.removeprefix("sqlite:///")
    if raw_path == ":memory:":
        return url
    path = Path(raw_path)
    if not path.is_absolute():
        path = Path.cwd() / path
    path.parent.mkdir(parents=True, exist_ok=True)
    return "sqlite:///" + path.as_posix()


@lru_cache
def get_engine() -> Engine:
    settings = get_settings()
    url = settings.database_url
    connect_args: dict = {}
    if url.startswith("sqlite"):
        url = _prepare_sqlite_url(url)
        connect_args["check_same_thread"] = False
    engine = create_engine(url, connect_args=connect_args, future=True, pool_pre_ping=True)
    if engine.dialect.name == "sqlite":

        @event.listens_for(engine, "connect")
        def _enable_fk(dbapi_connection, _connection_record) -> None:
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

    return engine


@lru_cache
def get_session_factory() -> sessionmaker[Session]:
    return sessionmaker(bind=get_engine(), autoflush=False, autocommit=False, expire_on_commit=False)


def get_db() -> Generator[Session, None, None]:
    session = get_session_factory()()
    try:
        yield session
    finally:
        session.close()


def check_database() -> bool:
    with get_engine().connect() as connection:
        connection.execute(text("SELECT 1"))
    return True


def init_schema() -> None:
    settings = get_settings()
    if not settings.auto_create_schema:
        return
    from app.models import Base

    if get_engine().dialect.name == "postgresql":
        with get_engine().begin() as connection:
            connection.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
    Base.metadata.create_all(bind=get_engine())


def reset_engine_cache() -> None:
    get_session_factory.cache_clear()
    get_engine.cache_clear()
