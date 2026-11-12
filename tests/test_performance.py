"""Regression guards for the performance work (query counts, payload size, no redundant work)."""
import json
import sys
import time
import types
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf
from sqlalchemy import event, text

from backend.config import settings
from backend.db.models import ModelMeasurement, TaskEvent, TaskRecord
from backend.db.session import engine, session_scope
from backend.services import audio
from backend.services.model_registry import registry
from backend.services.monitor import monitor
from backend.services.resource_manager import ModelRuntime, resources
from backend.services.tasks import slim_result
from tests.conftest import FakeWorker, make_wav, set_installed, wait_for_task


class QueryCounter:
    def __enter__(self):
        self.count = 0
        event.listen(engine, "before_cursor_execute", self._hook)
        return self

    def __exit__(self, *_exc):
        event.remove(engine, "before_cursor_execute", self._hook)

    def _hook(self, *_args, **_kwargs):
        self.count += 1


# ---------------------------------------------------------------- database
def test_sqlite_pragmas() -> None:
    with engine.connect() as connection:
        assert connection.execute(text("PRAGMA journal_mode")).scalar() == "wal"
        assert connection.execute(text("PRAGMA synchronous")).scalar() == 1  # NORMAL
        assert connection.execute(text("PRAGMA foreign_keys")).scalar() == 1
        assert connection.execute(text("PRAGMA temp_store")).scalar() == 2  # MEMORY


def test_model_catalog_uses_a_constant_number_of_queries(client) -> None:
    client.get("/api/models")  # warm-up
    with QueryCounter() as counter:
        response = client.get("/api/models")
    assert response.status_code == 200 and len(response.json()) >= 10
    assert counter.count <= 5, f"{counter.count} queries (was 73 before batching)"


def test_voice_list_uses_a_constant_number_of_queries(client) -> None:
    client.get("/api/voices")
    with QueryCounter() as counter:
        response = client.get("/api/voices")
    assert response.status_code == 200 and len(response.json()) >= 10
    assert counter.count <= 5, f"{counter.count} queries (was 41 before batching)"


def test_public_many_matches_single_model_payload_and_picks_latest_measurement() -> None:
    model = registry.get("faster-whisper-tiny")
    variant = registry.get_variant("faster-whisper-tiny", "cpu-int8")
    with session_scope() as session:
        rows = [  # inserted newest-first on purpose: the result must follow measured_at, not insertion order
            ModelMeasurement(model_id=model.id, variant_id=variant.id, load_ms=111, measured_at=datetime(2026, 1, 11, tzinfo=timezone.utc)),
            ModelMeasurement(model_id=model.id, variant_id=variant.id, load_ms=999, measured_at=datetime(2026, 1, 1, tzinfo=timezone.utc)),
        ]
        session.add_all(rows)
        session.flush()
        row_ids = [row.id for row in rows]
    try:
        single = registry.model_public(model.id)
        bulk = {item["id"]: item for item in registry.public_many(registry.all())}
        assert bulk[model.id] == single
        measured = next(v for v in single["variants"] if v["id"] == variant.id)["measurement"]
        assert measured is not None and measured["load_ms"] == 111
    finally:
        with session_scope() as session:
            for row_id in row_ids:
                session.delete(session.get(ModelMeasurement, row_id))
    assert registry.public_many([]) == []
    assert all("measurement" in v for item in bulk.values() for v in item["variants"])


def test_voice_payload_fields(client) -> None:
    voices = client.get("/api/voices").json()
    assert {"model_name", "model_installed", "has_reference"} <= set(voices[0])
    assert all(v["model_name"] for v in voices if v["model_id"])


# ---------------------------------------------------------------- task payloads
def _heavy_stt_task() -> str:
    segments = [{"start": i, "end": i + 1, "text": "слово " * 8, "words": [{"start": i, "end": i + 0.1, "text": "слово"}] * 8} for i in range(1500)]
    full = {"text": "слово " * 8 * 1500, "segments": segments, "language": "ru", "audio_duration_sec": 1500.0}
    task_id = f"heavy{time.time_ns()}"
    out = settings.data_dir / "outputs" / task_id
    out.mkdir(parents=True, exist_ok=True)
    (out / "transcript.json").write_text(json.dumps(full, ensure_ascii=False), encoding="utf-8")
    with session_scope() as session:
        session.add(TaskRecord(id=task_id, type="stt", status="completed", model_id="faster-whisper-tiny", text="hello",
                               params={"result": full}, output_paths=[str(out / "transcript.json")], rtf_infer=0.1))
    return task_id


