from __future__ import annotations

import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any, Callable

import soundfile as sf

from backend.engines.base import BaseEngine, gpu_memory_mb


class FasterWhisperEngine(BaseEngine):
    adapter = "faster_whisper"

    def load(self, spec: dict[str, Any]) -> dict[str, Any]:
        from faster_whisper import WhisperModel

        self.spec = spec
        device = "cuda" if spec.get("device") == "gpu" else "cpu"
        self.device = "cuda:0" if device == "cuda" else "cpu"
        precision = str(spec.get("precision") or "int8")
        if device == "cuda":
            compute_type = {"int8": "int8_float16", "fp16": "float16", "bf16": "bfloat16", "fp32": "float32"}.get(precision, "int8_float16")
        else:
            compute_type = "int8" if precision.startswith("int8") else "float32"
        model_path = str(spec.get("model_path") or spec.get("repo") or "")
        if not model_path:
            raise RuntimeError("Не указан путь к модели faster-whisper.")
        started = time.perf_counter()
        self.model = WhisperModel(
            model_path,
            device=device,
            compute_type=compute_type,
            cpu_threads=int(spec.get("settings", {}).get("cpu_threads") or 4),
            num_workers=1,
        )
        self.sample_rate = 16000
        return {
            "device": self.device,
            "precision": compute_type,
            "load_seconds": round(time.perf_counter() - started, 3),
            **gpu_memory_mb(),
        }

    def warmup(self) -> dict[str, Any]:
        import numpy as np

        started = time.perf_counter()
        segments, _info = self.model.transcribe(
            np.zeros(8000, dtype=np.float32),
            beam_size=1,
            vad_filter=False,
            word_timestamps=False,
            condition_on_previous_text=False,
        )
        list(segments)
        return {"warmed": True, "warmup_seconds": round(time.perf_counter() - started, 3)}

    def infer(self, payload: dict[str, Any], progress: Callable[[dict[str, Any]], None]) -> dict[str, Any]:
        import imageio_ffmpeg

        audio_path = str(payload["audio_path"])
        if not Path(audio_path).exists():
            raise FileNotFoundError(audio_path)
        started = time.perf_counter()
        with tempfile.TemporaryDirectory(prefix="myvs-stt-") as tmp:
            wav_path = Path(tmp) / "audio.wav"
            subprocess.run(
                [imageio_ffmpeg.get_ffmpeg_exe(), "-y", "-i", audio_path, "-ac", "1", "-ar", "16000", str(wav_path)],
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
            )
            audio, sample_rate = sf.read(wav_path, dtype="float32")
        if getattr(audio, "ndim", 1) > 1:
            audio = audio.mean(axis=1)
        if sample_rate != 16000:
            raise RuntimeError(f"Ожидалась частота 16000 Гц, получено {sample_rate}.")
        duration = len(audio) / 16000.0
        language = payload.get("language") or None
        if language == "auto":
            language = None
        beam_size = int(payload.get("beam_size") or 5)
        temperature = payload.get("temperature", 0.0)
        vad = bool(payload.get("vad", True))
        word_timestamps = bool(payload.get("word_timestamps", True))
        segments_iter, info = self.model.transcribe(
            audio,
            language=language,
            beam_size=beam_size,
            temperature=float(temperature),
            vad_filter=vad,
            word_timestamps=word_timestamps,
            condition_on_previous_text=False,
        )
        segments: list[dict[str, Any]] = []
        for segment in segments_iter:
            words = []
            if getattr(segment, "words", None):
                words = [
                    {"start": round(word.start, 3), "end": round(word.end, 3), "text": word.word, "probability": round(float(word.probability), 4)}
                    for word in segment.words
                ]
            segments.append(
                {
                    "start": round(segment.start, 3),
                    "end": round(segment.end, 3),
                    "text": segment.text.strip(),
                    "words": words,
                }
            )
            progress(
                {
                    "processed_sec": round(segment.end, 2),
                    "duration_sec": round(duration, 2),
                    "percent": min(99, round(segment.end / max(duration, 0.01) * 100)),
                    "segments": len(segments),
                }
            )
        text = " ".join(item["text"] for item in segments).strip()
        infer_sec = time.perf_counter() - started
        return {
            "text": text,
            "segments": segments,
            "language": info.language or language or "auto",
            "language_probability": round(float(info.language_probability or 0.0), 4),
            "audio_duration_sec": round(float(info.duration or duration), 3),
            "infer_seconds": round(infer_sec, 3),
            "rtf": round(infer_sec / max(float(info.duration or duration), 0.01), 4),
            **gpu_memory_mb(),
        }
