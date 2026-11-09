import hashlib
import http.server
import socketserver
import threading
import time
from pathlib import Path

import pytest

from backend.config import settings
from backend.db.models import Download
from backend.db.session import session_scope
from backend.services.downloads import downloads
from backend.services.model_registry import registry

PAYLOAD = (b"myvs-model-bytes-" * 5000)[:70_000]


@pytest.fixture()
def file_server(tmp_path):
    (tmp_path / "srv").mkdir()
    (tmp_path / "srv" / "a.bin").write_bytes(PAYLOAD)

    class Handler(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *a, **k):
            super().__init__(*a, directory=str(tmp_path / "srv"), **k)

        def log_message(self, *_a):  # silence
            pass

    server = socketserver.TCPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()
    server.server_close()


def _register(client, model_id: str, url: str, sha256: str | None = None, size: int | None = None) -> str:
    entry = {"path": "a.bin", "url": f"{url}/a.bin", "size": len(PAYLOAD) if size is None else size,
             "sha256": hashlib.sha256(PAYLOAD).hexdigest() if sha256 is None else sha256}
    response = client.post("/api/models/custom", json={
        "id": model_id, "name": model_id, "adapter": "piper",
        "variant": {"device": "cpu", "download": {"type": "url_files", "files": [entry]}},
    })
    assert response.status_code == 200, response.text
    return f"{model_id}:custom"


def _wait(download_id: str, timeout: float = 15.0) -> Download:
    deadline = time.time() + timeout
    while time.time() < deadline:
        row = downloads.get(download_id)
        if row.status in ("completed", "error", "cancelled", "paused"):
            return row
        time.sleep(0.05)
    raise AssertionError(f"download stuck: {downloads.get(download_id)}")


def test_download_completes_and_marks_installed(client, file_server) -> None:
    variant_id = _register(client, "custom-dl-ok", file_server)
    row = _wait(downloads.start("custom-dl-ok", variant_id).id)
    assert row.status == "completed", row.error
    dest = Path(registry.get_variant("custom-dl-ok", variant_id).install_path)
    assert (dest / "a.bin").read_bytes() == PAYLOAD
    assert (dest / ".myvs-complete").exists() and not list(dest.rglob("*.part"))
    assert registry.get_variant("custom-dl-ok", variant_id).install_state == "installed"
    verify = client.post("/api/models/custom-dl-ok/verify", json={"variant_id": variant_id}).json()
    assert verify["ok"] is True and verify["level"].startswith("sha256")


def test_checksum_mismatch_fails_download(client, file_server) -> None:
    variant_id = _register(client, "custom-dl-badsha", file_server, sha256="0" * 64)
    row = _wait(downloads.start("custom-dl-badsha", variant_id).id)
    assert row.status == "error" and "Контрольная сумма" in row.error
    assert registry.get_variant("custom-dl-badsha", variant_id).install_state == "error"


def test_http_error_fails_download(client, file_server, monkeypatch) -> None:
    from types import SimpleNamespace
    from backend.services import downloads as downloads_module

    # skip the 1+2+4+8 s retry back-off without touching the global time.sleep
    monkeypatch.setattr(downloads_module, "time", SimpleNamespace(monotonic=time.monotonic, sleep=lambda _s: None))
    variant_id = _register(client, "custom-dl-404", file_server + "/missing")
    row = _wait(downloads.start("custom-dl-404", variant_id).id)
    assert row.status == "error"


def test_resume_with_fully_downloaded_part_file(client, file_server) -> None:
    """A .part that already has every byte (crash right before the rename) must be finalised, not rejected."""
    variant_id = _register(client, "custom-dl-resume", file_server)
    dest = settings.data_dir / "models" / "custom-dl-resume" / "custom"
    dest.mkdir(parents=True, exist_ok=True)
    (dest / "a.bin.part").write_bytes(PAYLOAD)
    row = _wait(downloads.start("custom-dl-resume", variant_id, resume=True).id)
    assert row.status == "completed", row.error
    assert (dest / "a.bin").read_bytes() == PAYLOAD


def test_resume_from_partial_file_uses_range(client, file_server) -> None:
    variant_id = _register(client, "custom-dl-range", file_server)
    dest = settings.data_dir / "models" / "custom-dl-range" / "custom"
    dest.mkdir(parents=True, exist_ok=True)
    (dest / "a.bin.part").write_bytes(PAYLOAD[:12_345])
    row = _wait(downloads.start("custom-dl-range", variant_id, resume=True).id)
    # SimpleHTTPRequestHandler ignores Range and answers 200 -> the client must restart cleanly
    assert row.status == "completed", row.error
    assert (dest / "a.bin").read_bytes() == PAYLOAD


def test_progress_updates_keep_speed(client) -> None:
    with session_scope() as session:
        row = Download(model_id="m", variant_id="v", bytes_total=1000)
        session.add(row); session.flush(); download_id = row.id
    downloads._update(download_id, bytes_done=500, speed_bps=1234.5)
    assert downloads.get(download_id).speed_bps == 1234.5
    downloads._update(download_id, status="completed", bytes_done=1000)
    assert downloads.get(download_id).speed_bps == 0.0


def test_interrupted_downloads_become_paused(client) -> None:
    with session_scope() as session:
        row = Download(model_id="m", variant_id="v", status="downloading")
        session.add(row); session.flush(); download_id = row.id
    downloads.mark_interrupted()
    row = downloads.get(download_id)
    assert row.status == "paused" and "перезапуск" in row.error


def test_download_api_errors(client) -> None:
    assert client.get("/api/downloads/missing").status_code == 404
    for action in ("pause", "resume", "cancel"):
        assert client.post(f"/api/downloads/missing/{action}").status_code == 404
    assert client.post("/api/models/missing/download").status_code == 404
    local = client.post("/api/models/custom", json={"id": "custom-local", "name": "L", "adapter": "piper", "path": "/tmp"}).json()
    assert local["id"] == "custom-local"
    assert client.post("/api/models/custom-local/download").json()["error"]["code"] == "DOWNLOAD_FAILED"


def test_uninstall_removes_files_only_inside_models_dir(client, file_server) -> None:
    variant_id = _register(client, "custom-dl-rm", file_server)
    _wait(downloads.start("custom-dl-rm", variant_id).id)
    dest = Path(registry.get_variant("custom-dl-rm", variant_id).install_path)
    assert dest.exists()
    assert client.delete("/api/models/custom-dl-rm").json()["deleted_files"] == []  # delete_files defaults to false
    assert dest.exists()
    removed = client.delete("/api/models/custom-dl-rm", params={"delete_files": True}).json()["deleted_files"]
    assert removed == [str(dest)] and not dest.exists()
    assert registry.get_variant("custom-dl-rm", variant_id).install_state == "not_installed"