def test_task_list_is_light_but_detail_is_complete(client) -> None:
    task_id = _heavy_stt_task()
    listing = client.get("/api/tasks", params={"limit": 20})
    item = next(t for t in listing.json() if t["id"] == task_id)
    assert item["result"] is None and item["params"] == {}
    assert item["text"] == "hello" and item["rtf_infer"] == 0.1 and item["status"] == "completed"
    assert len(listing.content) < 50_000, "list rows must not carry transcripts"
    detail = client.get(f"/api/tasks/{task_id}").json()
    assert len(detail["result"]["segments"]) == 1500, "detail still returns the full transcript from transcript.json"


def test_task_list_filters_and_dates(client) -> None:
    task_id = _heavy_stt_task()
    rows = client.get("/api/tasks", params={"type": "stt", "status": "completed", "model_id": "faster-whisper-tiny"}).json()
    assert any(r["id"] == task_id for r in rows)
    assert all(r["type"] == "stt" and r["status"] == "completed" for r in rows)
    mine = next(r for r in rows if r["id"] == task_id)
    assert mine["queued_at"].endswith("+00:00") and mine["created_at"] is not None
    assert client.get("/api/tasks", params={"type": "tts", "model_id": "faster-whisper-tiny"}).json() == []
    assert len(client.get("/api/tasks", params={"limit": 1}).json()) == 1


def test_list_does_not_read_transcript_files(client, monkeypatch) -> None:
    _heavy_stt_task()
    reads: list[str] = []
    original = Path.read_text
    monkeypatch.setattr(Path, "read_text", lambda self, *a, **k: reads.append(str(self)) or original(self, *a, **k))
    client.get("/api/tasks", params={"limit": 50})
    assert not [r for r in reads if r.endswith("transcript.json")]


def test_slim_result() -> None:
    result = {"text": "t", "segments": [{"a": 1}, {"a": 2}], "language": "ru"}
    slim = slim_result(result)
    assert "segments" not in slim and slim["segments_count"] == 2 and slim["text"] == "t"
    assert "segments" in result, "input must not be mutated"
    assert slim_result(None) is None and slim_result({"x": 1}) == {"x": 1}


def test_completed_stt_stores_no_duplicate_transcripts(client, fake_worker, monkeypatch, wav_file) -> None:
    monkeypatch.setattr(resources, "_policy", "ask")
    set_installed("faster-whisper-tiny", "cpu-int8")
    try:
        response = client.post("/api/stt/transcribe", files={"file": ("a.wav", wav_file.read_bytes(), "audio/wav")})
        task = wait_for_task(client, response.json()["task_id"])
        assert task["status"] == "completed"
        assert [s["text"] for s in task["result"]["segments"]] == ["привет", "мир"]  # from transcript.json
        assert "result" not in task["progress"], "progress.result duplicated the whole result"
        with session_scope() as session:
            row = session.get(TaskRecord, task["id"])
            assert "segments" not in row.params["result"] and row.params["result"]["segments_count"] == 2
            events = session.query(TaskEvent).filter(TaskEvent.task_id == task["id"], TaskEvent.phase == "completed").all()
            assert events and all("segments" not in (e.data or {}) for e in events)
    finally:
        resources.unload_all(force=True)
        set_installed("faster-whisper-tiny", "cpu-int8", "not_installed")


# ---------------------------------------------------------------- audio post-processing
def test_engine_applied_speed_does_not_trigger_ffmpeg(tmp_path, monkeypatch) -> None:
    src = make_wav(tmp_path / "in.wav", seconds=1)
    monkeypatch.setattr(audio.subprocess, "run", lambda *a, **k: pytest.fail("ffmpeg must not run"))
    info = audio.postprocess_audio(src, tmp_path / "out.wav", speed=1.5, speed_already_applied=True)
    assert info == {"applied": False}


def test_noop_postprocess_can_skip_the_copy(tmp_path) -> None:
    src = make_wav(tmp_path / "in.wav", seconds=1)
    assert audio.postprocess_audio(src, tmp_path / "out.wav", copy_if_unchanged=False) == {"applied": False}
    assert not (tmp_path / "out.wav").exists()
    audio.postprocess_audio(src, tmp_path / "out2.wav")
    assert (tmp_path / "out2.wav").exists()


def test_tts_default_settings_leave_a_single_clean_output(client, fake_worker) -> None:
    set_installed("piper", "ru-voices")
    try:
        voice = client.get("/api/voices", params={"model_id": "piper", "language": "ru"}).json()[0]
        task = wait_for_task(client, client.post("/api/tts/synthesize", json={"text": "Привет", "voice_id": voice["id"]}).json()["task_id"])
        assert task["status"] == "completed"
        folder = settings.data_dir / "outputs" / task["id"]
        assert not (folder / "audio_final.wav").exists() and (folder / "audio.wav").exists()
        assert task["audio_duration_sec"] == pytest.approx(1.0, abs=0.05)
    finally:
        set_installed("piper", "ru-voices", "not_installed")


