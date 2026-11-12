from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any

from fastapi import APIRouter, File, Form, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, field_validator
from sqlmodel import select

from backend.api.errors import AppError
from backend.db.models import ModelRecord, ModelVariant, Voice
from backend.db.session import session_scope
from backend.services.model_registry import registry
from backend.services.tasks import tasks
from backend.services.voices import (
    analyze_file,
    create_cloned_voice,
    create_designed_voice,
    delete_voice,
    get_voice,
    list_voices,
    save_upload,
)

router = APIRouter(prefix="/api/voices", tags=["voices"])


def _model_info(model_ids: set[str]) -> tuple[dict[str, str], set[str]]:
    """model_id -> name and the set of model ids with an installed variant, in two queries."""
    ids = {model_id for model_id in model_ids if model_id}
    if not ids:
        return {}, set()
    with session_scope() as session:
        names = dict(session.exec(select(ModelRecord.id, ModelRecord.name).where(ModelRecord.id.in_(ids))).all())
        installed = set(
            session.exec(select(ModelVariant.model_id).where(ModelVariant.model_id.in_(ids), ModelVariant.install_state == "installed")).all()
        )
    return names, installed


def _public_many(voices: list[Voice]) -> list[dict[str, Any]]:
    names, installed = _model_info({voice.model_id for voice in voices if voice.model_id})
    return [
        {
            **voice.model_dump(),
            "model_name": names.get(voice.model_id or "", ""),
            "model_installed": bool(voice.model_id) and voice.model_id in installed,
            "has_reference": bool(voice.reference_path and Path(voice.reference_path).exists()),
        }
        for voice in voices
    ]


def _public(voice: Voice) -> dict[str, Any]:
    return _public_many([voice])[0]


@router.get("")
def list_all(
    kind: str | None = None,
    language: str | None = None,
    model_id: str | None = None,
) -> list[dict[str, Any]]:
    return _public_many(list_voices(kind, language, model_id))


@router.get("/{voice_id}")
def get_one(voice_id: str) -> dict[str, Any]:
    voice = get_voice(voice_id)
    if not voice:
        raise AppError("VOICE_NOT_FOUND", "Голос не найден.", 404)
    return _public(voice)


@router.post("/analyze")
def analyze(file: UploadFile = File(...)) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="myvs-ref-") as tmp:
        suffix = Path(file.filename or "reference.wav").suffix or ".wav"
        target = Path(tmp) / f"reference{suffix}"
        try:
            save_upload(file, target, max_mb=100)
        except ValueError as exc:
            raise AppError("UPLOAD_TOO_LARGE", str(exc), 413) from exc
        try:
            return analyze_file(target)
        except Exception as exc:
            raise AppError("AUDIO_DECODE_FAILED", f"Не удалось прочитать аудио: {exc}", 400) from exc


@router.post("/clone", status_code=201)
def clone(
    file: UploadFile = File(...),
    name: str = Form(...),
    language: str = Form("ru"),
    model_id: str = Form(...),
    consent: bool = Form(False),
    reference_text: str = Form(""),
    description: str = Form(""),
    test_text: str = Form(""),
) -> dict[str, Any]:
    model = registry.get(model_id)
    if not model or "clone" not in model.capabilities:
        raise AppError("VOICE_INCOMPATIBLE", "Выбранная модель не поддерживает клонирование.", 400)
    try:
        voice = create_cloned_voice(
            upload=file,
            name=name,
            language=language,
            model_id=model_id,
            consent=consent,
            reference_text=reference_text,
            description=description,
        )
    except ValueError as exc:
        raise AppError("VOICE_REJECTED", str(exc), 422) from exc
    result: dict[str, Any] = {"voice": _public(voice), "task_id": None}
    if test_text.strip():
        task = tasks.enqueue(
            "preview",
            model_id=model_id,
            voice_id=voice.id,
            text=test_text.strip(),
            language=language,
            params={"speed": 1.0, "pitch": 0.0, "volume": 1.0},
        )
        result["task_id"] = task.id
    return result


class DesignPayload(BaseModel):
    name: str
    description: str
    language: str = "ru"
    model_id: str
    test_text: str = ""


@router.post("/design", status_code=201)
def design(payload: DesignPayload) -> dict[str, Any]:
    model = registry.get(payload.model_id)
    if not model or "voice_design" not in model.capabilities:
        raise AppError("VOICE_INCOMPATIBLE", "Выбранная модель не поддерживает голос по описанию.", 400)
    try:
        voice = create_designed_voice(
            name=payload.name,
            description=payload.description,
            language=payload.language,
            model_id=payload.model_id,
        )
    except ValueError as exc:
        raise AppError("VOICE_REJECTED", str(exc), 422) from exc
    result: dict[str, Any] = {"voice": _public(voice), "task_id": None}
    if payload.test_text.strip():
        task = tasks.enqueue(
            "preview",
            model_id=payload.model_id,
            voice_id=voice.id,
            text=payload.test_text.strip(),
            language=payload.language,
            params={"speed": 1.0, "pitch": 0.0, "volume": 1.0},
        )
        result["task_id"] = task.id
    return result


class VoicePatch(BaseModel):
    name: str | None = None
    description: str | None = None
    language: str | None = None

    @field_validator("name")
    @classmethod
    def _name_not_blank(cls, value: str | None) -> str | None:
        if value is not None:
            value = value.strip()
            if not value:
                raise ValueError("name must not be blank")
        return value


@router.patch("/{voice_id}")
def patch(voice_id: str, payload: VoicePatch) -> dict[str, Any]:
    with session_scope() as session:
        voice = session.get(Voice, voice_id)
        if not voice:
            raise AppError("VOICE_NOT_FOUND", "Голос не найден.", 404)
        if voice.kind == "builtin":
            raise AppError("VOICE_PROTECTED", "Встроенные голоса нельзя изменять.", 400)
        if payload.name is not None:
            voice.name = payload.name
        if payload.description is not None:
            voice.description = payload.description
        if payload.language is not None:
            voice.language = payload.language
        session.add(voice)
        session.flush()
        session.refresh(voice)
        return _public(voice)


@router.delete("/{voice_id}")
def remove(voice_id: str) -> dict[str, bool]:
    try:
        ok = delete_voice(voice_id)
    except ValueError as exc:
        raise AppError("VOICE_PROTECTED", str(exc), 400) from exc
    if not ok:
        raise AppError("VOICE_NOT_FOUND", "Голос не найден.", 404)
    return {"deleted": True}


@router.get("/{voice_id}/reference")
def reference(voice_id: str) -> FileResponse:
    voice = get_voice(voice_id)
    if not voice or not voice.reference_path or not Path(voice.reference_path).exists():
        raise AppError("REFERENCE_NOT_FOUND", "Референс не найден.", 404)
    return FileResponse(voice.reference_path, media_type="audio/wav", filename=f"{voice_id}-reference.wav")
