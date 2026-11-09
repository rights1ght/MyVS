from __future__ import annotations

import math
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any, Callable

import soundfile as sf

from backend.engines.base import BaseEngine, gpu_memory_mb


class GigaAMEngine(BaseEngine):
    adapter = "gigaam"

    def load(self, spec: dict[str, Any]) -> dict[str, Any]:
        import gigaam

        self.spec = spec
        self.device = "cuda:0" if spec.get("device") == "gpu" else "cpu"
        model_name = str(spec.get("package_model") or "v2_rnnt")
        started = time.perf_counter()
        download_root = Path.home() / ".cache" / "gigaam"
        download_root.mkdir(parents=True, exist_ok=True)
        weight = download_root / f"{model_name}.ckpt"
        if not weight.exists():
            # The upstream Sber CDN currently presents an expired certificate.
            # Prefer a manual cache; otherwise fetch with verification disabled for
            # this single official CDN URL and retry with HTTP Range.
            import httpx
            import time as _time

            url = f"https://cdn.chatwm.opensmodel.sberdevices.ru/GigaAM/{model_name}.ckpt"
            part = weight.with_suffix(".ckpt.part")
            last_error: Exception | None = None
            for attempt in range(6):
                offset = part.stat().st_size if part.exists() else 0
                headers = {"Range": f"bytes={offset}-"} if offset else {}
                try:
                    with httpx.Client(verify=False, follow_redirects=True, timeout=httpx.Timeout(60, read=120)) as client:
                        with client.stream("GET", url, headers=headers) as response:
                            if offset and response.status_code == 200:
                                part.unlink(missing_ok=True)
                                offset = 0
                            response.raise_for_status()
                            with part.open("ab" if offset else "wb") as handle:
                                for chunk in response.iter_bytes(1024 * 1024):
                                    handle.write(chunk)
                    if part.stat().st_size >= 470_000_000:
                        last_error = None
                        break
                    last_error = RuntimeError(f"получено {part.stat().st_size} байт")
                except Exception as exc:
                    last_error = exc
                _time.sleep(min(2 ** attempt, 8))
            if last_error is not None:
                raise RuntimeError(f"Не удалось скачать GigaAM: {last_error}")
            part.replace(weight)
        import torch

        original_load = torch.load

        def trusted_load(*args, **kwargs):
            kwargs.setdefault("weights_only", False)
            return original_load(*args, **kwargs)

        torch.load = trusted_load
        try:
            self.model = gigaam.load_model(model_name, device=self.device, download_root=str(download_root))
        finally:
            torch.load = original_load
        self.sample_rate = 16000
        return {
            "device": self.device,
            "model_name": model_name,
            "load_seconds": round(time.perf_counter() - started, 3),
            **gpu_memory_mb(),
        }

    def _decode(self, audio_path: str, out_wav: Path) -> None:
        import imageio_ffmpeg

        ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
        subprocess.run(
            [ffmpeg, "-y", "-i", audio_path, "-ac", "1", "-ar", "16000", str(out_wav)],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

    def infer(self, payload: dict[str, Any], progress: Callable[[dict[str, Any]], None]) -> dict[str, Any]:
        started = time.perf_counter()
        source = str(payload["audio_path"])
        with tempfile.TemporaryDirectory(prefix="myvs-gigaam-") as tmp:
            wav_path = Path(tmp) / "audio.wav"
            self._decode(source, wav_path)
            data, sr = sf.read(wav_path, dtype="float32")
            if data.ndim > 1:
                data = data.mean(axis=1)
            total = len(data) / sr
            chunk_sec = 20.0
            overlap_sec = 1.0
            chunk_samples = int(chunk_sec * sr)
            step = int((chunk_sec - overlap_sec) * sr)
            segments: list[dict[str, Any]] = []
            offset = 0
            while offset < len(data):
                chunk = data[offset : offset + chunk_samples]
                if len(chunk) < sr * 0.2:
                    break
                chunk_path = Path(tmp) / f"chunk_{len(segments)}.wav"
                sf.write(chunk_path, chunk, sr)
                result = self.model.transcribe(str(chunk_path))
                text = result if isinstance(result, str) else getattr(result, "text", str(result))
                words = []
                for word in getattr(result, "words", []) or []:
                    words.append(
                        {
                            "start": round(offset / sr + float(word.start), 3),
                            "end": round(offset / sr + float(word.end), 3),
                            "text": word.text,
                        }
                    )
                start = offset / sr
                end = min(total, (offset + len(chunk)) / sr)
                if text.strip():
                    segments.append({"start": round(start, 3), "end": round(end, 3), "text": text.strip(), "words": words})
                progress(
                    {
                        "processed_sec": round(end, 2),
                        "duration_sec": round(total, 2),
                        "percent": min(99, int(end / max(total, 0.01) * 100)),
                        "segments": len(segments),
                    }
                )
                offset += step
                if offset + int(0.2 * sr) >= len(data):
                    break
        text = " ".join(segment["text"] for segment in segments).strip()
        infer_sec = time.perf_counter() - started
        return {
            "text": text,
            "segments": segments,
            "language": "ru",
            "language_probability": 1.0,
            "audio_duration_sec": round(total, 3),
            "infer_seconds": round(infer_sec, 3),
            "rtf": round(infer_sec / max(total, 0.01), 4),
            **gpu_memory_mb(),
        }
