from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi import APIRouter
from fastapi.responses import FileResponse, PlainTextResponse
from pydantic import BaseModel
from sqlmodel import desc, select

from backend.api.errors import AppError
from backend.config import settings
from backend.db.models import TaskEvent, TaskRecord
from backend.db.session import session_scope
from backend.services import audio as audio_service
from backend.services import transcript as transcript_service
from backend.services.resource_manager import ResourceError
from backend.services.tasks import progress_store, tasks

router = APIRouter(prefix="/api", tags=["tasks"])


@router.get("/tasks")
def list_tasks(
    type: str | None = None,
    model_id: str | None = None,
    status: str | None = None,
    project_id: str | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    with session_scope() as session:
        statement = select(TaskRecord).order_by(desc(TaskRecord.created_at)).limit(max(1, min(limit, 500)))
        if type:
            statement = statement.where(TaskRecord.type == type)
        if model_id:
            statement = statement.where(TaskRecord.model_id == model_id)
        if status:
            statement = statement.where(TaskRecord.status == status)
        if project_id:
            statement = statement.where(TaskRecord.project_id == project_id)
        rows = session.exec(statement).all()
    return [tasks.task_public(row) for row in rows]


@router.get("/tasks/{task_id}")
def get_task(task_id: str) -> dict[str, Any]:
    task = tasks.get(task_id)
    if not task:
        raise AppError("TASK_NOT_FOUND", "Задача не найдена.", 404)
    return tasks.task_public(task)


@router.get("/tasks/{task_id}/events")
def task_events(task_id: str) -> list[dict[str, Any]]:
    with session_scope() as session:
        rows = session.exec(select(TaskEvent).where(TaskEvent.task_id == task_id).order_by(TaskEvent.at)).all()
    return [
        {
            "id": row.id,
            "at": row.at.isoformat(),
            "phase": row.phase,
            "message": row.message,
            "data": row.data,
        }
        for row in rows
    ]


class ResolvePayload(BaseModel):
    choice: str
    model_id: str = ""
    variant_id: str = ""


@router.post("/tasks/{task_id}/resolve")
def resolve_task(task_id: str, payload: ResolvePayload) -> dict[str, Any]:
    try:
        task = tasks.resolve(task_id, payload.choice, model_id=payload.model_id, variant_id=payload.variant_id)
    except ResourceError as exc:
        raise AppError(exc.code, str(exc), 409) from exc
    if not task:
        raise AppError("TASK_NOT_FOUND", "Задача не найдена.", 404)
    return tasks.task_public(task)


@router.post("/tasks/{task_id}/cancel")
def cancel_task(task_id: str) -> dict[str, Any]:
    try:
        task = tasks.cancel(task_id)
    except ResourceError as exc:
        raise AppError(exc.code, str(exc), 409) from exc
    if not task:
        raise AppError("TASK_NOT_FOUND", "Задача не найдена.", 404)
    return tasks.task_public(task)


@router.post("/tasks/{task_id}/retry")
def retry_task(task_id: str) -> dict[str, Any]:
    original = tasks.get(task_id)
    if not original:
        raise AppError("TASK_NOT_FOUND", "Задача не найдена.", 404)
    new = tasks.enqueue(
        original.type,
        model_id=original.model_id,
        voice_id=original.voice_id,
        text=original.text,
        language=original.language,
        input_path=original.input_path,
        params={k: v for k, v in (original.params or {}).items() if k not in ("result", "resource_plan")},
        project_id=original.project_id,
        priority=original.priority,
        device=original.device,
        precision=original.precision,
    )
    with session_scope() as session:
        row = session.get(TaskRecord, new.id)
        if row:
            row.retry_of = task_id
            session.add(row)
    return tasks.task_public(tasks.get(new.id) or new)


@router.get("/tasks/{task_id}/export")
def export_task(task_id: str, format: str = "json", with_timestamps: bool = False):
    task = tasks.get(task_id)
    if not task:
        raise AppError("TASK_NOT_FOUND", "Задача не найдена.", 404)
    if task.type != "stt":
        raise AppError("EXPORT_NOT_SUPPORTED", "Экспорт доступен для STT-задач.", 400)
    transcript_path = next((path for path in task.output_paths if path.endswith("transcript.json")), "")
    if not transcript_path or not Path(transcript_path).exists():
        raise AppError("RESULT_NOT_READY", "Результат ещё не готов.", 409)
    data = transcript_service.load_transcript(transcript_path)
    segments = data.get("segments") or []
    fmt = format.lower()
    if fmt == "json":
        return PlainTextResponse(
            json.dumps(data, ensure_ascii=False, indent=2),
            media_type="application/json",
            headers={"Content-Disposition": f'attachment; filename="{task_id}.json"'},
        )
    if fmt == "srt":
        content = transcript_service.transcript_to_srt(segments)
        media_type = "application/x-subrip"
    elif fmt == "vtt":
        content = transcript_service.transcript_to_vtt(segments)
        media_type = "text/vtt"
    elif fmt == "txt":
        content = transcript_service.transcript_to_txt(segments, with_timestamps=with_timestamps)
        media_type = "text/plain"
    else:
        raise AppError("UNSUPPORTED_FORMAT", "Форматы: txt, srt, vtt, json.", 400)
    return PlainTextResponse(
        content,
        media_type=f"{media_type}; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{task_id}.{fmt}"'},
    )


@router.get("/tasks/{task_id}/audio")
def task_audio(task_id: str, format: str = "wav"):
    task = tasks.get(task_id)
    if not task:
        raise AppError("TASK_NOT_FOUND", "Задача не найдена.", 404)
    source = next((path for path in task.output_paths if path.endswith((".wav", ".mp3", ".ogg"))), "")
    if not source or not Path(source).exists():
        raise AppError("RESULT_NOT_READY", "Аудио ещё не готово.", 409)
    fmt = format.lower()
    if fmt == "wav":
        return FileResponse(source, media_type="audio/wav", filename=f"{task_id}.wav")
    target = settings.data_dir / "outputs" / task_id / f"audio.{fmt}"
    try:
        audio_service.export_audio(source, target, fmt)
    except Exception as exc:
        raise AppError("EXPORT_FAILED", f"Не удалось конвертировать аудио: {exc}", 400) from exc
    media = {"mp3": "audio/mpeg", "ogg": "audio/ogg"}.get(fmt, "application/octet-stream")
    return FileResponse(target, media_type=media, filename=f"{task_id}.{fmt}")


@router.get("/queue")
def queue() -> dict[str, Any]:
    with session_scope() as session:
        rows = session.exec(
            select(TaskRecord)
            .where(TaskRecord.status.in_(["queued", "running", "loading_model", "awaiting_decision"]))
            .order_by(TaskRecord.priority, TaskRecord.created_at)
        ).all()
    return {
        "tasks": [tasks.task_public(row) for row in rows],
        "counts": {
            "queued": sum(1 for row in rows if row.status == "queued"),
            "running": sum(1 for row in rows if row.status in ("running", "loading_model")),
            "awaiting": sum(1 for row in rows if row.status == "awaiting_decision"),
        },
    }
