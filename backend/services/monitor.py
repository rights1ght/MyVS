from __future__ import annotations

import logging
import platform
import time
from collections import deque
from datetime import datetime, timezone
from typing import Any, Callable

import psutil

from backend.config import settings
from backend.db.models import ResourceAlert
from backend.db.session import session_scope

logger = logging.getLogger(__name__)

from backend.services.nvml import NVML_BACKEND, NVML_ERROR as _NVML_IMPORT_ERROR, pynvml  # real pynvml or an nvidia-smi shim


def _mb(value: float) -> float:
    return round(value / (1024 * 1024), 1)


class Monitor:
    """One-hertz host/GPU sampler with a five-minute in-memory history."""

    def __init__(self) -> None:
        self.seq = 0
        self.history: deque[dict[str, Any]] = deque(maxlen=300)
        self.alerts: deque[dict[str, Any]] = deque(maxlen=30)
        self._last_disk = psutil.disk_io_counters()
        self._last_disk_ts = time.monotonic()
        self._last_level: dict[str, int] = {}
        self._last_alert_ts: dict[str, float] = {}
        self._nvml_ready = False
        self._gpu_error = ""
        self._gpu_index = 0
        self._handle: Any = None
        self._gpu_name = ""
        self._gpu_total_mb = 0.0
        self.persistence_enabled = False
        self.models_provider: Callable[[], list[dict[str, Any]]] | None = None
        psutil.cpu_percent(interval=None, percpu=True)
        self._init_gpu()

    # ------------------------------------------------------------------ GPU
    def _init_gpu(self) -> None:
        if settings.disable_nvml:
            self._gpu_error = "NVML отключён конфигурацией"
            return
        if pynvml is None:
            self._gpu_error = _NVML_IMPORT_ERROR or "pynvml не установлен"
            return
        try:
            pynvml.nvmlInit()
            count = pynvml.nvmlDeviceGetCount()
            if count < 1:
                self._gpu_error = "NVIDIA GPU не найден"
                return
            self._handle = pynvml.nvmlDeviceGetHandleByIndex(self._gpu_index)
            name = pynvml.nvmlDeviceGetName(self._handle)
            self._gpu_name = name.decode() if isinstance(name, bytes) else str(name)
            self._gpu_total_mb = _mb(float(pynvml.nvmlDeviceGetMemoryInfo(self._handle).total))
            self._nvml_ready = True
        except Exception as exc:
            self._gpu_error = str(exc)
            logger.warning("NVML unavailable: %s", exc)

    def probe_gpu(self) -> dict[str, Any]:
        return {
            "available": self._nvml_ready,
            "name": self._gpu_name,
            "total_mb": self._gpu_total_mb,
            "error": self._gpu_error,
            "backend": NVML_BACKEND,  # "nvidia-ml-py", "nvidia-smi" (fallback) or "none"
        }

    def _gpu_snapshot(self) -> dict[str, Any]:
        if not self._nvml_ready or self._handle is None:
            return {
                "available": False,
                "name": self._gpu_name,
                "error": self._gpu_error or "NVIDIA GPU/драйвер недоступны",
                "util": None,
                "vram_used_mb": None,
                "vram_total_mb": None,
                "temp_c": None,
                "power_w": None,
                "clock_mhz": None,
            }
        gpu = self._handle
        data: dict[str, Any] = {"available": True, "name": self._gpu_name, "error": ""}
        try:
            mem = pynvml.nvmlDeviceGetMemoryInfo(gpu)
            data["vram_used_mb"] = _mb(float(mem.used))
            data["vram_total_mb"] = _mb(float(mem.total))
        except Exception as exc:
            data["vram_used_mb"] = None
            data["vram_total_mb"] = None
            data["error"] = f"VRAM: {exc}"
        for key, fn in (
            ("util", lambda: pynvml.nvmlDeviceGetUtilizationRates(gpu).gpu),
            ("temp_c", lambda: pynvml.nvmlDeviceGetTemperature(gpu, pynvml.NVML_TEMPERATURE_GPU)),
            ("power_w", lambda: pynvml.nvmlDeviceGetPowerUsage(gpu) / 1000.0),
            ("clock_mhz", lambda: pynvml.nvmlDeviceGetClockInfo(gpu, pynvml.NVML_CLOCK_GRAPHICS)),
        ):
            try:
                data[key] = round(float(fn()), 1)
            except Exception:
                data[key] = None
        return data

    # ------------------------------------------------------------- CPU/RAM/IO
    def _cpu_snapshot(self) -> dict[str, Any]:
        per_core = psutil.cpu_percent(interval=None, percpu=True)
        freq = None
        try:
            current = psutil.cpu_freq()
            freq = round(current.current, 0) if current else None
        except Exception:
            pass
        temp = None
        try:
            sensors = psutil.sensors_temperatures()
            candidates = sensors.get("coretemp") or sensors.get("k10temp") or sensors.get("acpitz") or []
            if candidates:
                temp = round(max(item.current for item in candidates), 1)
        except Exception:
            pass
        return {
            "percent": round(sum(per_core) / len(per_core), 1) if per_core else 0.0,
            "per_core": [round(value, 1) for value in per_core],
            "freq_mhz": freq,
            "temp_c": temp,
        }

    def _ram_snapshot(self) -> dict[str, Any]:
        mem = psutil.virtual_memory()
        swap = psutil.swap_memory()
        return {
            "used_mb": _mb(mem.used),
            "total_mb": _mb(mem.total),
            "available_mb": _mb(mem.available),
            "percent": round(mem.percent, 1),
            "swap_used_mb": _mb(swap.used),
            "swap_total_mb": _mb(swap.total),
            "swap_percent": round(swap.percent, 1),
        }

    def _disk_snapshot(self) -> dict[str, Any]:
        now = time.monotonic()
        current = psutil.disk_io_counters()
        read_bps = write_bps = 0.0
        if current and self._last_disk:
            elapsed = max(now - self._last_disk_ts, 0.001)
            read_bps = max(0.0, (current.read_bytes - self._last_disk.read_bytes) / elapsed)
            write_bps = max(0.0, (current.write_bytes - self._last_disk.write_bytes) / elapsed)
        self._last_disk = current
        self._last_disk_ts = now
        usage = psutil.disk_usage(str(settings.data_dir))
        return {
            "read_mb_s": round(read_bps / (1024 * 1024), 2),
            "write_mb_s": round(write_bps / (1024 * 1024), 2),
            "free_gb": round(usage.free / (1024**3), 1),
            "total_gb": round(usage.total / (1024**3), 1),
        }

    # --------------------------------------------------------------- alerts
    @staticmethod
    def _level(value: float, medium: float, high: float, critical: float) -> int:
        if value >= critical:
            return 3
        if value >= high:
            return 2
        if value >= medium:
            return 1
        return 0

    def _alert(self, metric: str, level: int, value: float, threshold: float, message: str) -> None:
        if level <= self._last_level.get(metric, 0):
            return
        now = time.monotonic()
        severity = {1: "warning", 2: "high", 3: "critical"}[level]
        if now - self._last_alert_ts.get(metric, 0) < 30:
            for existing in reversed(self.alerts):
                # alerts store ``severity``, not a numeric level (this used to raise KeyError every second)
                if existing["metric"] == metric and existing["severity"] == severity:
                    return
        alert = {
            "id": f"mem-{int(time.time() * 1000)}-{metric}",
            "ts": datetime.now(timezone.utc).isoformat(),
            "severity": severity,
            "metric": metric,
            "value": round(value, 1),
            "threshold": threshold,
            "model_id": "",
            "task_id": "",
            "message": message,
            "acknowledged": False,
        }
        self.alerts.append(alert)
        self._last_level[metric] = level
        self._last_alert_ts[metric] = now
        if not self.persistence_enabled:
            return
        try:
            with session_scope() as session:
                session.add(
                    ResourceAlert(
                        severity=severity,
                        metric=metric,
                        value=value,
                        threshold=threshold,
                        message=message,
                    )
                )
        except Exception:
            logger.exception("failed to persist resource alert")

    def _check_alerts(self, snapshot: dict[str, Any]) -> None:
        ram = snapshot["ram"]
        self._alert(
            "ram",
            self._level(ram["percent"], 80, 90, 100),
            ram["percent"],
            80,
            f"RAM загружена на {ram['percent']}%",
        )
        self._alert(
            "swap",
            self._level(ram["swap_percent"], 80, 90, 100),
            ram["swap_percent"],
            80,
            f"Swap загружен на {ram['swap_percent']}%",
        )
        gpu = snapshot["gpu"]
        if gpu.get("available") and gpu.get("vram_total_mb"):
            pct = gpu["vram_used_mb"] / gpu["vram_total_mb"] * 100
            self._alert(
                "vram",
                self._level(pct, 80, 90, 100),
                pct,
                80,
                f"VRAM занята на {pct:.0f}%",
            )
        if gpu.get("temp_c") is not None:
            self._alert(
                "gpu_temp",
                self._level(gpu["temp_c"], 80, 87, 93),
                gpu["temp_c"],
                80,
                f"Температура GPU {gpu['temp_c']} °C",
            )
        # Reset levels after recovery so repeated spikes are reported.
        vram_pct = (
            (gpu["vram_used_mb"] / gpu["vram_total_mb"] * 100)
            if gpu.get("available") and gpu.get("vram_used_mb") and gpu.get("vram_total_mb")
            else 0
        )
        for metric, value in (
            ("ram", ram["percent"]),
            ("swap", ram["swap_percent"]),
            ("vram", vram_pct),
            ("gpu_temp", gpu.get("temp_c") or 0),
        ):
            if value < 80:
                self._last_level[metric] = 0

    # ---------------------------------------------------------------- public
    def sample(self) -> dict[str, Any]:
        self.seq += 1
        snapshot: dict[str, Any] = {
            "seq": self.seq,
            "ts": datetime.now(timezone.utc).isoformat(),
            "cpu": self._cpu_snapshot(),
            "gpu": self._gpu_snapshot(),
            "ram": self._ram_snapshot(),
            "disk": self._disk_snapshot(),
            "models": self.models_provider() if self.models_provider else [],
            "alerts": list(self.alerts)[-10:],
            "platform": platform.system(),
        }
        self._check_alerts(snapshot)
        self.history.append(snapshot)
        return snapshot

    def snapshot(self) -> dict[str, Any]:
        return self.history[-1] if self.history else self.sample()

    def get_history(self, seconds: int = 300, after: int | None = None) -> list[dict[str, Any]]:
        """Last ``seconds`` samples; with ``after`` only samples newer than that ``seq``.

        The Monitor page used to re-download all 300 samples (~170 KB) every 2 s; it now asks only for
        what it has not seen. A ``seq`` from before a server restart (greater than ours) means "send everything".
        """
        items = list(self.history)[-min(max(seconds, 1), 300) :]
        if after is not None and items and after <= items[-1]["seq"]:
            items = [item for item in items if item["seq"] > after]
        return items


monitor = Monitor()
