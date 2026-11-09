import math

import numpy as np
import soundfile as sf

from backend.services.audio import analyze_reference, read_mono


def test_reference_quality(tmp_path) -> None:
    sample_rate = 24000
    duration = 6
    t = np.arange(sample_rate * duration) / sample_rate
    tone = 0.08 * np.sin(2 * math.pi * 220 * t)
    # A speech-like envelope avoids a pure constant tone while remaining synthetic.
    envelope = 0.7 + 0.3 * np.sin(2 * math.pi * 2 * t)
    audio = (tone * envelope).astype(np.float32)
    path = tmp_path / "reference.wav"
    sf.write(path, audio, sample_rate, subtype="PCM_16")
    data, sr = read_mono(path)
    assert sr == sample_rate
    assert len(data) > 0
    analysis = analyze_reference(path)
    assert analysis["duration_sec"] > 5
    assert "clipping_ratio" in analysis
    assert "score" in analysis


def test_reference_too_short(tmp_path) -> None:
    path = tmp_path / "short.wav"
    sf.write(path, np.zeros(24000, dtype=np.float32), 24000, subtype="PCM_16")
    analysis = analyze_reference(path)
    assert analysis["ok"] is False
    assert any("корот" in issue for issue in analysis["issues"])
