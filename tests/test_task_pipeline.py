"""End-to-end task flow (API -> queue -> ResourceManager -> fake worker -> files)."""
import pytest
import soundfile as sf
from pathlib import Path

from backend.db.models import TaskRecord
from backend.db.session import session_scope
from backend.services.resource_manager import resources
from backend.services.tasks import tasks
from tests.conftest import make_wav, set_installed, wait_for_task


@pytest.fixture()
def piper_voice(client, fake_worker):
    set_installed("piper", "ru-voices")
    yield client.get("/api/voices", params={"model_id": "piper", "language": "ru"}).json()[0]
    set_installed("piper", "ru-voices", "not_installed")


@pytest.fixture()
def whisper(client, fake_worker, monkeypatch):
    monkeypatch.setattr(resources, "_policy", "ask")
    set_installed("faster-whisper-tiny", "cpu-int8")
    yield "faster-whisper-tiny"
    resources.unload_all(force=True)
    for suffix in ("cpu-int8", "int8"):
        set_installed("faster-whisper-tiny", suffix, "not_installed")


def _transcribe(client, wav: Path, **form):
    return client.post("/api/stt/transcribe", files={"file": ("a.wav", wav.read_bytes(), "audio/wav")}, data=form)


def test_tts_end_to_end(client, piper_voice) -> None:
    response = client.post("/api/tts/synthesize", json={"text": "Привет. Как дела?", "voice_id": piper_voice["id"]})
    assert response.status_code == 202, response.text
    task = wait_for_task(client, response.json()["task_id"])
    assert task["status"] == "completed", task
    assert task["audio_duration_sec"] > 0 and task["model_id"] == "piper"
    audio = client.get(f"/api/tasks/{task['id']}/audio")
    assert audio.status_code == 200 and audio.headers["content-type"] == "audio/wav"
    assert client.get(f"/api/tasks/{task['id']}/audio", params={"format": "flac"}).status_code == 400
    assert any(e["phase"] == "completed" for e in client.get(f"/api/tasks/{task['id']}/events").json())


def test_tts_volume_zero_produces_silence(client, piper_voice, tmp_path) -> None:
    response = client.post("/api/tts/synthesize", json={"text": "тишина", "voice_id": piper_voice["id"], "volume": 0})
    task = wait_for_task(client, response.json()["task_id"])
    assert task["status"] == "completed", task
    out = tmp_path / "out.wav"
    out.write_bytes(client.get(f"/api/tasks/{task['id']}/audio").content)
    data, _ = sf.read(out)
    assert abs(data).max() < 1e-3


def test_tts_long_text_is_chunked(client, piper_voice, fake_worker) -> None:
    text = " ".join(f"Предложение номер {i}." for i in range(60))
    task = wait_for_task(client, client.post("/api/tts/synthesize", json={"text": text, "voice_id": piper_voice["id"]}).json()["task_id"])
    assert task["status"] == "completed"
    assert task["result"]["chunks"] > 1
    assert len(fake_worker.instances[-1].infer_calls) == task["result"]["chunks"]


def test_stt_end_to_end_and_exports(client, whisper, wav_file) -> None:
    response = _transcribe(client, wav_file, language="ru")
    assert response.status_code == 202, response.text
    task = wait_for_task(client, response.json()["task_id"])
    assert task["status"] == "completed", task
    assert task["result"]["text"] == "привет мир"

    srt = client.get(f"/api/tasks/{task['id']}/export", params={"format": "srt"})
    assert "00:00:00,000 --> 00:00:01,000" in srt.text
    assert client.get(f"/api/tasks/{task['id']}/export", params={"format": "vtt"}).text.startswith("WEBVTT")
    assert client.get(f"/api/tasks/{task['id']}/export", params={"format": "txt"}).text == "привет\nмир"
    assert "[00:00:00.000" in client.get(f"/api/tasks/{task['id']}/export", params={"format": "txt", "with_timestamps": True}).text
    assert client.get(f"/api/tasks/{task['id']}/export", params={"format": "json"}).json()["language"] == "ru"
    assert client.get(f"/api/tasks/{task['id']}/export", params={"format": "docx"}).status_code == 400
    assert client.get(f"/api/tasks/{task['id']}/audio").status_code == 409


