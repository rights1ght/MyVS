from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable

import psutil
from sqlmodel import desc, select

from backend.config import settings
from backend.db.models import ModelMeasurement, ModelRecord, ModelRuntimeEvent, ModelVariant
from backend.db.session import session_scope
from backend.engines.worker_client import WorkerClient, WorkerError
from backend.services.model_registry import registry

logger = logging.getLogger(__name__)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _gb(value_mb: float | None) -> float:
    return round((value_mb or 0.0) / 1024, 3)


class ResourceError(Exception):
    def __init__(self, code: str, message: str, **details: Any) -> None:
        super().__init__(message)
        self.code = code
        self.details = details


@dataclass
class ResourcePlan:
    model_id: str
    variant_id: str
    model_name: str
    device: str
    precision: str
    need_vram_gb: float
    free_vram_gb: float
    need_ram_gb: float
    free_ram_gb: float
    verdict: str  # fits | tight | no
    margin_gb: float
    reason: str
    options: list[dict[str, Any]] = field(default_factory=list)
    source: str = "catalog"  # catalog | measured

    def as_dict(self) -> dict[str, Any]:
        return self.__dict__.copy()


@dataclass
class ModelRuntime:
    model_id: str
    variant_id: str
    model_name: str
    device: str
    precision: str
    worker: WorkerClient
    state: str = "loaded"
    last_used: float = field(default_factory=time.monotonic)
    loaded_at: float = field(default_factory=time.monotonic)
    metrics: dict[str, Any] = field(default_factory=dict)
    inference_lock: threading.Lock = field(default_factory=threading.Lock)
    busy: bool = False
    active_task_id: str = ""
    vram_mb: float = 0.0
    ram_mb: float = 0.0

    def public(self) -> dict[str, Any]:
        return {
            "model_id": self.model_id,
            "model_name": self.model_name,
            "variant_id": self.variant_id,
            "state": "busy" if self.busy else self.state,
            "device": self.device,
            "precision": self.precision,
            "vram_mb": self.vram_mb,
            "ram_mb": self.ram_mb,
            "last_used": datetime.fromtimestamp(time.time() - (time.monotonic() - self.last_used), tz=timezone.utc).isoformat(),
            "task_id": self.active_task_id or None,
        }


