from __future__ import annotations

import base64
import json
import logging
import os
import queue
import secrets
import subprocess
import sys
import threading
import time
from concurrent.futures import Future, TimeoutError as FutureTimeoutError
from multiprocessing.connection import Connection, Listener
from pathlib import Path
from typing import Any, Callable

import psutil

from backend.engines.runtimes import python_for

logger = logging.getLogger(__name__)
ROOT = Path(__file__).resolve().parents[2]


class WorkerError(Exception):
    def __init__(self, code: str, message: str, traceback: str = "") -> None:
        super().__init__(message)
        self.code = code
        self.traceback = traceback


class WorkerClient:
    def __init__(self, spec: dict[str, Any], *, log_prefix: str = "worker") -> None:
        self.spec = spec
        self.log_prefix = log_prefix
        self.process: subprocess.Popen[bytes] | None = None
        self.conn: Connection | None = None
        self.pid: int | None = None
        self.metrics: dict[str, Any] = {}
        self._reader: threading.Thread | None = None
        self._pending: dict[str, Future] = {}
        self._progress: dict[str, Callable[[dict[str, Any]], None]] = {}
        self._lock = threading.Lock()
        self._ready = threading.Event()
        self._fatal: WorkerError | None = None
        self._dead = False
        self._started_at = 0.0

    @property
    def alive(self) -> bool:
        return bool(self.process and self.process.poll() is None and not self._dead)

    def _env(self, python: str) -> dict[str, str]:
        env = os.environ.copy()
        env["MYVS_ROOT"] = str(ROOT)
        from backend.config import settings

        env["HF_HOME"] = str(settings.hf_cache)
        env["PYTHONPATH"] = str(ROOT) + os.pathsep + env.get("PYTHONPATH", "")
        env["PYTHONUTF8"] = "1"
        try:
            import shutil

            import imageio_ffmpeg

            source = Path(imageio_ffmpeg.get_ffmpeg_exe())
            bin_dir = ROOT / "data" / "bin"
            bin_dir.mkdir(parents=True, exist_ok=True)
            alias = bin_dir / ("ffmpeg.exe" if os.name == "nt" else "ffmpeg")
            if not alias.exists():
                try:
                    os.link(source, alias)
                except Exception:
                    shutil.copy2(source, alias)
            env["PATH"] = str(bin_dir) + os.pathsep + str(source.parent) + os.pathsep + env.get("PATH", "")
        except Exception:
            pass
        try:
            import site

            sites = site.getsitepackages()
            if sites:
                env["MYVS_MAIN_SITE"] = sites[-1]
        except Exception:
            pass
        return env

    def start(self, timeout: float = 900.0) -> dict[str, Any]:
        python, runtime = python_for(str(self.spec.get("adapter") or ""))
        self.spec["runtime_label"] = runtime
        self.spec["python"] = python
        token = secrets.token_bytes(24)
        listener = Listener(("127.0.0.1", 0), authkey=token)
        host, port = listener.address  # type: ignore[misc]
        env = self._env(python)
        env["MYVS_WORKER_HOST"] = str(host)
        env["MYVS_WORKER_PORT"] = str(port)
        env["MYVS_WORKER_AUTH"] = token.hex()
        env["MYVS_SPEC"] = base64.b64encode(json.dumps(self.spec, ensure_ascii=False).encode("utf-8")).decode("ascii")
        creationflags = 0
        if os.name == "nt":
            creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        self._started_at = time.monotonic()
        try:
            self.process = subprocess.Popen(
                [python, "-m", "backend.engines.worker_cli"],
                cwd=str(ROOT),
                env=env,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=creationflags,
            )
        except Exception:
            listener.close()
            raise
        self.pid = self.process.pid

        accepted: queue.Queue[Connection] = queue.Queue(maxsize=1)

        def accept() -> None:
            try:
                accepted.put(listener.accept())
            except Exception:
                pass
            finally:
                listener.close()

        threading.Thread(target=accept, name=f"myvs-accept-{self.pid}", daemon=True).start()
        try:
            self.conn = accepted.get(timeout=60)
        except queue.Empty:
            self.kill()
            raise WorkerError("WORKER_CRASHED", "Воркер не подключился к родительскому процессу.")
        self._reader = threading.Thread(target=self._read_loop, name=f"myvs-reader-{self.pid}", daemon=True)
        self._reader.start()
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self._ready.wait(0.2):
                if self._fatal:
                    raise self._fatal
                self.metrics["load_seconds"] = round(time.monotonic() - self._started_at, 3)
                return self.metrics
            if self.process and self.process.poll() is not None and not self._ready.is_set():
                raise WorkerError("WORKER_CRASHED", f"Воркер завершился с кодом {self.process.returncode}.")
        self.kill()
        raise WorkerError("WORKER_TIMEOUT", "Модель не загрузилась за отведённое время.")

    def _read_loop(self) -> None:
        conn = self.conn
        if conn is None:
            return
        while True:
            try:
                if not conn.poll(0.5):
                    if self.process and self.process.poll() is not None:
                        break
                    continue
                message = conn.recv()
            except (EOFError, OSError):
                break
            except Exception:
                logger.exception("worker reader error")
                break
            if not isinstance(message, dict):
                continue
            event = message.get("event")
            if event == "ready":
                self.metrics = dict(message.get("metrics") or {})
                self.metrics["pid"] = message.get("pid") or self.pid
                self._ready.set()
                continue
            if event == "fatal":
                error = message.get("error") or {}
                self._fatal = WorkerError(error.get("code", "WORKER_LOAD_FAILED"), error.get("message", "worker failed"), error.get("traceback", ""))
                self._ready.set()
                continue
            if event == "progress":
                request_id = str(message.get("id") or "")
                callback = self._progress.get(request_id)
                if callback:
                    try:
                        callback(dict(message.get("progress") or {}))
                    except Exception:
                        logger.exception("progress callback failed")
                continue
            request_id = str(message.get("id") or "")
            future = self._pending.pop(request_id, None)
            self._progress.pop(request_id, None)
            if not future:
                continue
            if message.get("ok"):
                future.set_result(message.get("result") or {})
            else:
                error = message.get("error") or {}
                future.set_exception(
                    WorkerError(error.get("code", "WORKER_ERROR"), error.get("message", "worker request failed"), error.get("traceback", ""))
                )
        self._dead = True
        self._ready.set()
        for future in list(self._pending.values()):
            if not future.done():
                future.set_exception(WorkerError("WORKER_DIED", "Воркер неожиданно завершился."))
        self._pending.clear()
        self._progress.clear()

    def call(
        self,
        op: str,
        payload: dict[str, Any] | None = None,
        *,
        timeout: float | None = 600.0,
        on_progress: Callable[[dict[str, Any]], None] | None = None,
    ) -> dict[str, Any]:
        if not self.alive or self.conn is None:
            raise WorkerError("WORKER_DEAD", "Воркер не запущен.")
        request_id = f"{self.pid}-{time.time_ns()}"
        future: Future = Future()
        with self._lock:
            self._pending[request_id] = future
            if on_progress:
                self._progress[request_id] = on_progress
            try:
                self.conn.send({"id": request_id, "op": op, "payload": payload or {}})
            except Exception as exc:
                self._pending.pop(request_id, None)
                self._progress.pop(request_id, None)
                raise WorkerError("WORKER_SEND_FAILED", str(exc)) from exc
        try:
            return future.result(timeout=timeout)
        except FutureTimeoutError:
            with self._lock:
                self._pending.pop(request_id, None)
                self._progress.pop(request_id, None)
            raise WorkerError("WORKER_TIMEOUT", "Операция модели заняла слишком много времени.")

    def infer(self, payload: dict[str, Any], on_progress: Callable[[dict[str, Any]], None] | None = None) -> dict[str, Any]:
        return self.call("infer", payload, timeout=None, on_progress=on_progress)

    def ping(self) -> dict[str, Any]:
        return self.call("ping", timeout=10.0)

    def unload(self) -> None:
        if self.conn and self.alive:
            try:
                self.call("unload", timeout=30.0)
            except Exception:
                logger.warning("graceful unload failed", exc_info=True)
        self.close(force=False)

    def kill(self) -> None:
        self.close(force=True)

    def close(self, *, force: bool) -> None:
        if self.conn is not None:
            try:
                self.conn.close()
            except Exception:
                pass
            self.conn = None
        self._dead = True
        process = self.process
        if process is None:
            return
        if process.poll() is None and not force:
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                pass
        if process.poll() is None:
            try:
                parent = psutil.Process(process.pid)
                for child in parent.children(recursive=True):
                    try:
                        child.kill()
                    except Exception:
                        pass
                parent.kill()
            except Exception:
                try:
                    process.kill()
                except Exception:
                    pass
        try:
            process.wait(timeout=5)
        except Exception:
            pass
        self.process = None

    def restart(self, timeout: float = 900.0) -> dict[str, Any]:
        self.kill()
        return self.start(timeout=timeout)