def test_export_errors(client) -> None:
    assert client.get("/api/tasks/missing/export").status_code == 404
    with session_scope() as session:
        tts_task = TaskRecord(type="tts", status="completed")
        stt_pending = TaskRecord(type="stt", status="running")
        session.add(tts_task); session.add(stt_pending); session.flush()
        tts_id, stt_id = tts_task.id, stt_pending.id
    assert client.get(f"/api/tasks/{tts_id}/export").json()["error"]["code"] == "EXPORT_NOT_SUPPORTED"
    assert client.get(f"/api/tasks/{stt_id}/export").json()["error"]["code"] == "RESULT_NOT_READY"


def test_stt_rejects_non_stt_model(client, piper_voice, wav_file) -> None:
    response = _transcribe(client, wav_file, model_id="piper")
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "MODEL_CATEGORY_MISMATCH"


def test_stt_input_validation(client, whisper) -> None:
    assert client.post("/api/stt/transcribe", files={"file": ("a.wav", b"tiny", "audio/wav")}).json()["error"]["code"] == "EMPTY_AUDIO"
    assert _transcribe(client, make_wav(Path("/tmp/x.wav"), 1), model_id="nope").json()["error"]["code"] == "MODEL_NOT_FOUND"
    assert _transcribe(client, make_wav(Path("/tmp/x.wav"), 1), model_id="faster-whisper-base").json()["error"]["code"] == "MODEL_NOT_INSTALLED"


def test_stt_params_are_clamped(client, whisper, wav_file) -> None:
    task = _transcribe(client, wav_file, beam_size="99", temperature="7", priority="500").json()["task"]
    assert task["params"]["beam_size"] == 10 and task["params"]["temperature"] == 1.0 and task["priority"] == 100
    wait_for_task(client, task["id"])


def test_tts_input_validation(client, piper_voice) -> None:
    base = {"voice_id": piper_voice["id"]}
    assert client.post("/api/tts/synthesize", json={**base, "text": "   "}).status_code == 422
    assert client.post("/api/tts/synthesize", json={**base, "text": "x" * 10001}).status_code == 422
    assert client.post("/api/tts/synthesize", json={"text": "a", "voice_id": "nope"}).json()["error"]["code"] == "VOICE_NOT_FOUND"


def test_tts_numeric_params_are_clamped_and_cannot_be_overridden(client, piper_voice) -> None:
    body = {"text": "привет", "voice_id": piper_voice["id"], "speed": 99, "pitch": -99, "volume": 0,
            "params": {"speed": 100, "volume": 50, "voice_kind": "cloned", "max_chars": 1, "pause_sec": 99, "exaggeration": 0.7}}
    task = client.post("/api/tts/synthesize", json=body).json()["task"]
    params = task["params"]
    assert (params["speed"], params["pitch"], params["volume"]) == (4.0, -12.0, 0.0)
    assert params["voice_kind"] == "builtin"
    assert 50 <= params["max_chars"] <= 1000 and 0 <= params["pause_sec"] <= 5
    assert params["exaggeration"] == 0.7
    wait_for_task(client, task["id"])


def test_cancel_queued_task_and_retry(client) -> None:
    with session_scope() as session:
        row = TaskRecord(type="tts", status="queued", model_id="piper", text="x")
        session.add(row); session.flush(); task_id = row.id
    cancelled = client.post(f"/api/tasks/{task_id}/cancel").json()
    assert cancelled["status"] == "cancelled" and cancelled["error_code"] == "CANCELLED"
    assert client.post(f"/api/tasks/{task_id}/cancel").json()["status"] == "cancelled"  # idempotent
    assert client.post("/api/tasks/missing/cancel").status_code == 404

    retried = client.post(f"/api/tasks/{task_id}/retry").json()
    assert retried["retry_of"] == task_id and retried["id"] != task_id
    wait_for_task(client, retried["id"])  # fails fast: model not installed


