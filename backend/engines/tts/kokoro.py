from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Callable

import numpy as np

from backend.engines.base import BaseEngine, gpu_memory_mb
from backend.engines.tts.common import concat_audio


class KokoroEngine(BaseEngine):
    adapter = "kokoro"

    def __init__(self) -> None:
        super().__init__()
        self.pipeline = None

    def load(self, spec: dict[str, Any]) -> dict[str, Any]:
        import torch
        from kokoro import KPipeline
        from kokoro.model import KModel

        self.spec = spec
        requested_gpu = spec.get("device") == "gpu"
        if requested_gpu and not torch.cuda.is_available():
            raise RuntimeError(
                "Выбран GPU-вариант Kokoro, но CUDA недоступна в окружении TTS-worker. "
                "Проверьте CUDA-сборку PyTorch и драйвер NVIDIA."
            )
        self.device = "cuda:0" if requested_gpu else "cpu"
        lang_code = str(spec.get("lang_code") or "a")
        path = Path(str(spec.get("model_path") or spec.get("repo") or "hexgrad/Kokoro-82M"))
        started = time.perf_counter()
        if path.is_dir():
            model = KModel(config=str(path / "config.json"), model=str(path / "kokoro-v1_0.pth"))
            self.pipeline = KPipeline(lang_code=lang_code, model=model, device=self.device)
            self.voice_tensors = {}
            for voice_path in (path / "voices").glob("*.pt"):
                self.voice_tensors[voice_path.stem] = torch.load(voice_path, map_location="cpu", weights_only=True)
        else:
            self.pipeline = KPipeline(lang_code=lang_code, repo_id=str(path), device=self.device)
            self.voice_tensors = {}
        self.sample_rate = 24000
        return {
            "device": self.device,
            "sample_rate": self.sample_rate,
            "load_seconds": round(time.perf_counter() - started, 3),
            **gpu_memory_mb(),
        }

    def infer(self, payload: dict[str, Any], progress: Callable[[dict[str, Any]], None]) -> dict[str, Any]:
        started = time.perf_counter()
        text = str(payload["text"])
        voice = str(payload.get("engine_voice_id") or "af_heart")
        speed = max(0.5, min(float(payload.get("speed") or 1.0), 2.0))
        voice_arg = self.voice_tensors.get(voice, voice) if self.voice_tensors else voice
        parts: list[np.ndarray] = []
        for index, (_, _, audio) in enumerate(self.pipeline(text, voice=voice_arg, speed=speed)):
            if audio is None:
                continue
            if hasattr(audio, "detach"):
                audio = audio.detach().cpu().float().numpy()
            parts.append(np.asarray(audio, dtype=np.float32))
            progress({"percent": min(90, 20 + index * 10), "chunks": index + 1})
        audio = concat_audio(parts, pause_sec=0.05, sample_rate=self.sample_rate)
        output = str(payload["output_path"])
        Path(output).parent.mkdir(parents=True, exist_ok=True)
        result = self.result_wav(audio, self.sample_rate, output)
        infer_sec = time.perf_counter() - started
        return {
            **result,
            "engine": "kokoro",
            "speed_applied": True,
            "infer_seconds": round(infer_sec, 3),
            "rtf": round(infer_sec / max(result["duration_sec"], 0.01), 4),
            **gpu_memory_mb(),
        }
