from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Callable

import numpy as np

from backend.engines.base import BaseEngine, gpu_memory_mb

LANG_MAP = {
    "ru": "ru",
    "en": "en",
    "de": "de",
    "fr": "fr",
    "es": "es",
    "it": "it",
    "pt": "pt",
    "pl": "pl",
    "tr": "tr",
    "nl": "nl",
    "sv": "sv",
    "no": "no",
    "da": "da",
    "fi": "fi",
    "el": "el",
    "he": "he",
    "hi": "hi",
    "ja": "ja",
    "ko": "ko",
    "ms": "ms",
    "sw": "sw",
    "ar": "ar",
    "zh": "zh",
}


class ChatterboxEngine(BaseEngine):
    adapter = "chatterbox"
    supports_clone = True

    def load(self, spec: dict[str, Any]) -> dict[str, Any]:
        from chatterbox.mtl_tts import ChatterboxMultilingualTTS

        self.spec = spec
        self.device = "cuda" if spec.get("device") == "gpu" else "cpu"
        started = time.perf_counter()
        model_path = str(spec.get("model_path") or "")
        if model_path and Path(model_path).exists():
            self.model = ChatterboxMultilingualTTS.from_local(model_path, self.device)
        else:
            self.model = ChatterboxMultilingualTTS.from_pretrained(device=self.device)
        self.sample_rate = int(getattr(self.model, "sr", 24000))
        return {
            "device": self.device,
            "sample_rate": self.sample_rate,
            "watermark": True,
            "load_seconds": round(time.perf_counter() - started, 3),
            **gpu_memory_mb(),
        }

    def infer(self, payload: dict[str, Any], progress: Callable[[dict[str, Any]], None]) -> dict[str, Any]:
        import torchaudio as ta

        started = time.perf_counter()
        text = str(payload["text"])
        language_id = LANG_MAP.get(str(payload.get("language") or "ru"), "ru")
        ref = payload.get("reference_path") or None
        kwargs: dict[str, Any] = {
            "language_id": language_id,
            "exaggeration": float(payload.get("exaggeration") or 0.5),
            "cfg_weight": float(payload.get("cfg_weight") or 0.5),
        }
        if ref and Path(str(ref)).exists():
            kwargs["audio_prompt_path"] = str(ref)
        progress({"percent": 25, "phase": "synthesis"})
        wav = self.model.generate(text, **kwargs)
        output = str(payload["output_path"])
        Path(output).parent.mkdir(parents=True, exist_ok=True)
        ta.save(output, wav, self.sample_rate)
        audio = wav.detach().cpu().float().numpy().squeeze() if hasattr(wav, "detach") else np.asarray(wav).squeeze()
        duration = len(audio) / max(self.sample_rate, 1)
        infer_sec = time.perf_counter() - started
        return {
            "output_path": output,
            "sample_rate": self.sample_rate,
            "duration_sec": round(duration, 3),
            "engine": "chatterbox",
            "watermark": True,
            "warning": "Файл содержит PerTh watermark Chatterbox.",
            "infer_seconds": round(infer_sec, 3),
            "rtf": round(infer_sec / max(duration, 0.01), 4),
            **gpu_memory_mb(),
        }


class ChatterboxTurboEngine(BaseEngine):
    adapter = "chatterbox_turbo"
    supports_clone = True

    def load(self, spec: dict[str, Any]) -> dict[str, Any]:
        from chatterbox.tts_turbo import ChatterboxTurboTTS

        self.spec = spec
        self.device = "cuda" if spec.get("device") == "gpu" else "cpu"
        started = time.perf_counter()
        model_path = str(spec.get("model_path") or "")
        if model_path and Path(model_path).exists():
            self.model = ChatterboxTurboTTS.from_local(model_path, self.device)
        else:
            self.model = ChatterboxTurboTTS.from_pretrained(device=self.device)
        self.sample_rate = int(getattr(self.model, "sr", 24000))
        return {
            "device": self.device,
            "sample_rate": self.sample_rate,
            "watermark": True,
            "load_seconds": round(time.perf_counter() - started, 3),
            **gpu_memory_mb(),
        }

    def infer(self, payload: dict[str, Any], progress: Callable[[dict[str, Any]], None]) -> dict[str, Any]:
        import torchaudio as ta

        started = time.perf_counter()
        kwargs: dict[str, Any] = {}
        ref = payload.get("reference_path") or None
        if ref and Path(str(ref)).exists():
            kwargs["audio_prompt_path"] = str(ref)
        progress({"percent": 25, "phase": "synthesis"})
        wav = self.model.generate(str(payload["text"]), **kwargs)
        output = str(payload["output_path"])
        Path(output).parent.mkdir(parents=True, exist_ok=True)
        ta.save(output, wav, self.sample_rate)
        audio = wav.detach().cpu().float().numpy().squeeze() if hasattr(wav, "detach") else np.asarray(wav).squeeze()
        duration = len(audio) / max(self.sample_rate, 1)
        infer_sec = time.perf_counter() - started
        return {
            "output_path": output,
            "sample_rate": self.sample_rate,
            "duration_sec": round(duration, 3),
            "engine": "chatterbox_turbo",
            "watermark": True,
            "warning": "Файл содержит PerTh watermark Chatterbox.",
            "infer_seconds": round(infer_sec, 3),
            "rtf": round(infer_sec / max(duration, 0.01), 4),
            **gpu_memory_mb(),
        }
