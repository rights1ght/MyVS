from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Callable

import numpy as np

from backend.engines.base import BaseEngine, gpu_memory_mb
from backend.engines.tts.common import concat_audio


class PiperEngine(BaseEngine):
    adapter = "piper"

    def __init__(self) -> None:
        super().__init__()
        self.voices: dict[str, Any] = {}
        self.voice_paths: dict[str, Path] = {}

    def load(self, spec: dict[str, Any]) -> dict[str, Any]:
        from piper import PiperVoice

        self.spec = spec
        self.device = "cpu"
        self.sample_rate = 22050
        self.voices = {}
        self.voice_paths = {}
        model_path = Path(str(spec.get("model_path") or ""))
        if not model_path.exists():
            raise RuntimeError(f"Каталог голосов Piper не найден: {model_path}")
        candidates = [model_path] if model_path.is_file() else sorted(model_path.rglob("*.onnx"))
        for path in candidates:
            if not path.exists():
                continue
            self.voice_paths[path.stem] = path
            self.voice_paths[path.name] = path
        if not self.voice_paths:
            raise RuntimeError("В каталоге Piper нет .onnx голосов.")
        return {
            "device": "cpu",
            "voices": sorted({path.stem for path in self.voice_paths.values()}),
            "load_seconds": 0.0,
            **gpu_memory_mb(),
        }

    def _voice(self, name: str | None) -> Any:
        from piper import PiperVoice

        if not name:
            name = next(iter(self.voice_paths))
        path = self.voice_paths.get(name)
        if path is None:
            # allow passing a relative path
            candidate = Path(str(self.spec.get("model_path") or "")) / name
            if candidate.exists():
                path = candidate
            else:
                raise RuntimeError(f"Голос Piper не найден: {name}")
        key = str(path)
        if key not in self.voices:
            self.voices[key] = PiperVoice.load(path, config_path=path.with_name(path.name + ".json"), use_cuda=False)
        return self.voices[key]

    def infer(self, payload: dict[str, Any], progress: Callable[[dict[str, Any]], None]) -> dict[str, Any]:
        from piper import SynthesisConfig

        started = time.perf_counter()
        voice = self._voice(payload.get("engine_voice_id") or payload.get("voice"))
        speed = max(0.25, min(float(payload.get("speed") or 1.0), 4.0))
        volume = max(0.0, min(float(payload.get("volume") or 1.0), 2.0))
        config = SynthesisConfig(length_scale=1.0 / speed, normalize_audio=True, volume=volume)
        parts: list[np.ndarray] = []
        sample_rate = 22050
        for index, chunk in enumerate(voice.synthesize(str(payload["text"]), syn_config=config)):
            parts.append(np.asarray(chunk.audio_float_array, dtype=np.float32))
            sample_rate = int(chunk.sample_rate)
            progress({"chunks": index + 1, "percent": min(95, (index + 1) * 12)})
        audio = concat_audio(parts, pause_sec=0.08, sample_rate=sample_rate)
        result = self.result_wav(audio, sample_rate, str(payload["output_path"]))
        infer_sec = time.perf_counter() - started
        return {
            **result,
            "engine": "piper",
            "speed_applied": True,
            "infer_seconds": round(infer_sec, 3),
            "rtf": round(infer_sec / max(result["duration_sec"], 0.01), 4),
            **gpu_memory_mb(),
        }
