"""NVML access that keeps working when ``nvidia-ml-py`` is not installed.

``pynvml`` is the real module when available. Otherwise, if the NVIDIA driver's ``nvidia-smi`` tool
exists, a small shim implements the handful of NVML calls MyVS uses on top of it. Without either,
``pynvml`` is ``None`` and ``NVML_ERROR`` explains what to install. A missing ``nvidia-ml-py`` used
to make the whole GPU invisible: the scheduler saw 0 GB of VRAM and refused GPU variants.
"""
from __future__ import annotations

import logging
import os
import shutil
import subprocess
import threading
import time
from types import SimpleNamespace
from typing import Any

logger = logging.getLogger(__name__)

_QUERY = "index,name,memory.total,memory.used,memory.free,utilization.gpu,temperature.gpu,power.draw,clocks.gr"
_TTL_SECONDS = 0.75  # one nvidia-smi process serves every caller inside this window


class NVMLError(RuntimeError):
    pass


def find_nvidia_smi() -> str | None:
    found = shutil.which("nvidia-smi")
    if found:
        return found
    for candidate in (
        os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32", "nvidia-smi.exe"),
        r"C:\Program Files\NVIDIA Corporation\NVSMI\nvidia-smi.exe",
    ):
        if os.path.exists(candidate):
            return candidate
    return None


def _number(text: str) -> float | None:
    try:
        return float(text)
    except (TypeError, ValueError):
        return None  # "[N/A]", "[Not Supported]"


class _SmiNvml:
    """The subset of the ``pynvml`` API used by MyVS, implemented with ``nvidia-smi``."""

    NVML_TEMPERATURE_GPU = 0
    NVML_CLOCK_GRAPHICS = 0

    def __init__(self, exe: str) -> None:
        self.exe = exe
        self._lock = threading.Lock()
        self._cache: tuple[float, list[dict[str, Any]]] | None = None

    # -- plumbing
    def _run(self, *args: str) -> str:
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)  # no console flash on Windows
        completed = subprocess.run([self.exe, *args], capture_output=True, text=True, timeout=10, creationflags=flags)
        if completed.returncode != 0:
            raise NVMLError(completed.stderr.strip() or "nvidia-smi failed")
        return completed.stdout

    def _gpus(self) -> list[dict[str, Any]]:
        with self._lock:
            now = time.monotonic()
            if self._cache and now - self._cache[0] < _TTL_SECONDS:
                return self._cache[1]
            rows = []
            for line in self._run(f"--query-gpu={_QUERY}", "--format=csv,noheader,nounits").splitlines():
                parts = [part.strip() for part in line.split(",")]
                if len(parts) < 9:
                    continue
                rows.append({
                    "index": int(parts[0]), "name": parts[1], "total": _number(parts[2]), "used": _number(parts[3]),
                    "free": _number(parts[4]), "util": _number(parts[5]), "temp": _number(parts[6]),
                    "power": _number(parts[7]), "clock": _number(parts[8]),
                })
            if not rows:
                raise NVMLError("nvidia-smi не вернул ни одной видеокарты")
            self._cache = (now, rows)
            return rows

    def _gpu(self, handle: int) -> dict[str, Any]:
        for row in self._gpus():
            if row["index"] == handle:
                return row
        raise NVMLError(f"GPU {handle} не найден")

    @staticmethod
    def _need(value: float | None) -> float:
        if value is None:
            raise NVMLError("значение недоступно")
        return value

    # -- pynvml-compatible surface
    def nvmlInit(self) -> None:
        self._gpus()

    def nvmlDeviceGetCount(self) -> int:
        return len(self._gpus())

    def nvmlDeviceGetHandleByIndex(self, index: int) -> int:
        self._gpu(index)
        return index

    def nvmlDeviceGetName(self, handle: int) -> str:
        return str(self._gpu(handle)["name"])

    def nvmlDeviceGetMemoryInfo(self, handle: int) -> SimpleNamespace:
        row, mib = self._gpu(handle), 1024 * 1024
        return SimpleNamespace(total=int(self._need(row["total"]) * mib), used=int(self._need(row["used"]) * mib), free=int(self._need(row["free"]) * mib))

    def nvmlDeviceGetUtilizationRates(self, handle: int) -> SimpleNamespace:
        return SimpleNamespace(gpu=self._need(self._gpu(handle)["util"]))

    def nvmlDeviceGetTemperature(self, handle: int, _sensor: int = 0) -> float:
        return self._need(self._gpu(handle)["temp"])

    def nvmlDeviceGetPowerUsage(self, handle: int) -> float:  # milliwatts, like NVML
        return self._need(self._gpu(handle)["power"]) * 1000.0

    def nvmlDeviceGetClockInfo(self, handle: int, _clock: int = 0) -> float:
        return self._need(self._gpu(handle)["clock"])

    def nvmlDeviceGetComputeRunningProcesses(self, _handle: int) -> list[SimpleNamespace]:
        processes = []
        for line in self._run("--query-compute-apps=pid,used_memory", "--format=csv,noheader,nounits").splitlines():
            pid, _, used = (part.strip() for part in line.partition(","))
            memory = _number(used)
            if pid.isdigit():
                processes.append(SimpleNamespace(pid=int(pid), usedGpuMemory=int(memory * 1024 * 1024) if memory is not None else None))
        return processes


def _load() -> tuple[Any, str, str]:
    """-> (pynvml-like module or None, backend name, error text)."""
    try:
        import pynvml as real  # provided by the nvidia-ml-py package

        return real, "nvidia-ml-py", ""
    except Exception as exc:
        problem = str(exc) or exc.__class__.__name__
    exe = find_nvidia_smi()
    if exe:
        logger.warning(
            "nvidia-ml-py не установлен (%s): использую nvidia-smi, это медленнее. "
            "Установите: python -m pip install nvidia-ml-py", problem,
        )
        return _SmiNvml(exe), "nvidia-smi", ""
    return None, "none", f"{problem}; nvidia-smi не найден. Установите драйвер NVIDIA и выполните: python -m pip install nvidia-ml-py"


pynvml, NVML_BACKEND, NVML_ERROR = _load()
