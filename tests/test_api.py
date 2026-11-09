from fastapi.testclient import TestClient

from backend.main import app


def test_health_and_catalog() -> None:
    with TestClient(app) as client:
        health = client.get("/api/health")
        assert health.status_code == 200
        assert health.json()["status"] == "ok"
        models = client.get("/api/models")
        assert models.status_code == 200
        assert len(models.json()) >= 14
        ids = {item["id"] for item in models.json()}
        assert "faster-whisper-small" in ids
        assert "qwen3-tts-0.6b" in ids
        voices = client.get("/api/voices")
        assert voices.status_code == 200
        assert len(voices.json()) >= 10


def test_startup_and_monitor() -> None:
    with TestClient(app) as client:
        startup = client.get("/api/system/startup/current").json()
        assert startup["ready"] is True
        assert startup["total_ms"] >= 0
        assert any(phase["name"] == "db_init" for phase in startup["phases"])
        snapshot = client.get("/api/monitor/snapshot")
        assert snapshot.status_code == 200
        body = snapshot.json()
        assert "cpu" in body and "gpu" in body and "ram" in body
        history = client.get("/api/system/startup/history").json()
        assert isinstance(history, list)


def test_validation_errors() -> None:
    with TestClient(app) as client:
        assert client.post("/api/tts/synthesize", json={}).status_code == 422
        assert client.post("/api/stt/transcribe").status_code == 422
        missing = client.get("/api/tasks/does-not-exist")
        assert missing.status_code == 404
        assert missing.json()["error"]["code"] == "TASK_NOT_FOUND"


def test_resource_status() -> None:
    with TestClient(app) as client:
        status = client.get("/api/resources/status").json()
        assert status["mode"] in ("parallel", "economy", "exclusive")
        assert "free_vram_gb" in status["memory"]
        assert "loaded" in status
        presets = client.get("/api/resources/presets").json()
        assert isinstance(presets, list)
