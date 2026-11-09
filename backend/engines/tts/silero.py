from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Callable

import numpy as np

from backend.engines.base import BaseEngine, gpu_memory_mb


class SileroEngine(BaseEngine):
    adapter = "silero"

    def load(self, spec: dict[str, Any]) -> dict[str, Any]:
        import torch
        from torch import package

        self.spec = spec
        self.sample_rate = 48000
        self.device = "cuda:0" if spec.get("device") == "gpu" else "cpu"
        path = Path(str(spec.get("model_path") or ""))
        if path.is_dir():
            candidates = list(path.rglob("*.pt"))
            path = candidates[0] if candidates else path
        if not path.exists():
            raise RuntimeError(f"Файл Silero не найден: {path}")
        started = time.perf_counter()
        importer = package.PackageImporter(str(path))
        self.model = importer.load_pickle("tts_models", "model")
        self.model.to(self.device)
        self.speakers = ["aidar", "baya", "kseniya", "xenia", "eugene"]
        return {
            "device": self.device,
            "voices": self.speakers,
            "load_seconds": round(time.perf_counter() - started, 3),
            **gpu_memory_mb(),
        }

    def infer(self, payload: dict[str, Any], progress: Callable[[dict[str, Any]], None]) -> dict[str, Any]:
        import torch

        started = time.perf_counter()
        speaker = str(payload.get("engine_voice_id") or payload.get("voice") or "baya")
        if speaker not in self.speakers:
            raise RuntimeError(f"Голос Silero не найден: {speaker}")
        text = str(payload["text"])
        progress({"percent": 10, "phase": "synthesis"})
        with torch.inference_mode():
            audio = self.model.apply_tts(
                text=text,
                speaker=speaker,
                sample_rate=int(self.sample_rate),
                put_accent=True,
                put_yo=True,
            )
        if isinstance(audio, torch.Tensor):
            audio = audio.detach().cpu().float().numpy()
        audio = np.asarray(audio, dtype=np.float32)
        progress({"percent": 85, "phase": "postprocess"})
        result = self.result_wav(audio, self.sample_rate, str(payload["output_path"]))
        infer_sec = time.perf_counter() - started
        return {
            **result,
            "engine": "silero",
            "infer_seconds": round(infer_sec, 3),
            "rtf": round(infer_sec / max(result["duration_sec"], 0.01), 4),
            **gpu_memory_mb(),
        }