# ---------------------------------------------------------------- resource manager
def _gpu_runtime(vram_mb: float = 2048.0) -> ModelRuntime:
    runtime = ModelRuntime(model_id="g", variant_id="g:x", model_name="g", device="cuda:0", precision="fp16", worker=FakeWorker({}), vram_mb=vram_mb)
    return runtime


def test_cpu_unload_does_not_sleep(monkeypatch) -> None:
    monkeypatch.setattr(time, "sleep", lambda _s: pytest.fail("unload must not sleep for CPU models"))
    runtime = _gpu_runtime()
    runtime.device = "cpu"
    assert resources._wait_vram_release(5.0, runtime) == resources._mem()["gpu_used_gb"]


def test_gpu_unload_returns_as_soon_as_vram_is_released(monkeypatch) -> None:
    readings = iter([5.0, 5.0, 3.0, 3.0])
    monkeypatch.setattr(resources, "_mem", lambda: {"gpu_used_gb": next(readings)})
    started = time.monotonic()
    used = resources._wait_vram_release(5.0, _gpu_runtime(2048.0), timeout=5.0)
    assert used == 3.0 and time.monotonic() - started < 1.0


def test_gpu_unload_gives_up_after_timeout(monkeypatch) -> None:
    monkeypatch.setattr(resources, "_mem", lambda: {"gpu_used_gb": 5.0})
    started = time.monotonic()
    assert resources._wait_vram_release(5.0, _gpu_runtime(), timeout=0.1) == 5.0
    assert 0.09 <= time.monotonic() - started < 1.0


def test_unloading_a_cpu_model_is_fast(client, fake_worker) -> None:
    set_installed("faster-whisper-tiny", "cpu-int8")
    try:
        resources.ensure_loaded("faster-whisper-tiny")
        started = time.monotonic()
        resources.unload("faster-whisper-tiny")
        assert time.monotonic() - started < 0.3, "unload used to cost a fixed 0.5 s"
    finally:
        set_installed("faster-whisper-tiny", "cpu-int8", "not_installed")


# ---------------------------------------------------------------- HTTP compression
def test_json_is_gzip_compressed_and_audio_is_not(client, fake_worker) -> None:
    response = client.get("/api/models", headers={"Accept-Encoding": "gzip"})
    assert response.headers.get("content-encoding") == "gzip"
    plain = client.get("/api/models", headers={"Accept-Encoding": "identity"})
    assert "content-encoding" not in plain.headers and response.json() == plain.json()
    assert client.get("/api/health", headers={"Accept-Encoding": "gzip"}).json()  # tiny bodies stay readable

    set_installed("piper", "ru-voices")
    try:
        voice = client.get("/api/voices", params={"model_id": "piper", "language": "ru"}).json()[0]
        task = wait_for_task(client, client.post("/api/tts/synthesize", json={"text": "Привет", "voice_id": voice["id"]}).json()["task_id"])
        audio_response = client.get(f"/api/tasks/{task['id']}/audio", headers={"Accept-Encoding": "gzip"})
        assert audio_response.status_code == 200 and "content-encoding" not in audio_response.headers
        assert audio_response.headers["content-type"] == "audio/wav"
        assert audio_response.content[:4] == b"RIFF"
        ranged = client.get(f"/api/tasks/{task['id']}/audio", headers={"Accept-Encoding": "gzip", "Range": "bytes=0-99"})
        assert "content-encoding" not in ranged.headers and len(ranged.content) in (100, len(audio_response.content))
    finally:
        set_installed("piper", "ru-voices", "not_installed")


# ---------------------------------------------------------------- monitor
def test_escalating_alerts_do_not_crash() -> None:
    """A second, higher alert for the same metric within 30 s raised KeyError('level') every second."""
    monitor.persistence_enabled = False
    monitor.alerts.clear()
    monitor._last_level.clear()
    monitor._last_alert_ts.clear()
    monitor._alert("ram", 1, 86.0, 85.0, "warning")
    monitor._alert("ram", 2, 93.0, 92.0, "high")
    monitor._alert("ram", 2, 93.5, 92.0, "high again")  # same severity inside 30 s: deduplicated
    assert [a["severity"] for a in monitor.alerts] == ["warning", "high"]
    monitor.alerts.clear()
    monitor._last_level.clear()
    monitor._last_alert_ts.clear()


# ---------------------------------------------------------------- STT decoding
def test_decode_audio_16k_fallback_pipe(tmp_path, monkeypatch) -> None:
    from backend.engines.stt import faster_whisper as fw

    monkeypatch.setitem(sys.modules, "faster_whisper", None)  # force the ffmpeg-pipe fallback
    monkeypatch.setitem(sys.modules, "faster_whisper.audio", None)
    samples = fw.decode_audio_16k(str(make_wav(tmp_path / "a.wav", seconds=2, sample_rate=44100)))
    assert samples.dtype == np.float32 and samples.ndim == 1
    assert len(samples) == pytest.approx(32000, abs=64) and 0.05 < float(np.abs(samples).max()) <= 1.0