def test_recover_marks_interrupted_tasks_failed(client) -> None:
    with session_scope() as session:
        row = TaskRecord(type="tts", status="running", model_id="piper")
        session.add(row); session.flush(); task_id = row.id
    tasks.recover()
    task = client.get(f"/api/tasks/{task_id}").json()
    assert task["status"] == "failed" and task["error_code"] == "SERVER_RESTARTED"


def test_queue_and_listing_filters(client) -> None:
    with session_scope() as session:
        row = TaskRecord(type="stt", status="awaiting_decision", model_id="faster-whisper-tiny")
        session.add(row); session.flush(); task_id = row.id
    queue = client.get("/api/queue").json()
    assert queue["counts"]["awaiting"] >= 1 and any(t["id"] == task_id for t in queue["tasks"])
    assert [t["id"] for t in client.get("/api/tasks", params={"status": "awaiting_decision", "type": "stt"}).json()].count(task_id) == 1
    assert len(client.get("/api/tasks", params={"limit": 1}).json()) == 1
    client.post(f"/api/tasks/{task_id}/cancel")


def test_resource_conflict_is_resolved_by_switching_to_cpu(client, whisper, wav_file, fake_worker, monkeypatch) -> None:
    set_installed("faster-whisper-tiny", "int8")  # GPU variant too
    starved = {"gpu_total_gb": 4.0, "gpu_used_gb": 3.9, "free_vram_gb": 0.0, "ram_total_gb": 64.0, "ram_used_gb": 8.0,
               "free_ram_gb": 48.0, "reserve_vram_gb": 0.8, "reserve_ram_gb": 3.0, "reserved_vram_gb": 0.0, "gpu_available": True}
    monkeypatch.setattr(resources, "_mem", lambda: dict(starved))
    task = wait_for_task(client, _transcribe(client, wav_file).json()["task_id"])
    assert task["status"] == "awaiting_decision", task
    options = task["progress"]["plan"]["options"]
    actions = [o["action"] for o in options]
    assert "cpu" in actions and "cancel" in actions
    assert len({o["id"] for o in options}) == len(options)

    resolved = client.post(f"/api/tasks/{task['id']}/resolve", json={"choice": "cpu"}).json()
    assert resolved["status"] in ("queued", "running", "completed")
    final = wait_for_task(client, task["id"])
    assert final["status"] == "completed" and final["device"] == "cpu"


def test_resolve_evict_uses_model_from_plan_options(monkeypatch) -> None:
    unloaded: list[str] = []
    monkeypatch.setattr(resources, "unload", lambda model_id, **_k: unloaded.append(model_id) or {"unloaded": True})
    plan = {"options": [{"id": "evict:qwen3-tts-0.6b", "action": "evict", "model_id": "qwen3-tts-0.6b"}, {"id": "cancel", "action": "cancel"}]}
    with session_scope() as session:
        row = TaskRecord(type="stt", status="awaiting_decision", model_id="faster-whisper-tiny", params={"resource_plan": plan})
        session.add(row); session.flush(); task_id = row.id
    tasks.resolve(task_id, "evict")  # no explicit model_id: must come from the plan
    assert unloaded == ["qwen3-tts-0.6b"]
    tasks.cancel(task_id)


def test_resolve_cancel_and_unknown_task(client) -> None:
    assert tasks.resolve("missing", "cancel") is None
    with session_scope() as session:
        row = TaskRecord(type="stt", status="awaiting_decision", model_id="x")
        session.add(row); session.flush(); task_id = row.id
    assert client.post(f"/api/tasks/{task_id}/resolve", json={"choice": "cancel"}).json()["status"] == "cancelled"
    assert client.post("/api/tasks/missing/resolve", json={"choice": "cancel"}).status_code == 404


def test_task_service_can_restart_after_stop() -> None:
    tasks.stop()
    tasks.start()
    assert not tasks._stop.is_set() and tasks._dispatcher is not None and tasks._dispatcher.is_alive()
