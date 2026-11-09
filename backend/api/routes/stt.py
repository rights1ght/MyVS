from __future__ import annotations

import shutil
import uuid
from pathlib import Path
from typing import Any

from fastapi import APIRouter, File, Form, UploadFile

from backend.api.errors import AppError
from backend.config import settings
from backend.services.model_registry import registry
from backend.services.tasks import tasks
from backend.services.voices import save_upload

router = APIRouter(prefix="/api/stt", tags=["stt"])


def pick_stt_model(requested: str | None) -> str:
    if requested:
        model = registry.get(requested)
        if not model:
            raise AppError("MODEL_NOT_FOUND", "Модель STT не найдена.", 404)
        if not any(v.install_state == "installed" for v in registry.variants(requested)):
            raise AppError("MODEL_NOT_INSTALLED", f"Модель «{model.name}» не скачана.", 409)
        return requested
    preferred = ["faster-whisper-small", "faster-whisper-base", "faster-whisper-tiny", "faster-whisper-medium", "faster-whisper-large-v3-turbo", "gigaam-v2"]
    for model_id in preferred:
        if any(v.install_state == "installed" for v in registry.variants(model_id)):
            return model_id
    raise AppError("MODEL_NOT_INSTALLED", "Нет установленной STT-модели. Скачайте Faster-Whisper в менеджере моделей.", 409)


@router.post("/transcribe", status_code=202)
async def transcribe(
    file: UploadFile = File(...),
    model_id: str = Form(""),
    language: str = Form("auto"),
    beam_size: int = Form(5),
    temperature: float = Form(0.0),
    vad: bool = Form(True),
    word_timestamps: bool = Form(True),
    project_id: str = Form(""),
    priority: int = Form(10),
) -> dict[str, Any]:
    model = pick_stt_model(model_id or None)
    upload_id = uuid.uuid4().hex
    suffix = Path(file.filename or "audio.wav").suffix or ".wav"
    target = settings.data_dir / "uploads" / f"{upload_id}{suffix}"
    try:
        save_upload(file, target, max_mb=2048)
    except ValueError as exc:
        raise AppError("UPLOAD_TOO_LARGE", str(exc), 413) from exc
    if target.stat().st_size < 256:
        target.unlink(missing_ok=True)
        raise AppError("EMPTY_AUDIO", "Аудиофайл пуст.", 400)
    task = tasks.enqueue(
        "stt",
        model_id=model,
        language=language,
        input_path=str(target),
        params={
            "beam_size": max(1, min(int(beam_size), 10)),
            "temperature": max(0.0, min(float(temperature), 1.0)),
            "vad": bool(vad),
            "word_timestamps": bool(word_timestamps),
            "original_name": file.filename,
        },
        project_id=project_id or None,
        priority=max(0, min(int(priority), 100)),
        device="gpu",
    )
    return {"task_id": task.id, "task": tasks.task_public(task)}


@router.get("/languages")
def languages(model_id: str | None = None) -> list[dict[str, str]]:
    names = {
        "ru": "Русский",
        "en": "English",
        "de": "Deutsch",
        "fr": "Français",
        "es": "Español",
        "it": "Italiano",
        "pt": "Português",
        "pl": "Polski",
        "uk": "Українська",
        "tr": "Türkçe",
        "zh": "中文",
        "ja": "日本語",
        "ko": "한국어",
        "ar": "العربية",
        "hi": "हिन्दी",
    }
    if model_id:
        model = registry.get(model_id)
        if not model:
            raise AppError("MODEL_NOT_FOUND", "Модель не найдена.", 404)
        codes = model.languages
    else:
        codes = ["ru", "en", "de", "fr", "es", "it", "pt", "pl", "uk", "tr", "zh", "ja", "ko", "ar", "hi"]
    return [{"code": "auto", "name": "Авто"}] + [{"code": code, "name": names.get(code, code)} for code in codes]
