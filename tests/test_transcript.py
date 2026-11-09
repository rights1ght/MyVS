from backend.services.transcript import (
    fmt_timestamp,
    transcript_to_srt,
    transcript_to_txt,
    transcript_to_vtt,
)


SEGMENTS = [
    {"start": 0.0, "end": 1.25, "text": "Привет"},
    {"start": 1.25, "end": 3.5, "text": "мир"},
]


def test_timestamp_formats() -> None:
    assert fmt_timestamp(0, srt=True) == "00:00:00,000"
    assert fmt_timestamp(1.5) == "00:00:01.500"
    assert fmt_timestamp(3661.25, srt=True) == "01:01:01,250"


def test_exports() -> None:
    srt = transcript_to_srt(SEGMENTS)
    assert "00:00:00,000 --> 00:00:01,250" in srt
    assert "Привет" in srt
    vtt = transcript_to_vtt(SEGMENTS)
    assert vtt.startswith("WEBVTT")
    assert "00:00:01.250 --> 00:00:03.500" in vtt
    assert transcript_to_txt(SEGMENTS) == "Привет\nмир"
    assert "[00:00:00.000" in transcript_to_txt(SEGMENTS, with_timestamps=True)
