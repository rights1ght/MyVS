from __future__ import annotations

import gc
import json
import logging
import os
import time
from pathlib import Path
from typing import Any, Callable, Protocol

import numpy as np

logger = logging.getLogger(__name__)


class Engine(Protocol):
    def load(self, spec: dict[str, Any]) -> dict[str, Any]: ...
    def unload(self) -> None: ...
    def infer(self, payload: dict[str, Any], progress: Callable[[dict[str, Any]], None]) -> dict[str, Any]: ...


class BaseEngine:
    adapter = "base"
    supports_tts = False
    supports_clone = False
    supports_design = False

    def __init__(self) -> None:
        self.spec: dict[str, Any] = {}
        self.model: Any = None
        self.device = "cpu"
        self.sample_rate = 24000

    def load(self, spec: dict[str, Any]) -> dict[str, Any]:
        self.spec = spec
        self.device = "cuda:0" if spec.get("device") == "gpu" else "cpu"
        return {"device": self.device, "sample_rate": self.sample_rate}

    def unload(self) -> None:
        self.model = None
        cleanup()

    def warmup(self) -> dict[str, Any]:
        """Optional one-shot warmup; safe no-op by default."""
        return {"warmed": False}

    def infer(self, payload: dict[str, Any], progress: Callable[[dict[str, Any]], None]) -> dict[str, Any]:
        raise NotImplementedError

    @staticmethod
    def read_json(path: str | Path) -> dict[str, Any]:
        with Path(path).open("r", encoding="utf-8") as handle:
            return json.load(handle)

    @staticmethod
    def write_json(path: str | Path, payload: dict[str, Any]) -> None:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with Path(path).open("w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)

    def result_wav(self, audio: np.ndarray, sample_rate: int, output_path: str) -> dict[str, Any]:
        import soundfile as sf

        audio = np.asarray(audio, dtype=np.float32)
        if audio.ndim > 1:
            audio = audio.mean(axis=1)
        peak = float(np.max(np.abs(audio))) if audio.size else 0.0
        if peak > 0.99:
            audio = audio / peak * 0.98
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        sf.write(output_path, audio, sample_rate, subtype="PCM_16")
        return {
            "output_path": output_path,
            "sample_rate": sample_rate,
            "duration_sec": round(len(audio) / max(sample_rate, 1), 3),
            "peak": round(peak, 4),
        }


def gpu_memory_mb() -> dict[str, float]:
    out: dict[str, float] = {}
    try:
        import torch

        if torch.cuda.is_available():
            free, total = torch.cuda.mem_get_info()
            out["vram_free_mb"] = round(free / 1024**2, 1)
            out["vram_total_mb"] = round(total / 1024**2, 1)
            out["vram_allocated_mb"] = round(torch.cuda.memory_allocated() / 1024**2, 1)
            out["vram_reserved_mb"] = round(torch.cuda.memory_reserved() / 1024**2, 1)
    except Exception:
        pass
    try:
        import pynvml

        pynvml.nvmlInit()
        handle = pynvml.nvmlDeviceGetHandleByIndex(0)
        mem = pynvml.nvmlDeviceGetMemoryInfo(handle)
        out["gpu_total_mb"] = round(mem.total / 1024**2, 1)
        out["gpu_used_mb"] = round(mem.used / 1024**2, 1)
    except Exception:
        pass
    try:
        import psutil

        out["ram_rss_mb"] = round(psutil.Process(os.getpid()).memory_info().rss / 1024**2, 1)
    except Exception:
        pass
    return out


def cleanup() -> None:
    gc.collect()
    torch = None
    try:
        import torch as torch_module

        torch = torch_module
    except Exception:
        torch = None
    if torch is not None:
        try:
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
                torch.cuda.ipc_collect()
        except Exception:
            pass


def progress_timer(progress: Callable[[dict[str, Any]], None], interval: float = 0.4):
    last = {"at": 0.0}

    def emit(**payload: Any) -> None:
        now = time.monotonic()
        if now - last["at"] >= interval:
            last["at"] = now
            progress(payload)

    return emit
