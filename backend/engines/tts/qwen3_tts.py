from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Callable

import numpy as np

from backend.engines.base import BaseEngine, gpu_memory_mb

LANGUAGES = {
    "ru": "Russian",
    "en": "English",
    "zh": "Chinese",
    "ja": "Japanese",
    "ko": "Korean",
    "de": "German",
    "fr": "French",
    "es": "Spanish",
    "it": "Italian",
    "pt": "Portuguese",
}
LANGUAGE_NAMES = {value.lower(): value for value in LANGUAGES.values()}


def qwen_language(code: str | None) -> str:
    if not code:
        return "Auto"
    if code in LANGUAGES:
        return LANGUAGES[code]
    return LANGUAGE_NAMES.get(code.lower(), code)


class Qwen3TTSEngine(BaseEngine):
    adapter = "qwen3_tts"
    supports_clone = True

    def __init__(self) -> None:
        super().__init__()
        self._prompts: dict[str, Any] = {}

    def load(self, spec: dict[str, Any]) -> dict[str, Any]:
        import torch
        from qwen_tts import Qwen3TTSModel

        self.spec = spec
        self.device = "cuda:0" if spec.get("device") == "gpu" else "cpu"
        self.sample_rate = 24000
        path = str(spec.get("model_path") or spec.get("repo") or "")
        dtype = torch.bfloat16 if self.device.startswith("cuda") else torch.float32
        started = time.perf_counter()
        self.model = Qwen3TTSModel.from_pretrained(path, device_map=self.device, dtype=dtype)
        return {
            "device": self.device,
            "load_seconds": round(time.perf_counter() - started, 3),
            **gpu_memory_mb(),
        }

    def _prompt(self, ref_audio: str, ref_text: str, x_vector_only: bool) -> Any:
        key = f"{ref_audio}|{ref_text}|{int(x_vector_only)}"
        if key not in self._prompts:
            self._prompts[key] = self.model.create_voice_clone_prompt(
                ref_audio=ref_audio,
                ref_text=ref_text or None,
                x_vector_only_mode=x_vector_only,
            )
        return self._prompts[key]

    def infer(self, payload: dict[str, Any], progress: Callable[[dict[str, Any]], None]) -> dict[str, Any]:
        import soundfile as sf
        import torch

        started = time.perf_counter()
        text = str(payload["text"])
        ref_audio = str(payload.get("reference_path") or "")
        if not ref_audio or not Path(ref_audio).exists():
            raise RuntimeError("Qwen3-TTS Base требует референс-аудио клонированного голоса.")
        ref_text = str(payload.get("reference_text") or "")
        language = qwen_language(payload.get("language"))
        progress({"percent": 10, "phase": "voice prompt"})
        prompt = self._prompt(ref_audio, ref_text, not bool(ref_text))
        progress({"percent": 25, "phase": "synthesis"})
        with torch.inference_mode():
            wavs, sr = self.model.generate_voice_clone(
                text=text,
                language=language,
                voice_clone_prompt=prompt,
            )
        audio = np.asarray(wavs[0], dtype=np.float32)
        output = str(payload["output_path"])
        Path(output).parent.mkdir(parents=True, exist_ok=True)
        sf.write(output, audio, int(sr), subtype="PCM_16")
        infer_sec = time.perf_counter() - started
        duration = len(audio) / max(int(sr), 1)
        return {
            "output_path": output,
            "sample_rate": int(sr),
            "duration_sec": round(duration, 3),
            "engine": "qwen3_tts",
            "infer_seconds": round(infer_sec, 3),
            "rtf": round(infer_sec / max(duration, 0.01), 4),
            **gpu_memory_mb(),
        }


class Qwen3TTSDesignEngine(BaseEngine):
    adapter = "qwen3_tts_design"
    supports_design = True

    def load(self, spec: dict[str, Any]) -> dict[str, Any]:
        import torch
        from qwen_tts import Qwen3TTSModel

        self.spec = spec
        self.device = "cuda:0" if spec.get("device") == "gpu" else "cpu"
        path = str(spec.get("model_path") or spec.get("repo") or "")
        dtype = torch.bfloat16 if self.device.startswith("cuda") else torch.float32
        started = time.perf_counter()
        self.model = Qwen3TTSModel.from_pretrained(path, device_map=self.device, dtype=dtype)
        self.sample_rate = 24000
        return {
            "device": self.device,
            "voice_design": True,
            "load_seconds": round(time.perf_counter() - started, 3),
            **gpu_memory_mb(),
        }

    def infer(self, payload: dict[str, Any], progress: Callable[[dict[str, Any]], None]) -> dict[str, Any]:
        import soundfile as sf
        import torch

        started = time.perf_counter()
        instruct = str(payload.get("instruct") or "")
        if not instruct:
            raise RuntimeError("Для VoiceDesign нужно текстовое описание голоса.")
        progress({"percent": 25, "phase": "voice design"})
        with torch.inference_mode():
            wavs, sr = self.model.generate_voice_design(
                text=str(payload["text"]),
                language=qwen_language(payload.get("language")),
                instruct=instruct,
            )
        audio = np.asarray(wavs[0], dtype=np.float32)
        output = str(payload["output_path"])
        Path(output).parent.mkdir(parents=True, exist_ok=True)
        sf.write(output, audio, int(sr), subtype="PCM_16")
        infer_sec = time.perf_counter() - started
        duration = len(audio) / max(int(sr), 1)
        return {
            "output_path": output,
            "sample_rate": int(sr),
            "duration_sec": round(duration, 3),
            "engine": "qwen3_tts_design",
            "infer_seconds": round(infer_sec, 3),
            "rtf": round(infer_sec / max(duration, 0.01), 4),
            **gpu_memory_mb(),
        }
