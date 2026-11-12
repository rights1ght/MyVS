from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

from sqlalchemy import event
from sqlalchemy.engine import Engine
from sqlmodel import Session, SQLModel, create_engine, select

from backend.config import settings
from backend.db.models import AppSetting, Project

settings.ensure_dirs()

engine = create_engine(
    f"sqlite:///{settings.db_path.as_posix()}",
    connect_args={"check_same_thread": False, "timeout": 30},
)


@event.listens_for(Engine, "connect")
def _sqlite_pragmas(dbapi_connection, _connection_record) -> None:  # type: ignore[no-untyped-def]
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    # WAL + synchronous=NORMAL is crash-safe for the database file (only the last commits can be
    # lost on power failure) and avoids an fsync on every commit; the queue/event code commits a lot.
    cursor.execute("PRAGMA synchronous=NORMAL")
    cursor.execute("PRAGMA cache_size=-32768")  # 32 MiB page cache per connection
    cursor.execute("PRAGMA temp_store=MEMORY")
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.execute("PRAGMA busy_timeout=30000")
    cursor.close()


def init_db() -> None:
    settings.ensure_dirs()
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        if not session.exec(select(Project)).first():
            session.add(Project(name="Без проекта", description="Задачи вне проекта", color="#5eead4"))
        defaults = {
            "resource_mode": {"value": settings.resource_mode},
            "conflict_policy": {"value": settings.conflict_policy},
            "reserve_vram_gb": {"value": settings.reserve_vram_gb},
            "reserve_ram_gb": {"value": settings.reserve_ram_gb},
            "idle_unload_seconds": {"value": settings.idle_unload_seconds},
            "theme": {"value": "dark"},
            "preload_models": {"value": []},
        }
        for key, value in defaults.items():
            if not session.get(AppSetting, key):
                session.add(AppSetting(key=key, value=value))
        session.commit()


@contextmanager
def session_scope() -> Iterator[Session]:
    with Session(engine, expire_on_commit=False) as session:
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
