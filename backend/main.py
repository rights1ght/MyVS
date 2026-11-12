from __future__ import annotations

import asyncio
import contextlib
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from backend.api.errors import install_error_handlers
from backend.api.routes import models as model_routes
from backend.api.routes import monitor as monitor_routes
from backend.api.routes import projects as project_routes
from backend.api.routes import resources as resource_routes
from backend.api.routes import settings as settings_routes
from backend.api.routes import stt as stt_routes
from backend.api.routes import system as system_routes
from backend.api.routes import tasks as task_routes
from backend.api.routes import tts as tts_routes
from backend.api.routes import voices as voice_routes
from backend.api.ws import monitor_ws
from backend.config import settings
from backend.db.session import init_db
from backend.services.downloads import downloads
from backend.services.model_registry import registry
from backend.services.monitor import monitor
from backend.services.resource_manager import resources
from backend.services.tasks import tasks
from backend.services.timers import startup
from backend.services.voices import seed_builtin_voices

logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


async def _monitor_loop() -> None:
    while True:
        started = asyncio.get_running_loop().time()
        try:
            snapshot = monitor.sample()
            await monitor_ws.broadcast(snapshot)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("monitor loop error")
        elapsed = asyncio.get_running_loop().time() - started
        await asyncio.sleep(max(0.05, 1.0 - elapsed))


@asynccontextmanager
async def lifespan(_app: FastAPI):
    with startup.phase("backend_init", "FastAPI + конфигурация"):
        settings.ensure_dirs()
        build_ms = int(__import__("os").environ.get("MYVS_FRONTEND_BUILD_MS", "0"))
        if build_ms:
            startup.record("frontend_build", build_ms, "ok", "Vite production build")
    with startup.phase("db_init", "SQLite / SQLModel"):
        init_db()
        monitor.persistence_enabled = True
        downloads.mark_interrupted()
    with startup.phase("gpu_probe", "NVML / GPU"):
        gpu = monitor.probe_gpu()
        logger.info("GPU: %s", gpu.get("name") or gpu.get("error"))
    with startup.phase("model_scan", "каталог моделей"):
        registry.sync()
        seed_builtin_voices()
        monitor.models_provider = resources.loaded
    with startup.phase("preload", "предзагрузка"):
        resources.start_idle_watcher()
        tasks.start()
        try:
            from backend.services.settings_service import get_settings_values

            preload = get_settings_values().get("preload_models") or []
            for model_id in preload:
                if any(v.install_state == "installed" for v in registry.variants(str(model_id))):
                    try:
                        resources.ensure_loaded(str(model_id), force=True)
                    except Exception:
                        logger.warning("preload failed for %s", model_id, exc_info=True)
        except Exception:
            logger.warning("preload settings unavailable", exc_info=True)
    if settings.frontend_index.exists():
        startup.record("frontend_ready", 0, "ok", "static SPA")
    startup.mark_ready()
    task = asyncio.create_task(_monitor_loop())
    try:
        yield
    finally:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
        tasks.stop()
        resources.stop()


class SelectiveGZipMiddleware:
    """GZip for JSON/text/static assets, but never for audio.

    Audio is streamed with Range support (``<audio>`` seeking); compressing it would break partial
    responses and gains nothing on already-dense WAV/MP3 payloads.
    """

    SKIP_SUFFIXES = ("/audio", "/reference")

    def __init__(self, app, minimum_size: int = 1024) -> None:  # type: ignore[no-untyped-def]
        self.app = app
        self.gzip = GZipMiddleware(app, minimum_size=minimum_size, compresslevel=4)  # level 9 (default) is ~5x slower for little gain

    async def __call__(self, scope, receive, send):  # type: ignore[no-untyped-def]
        if scope["type"] == "http" and scope["path"].endswith(self.SKIP_SUFFIXES):
            await self.app(scope, receive, send)
        else:
            await self.gzip(scope, receive, send)


def create_app() -> FastAPI:
    app = FastAPI(
        title="MyVS API",
        version=settings.version,
        description="Локальная студия речи: STT, TTS, клонирование голоса, модели и мониторинг.",
        lifespan=lifespan,
    )
    install_error_handlers(app)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://127.0.0.1:5173", "http://localhost:5173", "http://127.0.0.1:8000"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.add_middleware(SelectiveGZipMiddleware, minimum_size=1024)
    for router in (
        system_routes.router,
        monitor_routes.router,
        model_routes.router,
        resource_routes.router,
        task_routes.router,
        stt_routes.router,
        tts_routes.router,
        voice_routes.router,
        settings_routes.router,
        project_routes.router,
    ):
        app.include_router(router)

    @app.websocket("/ws/monitor")
    async def monitor_socket(ws: WebSocket) -> None:
        await monitor_ws.connect(ws)
        try:
            await ws.send_json(monitor.snapshot())
            while True:
                await ws.receive_text()
        except WebSocketDisconnect:
            pass
        except Exception:
            logger.debug("monitor websocket closed", exc_info=True)
        finally:
            await monitor_ws.disconnect(ws)

    @app.websocket("/ws/tasks/{task_id}")
    async def task_socket(ws: WebSocket, task_id: str) -> None:
        await ws.accept()
        try:
            while True:
                task = tasks.get(task_id)
                if not task:
                    await ws.send_json({"type": "error", "message": "task not found"})
                    break
                payload = tasks.task_public(task)
                await ws.send_json({"type": "task", **payload})
                if task.status in ("completed", "failed", "cancelled"):
                    break
                await asyncio.sleep(0.5)
        except WebSocketDisconnect:
            pass
        except Exception:
            logger.debug("task websocket closed", exc_info=True)
        finally:
            with contextlib.suppress(Exception):
                await ws.close()

    @app.websocket("/ws/downloads/{download_id}")
    async def download_socket(ws: WebSocket, download_id: str) -> None:
        await ws.accept()
        try:
            while True:
                row = downloads.get(download_id)
                if not row:
                    await ws.send_json({"type": "error", "message": "download not found"})
                    break
                await ws.send_json({"type": "download", **row.model_dump()})
                if row.status in ("completed", "error", "cancelled"):
                    break
                await asyncio.sleep(0.5)
        except WebSocketDisconnect:
            pass
        except Exception:
            logger.debug("download websocket closed", exc_info=True)
        finally:
            with contextlib.suppress(Exception):
                await ws.close()

    dist = settings.frontend_dist
    if dist.exists():
        assets = dist / "assets"
        if assets.exists():
            app.mount("/assets", StaticFiles(directory=assets), name="assets")

        @app.get("/{full_path:path}", include_in_schema=False)
        async def spa(full_path: str):
            if full_path.startswith(("api/", "ws/", "docs", "redoc", "openapi.json")):
                return JSONResponse({"error": {"code": "NOT_FOUND", "message": "Not found"}}, status_code=404)
            candidate = (dist / full_path).resolve()
            if full_path and candidate.is_file() and dist.resolve() in candidate.parents:
                return FileResponse(candidate)
            return FileResponse(dist / "index.html")

    else:

        @app.get("/", include_in_schema=False)
        async def no_frontend() -> JSONResponse:
            return JSONResponse(
                {
                    "message": "Frontend не собран.",
                    "hint": "Запустите python run.py или npm --prefix frontend run build.",
                    "docs": "/docs",
                }
            )

    return app


app = create_app()
