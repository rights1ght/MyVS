from __future__ import annotations

import hashlib
import logging
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import UploadFile
from sqlmodel import select

from backend.config import settings
from backend.db.models import TaskRecord, Voice
from backend.db.session import session_scope
from backend.services import audio as audio_service

logger = logging.getLogger(__name__)

BUILTIN = [
    # Piper RU
    ("Ирина", "piper", "ru_RU-irina-medium", "ru", "female"),
    ("Дмитрий", "piper", "ru_RU-dmitri-medium", "ru", "male"),
    ("Денис", "piper", "ru_RU-denis-medium", "ru", "male"),
    ("Руслан", "piper", "ru_RU-ruslan-medium", "ru", "male"),
    ("Amy", "piper", "en_US-amy-medium", "en", "female"),
    ("Ryan", "piper", "en_US-ryan-medium", "en", "male"),
    # Silero
    ("Aidar", "silero-v4", "aidar", "ru", "male"),
    ("Baya", "silero-v4", "baya", "ru", "female"),
    ("Kseniya", "silero-v4", "kseniya", "ru", "female"),
    ("Xenia", "silero-v4", "xenia", "ru", "female"),
    ("Eugene", "silero-v4", "eugene", "ru", "male"),
    # Kokoro (English only)
    ("Heart", "kokoro-82m", "af_heart", "en", "female"),
    ("Bella", "kokoro-82m", "af_bella", "en", "female"),
    ("Adam", "kokoro-82m", "am_adam", "en", "male"),
    ("Michael", "kokoro-82m", "am_michael", "en", "male"),
    ("Emma", "kokoro-82m", "bf_emma", "en", "female"),
    ("George", "kokoro-82m", "bm_george", "en", "male"),
    ("Xiaoxiao", "kokoro-82m", "zf_xiaoxiao", "zh", "female"),
    # Auto voices for clone models
    ("Авто (Chatterbox)", "chatterbox-multilingual", "auto", "ru", ""),
    ("Авто (OmniVoice)", "omnivoice", "auto", "ru", ""),
]


def seed_builtin_voices() -> None:
    with session_scope() as session:
        existing = session.exec(select(Voice).where(Voice.kind == "builtin")).all()
        seen = {(voice.model_id, voice.engine_voice_id) for voice in existing}
        for name, model_id, engine_voice_id, language, gender in BUILTIN:
            if (model_id, engine_voice_id) in seen:
                continue
            session.add(
                Voice(
                    name=name,
                    kind="builtin",
                    model_id=model_id,
                    engine_voice_id=engine_voice_id,
                    language=language,
                    gender=gender,
                    description="Встроенный голос",
                    commercial=True,
                    license="см. карточку модели",
                )
            )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def save_upload(upload: UploadFile, target: Path, max_mb: int = 100) -> Path:
    target.parent.mkdir(parents=True, exist_ok=True)
    size = 0
    with target.open("wb") as handle:
        while True:
            chunk = upload.file.read(1024 * 1024)
            if not chunk:
                break
            size += len(chunk)
            if size > max_mb * 1024 * 1024:
                handle.close()
                target.unlink(missing_ok=True)
                raise ValueError(f"Файл больше {max_mb} MB.")
            handle.write(chunk)
    return target


def analyze_file(path: Path) -> dict[str, Any]:
    with __import__("tempfile").TemporaryDirectory(prefix="myvs-analyze-") as tmp:
        wav = Path(tmp) / "reference.wav"
        audio_service.decode_to_wav(path, wav, sample_rate=24000, mono=True)
        return audio_service.analyze_reference(wav)


def create_cloned_voice(
    *,
    upload: UploadFile,
    name: str,
    language: str,
    model_id: str,
    consent: bool,
    reference_text: str = "",
    description: str = "",
) -> Voice:
    if not consent:
        raise ValueError("Нужно подтвердить право использовать этот голос.")
    voice_id = uuid.uuid4().hex
    folder = settings.data_dir / "voices" / voice_id
    folder.mkdir(parents=True, exist_ok=True)
    suffix = Path(upload.filename or "reference.wav").suffix or ".wav"
    original = folder / f"reference_original{suffix}"
    save_upload(upload, original, max_mb=100)
    reference = folder / "reference.wav"
    try:
        audio_service.decode_to_wav(original, reference, sample_rate=24000, mono=True)
    except Exception as exc:
        shutil.rmtree(folder, ignore_errors=True)
        raise ValueError(f"Не удалось прочитать аудио: {exc}") from exc
    analysis = audio_service.analyze_reference(reference)
    if analysis["duration_sec"] < 5 or analysis["duration_sec"] > 30:
        shutil.rmtree(folder, ignore_errors=True)
        raise ValueError("Референс должен быть длительностью 5–30 секунд.")
    if not analysis.get("ok"):
        # Keep the file for diagnostics, but do not add a broken voice.
        shutil.rmtree(folder, ignore_errors=True)
        raise ValueError("; ".join(analysis.get("issues") or ["Референс не прошёл проверку качества."]))
    quality = dict(analysis)
    quality["reference_text"] = reference_text.strip()
    with session_scope() as session:
        voice = Voice(
            name=name.strip() or "Клонированный голос",
            kind="cloned",
            model_id=model_id,
            engine_voice_id="reference",
            language=language,
            description=description or reference_text,
            reference_path=str(reference),
            reference_sha256=_sha256(reference),
            duration_sec=analysis["duration_sec"],
            quality_score=analysis["score"],
            quality_json=quality,
            consent_accepted=True,
            consent_at=datetime.now(timezone.utc),
            license="reference / user responsibility",
            commercial=False,
        )
        session.add(voice)
        session.flush()
        session.refresh(voice)
        return voice


def create_designed_voice(*, name: str, description: str, language: str, model_id: str) -> Voice:
    if not description.strip():
        raise ValueError("Опишите голос словами.")
    with session_scope() as session:
        voice = Voice(
            name=name.strip() or "Голос по описанию",
            kind="designed",
            model_id=model_id,
            engine_voice_id="design",
            language=language,
            description=description.strip(),
            quality_score=None,
            quality_json={"design_prompt": description.strip()},
            license="model license",
            commercial=False,
        )
        session.add(voice)
        session.flush()
        session.refresh(voice)
        return voice


def list_voices(kind: str | None = None, language: str | None = None, model_id: str | None = None) -> list[Voice]:
    with session_scope() as session:
        statement = select(Voice).order_by(Voice.created_at)
        if kind:
            statement = statement.where(Voice.kind == kind)
        if language:
            statement = statement.where(Voice.language == language)
        if model_id:
            statement = statement.where(Voice.model_id == model_id)
        return list(session.exec(statement).all())


def get_voice(voice_id: str) -> Voice | None:
    with session_scope() as session:
        return session.get(Voice, voice_id)


def delete_voice(voice_id: str) -> bool:
    voice = get_voice(voice_id)
    if not voice:
        return False
    if voice.kind == "builtin":
        raise ValueError("Встроенные голоса нельзя удалить.")
    if voice.reference_path:
        shutil.rmtree(Path(voice.reference_path).parent, ignore_errors=True)
    with session_scope() as session:
        row = session.get(Voice, voice_id)
        if row:
            for task in session.exec(select(TaskRecord).where(TaskRecord.voice_id == voice_id)).all():
                task.voice_id = None
                session.add(task)
            session.delete(row)
    return True
