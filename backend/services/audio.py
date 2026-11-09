from __future__ import annotations

import math
import shutil
import subprocess
from pathlib import Path
from typing import Any

import numpy as np
import soundfile as sf

from backend.config import settings


def ffmpeg_exe() -> str:
    candidate = shutil.which("ffmpeg")
    if candidate:
        return candidate
    import imageio_ffmpeg

    return imageio_ffmpeg.get_ffmpeg_exe()


def decode_to_wav(source: str | Path, target: str | Path, sample_rate: int = 16000, mono: bool = True) -> None:
    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    args = [ffmpeg_exe(), "-y", "-i", str(source), "-vn"]
    if mono:
        args += ["-ac", "1"]
    args += ["-ar", str(sample_rate), "-c:a", "pcm_s16le", str(target)]
    subprocess.run(args, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)


def probe(path: str | Path) -> dict[str, Any]:
    info = sf.info(str(path))
    return {
        "sample_rate": info.samplerate,
        "channels": info.channels,
        "duration_sec": round(info.frames / max(info.samplerate, 1), 3),
        "format": info.format,
    }


def read_mono(path: str | Path) -> tuple[np.ndarray, int]:
    data, sr = sf.read(str(path), dtype="float32", always_2d=False)
    if data.ndim > 1:
        data = data.mean(axis=1)
    return np.asarray(data, dtype=np.float32), int(sr)


def write_wav(path: str | Path, audio: np.ndarray, sample_rate: int) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    audio = np.asarray(audio, dtype=np.float32)
    if audio.ndim > 1:
        audio = audio.mean(axis=1)
    peak = float(np.max(np.abs(audio))) if audio.size else 0.0
    if peak > 0.99:
        audio = audio / peak * 0.98
    sf.write(path, audio, sample_rate, subtype="PCM_16")


def _atempo_chain(factor: float) -> list[str]:
    factor = max(0.1, min(factor, 10.0))
    parts: list[str] = []
    while factor > 2.0:
        parts.append("atempo=2.0")
        factor /= 2.0
    while factor < 0.5:
        parts.append("atempo=0.5")
        factor /= 0.5
    parts.append(f"atempo={factor:.6f}")
    return parts


