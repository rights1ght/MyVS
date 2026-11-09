from __future__ import annotations

from typing import Type

from backend.engines.base import BaseEngine

_ADAPTERS = {
    "faster_whisper": ("backend.engines.stt.faster_whisper", "FasterWhisperEngine"),
    "gigaam": ("backend.engines.stt.gigaam", "GigaAMEngine"),
    "piper": ("backend.engines.tts.piper", "PiperEngine"),
    "silero": ("backend.engines.tts.silero", "SileroEngine"),
    "kokoro": ("backend.engines.tts.kokoro", "KokoroEngine"),
    "chatterbox": ("backend.engines.tts.chatterbox", "ChatterboxEngine"),
    "chatterbox_turbo": ("backend.engines.tts.chatterbox", "ChatterboxTurboEngine"),
    "qwen3_tts": ("backend.engines.tts.qwen3_tts", "Qwen3TTSEngine"),
    "qwen3_tts_design": ("backend.engines.tts.qwen3_tts", "Qwen3TTSDesignEngine"),
    "voxcpm2": ("backend.engines.tts.voxcpm2", "VoxCPM2Engine"),
    "omnivoice": ("backend.engines.tts.omnivoice", "OmniVoiceEngine"),
}


def engine_class(adapter: str) -> Type[BaseEngine]:
    module_name, class_name = _ADAPTERS[adapter]
    module = __import__(module_name, fromlist=[class_name])
    return getattr(module, class_name)


def available_adapters() -> list[str]:
    return sorted(_ADAPTERS)
