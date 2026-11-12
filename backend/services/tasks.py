from __future__ import annotations

import logging
import queue
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

import numpy as np
from sqlmodel import select

from backend.config import settings
from backend.db.models import ModelRecord, TaskEvent, TaskRecord, Voice
from backend.db.session import session_scope
from backend.services import audio as audio_service
from backend.services.model_registry import registry
from backend.services.monitor import monitor
from backend.services.resource_manager import ResourceError, resources

logger = logging.getLogger(__name__)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _now() -> float:
    return time.monotonic()


# Keys of a task result that are large and already stored in the transcript file / output folder.
_BULKY_RESULT_KEYS = ("segments",)


def slim_result(result: dict[str, Any] | None) -> dict[str, Any] | None:
    """Result without the bulky parts (STT segments with word timestamps can be megabytes).

    The full transcript lives in ``transcript.json``. Keeping a second and third copy in the task row,
    the progress store and the event log made every task list request load/serialize hundreds of MB.
    """
    if not isinstance(result, dict):
        return result
    slim = {key: value for key, value in result.items() if key not in _BULKY_RESULT_KEYS}
    if "segments" in result:
        slim["segments_count"] = len(result["segments"] or [])
    return slim


_SUMMARY_COLUMNS = [column for column in TaskRecord.__table__.columns if column.name != "params"]
_DATETIME_FIELDS = ("queued_at", "started_at", "finished_at", "created_at", "updated_at")


def _param_float(params: dict[str, Any], key: str, default: float) -> float:
    """Numeric task parameter where 0 is a legitimate value (e.g. volume=0)."""
    value = params.get(key)
    return default if value is None else float(value)


def _task_public(task: TaskRecord) -> dict[str, Any]:
    return {
        **task.model_dump(),
        "queued_at": task.queued_at.isoformat() if task.queued_at else None,
        "started_at": task.started_at.isoformat() if task.started_at else None,
        "finished_at": task.finished_at.isoformat() if task.finished_at else None,
        "created_at": task.created_at.isoformat() if task.created_at else None,
        "updated_at": task.updated_at.isoformat() if task.updated_at else None,
    }


class TaskProgressStore:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._values: dict[str, dict[str, Any]] = {}

    def set(self, task_id: str, **payload: Any) -> None:
        with self._lock:
            current = self._values.setdefault(task_id, {})
            current.update(payload)
            current["updated_at"] = time.time()

    def get(self, task_id: str) -> dict[str, Any]:
        with self._lock:
            return dict(self._values.get(task_id, {}))

    def clear(self, task_id: str) -> None:
        with self._lock:
            self._values.pop(task_id, None)


progress_store = TaskProgressStore()


class TaskCancelled(Exception):
    pass