def test_decode_audio_16k_prefers_faster_whisper_decoder(monkeypatch) -> None:
    from backend.engines.stt import faster_whisper as fw

    calls = []
    package, module = types.ModuleType("faster_whisper"), types.ModuleType("faster_whisper.audio")
    module.decode_audio = lambda path, sampling_rate: calls.append((path, sampling_rate)) or np.ones(5, dtype=np.float64)
    package.audio = module
    monkeypatch.setitem(sys.modules, "faster_whisper", package)
    monkeypatch.setitem(sys.modules, "faster_whisper.audio", module)
    result = fw.decode_audio_16k("x.mp3")
    assert calls == [("x.mp3", 16000)] and result.dtype == np.float32


# ---------------------------------------------------------------- Chatterbox reference cache
class _StubModel:
    def __init__(self, fail_prepare=False, has_prepare=True):
        self.prepared, self.generated, self.fail_prepare = [], [], fail_prepare
        if has_prepare:
            self.prepare_conditionals = self._prepare

    def _prepare(self, path, **kwargs):
        if self.fail_prepare:
            raise RuntimeError("boom")
        self.prepared.append((path, kwargs))

    def generate(self, text, **kwargs):
        self.generated.append(kwargs)
        return np.zeros(2400, dtype=np.float32)


@pytest.fixture()
def chatterbox(monkeypatch, tmp_path):
    fake_ta = types.ModuleType("torchaudio")
    fake_ta.save = lambda path, wav, sr: sf.write(path, np.asarray(wav).squeeze(), sr)
    monkeypatch.setitem(sys.modules, "torchaudio", fake_ta)
    from backend.engines.tts import chatterbox as cb

    def make(engine_cls, model):
        engine = engine_cls()
        engine.model = model
        return engine

    return cb, make, make_wav(tmp_path / "ref.wav", seconds=1), tmp_path


@pytest.mark.parametrize("adapter", ["ChatterboxEngine", "ChatterboxTurboEngine"])
def test_reference_is_encoded_once_for_all_chunks(chatterbox, adapter) -> None:
    cb, make, ref, tmp = chatterbox
    model = _StubModel()
    engine = make(getattr(cb, adapter), model)
    for index in range(4):
        engine.infer({"text": "x", "output_path": str(tmp / f"{index}.wav"), "reference_path": str(ref), "language": "ru"}, lambda _p: None)
    assert len(model.prepared) == 1, "reference must be prepared once, not once per chunk"
    assert all("audio_prompt_path" not in kwargs for kwargs in model.generated)

    other = make_wav(tmp / "other.wav", seconds=1)  # a different voice invalidates the cache
    engine.infer({"text": "x", "output_path": str(tmp / "z.wav"), "reference_path": str(other)}, lambda _p: None)
    assert [p for p, _ in model.prepared] == [str(ref), str(other)]


@pytest.mark.parametrize("model", [_StubModel(fail_prepare=True), _StubModel(has_prepare=False)])
def test_reference_cache_falls_back_to_prompt_path(chatterbox, model) -> None:
    cb, make, ref, tmp = chatterbox
    engine = make(cb.ChatterboxEngine, model)
    for index in range(2):
        engine.infer({"text": "x", "output_path": str(tmp / f"{index}.wav"), "reference_path": str(ref)}, lambda _p: None)
    assert [kwargs.get("audio_prompt_path") for kwargs in model.generated] == [str(ref), str(ref)]


def test_no_reference_means_no_prompt(chatterbox) -> None:
    cb, make, _ref, tmp = chatterbox
    model = _StubModel()
    make(cb.ChatterboxEngine, model).infer({"text": "x", "output_path": str(tmp / "a.wav")}, lambda _p: None)
    assert model.prepared == [] and "audio_prompt_path" not in model.generated[0]


# ---------------------------------------------------------------- incremental monitor history
def test_monitor_history_returns_only_new_samples(client) -> None:
    for _ in range(4):
        monitor.sample()
    history = monitor.get_history(300)
    middle = history[len(history) // 2]["seq"]
    newer = monitor.get_history(300, after=middle)
    assert newer and all(item["seq"] > middle for item in newer) and len(newer) < len(history)
    # a seq from before a server restart is larger than ours -> send everything
    assert monitor.get_history(300, after=10**9)[0]["seq"] == monitor.get_history(300)[0]["seq"]
    response = client.get("/api/monitor/history", params={"seconds": 300, "after": middle})
    assert response.status_code == 200 and all(item["seq"] > middle for item in response.json())
    assert len(client.get("/api/monitor/history").json()) >= len(history)  # default behaviour unchanged