class ResourceManager:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        # Model process lifecycle is serialized to prevent duplicate workers,
        # reservation races and load/unload interleaving across model variants.
        self._lifecycle_lock = threading.RLock()
        self._runtimes: dict[str, ModelRuntime] = {}
        self._reserved_vram_gb = 0.0
        self._reserved_ram_gb = 0.0
        self._stop = threading.Event()
        self._idle_thread: threading.Thread | None = None
        self._mode = settings.resource_mode
        self._policy = settings.conflict_policy
        self._reserve_vram_gb = settings.reserve_vram_gb
        self._reserve_ram_gb = settings.reserve_ram_gb
        self._idle_seconds = settings.idle_unload_seconds
        self._gpu_total_mb = 0.0
        self._gpu_used_mb = 0.0
        self._gpu_available = False
        self._refresh_gpu()
        self._exclusive_snapshot: list[tuple[str, str]] = []
        self._exclusive_target: str = ""
        self._restoring = False

    # ------------------------------------------------------------- GPU / RAM
    def _refresh_gpu(self) -> None:
        if settings.disable_nvml:
            self._gpu_available = False
            return
        try:
            import pynvml

            pynvml.nvmlInit()
            handle = pynvml.nvmlDeviceGetHandleByIndex(0)
            info = pynvml.nvmlDeviceGetMemoryInfo(handle)
            self._gpu_total_mb = info.total / 1024**2
            self._gpu_used_mb = info.used / 1024**2
            self._gpu_available = True
        except Exception:
            self._gpu_available = False

    def refresh_settings(self) -> None:
        from backend.services.settings_service import get_settings_values

        values = get_settings_values()
        # Each value is applied independently: one corrupt row must not abort the
        # whole refresh (it runs every 15 s in the idle watcher, which also unloads idle models).
        def apply(key: str, attr: str, cast: Callable[[Any], Any], valid: Callable[[Any], bool] = lambda _v: True) -> None:
            try:
                value = cast(values.get(key, getattr(self, attr)))
                if not valid(value):
                    raise ValueError(value)
                setattr(self, attr, value)
            except (TypeError, ValueError):
                logger.warning("ignoring invalid setting %s=%r", key, values.get(key))

        apply("resource_mode", "_mode", str, lambda v: v in ("parallel", "economy", "exclusive"))
        apply("conflict_policy", "_policy", str, lambda v: v in ("ask", "auto"))
        apply("reserve_vram_gb", "_reserve_vram_gb", float, lambda v: v >= 0)
        apply("reserve_ram_gb", "_reserve_ram_gb", float, lambda v: v >= 0)
        apply("idle_unload_seconds", "_idle_seconds", int, lambda v: v >= 0)

    @property
    def mode(self) -> str:
        return self._mode

    @property
    def policy(self) -> str:
        return self._policy

    def set_mode(self, mode: str) -> None:
        if mode not in ("parallel", "economy", "exclusive"):
            raise ResourceError("INVALID_MODE", "Неизвестный режим ресурсов.")
        self._mode = mode

    def _mem(self) -> dict[str, float]:
        self._refresh_gpu()
        vm = psutil.virtual_memory()
        used_ram_gb = (vm.total - vm.available) / 1024**3
        return {
            "gpu_total_gb": round(self._gpu_total_mb / 1024, 3),
            "gpu_used_gb": round(self._gpu_used_mb / 1024, 3),
            "free_vram_gb": round(max(0.0, (self._gpu_total_mb - self._gpu_used_mb) / 1024 - self._reserve_vram_gb - self._reserved_vram_gb), 3),
            "ram_total_gb": round(vm.total / 1024**3, 3),
            "ram_used_gb": round(used_ram_gb, 3),
            "free_ram_gb": round(max(0.0, vm.total / 1024**3 - used_ram_gb - self._reserve_ram_gb - self._reserved_ram_gb), 3),
            "reserve_vram_gb": self._reserve_vram_gb,
            "reserve_ram_gb": self._reserve_ram_gb,
            "reserved_vram_gb": round(self._reserved_vram_gb, 3),
            "gpu_available": self._gpu_available,
        }

    # --------------------------------------------------------------- planning
    def _measurement(self, model_id: str, variant_id: str) -> ModelMeasurement | None:
        return registry.latest_measurement(model_id, variant_id)

    def plan(self, model_id: str, variant_id: str | None = None, device: str | None = None) -> ResourcePlan:
        model = registry.get(model_id)
        if not model:
            raise ResourceError("MODEL_NOT_FOUND", "Модель не найдена.")
        variant = registry.resolve_variant(model_id, variant_id)
        if not variant:
            raise ResourceError("VARIANT_NOT_FOUND", "Вариант модели не найден.")
        target_device = device or variant.device
        # Prefer an installed variant on the target device.
        if device and device != variant.device:
            candidates = [v for v in registry.variants(model_id) if v.device == device and v.install_state == "installed"]
            if candidates:
                variant = candidates[0]
            else:
                raise ResourceError("VARIANT_NOT_INSTALLED", f"Нет установленного варианта для {device}.")
        if variant.install_state != "installed":
            raise ResourceError("MODEL_NOT_INSTALLED", "Модель не скачана. Откройте менеджер моделей.", variant_id=variant.id)
        runtime = self._runtimes.get(model_id)
        if (
            runtime
            and runtime.state in ("loaded", "busy")
            and runtime.variant_id == variant.id
            and ("gpu" if runtime.device.startswith("cuda") else "cpu") == target_device
        ):
            mem = self._mem()
            return ResourcePlan(
                model_id=model_id,
                variant_id=runtime.variant_id,
                model_name=model.name,
                device=runtime.device,
                precision=runtime.precision,
                need_vram_gb=0.0,
                free_vram_gb=mem["free_vram_gb"],
                need_ram_gb=0.0,
                free_ram_gb=mem["free_ram_gb"],
                verdict="fits",
                margin_gb=mem["free_vram_gb"],
                reason="Модель уже загружена.",
                options=[],
                source="measured",
            )
        measurement = self._measurement(model_id, variant.id)
        if target_device == "cpu":
            need_vram = 0.0
            need_ram = measurement.ram_gb if measurement and measurement.ram_gb else variant.ram_estimate_gb + 0.3
        else:
            base = measurement.peak_vram_gb if measurement and measurement.peak_vram_gb else variant.vram_estimate_gb + 0.35
            need_vram = max(0.0, base)
            need_ram = measurement.ram_gb if measurement and measurement.ram_gb else variant.ram_estimate_gb + 0.5
        mem = self._mem()
        # When replacing an already loaded variant of this same model, account
        # for the memory that will be released before the new worker is started.
        if runtime and runtime.state in ("loaded", "busy"):
            if target_device == "gpu" and runtime.device.startswith("cuda"):
                reclaimed = runtime.vram_mb / 1024 if runtime.vram_mb else self._estimate_loaded(runtime)
                mem["free_vram_gb"] = round(mem["free_vram_gb"] + reclaimed, 3)
            elif target_device == "cpu" and runtime.device == "cpu":
                mem["free_ram_gb"] = round(mem["free_ram_gb"] + runtime.ram_mb / 1024, 3)
        if target_device == "cpu":
            free_vram = mem["free_vram_gb"]
            margin = mem["free_ram_gb"] - need_ram
            verdict = "fits" if margin >= 0.3 else "tight" if margin >= 0 else "no"
            reason = f"RAM: нужно {need_ram:.2f} GB, свободно {mem['free_ram_gb']:.2f} GB."
        else:
            free_vram = mem["free_vram_gb"]
            margin = free_vram - need_vram
            verdict = "fits" if margin >= 0.25 else "tight" if margin >= 0 else "no"
            reason = f"VRAM: нужно {need_vram:.2f} GB, свободно {free_vram:.2f} GB."
        options = self._options(model, variant, target_device, mem, need_vram, verdict)
        return ResourcePlan(
            model_id=model_id,
            variant_id=variant.id,
            model_name=model.name,
            device=target_device,
            precision=variant.precision,
            need_vram_gb=round(need_vram, 3),
            free_vram_gb=free_vram,
            need_ram_gb=round(need_ram, 3),
            free_ram_gb=mem["free_ram_gb"],
            verdict=verdict,
            margin_gb=round(margin, 3),
            reason=reason,
            options=options,
            source="measured" if measurement and measurement.peak_vram_gb else "catalog",
        )

    def _options(
        self,
        model: ModelRecord,
        variant: ModelVariant,
        device: str,
        mem: dict[str, float],
        need_vram: float,
        verdict: str,
    ) -> list[dict[str, Any]]:
        options: list[dict[str, Any]] = []
        if verdict == "fits":
            return options
        loaded = [runtime for runtime in self._runtimes.values() if runtime.device != "cpu"]
        for runtime in sorted(loaded, key=lambda item: item.last_used):
            if runtime.busy:
                continue
            reclaimed = runtime.vram_mb / 1024 if runtime.vram_mb else self._estimate_loaded(runtime)
            options.append(
                {
                    "id": f"evict:{runtime.model_id}",
                    "action": "evict",
                    "label": f"Выгрузить {runtime.model_name} (LRU)",
                    "model_id": runtime.model_id,
                    "reclaim_gb": round(reclaimed, 2),
                    "would_fit": (mem["free_vram_gb"] + reclaimed) - need_vram >= 0.25,
                }
            )
        if device == "gpu":
            for other in registry.variants(model.id):
                if other.device == "cpu" and other.install_state == "installed":
                    options.append(
                        {
                            "id": f"cpu:{other.id}",
                            "action": "cpu",
                            "label": "Перевести на CPU",
                            "variant_id": other.id,
                            "would_fit": mem["free_ram_gb"] - (other.ram_estimate_gb + 0.3) >= 0,
                        }
                    )
                    break
            for other in registry.variants(model.id):
                if other.device == "gpu" and other.install_state == "installed" and other.id != variant.id and other.vram_estimate_gb < variant.vram_estimate_gb:
                    options.append(
                        {
                            "id": f"quant:{other.id}",
                            "action": "quant",
                            "label": f"Взять вариант {other.label or other.precision}",
                            "variant_id": other.id,
                            "would_fit": mem["free_vram_gb"] - other.vram_estimate_gb >= 0.25,
                        }
                    )
        options.append({"id": "cancel", "action": "cancel", "label": "Отмена"})
        return options

    @staticmethod
    def _estimate_loaded(runtime: ModelRuntime) -> float:
        variant = registry.get_variant(runtime.model_id, runtime.variant_id)
        return variant.vram_estimate_gb if variant else 0.0

    # ---------------------------------------------------------------- loading
    def _enforce_mode(self, model: ModelRecord, variant: ModelVariant) -> None:
        other = [runtime for runtime in self._runtimes.values() if runtime.device != "cpu"]
        if variant.device != "gpu":
            return
        if model.requires_exclusive or self._mode == "exclusive":
            if not self._restoring and other and not self._exclusive_snapshot:
                self._exclusive_snapshot = [(runtime.model_id, runtime.variant_id) for runtime in other if runtime.model_id != model.id]
                self._exclusive_target = model.id
            for runtime in other:
                if runtime.busy:
                    raise ResourceError(
                        "GPU_BUSY",
                        f"Эксклюзивный режим: {runtime.model_name} занята задачей. Дождитесь завершения или отмените её.",
                        busy_model=runtime.model_name,
                    )
                self.unload(runtime.model_id, reason="exclusive")
        elif self._mode == "economy" and other:
            idle = [runtime for runtime in other if not runtime.busy]
            if idle:
                self.unload(min(idle, key=lambda item: item.last_used).model_id, reason="economy")
            else:
                raise ResourceError("GPU_BUSY", "Экономный режим: GPU занята другой моделью.", busy_model=other[0].model_name)

    def ensure_loaded(
        self,
        model_id: str,
        variant_id: str | None = None,
        *,
        device: str | None = None,
        task_id: str = "",
        force: bool = False,
        restoring: bool = False,
    ) -> ModelRuntime:
        with self._lifecycle_lock:
            return self._ensure_loaded_locked(
                model_id, variant_id, device=device, task_id=task_id, force=force, restoring=restoring
            )

    def _ensure_loaded_locked(
        self,
        model_id: str,
        variant_id: str | None = None,
        *,
        device: str | None = None,
        task_id: str = "",
        force: bool = False,
        restoring: bool = False,
    ) -> ModelRuntime:
        with self._lock:
            model = registry.get(model_id)
            if not model:
                raise ResourceError("MODEL_NOT_FOUND", "Модель не найдена.")
            variant = registry.resolve_variant(model_id, variant_id)
            if not variant:
                raise ResourceError("VARIANT_NOT_FOUND", "Вариант модели не найден.")
            if device and device != variant.device:
                candidates = [v for v in registry.variants(model_id) if v.device == device and v.install_state == "installed"]
                if candidates:
                    variant = candidates[0]
                else:
                    raise ResourceError("VARIANT_NOT_INSTALLED", f"Нет установленного варианта для {device}.")
            runtime = self._runtimes.get(model_id)
            desired_device = "cuda:0" if (device or variant.device) == "gpu" else "cpu"
            if runtime and runtime.state in ("loaded", "busy"):
                if runtime.variant_id == variant.id and runtime.device == desired_device:
                    runtime.last_used = time.monotonic()
                    return runtime
                if runtime.busy:
                    raise ResourceError("MODEL_BUSY", "Нельзя сменить вариант модели во время выполнения задачи.")
                self.unload(model_id, reason="variant-switch")
            elif runtime and runtime.state in ("loading", "unloading"):
                raise ResourceError("MODEL_TRANSITION", "Модель уже загружается или выгружается.")
            if not restoring:
                self._enforce_mode(model, variant)
            plan = self.plan(model_id, variant.id, device)
            if plan.verdict == "no" and not force:
                raise ResourceError("INSUFFICIENT_RESOURCES", plan.reason, plan=plan.as_dict())
            if plan.verdict == "tight" and self._policy == "ask" and not task_id and not force and not restoring:
                raise ResourceError("RESOURCE_CONFIRMATION", plan.reason, plan=plan.as_dict())
            if plan.device == "gpu":
                self._reserved_vram_gb += plan.need_vram_gb
            else:
                self._reserved_ram_gb += plan.need_ram_gb
            runtime = ModelRuntime(
                model_id=model_id,
                variant_id=variant.id,
                model_name=model.name,
                device="cuda:0" if plan.device == "gpu" else "cpu",
                precision=variant.precision,
                worker=None,  # type: ignore[arg-type]
                state="loading",
                active_task_id=task_id,
            )
            self._runtimes[model_id] = runtime
        started = time.monotonic()
        before_gpu = self._mem()["gpu_used_gb"]
        try:
            spec = self._build_spec(model, variant, plan)
            worker = WorkerClient(spec, log_prefix=model_id)
            runtime.worker = worker
            metrics = worker.start(timeout=900.0)
            try:
                warmup = worker.call("warmup", timeout=180.0)
                metrics["warmup"] = warmup
            except Exception:
                logger.warning("warmup failed for %s", model_id, exc_info=True)
            after = self._gpu_process_used(worker.pid)
            with self._lock:
                self._reserved_vram_gb = max(0.0, self._reserved_vram_gb - (plan.need_vram_gb if plan.device == "gpu" else 0.0))
                self._reserved_ram_gb = max(0.0, self._reserved_ram_gb - (plan.need_ram_gb if plan.device == "cpu" else 0.0))
            if plan.device == "gpu":
                after_gpu = self._mem()["gpu_used_gb"]
                delta_gpu = max(0.0, after_gpu - before_gpu)
                torch_alloc = float(metrics.get("vram_allocated_mb", 0) or 0) / 1024
                vram = max(after, delta_gpu, torch_alloc)
            else:
                vram = 0.0
            actual_device = str(metrics.get("device") or runtime.device)
            if plan.device == "gpu" and not actual_device.lower().startswith(("cuda", "gpu")):
                logger.warning(
                    "model %s requested GPU but worker reported %s; recording actual device",
                    model_id, actual_device,
                )
                runtime.device = "cpu"
                vram = 0.0
            elif actual_device.lower().startswith(("cuda", "gpu")):
                runtime.device = "cuda:0"
            else:
                runtime.device = "cpu"
            runtime.vram_mb = round(vram * 1024, 1)
            runtime.ram_mb = float(metrics.get("ram_rss_mb") or 0.0)
            runtime.metrics = metrics
            runtime.state = "loaded"
            runtime.loaded_at = time.monotonic()
            self._record_measurement(model, variant, plan, metrics, vram)
            self._runtime_event(model_id, variant.id, "load", plan.device, started, True, runtime.vram_mb)
            logger.info("loaded %s (%s) on %s, %.2f GB VRAM", model_id, variant.id, plan.device, vram)
            return runtime
        except Exception as exc:
            # A worker can fail after its process has been created but before
            # it reports READY. Always terminate it before dropping the runtime.
            if runtime.worker is not None:
                try:
                    runtime.worker.kill()
                except Exception:
                    logger.exception("failed to terminate worker after load error: %s", model_id)
            with self._lock:
                self._reserved_vram_gb = max(0.0, self._reserved_vram_gb - (plan.need_vram_gb if plan.device == "gpu" else 0.0))
                self._reserved_ram_gb = max(0.0, self._reserved_ram_gb - (plan.need_ram_gb if plan.device == "cpu" else 0.0))
                current = self._runtimes.get(model_id)
                if current and current.state == "loading":
                    self._runtimes.pop(model_id, None)
            self._runtime_event(model_id, variant.id, "load", plan.device, started, False, 0.0, str(exc))
            if isinstance(exc, WorkerError):
                raise ResourceError(exc.code, str(exc), traceback=exc.traceback) from exc
            raise

    def _build_spec(self, model: ModelRecord, variant: ModelVariant, plan: ResourcePlan) -> dict[str, Any]:
        source = dict(variant.source or {})
        model_path = variant.install_path or ""
        if source.get("type") in ("hf", "hf_files", "url_files") and model_path:
            model_path = variant.install_path
        from backend.services.settings_service import get_settings_values

        settings_payload = get_settings_values()
        settings_payload.update(self._profile_values(model.id))
        return {
            "model_id": model.id,
            "model_name": model.name,
            "variant_id": variant.id,
            "adapter": model.adapter,
            "device": plan.device,
            "precision": variant.precision,
            "model_path": model_path,
            "repo": source.get("repo") or "",
            "package_model": source.get("package_model") or "v2_rnnt",
            "package": source.get("package") or "",
            "settings": settings_payload,
            "capabilities": model.capabilities,
            "requires_exclusive": model.requires_exclusive,
        }

    def _profile_values(self, model_id: str) -> dict[str, Any]:
        with session_scope() as session:
            from backend.db.models import SettingsProfile

            profile = session.exec(
                select(SettingsProfile).where(SettingsProfile.model_id == model_id, SettingsProfile.is_default == True).limit(1)  # noqa: E712
            ).first()
            if profile:
                return dict(profile.values or {})
        return {}

    def _gpu_process_used(self, pid: int | None) -> float:
        if not pid:
            return 0.0
        try:
            import pynvml

            pynvml.nvmlInit()
            handle = pynvml.nvmlDeviceGetHandleByIndex(0)
            for proc in pynvml.nvmlDeviceGetComputeRunningProcesses(handle):
                if proc.pid == pid and getattr(proc, "usedGpuMemory", None):
                    return float(proc.usedGpuMemory) / 1024**3
        except Exception:
            pass
        return 0.0

    def _record_measurement(
        self,
        model: ModelRecord,
        variant: ModelVariant,
        plan: ResourcePlan,
        metrics: dict[str, Any],
        vram_gb: float,
    ) -> None:
        runtime_sig = f"{variant.precision}|{metrics.get('torch', '')}|{metrics.get('device', '')}"
        try:
            with session_scope() as session:
                row = ModelMeasurement(
                    model_id=model.id,
                    variant_id=variant.id,
                    device=plan.device,
                    precision=variant.precision,
                    context_vram_gb=0.0,
                    steady_vram_gb=round(vram_gb, 3),
                    peak_vram_gb=round(max(vram_gb, float(metrics.get("vram_allocated_mb", 0)) / 1024), 3),
                    ram_gb=round(float(metrics.get("ram_rss_mb", 0)) / 1024, 3),
                    load_ms=int(float(metrics.get("load_seconds", 0)) * 1000),
                    warmup_ms=0,
                    runtime_signature=runtime_sig,
                    sample_json=metrics,
                )
                session.add(row)
        except Exception:
            logger.exception("failed to store measurement")

    def _runtime_event(
        self,
        model_id: str,
        variant_id: str,
        action: str,
        device: str,
        started: float,
        ok: bool,
        vram_mb: float,
        error: str = "",
        pid: int | None = None,
    ) -> None:
        try:
            with session_scope() as session:
                session.add(
                    ModelRuntimeEvent(
                        model_id=model_id,
                        variant_id=variant_id,
                        action=action,
                        device=device,
                        started_at=datetime.fromtimestamp(time.time() - (time.monotonic() - started), tz=timezone.utc),
                        finished_at=_utcnow(),
                        ok=ok,
                        vram_after_mb=vram_mb,
                        pid=pid,
                        error=error,
                    )
                )
        except Exception:
            logger.exception("failed to store runtime event")

    # --------------------------------------------------------------- inference
    def infer(self, model_id: str, payload: dict[str, Any], on_progress: Callable[[dict[str, Any]], None] | None = None) -> dict[str, Any]:
        with self._lock:
            runtime = self._runtimes.get(model_id)
            if not runtime:
                raise ResourceError("MODEL_NOT_LOADED", "Модель не загружена.")
        with runtime.inference_lock:
            if runtime.state == "unloading":
                raise ResourceError("MODEL_UNLOADING", "Модель уже выгружается.")
            runtime.busy = True
            runtime.last_used = time.monotonic()
            try:
                result = runtime.worker.infer(payload, on_progress=on_progress)
                runtime.last_used = time.monotonic()
                return result
            except WorkerError as exc:
                if exc.code == "OOM":
                    self._handle_oom(model_id, exc)
                    raise ResourceError(
                        "OOM",
                        "Модель не поместилась в VRAM. Память освобождена, сервер работает.",
                        retryable=True,
                        actions=["economy", "cpu", "retry"],
                    ) from exc
                if exc.code in ("WORKER_TIMEOUT", "WORKER_DIED", "WORKER_DEAD", "WORKER_SEND_FAILED", "WORKER_STOP_TIMEOUT"):
                    try:
                        runtime.worker.kill()
                    except Exception:
                        logger.exception("failed to terminate broken worker: %s", model_id)
                    with self._lock:
                        if self._runtimes.get(model_id) is runtime:
                            self._runtimes.pop(model_id, None)
                    self._runtime_event(
                        model_id, runtime.variant_id, "worker-failure", runtime.device,
                        time.monotonic(), False, runtime.vram_mb, str(exc), pid=runtime.worker.pid,
                    )
                raise ResourceError(exc.code, str(exc), traceback=exc.traceback) from exc
            finally:
                runtime.busy = False
                runtime.active_task_id = ""

    def _handle_oom(self, model_id: str, exc: WorkerError) -> None:
        logger.error("OOM in %s: %s", model_id, exc)
        self.unload(model_id, reason="OOM", force=True)

    # ---------------------------------------------------------------- unloading
    def unload(self, model_id: str, *, reason: str = "manual", force: bool = False) -> dict[str, Any]:
        with self._lifecycle_lock:
            return self._unload_locked(model_id, reason=reason, force=force)

    def _unload_locked(self, model_id: str, *, reason: str = "manual", force: bool = False) -> dict[str, Any]:
        acquired_inference_lock = False
        with self._lock:
            runtime = self._runtimes.get(model_id)
            if not runtime:
                return {"unloaded": False}
            if runtime.state == "loading" and not force:
                raise ResourceError("MODEL_LOADING", "Модель ещё загружается; дождитесь готовности.")
            if runtime.state == "unloading":
                raise ResourceError("MODEL_UNLOADING", "Модель уже выгружается.")
            if not force:
                acquired_inference_lock = runtime.inference_lock.acquire(blocking=False)
                if not acquired_inference_lock or runtime.busy:
                    if acquired_inference_lock:
                        runtime.inference_lock.release()
                    raise ResourceError("MODEL_BUSY", "Модель занята задачей; дождитесь завершения.")
            runtime.state = "unloading"
        started = time.monotonic()
        before = self._mem()["gpu_used_gb"]
        worker = runtime.worker
        try:
            if worker is not None:
                try:
                    worker.unload()
                except Exception:
                    logger.warning("graceful worker unload failed; forcing process termination", exc_info=True)
                    worker.kill()
                if worker.alive:
                    raise ResourceError("WORKER_UNLOAD_FAILED", "Воркер остался запущенным после команды выгрузки.")
        except Exception as exc:
            with self._lock:
                if self._runtimes.get(model_id) is runtime:
                    runtime.state = "loaded"
            if isinstance(exc, ResourceError):
                raise
            raise ResourceError("WORKER_UNLOAD_FAILED", f"Не удалось завершить процесс модели: {exc}") from exc
        finally:
            if acquired_inference_lock:
                runtime.inference_lock.release()
        with self._lock:
            if self._runtimes.get(model_id) is runtime:
                self._runtimes.pop(model_id, None)
        time.sleep(0.5)
        after = self._mem()["gpu_used_gb"]
        released = max(0.0, before - after)
        self._runtime_event(model_id, runtime.variant_id, "unload", runtime.device, started, True, round(released * 1024, 1), pid=runtime.worker.pid if runtime.worker else None)
        logger.info("unloaded %s (%s), released %.2f GB", model_id, reason, released)
        return {"unloaded": True, "released_gb": round(released, 3), "reason": reason}

    def is_loaded(self, model_id: str) -> bool:
        return model_id in self._runtimes

    def evict_lru(self, *, required_gb: float = 0.0, exclude: str = "") -> list[dict[str, Any]]:
        evicted: list[dict[str, Any]] = []
        for runtime in sorted([r for r in self._runtimes.values() if r.model_id != exclude and not r.busy], key=lambda item: item.last_used):
            if runtime.device == "cpu":
                continue
            evicted.append(self.unload(runtime.model_id, reason="lru"))
            if self._mem()["free_vram_gb"] >= required_gb:
                break
        return evicted

    def unload_all(self, *, force: bool = True, reason: str = "manual-all") -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        for model_id in list(self._runtimes):
            try:
                results.append(self.unload(model_id, reason=reason, force=force))
            except ResourceError as exc:
                results.append({"model_id": model_id, "unloaded": False, "error": str(exc)})
        return results

    def unload_idle(self, force: bool = False) -> list[dict[str, Any]]:
        now = time.monotonic()
        if self._idle_seconds <= 0 and not force:
            return []
        targets = [
            runtime
            for runtime in self._runtimes.values()
            if not runtime.busy and (force or now - runtime.last_used >= self._idle_seconds)
        ]
        results: list[dict[str, Any]] = []
        for runtime in targets:
            # One model that cannot be unloaded (still loading, worker stuck) must not
            # prevent the remaining idle models from being released.
            try:
                results.append(self.unload(runtime.model_id, reason="idle"))
            except ResourceError as exc:
                logger.warning("idle unload of %s skipped: %s", runtime.model_id, exc)
        return results

    def restore_after_exclusive(self) -> list[str]:
        """Restore idle models that were evicted for an exclusive/exclusive-only task."""
        with self._lock:
            if self._restoring or (not self._exclusive_target and not self._exclusive_snapshot):
                return []
            target = self._exclusive_target
            target_runtime = self._runtimes.get(target) if target else None
            if target_runtime and target_runtime.busy:
                return []
            snapshot = list(self._exclusive_snapshot)
            self._exclusive_target = ""
            self._exclusive_snapshot = []
            self._restoring = True
        restored: list[str] = []
        try:
            from backend.services.settings_service import get_settings_values

            if not bool(get_settings_values().get("auto_restore_exclusive", True)):
                return []
            if target_runtime:
                self.unload(target, reason="exclusive-restore", force=True)
            for model_id, variant_id in snapshot:
                if model_id in self._runtimes:
                    restored.append(model_id)
                    continue
                try:
                    plan = self.plan(model_id, variant_id)
                    if plan.verdict == "no":
                        logger.info("not restoring %s: %s", model_id, plan.reason)
                        continue
                    self.ensure_loaded(model_id, variant_id, restoring=True, force=False)
                    restored.append(model_id)
                except Exception:
                    logger.warning("could not restore %s after exclusive task", model_id, exc_info=True)
            return restored
        finally:
            self._restoring = False

    def start_idle_watcher(self) -> None:
        if self._idle_thread and self._idle_thread.is_alive():
            return
        self._stop.clear()
        def loop() -> None:
            while not self._stop.wait(15):
                try:
                    self.refresh_settings()
                    self.unload_idle()
                except Exception:
                    logger.exception("idle watcher failed")
        self._idle_thread = threading.Thread(target=loop, name="myvs-idle-watcher", daemon=True)
        self._idle_thread.start()

    def stop(self) -> None:
        self._stop.set()
        for model_id in list(self._runtimes):
            try:
                self.unload(model_id, reason="shutdown", force=True)
            except Exception:
                pass

    # ------------------------------------------------------------------ status
    def loaded(self) -> list[dict[str, Any]]:
        return [runtime.public() for runtime in self._runtimes.values()]

    def status(self) -> dict[str, Any]:
        mem = self._mem()
        return {
            "mode": self._mode,
            "policy": self._policy,
            "reserve_vram_gb": self._reserve_vram_gb,
            "reserve_ram_gb": self._reserve_ram_gb,
            "idle_unload_seconds": self._idle_seconds,
            "memory": mem,
            "loaded": self.loaded(),
            "reserved_vram_gb": round(self._reserved_vram_gb, 3),
        }

    def presets(self) -> list[dict[str, Any]]:
        def find(model_id: str, device: str = "gpu") -> ModelVariant | None:
            for variant in registry.variants(model_id):
                if variant.device == device:
                    return variant
            return None
        pairs = [
            ("faster-whisper-small", "qwen3-tts-0.6b"),
            ("faster-whisper-small", "silero-v4"),
            ("faster-whisper-medium", "piper"),
            ("faster-whisper-large-v3-turbo", "kokoro-82m"),
        ]
        mem = self._mem()
        result = []
        for stt_id, tts_id in pairs:
            stt = find(stt_id, "gpu")
            tts = find(tts_id, "cpu" if tts_id in ("silero-v4", "piper") else "gpu")
            if not stt or not tts:
                continue
            stt_est = (self._measurement(stt_id, stt.id).peak_vram_gb if self._measurement(stt_id, stt.id) else stt.vram_estimate_gb + 0.35)
            tts_est = (self._measurement(tts_id, tts.id).peak_vram_gb if self._measurement(tts_id, tts.id) else tts.vram_estimate_gb + 0.35) if tts.device == "gpu" else 0
            need = stt_est + tts_est
            margin = mem["free_vram_gb"] - need
            result.append(
                {
                    "stt": stt_id,
                    "tts": tts_id,
                    "tts_device": tts.device,
                    "need_vram_gb": round(need, 2),
                    "free_vram_gb": mem["free_vram_gb"],
                    "verdict": "fits" if margin >= 0.25 else "tight" if margin >= 0 else "no",
                    "margin_gb": round(margin, 2),
                }
            )
        return result


resources = ResourceManager()