def postprocess_audio(
    source: str | Path,
    target: str | Path,
    *,
    speed: float = 1.0,
    pitch_semitones: float = 0.0,
    volume: float = 1.0,
    speed_already_applied: bool = False,
) -> dict[str, Any]:
    source = Path(source)
    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    speed = max(0.25, min(float(speed or 1.0), 4.0))
    pitch_semitones = max(-12.0, min(float(pitch_semitones or 0.0), 12.0))
    volume = max(0.0, min(float(volume or 1.0), 2.0))
    if abs(speed - 1.0) < 0.001 and abs(pitch_semitones) < 0.01 and abs(volume - 1.0) < 0.001:
        if source.resolve() != target.resolve():
            shutil.copy2(source, target)
        return {"applied": False}
    info = sf.info(str(source))
    sr = info.samplerate
    filters: list[str] = []
    pitch_ratio = 2 ** (pitch_semitones / 12.0)
    if abs(pitch_semitones) >= 0.01:
        filters.append(f"asetrate={int(sr * pitch_ratio)}")
        filters.append(f"aresample={sr}")
        filters.extend(_atempo_chain(1.0 / pitch_ratio))
    if not speed_already_applied and abs(speed - 1.0) >= 0.001:
        filters.extend(_atempo_chain(speed))
    if abs(volume - 1.0) >= 0.001:
        filters.append(f"volume={volume:.4f}")
    if not filters:
        filters.append("anull")
    args = [
        ffmpeg_exe(),
        "-y",
        "-i",
        str(source),
        "-af",
        ",".join(filters),
        "-ar",
        str(sr),
        "-ac",
        "1",
        "-c:a",
        "pcm_s16le",
        str(target),
    ]
    subprocess.run(args, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    return {"applied": True, "filters": filters}


def export_audio(source: str | Path, target: str | Path, format: str = "wav") -> None:
    if format == "wav":
        if Path(source).resolve() != Path(target).resolve():
            shutil.copy2(source, target)
        return
    codec = {"mp3": "libmp3lame", "ogg": "libvorbis"}.get(format)
    if not codec:
        raise ValueError(f"Unsupported audio format: {format}")
    subprocess.run(
        [ffmpeg_exe(), "-y", "-i", str(source), "-c:a", codec, str(target)],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )


def analyze_reference(path: str | Path) -> dict[str, Any]:
    audio, sr = read_mono(path)
    if audio.size == 0:
        return {"ok": False, "score": 0, "issues": ["Пустой аудиофайл."], "duration_sec": 0}
    duration = len(audio) / max(sr, 1)
    peak = float(np.max(np.abs(audio)))
    peak_dbfs = 20 * math.log10(max(peak, 1e-8))
    rms = float(np.sqrt(np.mean(np.square(audio))))
    rms_dbfs = 20 * math.log10(max(rms, 1e-8))
    clipping = float(np.mean(np.abs(audio) >= 0.999))
    frame = max(1, int(sr * 0.03))
    frames = audio[: len(audio) // frame * frame].reshape(-1, frame)
    energies = np.sqrt(np.mean(frames**2, axis=1)) if frames.size else np.array([])
    threshold = max(float(np.median(energies)) * 0.35, 1e-4) if energies.size else 1e-4
    speech = energies > threshold
    speech_ratio = float(np.mean(speech)) if energies.size else 0.0
    silence_ratio = 1.0 - speech_ratio
    if speech.any():
        snr = 20 * math.log10(max(float(np.mean(energies[speech])) / max(float(np.mean(energies[~speech])) if (~speech).any() else 1e-5, 1e-6), 1e-6))
    else:
        snr = 0.0
    issues: list[str] = []
    warnings: list[str] = []
    if duration < 5:
        issues.append(f"Слишком короткий референс: {duration:.1f} с (нужно 5–30 с).")
    elif duration > 30:
        issues.append(f"Слишком длинный референс: {duration:.1f} с (нужно 5–30 с).")
    if clipping > 0.001:
        issues.append(f"Клиппинг: {clipping * 100:.2f}% сэмплов на пределе.")
    elif clipping > 0.0001:
        warnings.append(f"Небольшой клиппинг: {clipping * 100:.2f}%.")
    if rms_dbfs < -38:
        warnings.append("Очень тихая запись; возможно, много шума.")
    if peak_dbfs < -20:
        warnings.append("Низкий пик; голос может быть тихим.")
    if snr < 10 and speech.any() and (~speech).any():
        warnings.append(f"Низкий ориентировочный SNR: {snr:.1f} dB.")
    if speech_ratio < 0.45:
        warnings.append("Много тишины или пауз; лучше выбрать более плотный фрагмент.")
    score = 100.0
    score -= max(0, 5 - duration) * 12
    score -= max(0, duration - 30) * 2
    score -= min(30, clipping * 1000)
    if rms_dbfs < -38:
        score -= 12
    if snr < 10 and speech.any():
        score -= 15
    if speech_ratio < 0.45:
        score -= 10
    score = max(0, min(100, round(score)))
    return {
        "ok": not issues,
        "score": score,
        "duration_sec": round(duration, 3),
        "sample_rate": sr,
        "peak_dbfs": round(peak_dbfs, 2),
        "rms_dbfs": round(rms_dbfs, 2),
        "clipping_ratio": round(clipping, 5),
        "silence_ratio": round(silence_ratio, 3),
        "speech_ratio": round(speech_ratio, 3),
        "snr_db": round(snr, 2),
        "issues": issues,
        "warnings": warnings,
        "recommendation": "Референс подходит." if not issues else "Перезапишите референс с учётом замечаний.",
    }
