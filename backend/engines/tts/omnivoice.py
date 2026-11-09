from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Callable

import numpy as np

from backend.engines.base import BaseEngine, gpu_memory_mb


class OmniVoiceEngine(BaseEngine):
    adapter = "omnivoice"
    supports_clone = True
    supports_design = True

    def __init__(self) -> None:
        super().__init__()
        self._prompts: dict[str, Any] = {}

    def load(self, spec: dict[str, Any]) -> dict[str, Any]:
        import torch
        from omnivoice import OmniVoice

        self.spec = spec
        self.device = "cuda:0" if spec.get("device") == "gpu" else "cpu"
        path = str(spec.get("model_path") or spec.get("repo") or "k2-fsa/OmniVoice")
        dtype = torch.float16 if self.device.startswith("cuda") else torch.float32
        started = time.perf_counter()
        self.model = OmniVoice.from_pretrained(path, device_map=self.device, dtype=dtype)
        self.sample_rate = 24000
        return {
            "device": self.device,
            "sample_rate": self.sample_rate,
            "noncommercial": True,
            "load_seconds": round(time.perf_counter() - started, 3),
            **gpu_memory_mb(),
        }

    def infer(self, payload: dict[str, Any], progress: Callable[[dict[str, Any]], None]) -> dict[str, Any]:
        import soundfile as sf

        started = time.perf_counter()
        kwargs: dict[str, Any] = {"text": str(payload["text"])}
        ref = payload.get("reference_path")
        if ref and Path(str(ref)).exists():
            ref_text = str(payload.get("reference_text") or "")
            key = f"{ref}|{ref_text}"
            if key not in self._prompts:
                self._prompts[key] = self.model.create_voice_clone_prompt(ref_audio=str(ref), ref_text=ref_text or None)
            kwargs["voice_clone_prompt"] = self._prompts[key]
        instruct = str(payload.get("instruct") or "").strip()
        if instruct:
            kwargs["instruct"] = instruct
        if payload.get("speed"):
            kwargs["speed"] = float(payload["speed"])
        progress({"percent": 20, "phase": "synthesis"})
        audio = self.model.generate(**kwargs)
        if isinstance(audio, (list, tuple)):
            audio = audio[0]
        audio = np.asarray(audio, dtype=np.float32)
        output = str(payload["output_path"])
        Path(output).parent.mkdir(parents=True, exist_ok=True)
        sf.write(output, audio, self.sample_rate, subtype="PCM_16")
        duration = len(audio) / max(self.sample_rate, 1)
        infer_sec = time.perf_counter() - started
        return {
            "output_path": output,
            "sample_rate": self.sample_rate,
            "duration_sec": round(duration, 3),
            "engine": "omnivoice",
            "noncommercial": True,
            "speed_applied": bool(payload.get("speed")),
            "infer_seconds": round(infer_sec, 3),
            "rtf": round(infer_sec / max(duration, 0.01), 4),
            **gpu_memory_mb(),
        }