class TaskService:
    def __init__(self) -> None:
        self._queue: queue.PriorityQueue[tuple[int, int, str]] = queue.PriorityQueue()
        self._counter = 0
        self._counter_lock = threading.Lock()
        self._executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="myvs-task")
        self._dispatcher: threading.Thread | None = None
        self._stop = threading.Event()
        self._cancelling: set[str] = set()
        self._cancelling_lock = threading.Lock()

    def is_cancel_requested(self, task_id: str) -> bool:
        with self._cancelling_lock:
            return task_id in self._cancelling

    def _clear_cancel(self, task_id: str) -> None:
        with self._cancelling_lock:
            self._cancelling.discard(task_id)

    def start(self) -> None:
        if self._dispatcher and self._dispatcher.is_alive():
            if not self._stop.is_set():
                return
            # stop() was called but the old dispatcher has not noticed yet (it polls every 0.5 s);
            # wait for it, otherwise it would exit right after we clear the flag and nothing would dispatch.
            self._dispatcher.join(timeout=3)
        self._stop.clear()  # allow start() after stop() (lifespan restart, tests)
        self.recover()
        self._dispatcher = threading.Thread(target=self._dispatch, name="myvs-dispatcher", daemon=True)
        self._dispatcher.start()

    def recover(self) -> None:
        """Repair task state left by an unclean process/server restart."""
        with session_scope() as session:
            rows = session.exec(select(TaskRecord).where(TaskRecord.status.in_(["running", "loading_model"]))).all()
            for row in rows:
                row.status = "failed"
                row.finished_at = _utcnow()
                row.total_ms = int((row.finished_at - row.queued_at).total_seconds() * 1000)
                row.error_code = "SERVER_RESTARTED"
                row.error_message = "Сервер был перезапущен во время выполнения задачи."
                row.updated_at = _utcnow()
                session.add(row)
                progress_store.set(row.id, status="failed", error_code="SERVER_RESTARTED", message=row.error_message)
            queued = session.exec(select(TaskRecord).where(TaskRecord.status == "queued").order_by(TaskRecord.priority, TaskRecord.created_at)).all()
            queue_rows = [(row.priority, row.id) for row in queued]
        for priority, task_id in queue_rows:
            self._queue.put((priority, self._next(), task_id))
            progress_store.set(task_id, status="queued", message="Восстановлено после перезапуска")

    def stop(self) -> None:
        self._stop.set()

    def _next(self) -> int:
        with self._counter_lock:
            self._counter += 1
            return self._counter

    def enqueue(
        self,
        task_type: str,
        *,
        model_id: str = "",
        voice_id: str | None = None,
        text: str = "",
        language: str = "",
        input_path: str = "",
        params: dict[str, Any] | None = None,
        project_id: str | None = None,
        priority: int = 10,
        device: str = "gpu",
        precision: str = "fp16",
        task_id: str | None = None,
    ) -> TaskRecord:
        with session_scope() as session:
            task = TaskRecord(
                id=task_id or uuid4().hex,
                type=task_type,
                status="queued",
                priority=priority,
                model_id=model_id,
                voice_id=voice_id,
                text=text,
                language=language,
                input_path=input_path,
                params=dict(params or {}),
                project_id=project_id,
                device=device,
                precision=precision,
                queued_at=_utcnow(),
            )
            session.add(task)
            session.flush()
            session.refresh(task)
            session.commit()
            task_id = task.id
        self._queue.put((priority, self._next(), task_id))
        progress_store.set(task_id, status="queued", queue_started=time.time())
        logger.info("task queued %s type=%s model=%s", task_id, task_type, model_id)
        return self.get(task_id)  # type: ignore[return-value]

    def requeue(self, task_id: str, *, priority: int | None = None) -> None:
        self._clear_cancel(task_id)
        with session_scope() as session:
            task = session.get(TaskRecord, task_id)
            if not task or task.status in ("completed", "failed", "cancelled"):
                return
            task.status = "queued"
            task.error_code = ""
            task.error_message = ""
            if priority is not None:
                task.priority = priority
            task.updated_at = _utcnow()
            session.add(task)
            session.commit()
            priority = task.priority
        self._queue.put((priority or 10, self._next(), task_id))
        progress_store.set(task_id, status="queued")

    def _dispatch(self) -> None:
        while not self._stop.is_set():
            try:
                _priority, _seq, task_id = self._queue.get(timeout=0.5)
            except queue.Empty:
                continue
            try:
                self._executor.submit(self._execute, task_id)
            except Exception:
                logger.exception("could not submit task %s", task_id)

    def get(self, task_id: str) -> TaskRecord | None:
        with session_scope() as session:
            return session.get(TaskRecord, task_id)

    def _event(self, task_id: str, phase: str, message: str = "", data: dict[str, Any] | None = None) -> None:
        try:
            with session_scope() as session:
                session.add(TaskEvent(task_id=task_id, phase=phase, message=message, data=data or {}))
        except Exception:
            logger.exception("task event failed")
        progress_store.set(task_id, last_event=phase, last_message=message)

    def _allocate_model(self, task: TaskRecord) -> tuple[ModelRecord, str, str]:
        voice = None
        if task.voice_id:
            with session_scope() as session:
                voice = session.get(Voice, task.voice_id)
        model_id = task.model_id or (voice.model_id if voice else "")
        if not model_id:
            candidates = [model for model in registry.all() if model.category in ("tts", "clone") and model.enabled]
            for model in candidates:
                variants = [v for v in registry.variants(model.id) if v.install_state == "installed"]
                if variants:
                    model_id = model.id
                    break
        if not model_id:
            raise ResourceError("MODEL_NOT_SELECTED", "Не выбрана модель или нет установленных моделей. Откройте менеджер моделей.")
        model = registry.get(model_id)
        if not model:
            raise ResourceError("MODEL_NOT_FOUND", "Модель не найдена.")
        variant = registry.resolve_variant(model_id, task.params.get("variant_id") if task.params else None)
        if not variant or variant.install_state != "installed":
            raise ResourceError(
                "MODEL_NOT_INSTALLED",
                f"Модель «{model.name}» не скачана.",
                actions=[{"id": "open_models", "label": "Открыть модели"}],
            )
        device = task.device or variant.device
        if device != variant.device:
            alt = [v for v in registry.variants(model_id) if v.device == device and v.install_state == "installed"]
            if alt:
                variant = alt[0]
            else:
                device = variant.device
        return model, variant.id, device

    def _set_awaiting(self, task_id: str, error: ResourceError) -> None:
        plan = (error.details.get("plan") if error.details else None) or {}
        with session_scope() as session:
            task = session.get(TaskRecord, task_id)
            if not task:
                return
            task.status = "awaiting_decision"
            task.error_code = error.code
            task.error_message = str(error)
            params = dict(task.params or {})
            params["resource_plan"] = plan
            task.params = params
            task.updated_at = _utcnow()
            session.add(task)
        progress_store.set(task_id, status="awaiting_decision", plan=plan, message=str(error))
        self._event(task_id, "awaiting_decision", str(error), {"plan": plan})

    def resolve(self, task_id: str, choice: str, *, model_id: str = "", variant_id: str = "") -> TaskRecord | None:
        task = self.get(task_id)
        if not task:
            return None
        if task.status != "awaiting_decision":
            return task
        params = dict(task.params or {})
        plan = params.get("resource_plan") or {}
        if choice == "cancel":
            self.cancel(task_id)
            return self.get(task_id)
        if choice == "evict":
            target = model_id or next((opt.get("model_id") for opt in plan.get("options", []) if opt.get("action") == "evict"), "")
            if target:
                resources.unload(target, reason="task-decision")
        elif choice == "cpu":
            cpu_variants = [v for v in registry.variants(task.model_id) if v.device == "cpu" and v.install_state == "installed"]
            if not cpu_variants:
                raise ResourceError("CPU_VARIANT_MISSING", "Для этой модели нет установленного CPU-варианта.")
            params["variant_id"] = cpu_variants[0].id
            with session_scope() as session:
                row = session.get(TaskRecord, task_id)
                if row:
                    row.device = "cpu"
                    row.precision = cpu_variants[0].precision
                    row.params = params
        elif choice == "quant":
            if variant_id:
                variant = registry.get_variant(task.model_id, variant_id)
                if variant:
                    params["variant_id"] = variant.id
                    with session_scope() as session:
                        row = session.get(TaskRecord, task_id)
                        if row:
                            row.precision = variant.precision
                            row.params = params
        elif choice == "confirm":
            params["confirmed"] = True
        params.pop("resource_plan", None)
        with session_scope() as session:
            row = session.get(TaskRecord, task_id)
            if not row:
                return None
            row.status = "queued"
            row.error_code = ""
            row.error_message = ""
            row.params = params
            row.updated_at = _utcnow()
            session.add(row)
            session.commit()
        self._queue.put((task.priority, self._next(), task_id))
        progress_store.set(task_id, status="queued")
        return self.get(task_id)

    def cancel(self, task_id: str) -> TaskRecord | None:
        with session_scope() as session:
            task = session.get(TaskRecord, task_id)
            if not task:
                return None
            if task.status in ("completed", "failed", "cancelled"):
                return task
            if task.status in ("running", "loading_model"):
                with self._cancelling_lock:
                    self._cancelling.add(task_id)
                progress_store.set(task_id, cancel_requested=True, message="Отмена после текущего шага")
                task.error_message = "Запрошена отмена; задача остановится после текущего шага."
                task.updated_at = _utcnow()
                session.add(task)
                return task
            task.status = "cancelled"
            task.finished_at = _utcnow()
            task.error_code = "CANCELLED"
            task.error_message = "Отменено пользователем."
            task.updated_at = _utcnow()
            session.add(task)
        progress_store.set(task_id, status="cancelled")
        self._clear_cancel(task_id)
        return self.get(task_id)

    def _mark_cancelled(self, task_id: str) -> None:
        with session_scope() as session:
            row = session.get(TaskRecord, task_id)
            if not row:
                return
            row.status = "cancelled"
            row.finished_at = _utcnow()
            row.total_ms = int((row.finished_at - row.queued_at).total_seconds() * 1000)
            row.error_code = "CANCELLED"
            row.error_message = "Отменено пользователем."
            row.updated_at = _utcnow()
            session.add(row)
        progress_store.set(task_id, status="cancelled", phase="cancelled")
        self._clear_cancel(task_id)
        self._event(task_id, "cancelled", "Отменено пользователем")

    def _execute(self, task_id: str) -> None:
        task = self.get(task_id)
        if not task or task.status != "queued":
            return
        if self.is_cancel_requested(task_id):
            self._mark_cancelled(task_id)
            return
        started_mono = _now()
        started_utc = _utcnow()
        with session_scope() as session:
            row = session.get(TaskRecord, task_id)
            if not row:
                return
            row.status = "running"
            row.started_at = started_utc
            row.queue_ms = int((started_utc - row.queued_at).total_seconds() * 1000)
            row.updated_at = started_utc
            session.add(row)
        progress_store.set(task_id, status="running", phase="admission", started_at=started_utc.isoformat())
        stop_metrics = threading.Event()
        peaks = {"cpu": 0.0, "gpu": 0.0, "vram": 0.0, "ram": 0.0, "temp": 0.0, "model_vram": 0.0}

        def watch_metrics() -> None:
            while not stop_metrics.wait(0.5):
                snapshot = monitor.snapshot()
                peaks["cpu"] = max(peaks["cpu"], snapshot.get("cpu", {}).get("percent", 0) or 0)
                gpu = snapshot.get("gpu", {})
                peaks["gpu"] = max(peaks["gpu"], gpu.get("util") or 0)
                peaks["vram"] = max(peaks["vram"], gpu.get("vram_used_mb") or 0)
                peaks["ram"] = max(peaks["ram"], snapshot.get("ram", {}).get("used_mb", 0) or 0)
                peaks["temp"] = max(peaks["temp"], gpu.get("temp_c") or 0)

        watcher = threading.Thread(target=watch_metrics, name=f"myvs-peaks-{task_id}", daemon=True)
        watcher.start()
        infer_seconds = 0.0
        post_started = 0.0
        load_ms = 0
        warnings: list[str] = []
        result: dict[str, Any] = {}
        try:
            model, variant_id, device = self._allocate_model(task)
            variant = registry.get_variant(model.id, variant_id)
            if model.watermark:
                warnings.append("Chatterbox: все выходные файлы содержат PerTh watermark.")
            if not model.commercial:
                warnings.append("Лицензия модели/весов ограничивает коммерческое использование.")
            plan = resources.plan(model.id, variant_id, device)
            if plan.verdict in ("no", "tight") and not (task.params or {}).get("confirmed"):
                if resources.policy == "auto" and plan.verdict == "no":
                    resources.evict_lru(required_gb=plan.need_vram_gb, exclude=model.id)
                    plan = resources.plan(model.id, variant_id, device)
                if plan.verdict in ("no", "tight"):
                    raise ResourceError(
                        "INSUFFICIENT_RESOURCES" if plan.verdict == "no" else "RESOURCE_CONFIRMATION",
                        plan.reason,
                        plan=plan.as_dict(),
                    )
            load_started = _now()
            runtime = resources.ensure_loaded(model.id, variant_id, device=device, task_id=task_id, force=bool((task.params or {}).get("confirmed")))
            if self.is_cancel_requested(task_id):
                self._mark_cancelled(task_id)
                return
            load_ms = int((_now() - load_started) * 1000)
            progress_store.set(task_id, phase="load", load_ms=load_ms, model_id=model.id)
            self._event(task_id, "model_loaded", f"{model.name} → {runtime.device}", {"load_ms": load_ms})
            if task.type == "stt":
                result = self._run_stt(task, runtime)
            elif task.type in ("tts", "preview"):
                result = self._run_tts(task, runtime, warnings)
            else:
                raise ResourceError("UNSUPPORTED_TASK", f"Неизвестный тип задачи: {task.type}")
            if self.is_cancel_requested(task_id):
                self._mark_cancelled(task_id)
                return
            infer_seconds = float(result.pop("infer_seconds", 0.0) or 0.0)
            post_started = _now()
            audio_path = str(result.get("output_path") or "")
            if audio_path and task.type in ("tts", "preview"):
                audio_path, post_info = self._postprocess_tts(task, audio_path, result)
                result.update(post_info)
            post_ms = int((_now() - post_started) * 1000)
            finished = _utcnow()
            duration = float(result.get("audio_duration_sec") or result.get("duration_sec") or 0.0)
            with session_scope() as session:
                row = session.get(TaskRecord, task_id)
                if not row:
                    return
                row.status = "completed"
                row.finished_at = finished
                row.load_ms = load_ms
                row.infer_ms = int(infer_seconds * 1000)
                row.post_ms = post_ms
                row.total_ms = int((finished - row.queued_at).total_seconds() * 1000)
                row.audio_duration_sec = duration
                row.rtf_infer = round(infer_seconds / max(duration, 0.01), 4) if duration else 0.0
                row.rtf_total = round((row.infer_ms + row.post_ms) / 1000 / max(duration, 0.01), 4) if duration else 0.0
                row.peak_cpu_pct = peaks["cpu"]
                row.peak_gpu_pct = peaks["gpu"]
                row.peak_vram_mb = peaks["vram"]
                row.peak_ram_mb = peaks["ram"]
                row.peak_gpu_temp_c = peaks["temp"]
                row.warnings = warnings
                row.output_paths = [p for p in [result.get("output_path"), result.get("transcript_path")] if p]
                row.params = {**(row.params or {}), "result": slim_result(result)}
                row.updated_at = finished
                session.add(row)
            progress_store.set(task_id, status="completed", phase="done", result=slim_result(result), timings={
                "queue_ms": task.queue_ms,
                "load_ms": load_ms,
                "infer_ms": int(infer_seconds * 1000),
                "post_ms": post_ms,
                "total_ms": int((finished - task.queued_at).total_seconds() * 1000),
            })
            self._event(task_id, "completed", "Готово", slim_result(result))
            logger.info("task completed %s in %.2fs", task_id, _now() - started_mono)
        except TaskCancelled:
            self._mark_cancelled(task_id)
        except ResourceError as exc:
            if exc.code in ("INSUFFICIENT_RESOURCES", "RESOURCE_CONFIRMATION"):
                self._set_awaiting(task_id, exc)
            else:
                self._fail(task_id, exc.code, str(exc), peaks)
        except Exception as exc:
            logger.exception("task failed %s", task_id)
            self._fail(task_id, "TASK_FAILED", str(exc), peaks)
        finally:
            stop_metrics.set()
            watcher.join(timeout=2)
            try:
                resources.restore_after_exclusive()
            except Exception:
                logger.warning("exclusive restore failed", exc_info=True)

    def _fail(self, task_id: str, code: str, message: str, peaks: dict[str, float]) -> None:
        with session_scope() as session:
            row = session.get(TaskRecord, task_id)
            if not row:
                return
            row.status = "failed"
            row.finished_at = _utcnow()
            row.total_ms = int((row.finished_at - row.queued_at).total_seconds() * 1000)
            row.error_code = code
            row.error_message = message
            row.peak_cpu_pct = peaks["cpu"]
            row.peak_gpu_pct = peaks["gpu"]
            row.peak_vram_mb = peaks["vram"]
            row.peak_ram_mb = peaks["ram"]
            row.peak_gpu_temp_c = peaks["temp"]
            row.updated_at = _utcnow()
            session.add(row)
        progress_store.set(task_id, status="failed", error_code=code, message=message)
        self._event(task_id, "failed", message, {"code": code})

    def _voice_payload(self, task: TaskRecord) -> dict[str, Any]:
        if not task.voice_id:
            return {}
        with session_scope() as session:
            voice = session.get(Voice, task.voice_id)
        if not voice:
            return {}
        return {
            "voice": voice.engine_voice_id,
            "engine_voice_id": voice.engine_voice_id,
            "reference_path": voice.reference_path,
            "reference_text": (voice.quality_json or {}).get("reference_text", ""),
            "instruct": voice.description if voice.kind == "designed" else "",
        }

    def _run_stt(self, task: TaskRecord, runtime: Any) -> dict[str, Any]:
        params = task.params or {}
        output_dir = settings.data_dir / "outputs" / task.id
        output_dir.mkdir(parents=True, exist_ok=True)
        payload = {
            "audio_path": task.input_path,
            "language": task.language or params.get("language") or "auto",
            "beam_size": int(params.get("beam_size") or 5),
            "temperature": float(params.get("temperature") or 0.0),
            "vad": bool(params.get("vad", True)),
            "word_timestamps": bool(params.get("word_timestamps", True)),
        }
        self._event(task.id, "inference", "Транскрипция", {"payload": payload})
        result = resources.infer(runtime.model_id, payload, on_progress=lambda p: progress_store.set(task.id, phase="inference", progress=p))
        transcript_path = output_dir / "transcript.json"
        transcript = {
            "task_id": task.id,
            "type": "stt",
            "model_id": task.model_id,
            "language": result.get("language"),
            "language_probability": result.get("language_probability"),
            "audio_duration_sec": result.get("audio_duration_sec"),
            "text": result.get("text", ""),
            "segments": result.get("segments", []),
            "warnings": task.warnings,
        }
        transcript_path.write_text(__import__("json").dumps(transcript, ensure_ascii=False, indent=2), encoding="utf-8")
        return {
            "output_path": str(transcript_path),
            "transcript_path": str(transcript_path),
            "text": result.get("text", ""),
            "segments": result.get("segments", []),
            "language": result.get("language"),
            "language_probability": result.get("language_probability"),
            "audio_duration_sec": result.get("audio_duration_sec"),
            "infer_seconds": result.get("infer_seconds", 0.0),
            "worker_metrics": result.get("_worker_metrics", {}),
        }

    def _run_tts(self, task: TaskRecord, runtime: Any, warnings: list[str]) -> dict[str, Any]:
        from backend.engines.tts.common import split_text

        params = task.params or {}
        output_dir = settings.data_dir / "outputs" / task.id
        chunk_dir = output_dir / "chunks"
        chunk_dir.mkdir(parents=True, exist_ok=True)
        text = task.text or str(params.get("text") or "")
        chunks = split_text(text, max_chars=int(params.get("max_chars") or 280))
        if not chunks:
            raise ResourceError("EMPTY_TEXT", "Текст для синтеза пуст.")
        voice_payload = self._voice_payload(task)
        language = task.language or params.get("language") or "ru"
        speed = _param_float(params, "speed", 1.0)
        pitch = _param_float(params, "pitch", 0.0)
        volume = _param_float(params, "volume", 1.0)
        chunk_results: list[dict[str, Any]] = []
        infer_seconds = 0.0
        sample_rate = 24000
        for index, chunk in enumerate(chunks):
            if self.is_cancel_requested(task.id):
                raise TaskCancelled()
            chunk_path = chunk_dir / f"{index:03d}.wav"
            payload = {
                "text": chunk,
                "output_path": str(chunk_path),
                "language": language,
                "speed": speed,
                "pitch": pitch,
                "volume": volume,
                "cfg_value": params.get("cfg_value"),
                "exaggeration": params.get("exaggeration"),
                "cfg_weight": params.get("cfg_weight"),
                "inference_timesteps": params.get("inference_timesteps"),
                **voice_payload,
            }
            self._event(task.id, "inference", f"Чанк {index + 1}/{len(chunks)}")
            result = resources.infer(runtime.model_id, payload, on_progress=lambda p, idx=index: progress_store.set(task.id, phase="inference", chunk=idx, chunk_count=len(chunks), progress=p))

            infer_seconds += float(result.get("infer_seconds", 0.0) or 0.0)
            sample_rate = int(result.get("sample_rate") or sample_rate)
            if result.get("warning"):
                warnings.append(str(result["warning"]))
            chunk_results.append(result)
        parts: list[np.ndarray] = []
        for item in chunk_results:
            data, sr = audio_service.read_mono(item["output_path"])
            if sr != sample_rate:
                raise ResourceError("SAMPLE_RATE_MISMATCH", "Чанки TTS имеют разную частоту дискретизации.")
            parts.append(data)
        from backend.engines.tts.common import concat_audio

        combined = concat_audio(parts, pause_sec=float(params.get("pause_sec") or 0.12), sample_rate=sample_rate)
        output_path = output_dir / "audio.wav"
        audio_service.write_wav(output_path, combined, sample_rate)
        return {
            "output_path": str(output_path),
            "duration_sec": round(len(combined) / max(sample_rate, 1), 3),
            "sample_rate": sample_rate,
            "chunks": len(chunks),
            "chunk_results": chunk_results,
            "infer_seconds": infer_seconds,
            "worker_metrics": chunk_results[-1].get("_worker_metrics", {}) if chunk_results else {},
        }

    def _postprocess_tts(self, task: TaskRecord, audio_path: str, result: dict[str, Any]) -> tuple[str, dict[str, Any]]:
        params = task.params or {}
        output_path = Path(audio_path)
        processed = output_path.with_name("audio_final.wav")
        info = audio_service.postprocess_audio(
            output_path,
            processed,
            speed=_param_float(params, "speed", 1.0),
            pitch_semitones=_param_float(params, "pitch", 0.0),
            volume=_param_float(params, "volume", 1.0),
            speed_already_applied=result.get("chunk_results", [{}])[-1].get("speed_applied", False) if result.get("chunk_results") else False,
            copy_if_unchanged=False,
        )
        if processed.exists():
            output_path.unlink(missing_ok=True)
            processed.replace(output_path)
        if output_path.exists():
            result["audio_duration_sec"] = round(audio_service.probe(output_path)["duration_sec"], 3)
            result["postprocess"] = info
        return str(output_path), {"postprocess": info}

    def list_tasks(self, limit: int = 100, status: str | None = None) -> list[TaskRecord]:
        with session_scope() as session:
            statement = select(TaskRecord).order_by(TaskRecord.created_at.desc()).limit(max(1, min(limit, 500)))
            if status:
                statement = statement.where(TaskRecord.status == status)
            return list(session.exec(statement).all())

    def task_public(self, task: TaskRecord) -> dict[str, Any]:
        data = _task_public(task)
        params = dict(task.params or {})
        result = params.get("result")
        if task.type == "stt" and task.output_paths:
            transcript_path = next((p for p in task.output_paths if p.endswith("transcript.json")), "")
            if transcript_path and Path(transcript_path).exists():
                try:
                    result = __import__("json").loads(Path(transcript_path).read_text(encoding="utf-8"))
                except Exception:
                    pass
        data["result"] = result
        # ``progress.result`` duplicated ``result``; drop it to halve the payload of every poll.
        data["progress"] = {key: value for key, value in progress_store.get(task.id).items() if key != "result"}
        data.pop("params", None)
        data["params"] = params
        return data

    def task_summaries(
        self,
        *,
        limit: int = 100,
        type: str | None = None,
        model_id: str | None = None,
        status: str | None = None,
        project_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """Light task rows for list views: no ``params``/``result`` and no transcript file reads."""
        statement = select(*_SUMMARY_COLUMNS).order_by(TaskRecord.created_at.desc()).limit(max(1, min(limit, 500)))
        for column, value in ((TaskRecord.type, type), (TaskRecord.model_id, model_id), (TaskRecord.status, status), (TaskRecord.project_id, project_id)):
            if value:
                statement = statement.where(column == value)
        with session_scope() as session:
            rows = session.exec(statement).all()
        summaries: list[dict[str, Any]] = []
        for row in rows:
            data = dict(row._mapping)
            for field in _DATETIME_FIELDS:
                if data.get(field) is not None:
                    data[field] = data[field].isoformat()
            data["params"] = {}
            data["result"] = None
            data["progress"] = {key: value for key, value in progress_store.get(data["id"]).items() if key != "result"}
            summaries.append(data)
        return summaries


tasks = TaskService()
