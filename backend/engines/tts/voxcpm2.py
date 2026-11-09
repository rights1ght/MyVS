from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Callable

import numpy as np

from backend.engines.base import BaseEngine, gpu_memory_mb


class VoxCPM2Engine(BaseEngine):
    adapter = "voxcpm2"
    supports_clone = True
    supports_design = True

    def load(self, spec: dict[str, Any]) -> dict[str, Any]:
        from voxcpm import VoxCPM

        self.spec = spec
        self.device = "cuda" if spec.get("device") == "gpu" else "cpu"
        started = time.perf_counter()
        path = str(spec.get("model_path") or spec.get("repo") or "openbmb/VoxCPM2")
        self.model = VoxCPM.from_pretrained(path, load_denoiser=False, device=self.device, optimize=False)
        self.sample_rate = int(getattr(self.model.tts_model, "sample_rate", 48000))
        return {
            "device": self.device,
            "sample_rate": self.sample_rate,
            "exclusive": True,
            "load_seconds": round(time.perf_counter() - started, 3),
            **gpu_memory_mb(),
        }

    def infer(self, payload: dict[str, Any], progress: Callable[[dict[str, Any]], None]) -> dict[str, Any]:
        import soundfile as sf

        started = time.perf_counter()
        text = str(payload["text"])
        instruct = str(payload.get("instruct") or "").strip()
        if instruct:
            text = f"({instruct}) {text}"
        kwargs: dict[str, Any] = {
            "cfg_value": float(payload.get("cfg_value") or 2.0),
            "inference_timesteps": int(payload.get("inference_timesteps") or 10),
            "normalize": True,
        }
        ref = payload.get("reference_path")
        if ref and Path(str(ref)).exists():
            kwargs["reference_wav_path"] = str(ref)
        progress({"percent": 20, "phase": "synthesis"})
        wav = self.model.generate(text=text, **kwargs)
        audio = np.asarray(wav, dtype=np.float32)
        output = str(payload["output_path"])
        Path(output).parent.mkdir(parents=True, exist_ok=True)
        sf.write(output, audio, self.sample_rate, subtype="PCM_16")
        duration = len(audio) / max(self.sample_rate, 1)
        infer_sec = time.perf_counter() - started
        return {
            "output_path": output,
            "sample_rate": self.sample_rate,
            "duration_sec": round(duration, 3),
            "engine": "voxcpm2",
            "infer_seconds": round(infer_sec, 3),
            "rtf": round(infer_sec / max(duration, 0.01), 4),
            **gpu_memory_mb(),
        }
