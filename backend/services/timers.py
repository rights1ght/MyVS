from __future__ import annotations

import contextlib
import logging
import os
import time
from datetime import datetime, timezone
from typing import Iterator

from backend.config import settings
from backend.db.models import StartupPhase, StartupRun
from backend.db.session import session_scope

logger = logging.getLogger(__name__)


class StartupTracker:
    """Measures boot phases and persists a compact history."""

    def __init__(self) -> None:
        started_epoch = float(os.environ.get("MYVS_STARTED_AT", time.time()))
        self.started_at = datetime.fromtimestamp(started_epoch, tz=timezone.utc)
        self._started_perf = time.perf_counter() - max(0.0, time.time() - started_epoch)
        self.phases: list[dict[str, object]] = []
        self.ready = False
        self.ready_at: datetime | None = None
        self.total_ms = 0
        self._persisted = False
        self._active: dict[str, float] = {}

    @contextlib.contextmanager
    def phase(self, name: str, detail: str = "") -> Iterator[None]:
        started = time.perf_counter()
        self._active[name] = started
        status = "ok"
        error = ""
        try:
            yield
        except Exception as exc:
            status = "error"
            error = str(exc)
            raise
        finally:
            duration_ms = int((time.perf_counter() - started) * 1000)
            self.record(name, duration_ms, status, detail or error)

    def record(self, name: str, duration_ms: int, status: str = "ok", detail: str = "") -> None:
        for phase in self.phases:
            if phase["name"] == name:
                phase.update(duration_ms=duration_ms, status=status, detail=detail)
                return
        self.phases.append(
            {
                "name": name,
                "duration_ms": duration_ms,
                "status": status,
                "detail": detail,
            }
        )

    def mark_ready(self) -> None:
        if self.ready:
            return
        self.ready = True
        self.ready_at = datetime.now(timezone.utc)
        self.total_ms = int((time.perf_counter() - self._started_perf) * 1000)
        for phase in self.phases:
            logger.info("startup %-16s %6d ms  %s", phase["name"], phase["duration_ms"], phase["detail"])
        logger.info("startup READY in %d ms", self.total_ms)
        self.persist()

    def persist(self) -> None:
        if self._persisted:
            return
        try:
            with session_scope() as session:
                run = StartupRun(
                    app_version=settings.version,
                    started_at=self.started_at,
                    ready_at=self.ready_at,
                    total_ms=self.total_ms,
                    ok=True,
                )
                session.add(run)
                session.flush()
                for phase in self.phases:
                    session.add(
                        StartupPhase(
                            run_id=run.id,
                            name=str(phase["name"]),
                            duration_ms=int(phase["duration_ms"]),
                            status=str(phase["status"]),
                            detail=str(phase["detail"]),
                        )
                    )
            self._persisted = True
        except Exception:
            logger.exception("failed to persist startup timing")

    def as_dict(self) -> dict[str, object]:
        return {
            "started_at": self.started_at.isoformat(),
            "ready_at": self.ready_at.isoformat() if self.ready_at else None,
            "total_ms": self.total_ms,
            "ready": self.ready,
            "phases": self.phases,
            "version": settings.version,
        }


startup = StartupTracker()
