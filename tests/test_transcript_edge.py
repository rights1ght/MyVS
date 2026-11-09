import pytest

from backend.services.transcript import fmt_timestamp, transcript_to_srt, transcript_to_txt, transcript_to_vtt


@pytest.mark.parametrize(
    ("seconds", "expected"),
    [
        (0.0004, "00:00:00,000"),
        (59.9996, "00:01:00,000"),  # rounding must carry into minutes, never "00:00:60,000"
        (3599.9999, "01:00:00,000"),  # ...and into hours
        (86399.5, "23:59:59,500"),
        (-5, "00:00:00,000"),
    ],
)
def test_srt_timestamp_rounding_carries(seconds: float, expected: str) -> None:
    assert fmt_timestamp(seconds, srt=True) == expected


def test_vtt_uses_dot_separator() -> None:
    assert fmt_timestamp(61.0049) == "00:01:01.005"


def test_txt_tolerates_missing_text() -> None:
    segments = [{"start": 0, "end": 1, "text": None}, {"start": 1, "end": 2}]
    assert transcript_to_txt(segments) == "\n"
    assert transcript_to_txt(segments, with_timestamps=True).count("\n") == 1


def test_empty_transcript() -> None:
    assert transcript_to_srt([]) == ""
    assert transcript_to_vtt([]).startswith("WEBVTT")
    assert transcript_to_txt([]) == ""


def test_srt_structure_and_trimming() -> None:
    srt = transcript_to_srt([{"start": 0, "end": 1, "text": "  a  "}, {"start": 1, "end": 2, "text": "b"}])
    blocks = [b for b in srt.split("\n\n") if b.strip()]
    assert [b.splitlines()[0] for b in blocks] == ["1", "2"]
    assert blocks[0].splitlines()[2] == "a"
