from __future__ import annotations

import logging
import os
import sys
import traceback
from pathlib import Path
from typing import Any

from backend.engines.base import cleanup, gpu_memory_mb
from backend.engines.registry import engine_class

# Adapter-specific venvs can fall back to the main environment for heavy shared
# packages (torch etc.) without shadowing their own pinned dependencies.
_main_site = os.environ.get("MYVS_MAIN_SITE")
if _main_site and _main_site not in sys.path:
    sys.path.append(_main_site)


def _configure_logging(model_id: str) -> None:
    root = Path(os.environ.get("MYVS_ROOT", Path(__file__).resolve().parents[2]))
    log_dir = root / "data" / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / f"worker-{model_id.replace(':', '-')}.log"
    handlers: list[logging.Handler] = [logging.FileHandler(log_file, encoding="utf-8")]
    if os.environ.get("MYVS_WORKER_STDERR", "0") == "1":
        handlers.append(logging.StreamHandler())
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        handlers=handlers,
        force=True,
    )


def worker_entry(conn: Any, spec: dict[str, Any]) -> None:
    _configure_logging(str(spec.get("model_id") or "worker"))
    logger = logging.getLogger("myvs.worker")
    engine = None
    try:
        adapter = str(spec["adapter"])
        limit_gb = float((spec.get("settings") or {}).get("vram_limit_gb") or 0)
        if limit_gb > 0 and spec.get("device") == "gpu":
            try:
                import torch

                if torch.cuda.is_available():
                    total_gb = torch.cuda.get_device_properties(0).total_memory / 1024**3
                    torch.cuda.set_per_process_memory_fraction(min(1.0, limit_gb / max(total_gb, 0.1)), device=0)
                    logger.info("applied worker VRAM cap %.2f GB of %.2f GB", limit_gb, total_gb)
            except Exception:
                logger.warning("could not apply worker VRAM cap", exc_info=True)
        logger.info("loading adapter=%s model=%s device=%s precision=%s", adapter, spec.get("model_id"), spec.get("device"), spec.get("precision"))
        engine = engine_class(adapter)()
        metrics = engine.load(spec)
        payload = {
            "event": "ready",
            "pid": os.getpid(),
            "metrics": {**metrics, **gpu_memory_mb()},
        }
        conn.send(payload)
        while True:
            message = conn.recv()
            if not isinstance(message, dict):
                continue
            request_id = message.get("id")
            op = message.get("op")
            if op == "ping":
                conn.send({"id": request_id, "ok": True, "result": {"pong": True, **gpu_memory_mb()}})
                continue
            if op == "unload":
                engine.unload()
                engine = None
                cleanup()
                conn.send({"id": request_id, "ok": True, "result": {"unloaded": True, **gpu_memory_mb()}})
                break
            if op == "metrics":
                conn.send({"id": request_id, "ok": True, "result": gpu_memory_mb()})
                continue
            if op == "warmup":
                try:
                    result = engine.warmup()
                    conn.send({"id": request_id, "ok": True, "result": result})
                except Exception as exc:
                    logger.exception("warmup failed")
                    conn.send({"id": request_id, "ok": False, "error": {"code": "WARMUP_FAILED", "message": str(exc)}})
                continue
            if op == "infer":
                def progress(data: dict[str, Any], rid=request_id) -> None:
                    conn.send({"event": "progress", "id": rid, "progress": data})

                try:
                    result = engine.infer(dict(message.get("payload") or {}), progress)
                    result = {**result, "_worker_metrics": gpu_memory_mb()}
                    conn.send({"id": request_id, "ok": True, "result": result})
                except Exception as exc:
                    logger.exception("inference failed")
                    code = "OOM" if "out of memory" in str(exc).lower() else "INFERENCE_FAILED"
                    conn.send(
                        {
                            "id": request_id,
                            "ok": False,
                            "error": {"code": code, "message": str(exc), "traceback": traceback.format_exc()},
                        }
                    )
                    if code == "OOM":
                        cleanup()
                        break
                continue
            conn.send({"id": request_id, "ok": False, "error": {"code": "UNKNOWN_OP", "message": op}})
    except Exception as exc:
        logger.exception("worker failed")
        try:
            conn.send(
                {
                    "event": "fatal",
                    "error": {
                        "code": "OOM" if "out of memory" in str(exc).lower() else "WORKER_LOAD_FAILED",
                        "message": str(exc),
                        "traceback": traceback.format_exc(),
                    },
                }
            )
        except Exception:
            pass
    finally:
        if engine is not None:
            try:
                engine.unload()
            except Exception:
                pass
        cleanup()
        try:
            conn.close()
        except Exception:
            pass
        logger.info("worker exiting")


if __name__ == "__main__":
    # Spawned workers are started by WorkerClient; this entry point is for debugging only.
    print("worker_main is started by WorkerClient", file=sys.stderr)
