from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def fmt_timestamp(seconds: float, *, srt: bool = False) -> str:
    seconds = max(0.0, float(seconds))
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    millis = int(round((seconds - int(seconds)) * 1000))
    if millis >= 1000:
        secs += 1
        millis -= 1000
    separator = "," if srt else "."
    return f"{hours:02d}:{minutes:02d}:{secs:02d}{separator}{millis:03d}"


def transcript_to_srt(segments: list[dict[str, Any]]) -> str:
    lines: list[str] = []
    for index, segment in enumerate(segments, 1):
        lines.append(str(index))
        lines.append(f"{fmt_timestamp(segment['start'], srt=True)} --> {fmt_timestamp(segment['end'], srt=True)}")
        lines.append(str(segment.get("text") or "").strip())
        lines.append("")
    return "\n".join(lines)


def transcript_to_vtt(segments: list[dict[str, Any]]) -> str:
    lines = ["WEBVTT", ""]
    for index, segment in enumerate(segments, 1):
        lines.append(str(index))
        lines.append(f"{fmt_timestamp(segment['start'])} --> {fmt_timestamp(segment['end'])}")
        lines.append(str(segment.get("text") or "").strip())
        lines.append("")
    return "\n".join(lines)


def transcript_to_txt(segments: list[dict[str, Any]], with_timestamps: bool = False) -> str:
    if with_timestamps:
        return "\n".join(f"[{fmt_timestamp(item['start'])} → {fmt_timestamp(item['end'])}] {item.get('text', '').strip()}" for item in segments)
    return "\n".join(str(item.get("text") or "").strip() for item in segments)


def load_transcript(path: str | Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))
