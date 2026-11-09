from __future__ import annotations

import re
from typing import Any

import numpy as np


def split_text(text: str, max_chars: int = 280) -> list[str]:
    text = re.sub(r"\s+", " ", text or "").strip()
    if not text:
        return []
    sentences = re.split(r"(?<=[.!?。！？])\s+|(?<=\n)", text)
    chunks: list[str] = []
    current = ""
    for sentence in sentences:
        sentence = sentence.strip()
        if not sentence:
            continue
        if len(sentence) > max_chars:
            parts = re.split(r"(?<=[,;:—])\s+", sentence)
            for part in parts:
                if not part:
                    continue
                if current and len(current) + len(part) + 1 > max_chars:
                    chunks.append(current.strip())
                    current = part
                else:
                    current = f"{current} {part}".strip()
            continue
        if current and len(current) + len(sentence) + 1 > max_chars:
            chunks.append(current.strip())
            current = sentence
        else:
            current = f"{current} {sentence}".strip()
    if current:
        chunks.append(current.strip())
    return chunks or [text]


def concat_audio(parts: list[np.ndarray], pause_sec: float = 0.12, sample_rate: int = 24000) -> np.ndarray:
    if not parts:
        return np.zeros(0, dtype=np.float32)
    silence = np.zeros(int(sample_rate * pause_sec), dtype=np.float32)
    out: list[np.ndarray] = []
    for index, part in enumerate(parts):
        if index:
            out.append(silence)
        out.append(np.asarray(part, dtype=np.float32))
    return np.concatenate(out)


def rtf(infer_seconds: float, audio_seconds: float) -> float:
    return round(infer_seconds / max(audio_seconds, 0.01), 4)
