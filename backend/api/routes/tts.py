from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, Field, field_validator

from backend.api.errors import AppError
from backend.services.model_registry import registry
from backend.services.tasks import tasks
from backend.services.voices import get_voice

router = APIRouter(prefix="/api/tts", tags=["tts"])


class SynthesizePayload(BaseModel):
    text: str = Field(min_length=1, max_length=10000)
    voice_id: str
    model_id: str = ""
    language: str = "ru"
    speed: float = 1.0
    pitch: float = 0.0
    volume: float = 1.0
    project_id: str | None = None
    priority: int = 10
    device: str = "gpu"
    variant_id: str | None = None
    params: dict[str, Any] = Field(default_factory=dict)
    task_type: str = "tts"

    @field_validator("text")
    @classmethod
    def _text_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("text must not be blank")
        return value


# Engine-specific knobs a client may pass through ``params`` (name -> (type, min, max)).
# Everything else is dropped: ``params`` used to be merged *after* the clamped
# speed/pitch/volume, so it could override them, and it could also inject
# internal keys such as ``confirmed`` (skips the resource check) or ``max_chars=1``.
_EXTRA_PARAMS: dict[str, tuple[type, float, float]] = {
    "cfg_value": (float, 0.0, 20.0),
    "cfg_weight": (float, 0.0, 2.0),
    "exaggeration": (float, 0.0, 2.0),
    "pause_sec": (float, 0.0, 5.0),
    "inference_timesteps": (int, 1, 100),
    "max_chars": (int, 50, 1000),
}


def _sanitize_params(raw: dict[str, Any]) -> dict[str, Any]:
    clean: dict[str, Any] = {}
    for key, (kind, low, high) in _EXTRA_PARAMS.items():
        if raw.get(key) is None:
            continue
        try:
            value = kind(raw[key])
        except (TypeError, ValueError):
            raise AppError("VALIDATION_ERROR", f"params.{key}: некорректное значение.", 422) from None
        clean[key] = max(kind(low), min(value, kind(high)))
    return clean


def _choose_model(voice: Any, requested: str) -> str:
    model_id = requested or (voice.model_id if voice else "")
    if not model_id:
        for model in registry.all():
            if model.category in ("tts", "clone") and any(v.install_state == "installed" for v in registry.variants(model.id)):
                model_id = model.id
                break
    if not model_id:
        raise AppError("MODEL_NOT_SELECTED", "Не выбрана TTS-модель.", 400)
    model = registry.get(model_id)
    if not model:
        raise AppError("MODEL_NOT_FOUND", "Модель не найдена.", 404)
    if not any(v.install_state == "installed" for v in registry.variants(model_id)):
        raise AppError("MODEL_NOT_INSTALLED", f"Модель «{model.name}» не скачана.", 409)
    if voice:
        if voice.kind == "cloned" and "clone" not in model.capabilities:
            raise AppError("VOICE_INCOMPATIBLE", f"Модель «{model.name}» не поддерживает клонирование голоса.", 400)
        if voice.kind == "designed" and "voice_design" not in model.capabilities:
            raise AppError("VOICE_INCOMPATIBLE", f"Модель «{model.name}» не поддерживает голос по описанию.", 400)
    return model_id


def _enqueue(payload: SynthesizePayload, *, task_type: str) -> dict[str, Any]:
    voice = get_voice(payload.voice_id)
    if not voice:
        raise AppError("VOICE_NOT_FOUND", "Голос не найден.", 404)
    model_id = _choose_model(voice, payload.model_id)
    params = {
        "speed": max(0.25, min(float(payload.speed), 4.0)),
        "pitch": max(-12.0, min(float(payload.pitch), 12.0)),
        "volume": max(0.0, min(float(payload.volume), 2.0)),
        "voice_kind": voice.kind,
        "variant_id": payload.variant_id,
        **_sanitize_params(payload.params),
    }
    task = tasks.enqueue(
        task_type,
        model_id=model_id,
        voice_id=voice.id,
        text=payload.text,
        language=payload.language,
        params=params,
        project_id=payload.project_id,
        priority=max(0, min(int(payload.priority), 100)),
        device=payload.device,
        precision="fp16",
    )
    return {"task_id": task.id, "task": tasks.task_public(task)}


@router.post("/synthesize", status_code=202)
def synthesize(payload: SynthesizePayload) -> dict[str, Any]:
    return _enqueue(payload, task_type="tts")


@router.post("/preview", status_code=202)
def preview(payload: SynthesizePayload) -> dict[str, Any]:
    return _enqueue(payload, task_type="preview")


@router.get("/formats")
def formats() -> dict[str, Any]:
    return {
        "input": ["wav"],
        "output": ["wav", "mp3", "ogg"],
        "default": "wav",
    }
