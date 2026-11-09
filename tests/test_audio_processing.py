from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

from backend.services import audio
from tests.conftest import make_wav


def _peak(path: Path) -> float:
    data, _ = audio.read_mono(path)
    return float(np.max(np.abs(data)))


@pytest.mark.parametrize("factor", [0.25, 0.5, 1.0, 1.7, 3.0, 4.0, 10.0])
def test_atempo_chain_is_valid_and_multiplies_back(factor: float) -> None:
    parts = audio._atempo_chain(factor)
    values = [float(p.split("=")[1]) for p in parts]
    assert all(0.5 <= v <= 2.0 for v in values), "ffmpeg atempo only accepts 0.5..2.0"
    assert np.prod(values) == pytest.approx(min(max(factor, 0.1), 10.0), rel=1e-4)


def test_postprocess_noop_copies_file(tmp_path: Path) -> None:
    src = make_wav(tmp_path / "in.wav", seconds=1)
    out = tmp_path / "out.wav"
    assert audio.postprocess_audio(src, out) == {"applied": False}
    assert out.read_bytes() == src.read_bytes()


def test_postprocess_volume_zero_mutes(tmp_path: Path) -> None:
    src = make_wav(tmp_path / "in.wav", seconds=1)
    out = tmp_path / "out.wav"
    info = audio.postprocess_audio(src, out, volume=0.0)
    assert info["applied"] is True
    assert _peak(out) < 1e-3


def test_postprocess_volume_scales(tmp_path: Path) -> None:
    src = make_wav(tmp_path / "in.wav", seconds=1, amplitude=0.2)
    out = tmp_path / "out.wav"
    audio.postprocess_audio(src, out, volume=0.5)
    assert _peak(out) == pytest.approx(_peak(src) * 0.5, rel=0.05)


def test_postprocess_speed_changes_duration(tmp_path: Path) -> None:
    src = make_wav(tmp_path / "in.wav", seconds=2)
    out = tmp_path / "out.wav"
    audio.postprocess_audio(src, out, speed=2.0)
    assert audio.probe(out)["duration_sec"] == pytest.approx(1.0, abs=0.1)


def test_postprocess_speed_already_applied_is_skipped(tmp_path: Path) -> None:
    src = make_wav(tmp_path / "in.wav", seconds=2)
    out = tmp_path / "out.wav"
    audio.postprocess_audio(src, out, speed=2.0, volume=0.9, speed_already_applied=True)
    assert audio.probe(out)["duration_sec"] == pytest.approx(2.0, abs=0.1)


def test_postprocess_pitch_keeps_duration(tmp_path: Path) -> None:
    src = make_wav(tmp_path / "in.wav", seconds=2)
    out = tmp_path / "out.wav"
    audio.postprocess_audio(src, out, pitch_semitones=5)
    assert audio.probe(out)["duration_sec"] == pytest.approx(2.0, abs=0.15)


def test_export_rejects_unknown_format(tmp_path: Path) -> None:
    src = make_wav(tmp_path / "in.wav", seconds=1)
    with pytest.raises(ValueError):
        audio.export_audio(src, tmp_path / "x.flac", "flac")


def test_export_wav_copies(tmp_path: Path) -> None:
    src = make_wav(tmp_path / "in.wav", seconds=1)
    audio.export_audio(src, tmp_path / "x.wav", "wav")
    assert (tmp_path / "x.wav").exists()


def test_write_wav_normalizes_peaks_and_downmixes(tmp_path: Path) -> None:
    stereo = np.stack([np.full(1000, 2.5, dtype=np.float32), np.full(1000, 0.5, dtype=np.float32)], axis=1)
    path = tmp_path / "w.wav"
    audio.write_wav(path, stereo, 16000)
    info = sf.info(str(path))
    assert info.channels == 1
    assert _peak(path) <= 0.99


def test_decode_to_wav_resamples(tmp_path: Path) -> None:
    src = make_wav(tmp_path / "in.wav", seconds=1, sample_rate=44100)
    out = tmp_path / "out.wav"
    audio.decode_to_wav(src, out, sample_rate=16000)
    info = audio.probe(out)
    assert info["sample_rate"] == 16000 and info["channels"] == 1


def test_analyze_reference_flags_clipping(tmp_path: Path) -> None:
    path = tmp_path / "clip.wav"
    t = np.arange(24000 * 6) / 24000
    sf.write(path, np.clip(3.0 * np.sin(2 * np.pi * 200 * t), -1, 1).astype(np.float32), 24000)
    result = audio.analyze_reference(path)
    assert result["ok"] is False
    assert any("Клиппинг" in issue for issue in result["issues"])


def test_analyze_reference_too_long(tmp_path: Path) -> None:
    result = audio.analyze_reference(make_wav(tmp_path / "long.wav", seconds=31))
    assert result["ok"] is False
    assert any("длинный" in issue for issue in result["issues"])


def test_analyze_reference_good_sample_scores_high(tmp_path: Path) -> None:
    result = audio.analyze_reference(make_wav(tmp_path / "ok.wav", seconds=8))
    assert result["ok"] is True and result["score"] >= 70


def test_analyze_reference_empty_and_silent(tmp_path: Path) -> None:
    empty = tmp_path / "empty.wav"
    sf.write(empty, np.zeros(0, dtype=np.float32), 24000)
    assert audio.analyze_reference(empty)["ok"] is False
    silent = tmp_path / "silent.wav"
    sf.write(silent, np.zeros(24000 * 6, dtype=np.float32), 24000)
    result = audio.analyze_reference(silent)
    assert result["duration_sec"] == pytest.approx(6.0)
    assert result["warnings"], "silence must produce quality warnings"
