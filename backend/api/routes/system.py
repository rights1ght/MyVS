from __future__ import annotations

import importlib.metadata
import os
import platform
import shutil
import signal
import sys
import threading
import time
from pathlib import Path

import psutil
from fastapi import APIRouter
from pydantic import BaseModel
from sqlmodel import desc, select

from backend.config import settings
from backend.api.schemas import HealthOut, StartupHistoryItem, StartupInfo, SystemInfo
from backend.db.models import StartupPhase, StartupRun
from backend.db.session import session_scope
from backend.api.errors import AppError
from backend.engines.runtimes import runtime_status
from backend.services.preflight import check_environment
from backend.services.monitor import monitor
from backend.services.resource_manager import resources
from backend.services.tasks import tasks
from backend.services.timers import startup

router = APIRouter(prefix="/api", tags=["system"])


@router.get("/health", response_model=HealthOut)
def health() -> HealthOut:
    return HealthOut(version=settings.version, ready=startup.ready, data_dir=str(settings.data_dir))


@router.get("/system/info", response_model=SystemInfo)
def system_info() -> SystemInfo:
    disk = psutil.disk_usage(str(settings.data_dir))
    return SystemInfo(
        app=settings.app_name,
        version=settings.version,
        platform=f"{platform.system()} {platform.release()}",
        python=sys.version.split()[0],
        host=settings.host,
        port=settings.port,
        gpu=monitor.probe_gpu(),
        data_dir=str(settings.data_dir),
        frontend_built=settings.frontend_index.exists(),
        reserve_vram_gb=settings.reserve_vram_gb,
        reserve_ram_gb=settings.reserve_ram_gb,
        disk_free_gb=round(disk.free / (1024**3), 1),
    )


@router.get("/system/startup/current", response_model=StartupInfo)
def startup_current() -> StartupInfo:
    return StartupInfo(**startup.as_dict())  # type: ignore[arg-type]


@router.get("/system/startup/history", response_model=list[StartupHistoryItem])
def startup_history(limit: int = 20) -> list[StartupHistoryItem]:
    limit = max(1, min(limit, 100))
    with session_scope() as session:
        runs = session.exec(select(StartupRun).order_by(desc(StartupRun.started_at)).limit(limit)).all()
        items: list[StartupHistoryItem] = []
        for run in runs:
            phases = session.exec(
                select(StartupPhase).where(StartupPhase.run_id == run.id).order_by(StartupPhase.started_at)
            ).all()
            items.append(
                StartupHistoryItem(
                    id=run.id,
                    app_version=run.app_version,
                    started_at=run.started_at.isoformat(),
                    ready_at=run.ready_at.isoformat() if run.ready_at else None,
                    total_ms=run.total_ms,
                    ok=run.ok,
                    error=run.error,
                    phases=[
                        {
                            "name": phase.name,
                            "duration_ms": phase.duration_ms,
                            "status": phase.status,
                            "detail": phase.detail,
                        }
                        for phase in phases
                    ],
                )
            )
    return items


class ShutdownPayload(BaseModel):
    confirm: bool = False


@router.post("/system/shutdown", status_code=202)
def shutdown(payload: ShutdownPayload) -> dict[str, object]:
    """Unload every model, stop task dispatch and terminate the local server."""
    if not payload.confirm:
        raise AppError("CONFIRM_REQUIRED", "Подтвердите остановку сервера.", 400)
    loaded = [item["model_id"] for item in resources.loaded()]
    try:
        resources.stop()
    except Exception:
        pass
    try:
        tasks.stop()
    except Exception:
        pass
    marker = settings.data_dir / ".shutdown"
    marker.write_text(str(time.time()), encoding="utf-8")
    pid = os.getpid()

    def terminate() -> None:
        time.sleep(1.2)
        try:
            if os.name != "nt":
                os.kill(pid, signal.SIGTERM)
            else:
                # The response must reach the browser before the process ends.
                os._exit(0)
        except Exception:
            os._exit(0)

    threading.Thread(target=terminate, name="myvs-shutdown", daemon=True).start()
    return {
        "status": "shutting_down",
        "loaded_before": loaded,
        "message": "Модели выгружены, сервер останавливается.",
    }


@router.get("/system/diagnostics")
def diagnostics() -> dict[str, object]:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        try:
            import imageio_ffmpeg

            ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
        except Exception:
            ffmpeg = None
    packages: dict[str, str] = {}
    for name in ("fastapi", "sqlmodel", "psutil", "nvidia-ml-py", "huggingface-hub", "faster-whisper", "torch", "omnivoice"):
        try:
            packages[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            packages[name] = "not installed"
    gpu = monitor.probe_gpu()
    return {
        "gpu": gpu,
        "python": sys.executable,
        "warnings": check_environment(gpu_present=bool(gpu.get("available"))),
        "ffmpeg": ffmpeg,
        "packages": packages,
        "db_path": str(settings.db_path),
        "db_exists": Path(settings.db_path).exists(),
        "worker_pid": None,
        "frontend_index": str(settings.frontend_index),
        "runtimes": runtime_status(),
    }
